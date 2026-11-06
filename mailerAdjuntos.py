#!/usr/bin/env python3
"""
Envía correos personalizados con adjuntos (PDF, Word, Excel, etc.) que se
seleccionan automáticamente según el nombre del destinatario.

Reutiliza mailer.py (misma carpeta) y el mismo archivo .env.

Cómo se buscan los adjuntos de cada contacto (carpeta por defecto: ./adjuntos):

  1. Subcarpeta con el nombre del contacto:
        adjuntos/juan_perez/certificado.pdf
        adjuntos/Juan Pérez/notas.docx

  2. Archivos sueltos cuyo nombre contenga el nombre completo del contacto:
        adjuntos/Juan Perez - certificado.pdf
        adjuntos/certificado_juan_perez.pdf

  3. Archivos para TODOS los contactos, en la subcarpeta:
        adjuntos/_comunes/reglamento.pdf

Se ignoran mayúsculas, tildes y signos al comparar nombres.

Ejemplos:
    python mailer_adjuntos.py --subject "Hola {nombre}" --message "Adjunto tus documentos." --dry-run
    python mailer_adjuntos.py --csv contacts.csv --adjuntos ./adjuntos --solo-con-adjunto
"""

import argparse
import mimetypes
import os
import re
import smtplib
import ssl
import sys
import unicodedata
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

# Importar mailer también carga el archivo .env
from mailer import EMAIL_REGEX, load_contacts, render_template

EXTENSIONES_PERMITIDAS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".png", ".jpg", ".jpeg", ".zip",
}
CARPETA_COMUNES = "_comunes"
LIMITE_MB = 20  # Gmail permite 25 MB en total; dejamos margen


