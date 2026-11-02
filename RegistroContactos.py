#!/usr/bin/env python3
"""
Editor de CSV de contactos.
Columnas: nombre, email, empresa, tipo_usuario
Uso: python editor_csv.py [archivo.csv]
"""

import csv
import os
import re
import sys

ARCHIVO = sys.argv[1] if len(sys.argv) > 1 else "contacts.csv"
COLUMNAS = ["nombre", "email", "empresa", "tipo_usuario"]
TIPOS = ["estudiante", "profesor", "administrativo", "directivo", "otro"]


# ---------- Lectura / escritura ----------
def cargar():
    if not os.path.exists(ARCHIVO):
        return []
    with open(ARCHIVO, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def guardar(filas):
    with open(ARCHIVO, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNAS)
        writer.writeheader()
        writer.writerows(filas)
    print(f"✔ Guardado en {ARCHIVO}")


# ---------- Utilidades ----------
def email_valido(email):
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) is not None


def pedir(texto, actual=None):
    sufijo = f" [{actual}]" if actual else ""
    valor = input(f"{texto}{sufijo}: ").strip()
    return valor if valor else (actual or "")


def pedir_email(actual=None):
    while True:
        email = pedir("Email", actual)
        if email_valido(email):
            return email
        print("  ✘ Email no válido, intenta de nuevo.")


def pedir_tipo(actual=None):
    print("Tipos disponibles:")
    for i, t in enumerate(TIPOS, 1):
        print(f"  {i}. {t}")
    while True:
        valor = pedir("Tipo de usuario (número o texto)", actual).lower()
        if valor.isdigit() and 1 <= int(valor) <= len(TIPOS):
            return TIPOS[int(valor) - 1]
        if valor in TIPOS:
            return valor
        print("  ✘ Tipo no válido.")


def mostrar(filas):
    if not filas:
        print("(No hay registros)")
        return
    anchos = {c: max(len(c), *(len(f[c]) for f in filas)) for c in COLUMNAS}
    encabezado = "  #  " + " | ".join(c.ljust(anchos[c]) for c in COLUMNAS)
    print(encabezado)
    print("-" * len(encabezado))
    for i, f in enumerate(filas, 1):
        print(f"{i:>3}  " + " | ".join(f[c].ljust(anchos[c]) for c in COLUMNAS))


def pedir_indice(filas):
    mostrar(filas)
    if not filas:
        return None
    valor = input("Número de registro: ").strip()
    if valor.isdigit() and 1 <= int(valor) <= len(filas):
        return int(valor) - 1
    print("✘ Número no válido.")
    return None


# ---------- Acciones ----------
def agregar(filas):
    print("\n--- Nuevo usuario ---")
    filas.append({
        "nombre": pedir("Nombre"),
        "email": pedir_email(),
        "empresa": pedir("Empresa"),
        "tipo_usuario": pedir_tipo(),
    })
    guardar(filas)


def editar(filas):
    print("\n--- Editar usuario ---")
    i = pedir_indice(filas)
    if i is None:
        return
    f = filas[i]
    print("(Enter para dejar el valor actual)")
    f["nombre"] = pedir("Nombre", f["nombre"])
    f["email"] = pedir_email(f["email"])
    f["empresa"] = pedir("Empresa", f["empresa"])
    f["tipo_usuario"] = pedir_tipo(f["tipo_usuario"])
    guardar(filas)


def eliminar(filas):
    print("\n--- Eliminar usuario ---")
    i = pedir_indice(filas)
    if i is None:
        return
    if input(f"¿Eliminar a {filas[i]['nombre']}? (s/n): ").lower() == "s":
        filas.pop(i)
        guardar(filas)


def buscar(filas):
    q = input("\nBuscar (nombre, email, empresa o tipo): ").strip().lower()
    resultados = [f for f in filas if any(q in v.lower() for v in f.values())]
    mostrar(resultados)


def filtrar_tipo(filas):
    tipo = pedir_tipo()
    mostrar([f for f in filas if f["tipo_usuario"] == tipo])


# ---------- Menú ----------
def main():
    filas = cargar()
    # Normaliza por si el CSV tiene columnas faltantes
    for f in filas:
        for c in COLUMNAS:
            f.setdefault(c, "")

    opciones = {
        "1": ("Ver todos", lambda: mostrar(filas)),
        "2": ("Agregar", lambda: agregar(filas)),
        "3": ("Editar", lambda: editar(filas)),
        "4": ("Eliminar", lambda: eliminar(filas)),
        "5": ("Buscar", lambda: buscar(filas)),
        "6": ("Filtrar por tipo de usuario", lambda: filtrar_tipo(filas)),
    }

    while True:
        print(f"\n===== Editor de usuarios ({ARCHIVO}) =====")
        for k, (nombre, _) in opciones.items():
            print(f"{k}. {nombre}")
        print("0. Salir")
        eleccion = input("Elige una opción: ").strip()
        if eleccion == "0":
            break
        if eleccion in opciones:
            opciones[eleccion][1]()
        else:
            print("✘ Opción no válida.")


if __name__ == "__main__":
    main()