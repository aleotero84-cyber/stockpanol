# Pañol — Control de Stock
### Streamlit + Supabase

---

## ¿Qué es esto?

App web para gestionar el stock del pañol de la IACI - UNQUI.
- **Vista pública**: cualquiera puede ver el stock sin login.
- **Administración**: agregar, editar, eliminar ítems y registrar entradas/salidas requiere contraseña.
- **Base de datos en la nube**: Supabase (PostgreSQL gratuito).
- **Hosting gratuito**: Streamlit Community Cloud.

---

## PASO 1 — Configurar Supabase

1. Entrá a [supabase.com](https://supabase.com) e iniciá sesión.
2. Creá un nuevo proyecto (elegí una región cercana, ej: South America).
3. Cuando esté listo, andá a **SQL Editor** y pegá el contenido de `setup_supabase.sql`. Ejecutalo.
4. Andá a **Project Settings → API** y copiá:
   - **Project URL** → algo como `https://abcdefgh.supabase.co`
   - **anon public key** → el token largo que empieza con `eyJ...`

---

## PASO 2 — Subir el código a GitHub

1. Creá un repositorio nuevo en [github.com](https://github.com) (puede ser privado).
2. Subí todos los archivos de esta carpeta **excepto** `.streamlit/secrets.toml`.
   El `.gitignore` ya lo excluye automáticamente.

---

## PASO 3 — Publicar en Streamlit Community Cloud

1. Andá a [share.streamlit.io](https://share.streamlit.io) e iniciá sesión con GitHub.
2. Hacé clic en **"New app"**.
3. Seleccioná tu repositorio y como archivo principal elegí `app.py`.
4. Antes de hacer deploy, hacé clic en **"Advanced settings"** y en la sección
   **Secrets** pegá esto (reemplazando con tus datos reales):

```toml
[supabase]
url = "https://TU-PROYECTO.supabase.co"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

5. Hacé clic en **Deploy**. En 2-3 minutos la app va a estar online.

---

## PASO 4 — Probar localmente (opcional)

```bash
pip install streamlit supabase pandas
# Completá .streamlit/secrets.toml con tus credenciales
streamlit run app.py
```

---

## Contraseña de administración

```
panol.unqui.iaci
```

La sesión se mantiene activa mientras el navegador esté abierto.
Para cerrar sesión hay un botón en el panel de administración.

---

## Archivos del proyecto

```
paniol-streamlit/
├── app.py                  ← App principal
├── requirements.txt        ← Dependencias
├── setup_supabase.sql      ← SQL para crear las tablas
├── .gitignore              ← Excluye secrets.toml de Git
├── .streamlit/
│   └── secrets.toml        ← Credenciales (NO subir a Git)
└── README.md
```