# ---------- Utilidades ----------
def normalizar(texto: str) -> str:
    """'Juan Pérez' -> 'juan_perez' (sin tildes, minúsculas, solo a-z0-9 y _)."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_")


def obtener(row: dict[str, str], *claves: str) -> str:
    """Devuelve el valor de la primera columna que coincida (sin importar mayúsculas)."""
    for key, value in row.items():
        if key.strip().lower() in claves and value.strip():
            return value.strip()
    return ""


def listar_archivos(carpeta: Path) -> list[Path]:
    if not carpeta.is_dir():
        return []
    return sorted(
        p for p in carpeta.iterdir()
        if p.is_file()
        and p.suffix.lower() in EXTENSIONES_PERMITIDAS
        and not p.name.startswith(("~$", "."))  # temporales de Word / ocultos
    )


def buscar_adjuntos(nombre: str, carpeta: Path) -> list[Path]:
    """Busca los archivos que le corresponden a un contacto según su nombre."""
    encontrados: list[Path] = []

    # 3. Archivos comunes para todos
    encontrados += listar_archivos(carpeta / CARPETA_COMUNES)

    clave = normalizar(nombre)
    if clave and carpeta.is_dir():
        # 1. Subcarpeta con el nombre del contacto
        for sub in sorted(carpeta.iterdir()):
            if sub.is_dir() and sub.name != CARPETA_COMUNES and normalizar(sub.name) == clave:
                encontrados += listar_archivos(sub)

        # 2. Archivos sueltos que contengan el nombre completo
        #    (los guiones bajos evitan que "ana" coincida con "mariana")
        for archivo in listar_archivos(carpeta):
            if f"_{clave}_" in f"_{normalizar(archivo.stem)}_":
                encontrados.append(archivo)

    # Quita duplicados conservando el orden
    return list(dict.fromkeys(encontrados))


def adjuntar(mensaje: EmailMessage, ruta: Path) -> None:
    tipo, _ = mimetypes.guess_type(ruta.name)
    maintype, subtype = (tipo or "application/octet-stream").split("/", 1)
    mensaje.add_attachment(
        ruta.read_bytes(), maintype=maintype, subtype=subtype, filename=ruta.name
    )


def tamano_mb(archivos: list[Path]) -> float:
    return sum(a.stat().st_size for a in archivos) / (1024 * 1024)


# ---------- Programa principal ----------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Envía correos con adjuntos asignados según el nombre del destinatario."
    )
    parser.add_argument("--csv", type=Path, default=Path(__file__).with_name("contacts.csv"),
                        help="CSV de contactos (por defecto contacts.csv junto al script)")
    parser.add_argument("--adjuntos", type=Path, default=Path(__file__).with_name("adjuntos"),
                        help="Carpeta con los documentos (por defecto ./adjuntos)")
    parser.add_argument("--subject", default=os.getenv("EMAIL_SUBJECT"),
                        help="Asunto; admite {columna} (o EMAIL_SUBJECT en .env)")
    parser.add_argument("--message", default=os.getenv("EMAIL_MESSAGE"),
                        help="Cuerpo; admite {columna} (o EMAIL_MESSAGE en .env)")
    parser.add_argument("--solo-con-adjunto", action="store_true",
                        help="No envía el correo a contactos que no tengan ningún adjunto")
    parser.add_argument("--dry-run", action="store_true",
                        help="Muestra qué se enviaría a cada persona sin conectarse al SMTP")
    args = parser.parse_args()

    if not args.subject or not args.message:
        parser.error("Indica --subject y --message o define EMAIL_SUBJECT y EMAIL_MESSAGE en .env.")

    if not args.adjuntos.is_dir():
        print(f"[ERROR] No existe la carpeta de adjuntos: {args.adjuntos}", file=sys.stderr)
        return 1

    try:
        contactos = load_contacts(args.csv)
    except (OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1

    # Configuración SMTP (igual que mailer.py)
    sender_email = os.getenv("SENDER_EMAIL") or os.getenv("EMAIL", "")
    sender_password = os.getenv("SENDER_PASSWORD") or os.getenv("PASSWORD", "")
    sender_name = os.getenv("SENDER_NAME", "")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    try:
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        print("[ERROR] SMTP_PORT debe ser un número válido.", file=sys.stderr)
        return 1
    use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() in ("true", "1", "yes")

    # Prepara la lista de envíos: (contacto, nombre, email, archivos)
    envios = []
    omitidos = 0
    for row in contactos:
        email = obtener(row, "email")
        nombre = obtener(row, "nombre", "name", "first_name", "firstname")
        if not EMAIL_REGEX.fullmatch(email):
            print(f"[OMITIDO] Email no válido: {email!r}")
            omitidos += 1
            continue

        archivos = buscar_adjuntos(nombre, args.adjuntos)
        # Los archivos de _comunes no cuentan como "adjunto propio"
        propios = [a for a in archivos if a.parent.name != CARPETA_COMUNES]

        if args.solo_con_adjunto and not propios:
            print(f"[OMITIDO] {nombre or email}: sin adjuntos propios")
            omitidos += 1
            continue
        if tamano_mb(archivos) > LIMITE_MB:
            print(f"[OMITIDO] {nombre or email}: adjuntos superan {LIMITE_MB} MB "
                  f"({tamano_mb(archivos):.1f} MB)")
            omitidos += 1
            continue

        row["email"] = email
        envios.append((row, nombre or email, email, archivos))

    if not envios:
        print("[ERROR] No hay correos para enviar.", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"[DRY-RUN] Se enviarían {len(envios)} correo(s):")
        for row, nombre, email, archivos in envios:
            print(f"\n  {nombre} <{email}> | {render_template(args.subject, row)}")
            if archivos:
                for a in archivos:
                    print(f"     📎 {a.relative_to(args.adjuntos)}")
            else:
                print("     (sin adjuntos)")
        return 0

    if not sender_email or not sender_password:
        print("[ERROR] Define SENDER_EMAIL y SENDER_PASSWORD (o EMAIL y PASSWORD) en .env.",
              file=sys.stderr)
        return 1

    context = ssl.create_default_context()
    enviados = 0
    fallidos = 0
    try:
        conexion = (
            smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=60, context=context)
            if smtp_port == 465
            else smtplib.SMTP(smtp_server, smtp_port, timeout=60)
        )
        with conexion as smtp:
            smtp.ehlo()
            if use_tls and smtp_port != 465:
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(sender_email, sender_password)

            for row, nombre, email, archivos in envios:
                mensaje = EmailMessage()
                mensaje["Subject"] = render_template(args.subject, row)
                mensaje["From"] = formataddr((sender_name, sender_email)) if sender_name else sender_email
                mensaje["To"] = email
                mensaje.set_content(render_template(args.message, row))

                try:
                    for archivo in archivos:
                        adjuntar(mensaje, archivo)
                    smtp.send_message(mensaje)
                except (OSError, smtplib.SMTPException) as error:
                    fallidos += 1
                    print(f"[FALLÓ] {nombre} <{email}>: {error}", file=sys.stderr)
                    continue

                enviados += 1
                print(f"[ENVIADO] {nombre} <{email}> ({len(archivos)} adjunto(s))")

    except (OSError, smtplib.SMTPException) as error:
        print(f"[ERROR] Falló la conexión SMTP tras {enviados} correo(s): {error}", file=sys.stderr)
        return 1

    print(f"\nTerminado: {enviados} enviado(s), {fallidos} fallido(s), {omitidos} omitido(s).")
    return 0 if fallidos == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())