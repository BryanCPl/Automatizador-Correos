# Automatizador de correos

Envía un correo personalizado a cada contacto de un CSV usando SMTP. La lista y
las credenciales se mantienen separadas del código.

## Configuración

1. Instala la dependencia:

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. Copia `.env.example` a `.env` y completa el correo y la contraseña de
   aplicación de SMTP. Gmail requiere una contraseña de aplicación; no uses la
   contraseña normal de tu cuenta.
3. Copia `contacts.example.csv` a `contacts.csv` y reemplaza los datos de
   ejemplo con tus destinatarios. El CSV debe incluir una columna `email`.
   Puedes agregar columnas como `name` y `company` para personalizar el correo.

El `.env` está excluido de Git. No compartas ni publiques ese archivo.

## Envío

El asunto y el cuerpo pueden definirse en `.env` (`EMAIL_SUBJECT` y
`EMAIL_MESSAGE`) o pasarse al ejecutar:

```powershell
python mailer.py --subject "Hola {name}" --message "Hola {name}, te escribimos de {company}."
```

El script usa `contacts.csv` junto a `mailer.py` por defecto. Para usar otra
lista, pasa `--csv ruta\contactos.csv`.

Antes de enviar, puedes verificar los destinatarios sin conectar al servidor:

```powershell
python mailer.py --dry-run
```

Configuración SMTP por defecto: Gmail, puerto 587 y STARTTLS. También se admite
el puerto 465 con SSL implícito. Se puede cambiar con `SMTP_SERVER`,
`SMTP_PORT` y `SMTP_USE_TLS` en `.env`.
