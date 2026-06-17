# Pañol — Control de Stock (Multi-Almacén)
### Streamlit + Supabase

---

## ¿Qué es esto?

App web para gestionar stock de **uno o varios almacenes independientes** (por ejemplo: el pañol de la IACI - UNQUI, una droguería, un depósito, etc.) desde una misma aplicación.

- **Multi-almacén**: podés crear tantos almacenes como necesites, cada uno con su propio stock, historial y contraseña de administración.
- **Vista pública**: cualquiera puede ver el stock de un almacén sin login.
- **Administración por almacén**: agregar, editar, eliminar ítems y registrar entradas/salidas requiere la contraseña *de ese almacén específico*.
- **Base de datos en la nube**: Supabase (PostgreSQL gratuito).
- **Hosting gratuito**: Streamlit Community Cloud.

---

## PASO 1 — Configurar Supabase

1. Entrá a [supabase.com](https://supabase.com) e iniciá sesión.
2. Creá un nuevo proyecto (elegí una región cercana, ej: South America).
3. Cuando esté listo, andá a **SQL Editor** y pegá el contenido de `setup_supabase.sql`. Ejecutalo.
   - Esto crea 3 tablas: `paniol_almacenes`, `paniol_items` y `paniol_movimientos`.
   - Se inserta un almacén de ejemplo llamado **"Pañol IACI"** con contraseña `panol.unqui.iaci` y sus ítems de muestra.
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

## Cómo funciona el sistema multi-almacén

Al abrir la app vas a ver una **pantalla de selección de almacén**:

- Si ya existen almacenes (por ejemplo el "Pañol IACI" de ejemplo), aparecen como tarjetas para elegir.
- Para crear uno nuevo (por ejemplo, una droguería), desplegá **"➕ Crear nuevo almacén"**, completá:
  - Nombre (ej: "Droguería Central")
  - Un emoji como ícono (opcional, ej: 💊)
  - Una contraseña de administración **propia para ese almacén**
- Una vez creado, entrás directo a ese almacén con stock vacío, listo para empezar a cargar ítems.

Dentro de cada almacén, todo funciona igual que antes (pestañas de Stock, Administrar e Historial), pero los datos de cada almacén están completamente separados de los demás: un ítem o movimiento de la droguería nunca se mezcla con los del pañol.

Hay un botón **"⇄ Cambiar de almacén"** en la parte superior para volver al selector en cualquier momento.

### Sobre las contraseñas

- Cada almacén tiene su propia contraseña de administración, definida al crearlo.
- Las contraseñas se guardan **hasheadas** (SHA-256) en la base de datos, no en texto plano.
- Si perdés la contraseña de un almacén, podés cambiarla manualmente desde Supabase: en **Table Editor → paniol_almacenes**, editá el campo `clave_hash` del almacén correspondiente. Para generar el hash de una nueva contraseña podés correr en Python:
  ```python
  import hashlib
  print(hashlib.sha256("tu-nueva-clave".encode()).hexdigest())
  ```
  y pegar el resultado en `clave_hash`.

### Almacén de ejemplo

El script SQL crea un almacén llamado **"Pañol IACI"** con la contraseña:
```
panol.unqui.iaci
```
Podés borrarlo desde Supabase (Table Editor → paniol_almacenes) si no lo necesitás; al borrar el almacén se borran en cascada sus ítems y movimientos.

---

## Archivos del proyecto

```
paniol-streamlit/
├── app.py                  ← App principal (multi-almacén)
├── requirements.txt        ← Dependencias
├── setup_supabase.sql      ← SQL para crear las tablas (almacenes, items, movimientos)
├── .gitignore              ← Excluye secrets.toml de Git
├── .streamlit/
│   └── secrets.toml        ← Credenciales (NO subir a Git)
└── README.md
```
