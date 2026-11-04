"""
Pañol — Control de stock  +  HOPSIE — Cerveza artesanal (comanda de mesas, stock, caja y admin)
Streamlit + Supabase

Una sola app con dos módulos que se eligen en la barra de pestañas de arriba:
  · 🔧 Pañol  → multi-almacén · subcategorías · unidades · columnas personalizadas · préstamos · apariencia editable
  · 🍺 HOPSIE → salón · comanda · cobro (efectivo / QR / tarjeta) · cocina y barra · admin

Cada módulo carga su propio estilo y consulta solo sus propias tablas cuando está activo.
Enlace directo a HOPSIE: agregar  ?modulo=hopsie  a la dirección de la app.

Antes de desplegar:
  1) Pañol  → ejecutar migracion_v2.sql y migracion_v3.sql en el SQL Editor de Supabase.
  2) HOPSIE → ejecutar hopsie_schema.sql en el SQL Editor de Supabase (crea las tablas hopsie_*)
     después hopsie_migracion_clientes.sql (clientes habitué/VIP, cuentas de barra y cuentas sin mesa)
     y por último hopsie_migracion_v3.sql (confirmación del pedido antes de que llegue a cocina/barra).
  3) Secrets de Streamlit Cloud:

        [supabase]                        # Pañol (anon public)
        url = "https://TU-PROYECTO.supabase.co"
        key = "TU_ANON_KEY"

        [hopsie_supabase]                 # HOPSIE (service_role: sus tablas tienen RLS y no son públicas)
        url = "https://TU-PROYECTO.supabase.co"
        key = "TU_SERVICE_ROLE_KEY"

        [mercadopago]                     # opcional: QR dinámico con el monto exacto
        access_token = "APP_USR-..."

        [whatsapp]                        # opcional: envío automático del ticket .png al cliente (WhatsApp Cloud API)
        token = "EAAG..."                  # token permanente de la app de Meta
        phone_id = "1234567890"            # ID del número de WhatsApp Business
        template = ""                     # (recomendado) plantilla aprobada con encabezado de IMAGEN; vacío = imagen libre (solo dentro de las 24 h)
        template_lang = "es_AR"
        template_vars = 0                 # variables del cuerpo de la plantilla: 1={{cliente}}  2=+{{total}}  3=+{{local}}

        [admin]                           # opcional: contraseña de rescate del administrador de Pañol
        password = "..."

  4) Logo de HOPSIE: hopsie_logo.png junto a este archivo
     (o subirlo desde HOPSIE → Admin → Apariencia).
  5) Logos de bancos/billeteras (opcional): carpeta logos/ con mercadopago.png, uala.png, naranjax.png,
     cuentadni.png, modo.png, bna.png, galicia.png, santander.png, bbva.png, macro.png, brubank.png,
     lemon.png (png/jpg/webp/svg). Si falta alguno se muestra una etiqueta de color.

requirements.txt:  streamlit  supabase  pillow  pandas  requests  qrcode[pil]
packages.txt   :  fonts-dejavu-core        (tipografía del ticket .png; si falta se usa una de respaldo)
"""

import base64
import hashlib
import hmac
import io
import json
import math
import os
import re
import secrets as pysecrets
import tempfile
import time
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from html import escape as esc
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from supabase import create_client

try:
    import qrcode
except ImportError:  # sin este paquete la app funciona igual, pero HOPSIE no puede generar QR
    qrcode = None

BASE_DIR = Path(__file__).resolve().parent
EXTS = ("png", "jpg", "jpeg", "webp", "svg")
MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "svg": "image/svg+xml"}


def _buscar_archivo(nombres, carpetas):
    for carpeta in carpetas:
        for n in nombres:
            for e in EXTS:
                p = carpeta / f"{n}.{e}"
                if p.exists():
                    return p
    return None


_LOGO_FILE = _buscar_archivo(["hopsie_logo", "logo_hopsie", "hopsie"],
                             [BASE_DIR, BASE_DIR / "assets", BASE_DIR / "logos"])
_HOP_ICON = "🍺"
if _LOGO_FILE and _LOGO_FILE.suffix.lower() != ".svg":
    try:
        _HOP_ICON = Image.open(_LOGO_FILE)
    except Exception:
        _HOP_ICON = "🍺"


# ─────────────────────────────────────────
# MÓDULOS (pestañas principales) Y CONFIGURACIÓN DE PÁGINA
# ─────────────────────────────────────────
MOD_PANOL, MOD_HOPSIE = "🔧 Pañol", "🍺 HOPSIE"
MODULOS = [MOD_PANOL, MOD_HOPSIE]

# La barra de módulos se inyecta ANTES de dibujar el selector, así se ve igual en Pañol y en HOPSIE
MODULE_BAR_CSS = """
.block-container [class*="st-key-nav_mod"] button{min-height:3rem !important;border-radius:999px !important;padding:.4rem 1.4rem !important;
  background:rgba(127,127,127,.14) !important;-webkit-backdrop-filter:blur(12px) saturate(160%);backdrop-filter:blur(12px) saturate(160%);
  border:2px solid var(--accent, #00E5CF) !important;box-shadow:0 6px 18px rgba(0,0,0,.25), inset 0 1px 0 rgba(255,255,255,.35) !important;}
.block-container [class*="st-key-nav_mod"] button p{font-size:1.1rem !important;font-weight:800 !important;color:var(--text, #fff) !important}
.block-container [class*="st-key-nav_mod"] button[kind="primary"]{background:var(--accent, linear-gradient(135deg,#FF2E93,#FF8A00)) !important;
  box-shadow:0 0 22px rgba(255,46,147,.45), inset 0 1px 0 rgba(255,255,255,.45) !important}
.block-container [class*="st-key-nav_mod"] button[kind="primary"] p{color:var(--on-accent, #fff) !important}
@media (max-width:640px){
  .st-key-modbar [data-testid="stHorizontalBlock"]{flex-wrap:wrap !important;gap:8px !important}
  .st-key-modbar [data-testid="stColumn"]{flex:1 1 calc(50% - 8px) !important;min-width:calc(50% - 8px) !important}
  .st-key-modbar [data-testid="stColumn"]:nth-child(3){display:none !important}
}
"""

if "app_modulo" not in st.session_state:  # primer ingreso: respeta  ?modulo=hopsie
    _qp = str(st.query_params.get("modulo", "")).strip().lower()
    st.session_state["app_modulo"] = MOD_HOPSIE if _qp == "hopsie" else MOD_PANOL

if st.session_state["app_modulo"] == MOD_HOPSIE:
    st.set_page_config(
        page_title="HOPSIE · Cerveza Artesanal",
        page_icon=_HOP_ICON,
        layout="wide",
        initial_sidebar_state="collapsed",
    )
else:
    st.set_page_config(
        page_title="Pañol — Control de stock",
        page_icon="🔧",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

# ─────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────
CATEGORIAS = ["herramienta", "material", "equipo", "consumible", "otro"]
NUEVA_SUBCAT_OPCION = "➕ Nueva subcategoría…"

# Campos propios del ítem que cada almacén puede ocultar si no los necesita
BASE_OPCIONALES = {
    "subcategoria": "Subcategoría",
    "numero_patrimonio": "N° de patrimonio",
    "minimo": "Stock mínimo",
    "ubicacion": "Ubicación",
    "descripcion": "Descripción",
}

# Tipos de columnas personalizadas
TIPOS = {
    "texto": "Texto",
    "numero": "Número",
    "fecha": "Fecha",
    "lista": "Lista de opciones",
    "si_no": "Sí / No",
}

FUENTES = ["IBM Plex Sans", "Inter", "DM Sans", "Source Sans 3", "Poppins"]

TEMAS = {
    "Claro": dict(
        scheme="light", bg="#F4F5F8", surface="#FFFFFF", surface2="#EEF0F5", border="#DCE0E8",
        text="#18202E", muted="#647085", ok="#12805A", ok_bg="#DFF3EA",
        warn="#A85F00", warn_bg="#FDEFD6", bad="#C0302F", bad_bg="#FBE3E3",
        shadow="0 1px 2px rgba(16,24,40,.05), 0 2px 6px rgba(16,24,40,.06)",
    ),
    "Oscuro": dict(
        scheme="dark", bg="#0E1117", surface="#161B25", surface2="#1E2431", border="#2B3345",
        text="#E7EAF1", muted="#8D96AA", ok="#4CD08B", ok_bg="#10301F",
        warn="#F0A04B", warn_bg="#33240F", bad="#FF7070", bad_bg="#381719",
        shadow="none",
    ),
}

CFG_DEFAULT = {
    "app_nombre": "Pañol",
    "app_subtitulo": "Control de stock",
    "color_acento": "#1F5FBF",
    "tema": "Claro",
    "fuente": "IBM Plex Sans",
    "logo_b64": None,  # None = usar iacilog.png si existe; "" = sin logo
}

# ─────────────────────────────────────────
# SUPABASE
# ─────────────────────────────────────────
@st.cache_resource
def get_supabase():
    if "supabase" not in st.secrets:
        return None
    url = st.secrets["supabase"].get("url", "").strip()
    key = st.secrets["supabase"].get("key", "").strip()
    if not url or not key or url == "https://XXXXXXXXXXXXXXXXXX.supabase.co":
        return None
    return create_client(url, key)


supabase = get_supabase()


def error_supabase_panol():
    st.error("⚠️ **No se pudo conectar a Supabase.** Verificá que los Secrets estén bien configurados.")
    st.markdown("""
    **Pasos para solucionarlo:**
    1. En Streamlit Cloud → **Manage app** → **Secrets**
    2. Asegurate de que el contenido sea exactamente:
    ```toml
    [supabase]
    url = "https://TU-PROYECTO.supabase.co"
    key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    ```
    3. La key debe ser la **anon public** (en Supabase: *Project Settings → API → anon public*)
    4. Guardá los Secrets y hacé **Reboot app**
    """)

# ─────────────────────────────────────────
# HELPERS GENERALES
# ─────────────────────────────────────────
def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_clave(clave: str) -> str:
    """Hash de las contraseñas de almacén (compatible con las ya guardadas)."""
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()


def slugificar(nombre: str) -> str:
    s = nombre.strip().lower()
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "_", "-"):
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "almacen"


def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    return None


def procesar_logo(archivo, max_px=480):
    """Convierte la imagen subida a PNG acotado y la devuelve en base64."""
    img = Image.open(archivo).convert("RGBA")
    img.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


try:
    TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")
except Exception:  # si el servidor no tiene base de zonas horarias
    TZ_AR = timezone(timedelta(hours=-3))


def ahora_ar():
    """Hora actual de Argentina (sin zona), redondeada al minuto."""
    return datetime.now(TZ_AR).replace(tzinfo=None, second=0, microsecond=0)


def parse_dt(v):
    """Convierte lo que devuelve Supabase ('2026-10-08T14:30:00') a datetime."""
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("T", " ")[:19])
    except ValueError:
        return None


def fmt_dt(v):
    d = parse_dt(v)
    return d.strftime("%d/%m/%Y %H:%M") if d else "—"


def flash(tipo, texto, toast=False):
    """Mensaje que se muestra tras el próximo rerun. Con toast=True aparece como aviso flotante
    (útil cuando la persona está más abajo en la página)."""
    if toast:
        st.session_state.toast = texto
    else:
        st.session_state.msg = (tipo, texto)


# ─────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────
_defaults = {
    "almacen_id": None,
    "autenticado": False,     # sesión de administración del almacén activo
    "admin_global": False,    # sesión del administrador general
    "vista": None,            # None | "config"
    "msg": None,              # ("tipo", "texto")
    "toast": None,
}
for _k, _v in _defaults.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ─────────────────────────────────────────
# CONFIGURACIÓN GLOBAL (tabla paniol_config)
# ─────────────────────────────────────────
@st.cache_data(ttl=10)
def get_config_db():
    """Devuelve (dict de config, migración_ok)."""
    try:
        res = supabase.table("paniol_config").select("clave,valor").execute()
        supabase.table("paniol_items").select("extras,prestable").limit(1).execute()
        supabase.table("paniol_columnas").select("id").limit(1).execute()
        supabase.table("paniol_prestamos").select("id").limit(1).execute()
        return {r["clave"]: r["valor"] for r in (res.data or [])}, True
    except Exception:
        return {}, False


def get_cfg():
    db, _ = get_config_db()
    cfg = dict(CFG_DEFAULT)
    for k in CFG_DEFAULT:
        if k in db and db[k] is not None:
            cfg[k] = db[k]
    return cfg


def guardar_config(pares: dict):
    filas = [{"clave": k, "valor": v} for k, v in pares.items()]
    supabase.table("paniol_config").upsert(filas).execute()
    get_config_db.clear()


def borrar_config(claves):
    for k in claves:
        supabase.table("paniol_config").delete().eq("clave", k).execute()
    get_config_db.clear()


def logo_app(cfg):
    logo = cfg.get("logo_b64")
    if logo is None:
        return get_base64_image("iacilog.png")
    return logo or None


# ─────────────────────────────────────────
# ADMINISTRADOR GENERAL
# ─────────────────────────────────────────
def _hash_admin(clave: str, salt_hex: str = None) -> str:
    salt_hex = salt_hex or os.urandom(16).hex()
    dig = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), bytes.fromhex(salt_hex), 200_000).hex()
    return f"pbkdf2${salt_hex}${dig}"


def _clave_admin_secrets() -> str:
    """Contraseña opcional definida en Secrets: [admin] password = "..." (sirve de rescate)."""
    try:
        return str(st.secrets["admin"]["password"])
    except Exception:
        return ""


def _hash_admin_guardado():
    return get_config_db()[0].get("admin_clave_hash")


def admin_configurada() -> bool:
    return bool(_clave_admin_secrets() or _hash_admin_guardado())


def verificar_admin(clave: str) -> bool:
    if not clave:
        return False
    sec = _clave_admin_secrets()
    if sec and hmac.compare_digest(clave.encode("utf-8"), sec.encode("utf-8")):
        return True
    guardado = _hash_admin_guardado()
    if not guardado:
        return False
    try:
        _, salt_hex, dig = guardado.split("$")
        calc = _hash_admin(clave, salt_hex).split("$")[2]
        return hmac.compare_digest(calc, dig)
    except Exception:
        return False


def definir_clave_admin(clave: str):
    guardar_config({"admin_clave_hash": _hash_admin(clave)})


# ─────────────────────────────────────────
# ESTILOS
# ─────────────────────────────────────────
def _hex_valido(h):
    return isinstance(h, str) and len(h) == 7 and h.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in h[1:])


def _texto_sobre(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#FFFFFF" if (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.6 else "#111827"


CSS_BASE = """
.stApp, [data-testid="stAppViewContainer"] { background: var(--bg) !important; color: var(--text); font-family: var(--font), system-ui, sans-serif; }
[data-testid="stHeader"] { background: var(--bg) !important; }
#MainMenu, footer, [data-testid="stDecoration"], [data-testid="stAppDeployButton"] { display: none !important; }
.block-container { padding-top: 4.5rem !important; padding-bottom: 4rem !important; max-width: 1180px; }

h1, h2, h3, h4, h5 { font-family: var(--font), system-ui, sans-serif !important; color: var(--text) !important; font-weight: 600 !important; letter-spacing: -0.01em; }
h4 { font-size: 1.15rem !important; }
h5 { font-size: 1rem !important; }
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li, [data-testid="stWidgetLabel"] p, label, label p { color: var(--text); }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: var(--muted) !important; }
button, input, textarea { font-family: var(--font), system-ui, sans-serif !important; }

/* Campos */
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {
    background: var(--surface) !important; border-color: var(--border) !important; border-radius: 8px !important;
}
[data-baseweb="input"] input, [data-baseweb="base-input"] input, textarea {
    color: var(--text) !important; -webkit-text-fill-color: var(--text) !important; background: transparent !important;
}
[data-baseweb="select"] * { color: var(--text) !important; }
[data-baseweb="select"] svg { fill: var(--muted) !important; }
::placeholder { color: var(--muted) !important; opacity: .8 !important; -webkit-text-fill-color: var(--muted) !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="base-input"]:focus-within, [data-baseweb="select"]:focus-within > div {
    border-color: var(--accent) !important; box-shadow: 0 0 0 3px var(--accent-soft) !important;
}
[data-baseweb="popover"] ul, [data-baseweb="menu"] { background: var(--surface) !important; }
[data-baseweb="popover"] li, [data-baseweb="menu"] li { color: var(--text) !important; background: var(--surface) !important; }
[data-baseweb="popover"] li:hover, [data-baseweb="menu"] li:hover, [data-baseweb="popover"] li[aria-selected="true"] { background: var(--surface2) !important; }
[data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"] { background: var(--surface2) !important; color: var(--text) !important; }
[data-testid="stFileUploaderDropzone"] { background: var(--surface) !important; border: 1px dashed var(--border) !important; border-radius: 10px !important; }
[data-testid="stFileUploaderDropzone"] span, [data-testid="stFileUploaderDropzone"] small { color: var(--muted) !important; }

[data-testid="stDateInputField"], [data-testid="stTimeInputTimeDisplay"] {
    background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 8px !important;
}
[data-testid="stDateInputField"] *, [data-testid="stTimeInputTimeDisplay"] * {
    color: var(--text) !important; -webkit-text-fill-color: var(--text) !important; background: transparent !important;
}
[data-testid="stDateInputField"]:focus-within, [data-testid="stTimeInputTimeDisplay"]:focus-within {
    border-color: var(--accent) !important; box-shadow: 0 0 0 3px var(--accent-soft) !important;
}
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stExpander"], [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stExpander"] details,
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .pn-row) [data-testid="stExpander"], [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .pn-row) [data-testid="stExpander"] details {
    background: var(--surface2) !important; border-color: transparent !important;
}

/* Botones */
.stButton button, [data-testid^="stBaseButton"] {
    border-radius: 8px !important; font-weight: 600 !important; font-size: 14px !important;
    min-height: 2.5rem; transition: border-color .15s, background .15s, box-shadow .15s !important;
}
.stButton button[kind="secondary"], [data-testid="stBaseButton-secondary"] {
    background: var(--surface) !important; color: var(--text) !important; border: 1px solid var(--border) !important;
}
.stButton button[kind="secondary"]:hover, [data-testid="stBaseButton-secondary"]:hover {
    border-color: var(--accent) !important; color: var(--accent) !important;
}
.stButton button[kind="primary"], [data-testid="stBaseButton-primary"] {
    background: var(--accent) !important; color: var(--on-accent) !important; border: 1px solid var(--accent) !important;
}
.stButton button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover { filter: brightness(1.08); box-shadow: 0 2px 8px var(--accent-soft); }
.stButton button:focus-visible { outline: 2px solid var(--accent) !important; outline-offset: 2px; }
.stButton button p, [data-testid^="stBaseButton"] p { color: inherit !important; }

/* Pestañas */
[data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid var(--border); }
[data-baseweb="tab"] { color: var(--muted) !important; font-weight: 600 !important; padding: 10px 18px !important; background: transparent !important; }
[data-baseweb="tab"] p { color: inherit !important; font-weight: 600; }
[data-baseweb="tab"][aria-selected="true"] { color: var(--accent) !important; }
[data-baseweb="tab-highlight"] { background: var(--accent) !important; height: 2px !important; }
[data-baseweb="tab-border"] { background: transparent !important; }

/* Expanders, alertas, contenedores */
[data-testid="stExpander"], [data-testid="stExpander"] details { background: var(--surface) !important; border-color: var(--border) !important; border-radius: 10px !important; }
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary p { color: var(--text) !important; }
[data-testid="stAlert"] { border-radius: 10px !important; }
[data-testid="stAlert"] *, [data-testid="stAlert"] p { color: var(--text) !important; }
[data-testid="stVerticalBlockBorderWrapper"], [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .pn-row) { background: var(--surface); border-color: var(--border) !important; border-radius: 12px !important; box-shadow: var(--shadow); }
hr, .pn-divider { border: none; border-top: 1px solid var(--border); margin: 18px 0; }

/* Barra superior */
.pn-top { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; padding: 0 0 18px; margin-bottom: 18px; border-bottom: 1px solid var(--border); }
.pn-brand { display: flex; align-items: center; gap: 14px; }
.pn-logo-chip { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 6px 8px; display: flex; align-items: center; justify-content: center; }
.pn-logo-chip img { display: block; height: 42px; width: auto; max-width: 170px; object-fit: contain; }
.pn-title { font-size: 21px; font-weight: 700; line-height: 1.15; color: var(--text); }
.pn-sub { font-size: 13px; color: var(--muted); margin-top: 2px; }
.pn-pill { display: inline-flex; align-items: center; gap: 9px; background: var(--surface); border: 1px solid var(--border); border-radius: 999px; padding: 6px 16px 6px 7px; font-size: 14px; font-weight: 600; color: var(--text); }
.pn-pill-media { width: 26px; height: 26px; border-radius: 50%; background: var(--surface2); display: flex; align-items: center; justify-content: center; font-size: 15px; overflow: hidden; }
.pn-pill-media.has-logo { background: #fff; }
.pn-pill-media img { width: 100%; height: 100%; object-fit: contain; }

/* Indicadores */
.pn-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 20px; }
.pn-kpi { background: var(--surface); border: 1px solid var(--border); border-left: 4px solid var(--accent); border-radius: 12px; padding: 14px 18px; box-shadow: var(--shadow); }
.pn-kpi.warn { border-left-color: var(--warn); }
.pn-kpi.ok { border-left-color: var(--ok); }
.pn-kpi-num { font-size: 26px; font-weight: 700; line-height: 1.1; color: var(--text); font-variant-numeric: tabular-nums; }
.pn-kpi.warn .pn-kpi-num { color: var(--warn); }
.pn-kpi.ok .pn-kpi-num { color: var(--ok); }
.pn-kpi-lbl { font-size: 13px; color: var(--muted); margin-top: 2px; }

/* Tablas */
.pn-table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); box-shadow: var(--shadow); }
.pn-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.pn-table th { text-align: left; font-size: 12px; font-weight: 600; color: var(--muted); padding: 12px 16px; background: var(--surface2); border-bottom: 1px solid var(--border); white-space: nowrap; }
.pn-table td { padding: 12px 16px; border-bottom: 1px solid var(--border); color: var(--text); vertical-align: middle; }
.pn-table tbody tr:last-child td { border-bottom: none; }
.pn-table tbody tr:hover td { background: var(--surface2); }
.pn-table tr.pn-group td { background: var(--accent-soft) !important; color: var(--accent); font-weight: 600; font-size: 13px; padding: 8px 16px; }
.pn-name { font-weight: 600; color: var(--text); }
.pn-muted { color: var(--muted); font-size: 13px; }
.pn-chip { display: inline-block; background: var(--surface2); color: var(--text); border: 1px solid var(--border); padding: 2px 9px; border-radius: 6px; font-size: 12px; font-weight: 500; }
.pn-num { font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
.pn-ok { color: var(--ok); } .pn-low { color: var(--warn); } .pn-zero { color: var(--bad); }
.pn-badge { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 999px; white-space: nowrap; }
.pn-badge::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.pn-badge-ok { background: var(--ok-bg); color: var(--ok); }
.pn-badge-low { background: var(--warn-bg); color: var(--warn); }
.pn-badge-agotado { background: var(--bad-bg); color: var(--bad); }
.pn-badge-loan { background: var(--accent-soft); color: var(--accent); }
.pn-loan { font-size: 12px; color: var(--muted); margin-top: 4px; line-height: 1.35; }
.pn-loan b { color: var(--text); font-weight: 600; }
/* Stock: encabezado y filas con la misma grilla de columnas */
.pn-head, .pn-row { display: grid; column-gap: 16px; align-items: center; }
.pn-head { font-size: 12px; font-weight: 600; color: var(--muted); padding: 2px 0; }
.pn-row { padding: 2px 0; }
.pn-cell { min-width: 0; overflow-wrap: anywhere; font-size: 14px; color: var(--text); }
.pn-cell-lbl { display: none; font-size: 11px; font-weight: 600; color: var(--muted); margin-bottom: 3px; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.pn-head), [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .pn-head) { background: var(--surface2) !important; box-shadow: 0 6px 12px -8px rgba(16, 24, 40, .45) !important; }
/* Encabezado flotante: queda fijo debajo de la barra superior al bajar por el stock.
   Se fija el ENVOLTORIO del contenedor (hijo directo de la lista), no el contenedor interno. */
[data-testid="stTabs"], [data-testid="stTabPanel"], [data-baseweb="tab-panel"] { overflow: visible !important; }
[data-testid="stLayoutWrapper"]:has(> [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] .pn-head), [data-testid="stLayoutWrapper"].st-key-pn_head, [data-testid="stVerticalBlockBorderWrapper"]:has(.pn-head) {
    position: sticky !important; top: 3.75rem; z-index: 100; }
[data-testid="stLayoutWrapper"]:has(> [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] .pn-head)::before { content: ""; position: absolute; left: 0; right: 0; top: -20px; height: 20px; background: var(--bg); pointer-events: none; }
/* Botón flotante de búsqueda (redondo, arriba del logo/botón de Streamlit) */
.st-key-pn_fab { position: fixed !important; right: 22px; bottom: 104px; z-index: 1000; width: auto !important; }
div.st-key-pn_fab .stButton button, div.st-key-pn_fab [data-testid^="stBaseButton"] {
    width: 56px !important; height: 56px !important; min-height: 56px !important; padding: 0 !important;
    border-radius: 50% !important; border: none !important;
    background-color: var(--accent) !important; background-image: var(--fab-icon) !important;
    background-repeat: no-repeat !important; background-position: center !important; background-size: 28px 28px !important;
    box-shadow: 0 8px 22px rgba(0, 0, 0, .28) !important; color: transparent !important;
}
div.st-key-pn_fab .stButton button:hover, div.st-key-pn_fab [data-testid^="stBaseButton"]:hover {
    transform: scale(1.07); filter: brightness(1.08); border: none !important;
}
div.st-key-pn_fab .stButton button *, div.st-key-pn_fab [data-testid^="stBaseButton"] * { display: none !important; }
div[role="dialog"] { background: var(--bg) !important; color: var(--text); }
@media (max-width: 900px) {
    [data-testid="stLayoutWrapper"]:has(> [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] .pn-head), [data-testid="stLayoutWrapper"].st-key-pn_head, [data-testid="stVerticalBlockBorderWrapper"]:has(.pn-head) { display: none !important; }
    .pn-head { display: none; }
    .pn-row { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)) !important; row-gap: 12px; }
    .pn-cell-lbl { display: block; }
}
.pn-group-title { display: flex; align-items: center; gap: 10px; font-size: 13px; font-weight: 600; color: var(--accent); margin: 20px 0 4px; }
.pn-group-title::after { content: ""; flex: 1; height: 1px; background: var(--border); }
.pn-section { font-size: 13px; font-weight: 600; color: var(--muted); margin: 18px 0 8px; }

/* Selección de almacén */
.alm-head { display: flex; align-items: center; gap: 14px; padding: 4px 2px 10px; }
.alm-media { width: 56px; height: 56px; flex: none; border-radius: 12px; background: var(--surface2); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; font-size: 28px; overflow: hidden; }
.alm-media.has-logo { background: #fff; }
.alm-media img { width: 100%; height: 100%; object-fit: contain; padding: 4px; }
.alm-nombre { font-size: 16px; font-weight: 600; color: var(--text); line-height: 1.25; }

/* Login */
.pn-login { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 28px; text-align: center; max-width: 420px; margin: 0 auto; box-shadow: var(--shadow); }
.pn-login-title { font-size: 17px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
.pn-login-sub { font-size: 13px; color: var(--muted); }

/* Historial */
.pn-mov-ent { background: var(--ok-bg); color: var(--ok); }
.pn-mov-sal { background: var(--warn-bg); color: var(--warn); }

::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

@media (max-width: 720px) {
    .pn-kpis { grid-template-columns: 1fr; }
    .pn-title { font-size: 18px; }
}

"""


def inyectar_css(cfg):
    t = TEMAS.get(cfg["tema"], TEMAS["Claro"])
    acento = cfg["color_acento"] if _hex_valido(cfg["color_acento"]) else CFG_DEFAULT["color_acento"]
    fuente = cfg["fuente"] if cfg["fuente"] in FUENTES else CFG_DEFAULT["fuente"]
    url = f"https://fonts.googleapis.com/css2?family={fuente.replace(' ', '+')}:wght@400;500;600;700&display=swap"
    variables = {
        "bg": t["bg"], "surface": t["surface"], "surface2": t["surface2"], "border": t["border"],
        "text": t["text"], "muted": t["muted"], "ok": t["ok"], "ok-bg": t["ok_bg"],
        "warn": t["warn"], "warn-bg": t["warn_bg"], "bad": t["bad"], "bad-bg": t["bad_bg"],
        "shadow": t["shadow"], "accent": acento, "accent-soft": acento + "1F",
        "on-accent": _texto_sobre(acento), "font": f"'{fuente}'",
    }
    trazo = _texto_sobre(acento).replace("#", "%23")
    variables["fab-icon"] = (
        'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 24 24\' fill=\'none\' '
        f'stroke=\'{trazo}\' stroke-width=\'2.4\' stroke-linecap=\'round\' stroke-linejoin=\'round\'%3E'
        '%3Ccircle cx=\'10.5\' cy=\'10.5\' r=\'6.5\'/%3E%3Cline x1=\'15.5\' y1=\'15.5\' x2=\'21\' y2=\'21\'/%3E%3C/svg%3E")')
    root = ":root{" + ";".join(f"--{k}:{v}" for k, v in variables.items()) + f";color-scheme:{t['scheme']}" + "}"
    st.markdown(f"<style>@import url('{url}');{root}{CSS_BASE}</style>", unsafe_allow_html=True)


# ─────────────────────────────────────────
# HELPERS DE DB — ALMACENES
# ─────────────────────────────────────────
@st.cache_data(ttl=10)
def get_almacenes():
    try:
        res = (supabase.table("paniol_almacenes")
               .select("id,nombre,slug,icono,creado,logo_b64,config").order("nombre").execute())
        return res.data or []
    except Exception as e:
        st.error(f"❌ Error al obtener almacenes: `{type(e).__name__}`")
        return []


def almacen_actual():
    for a in get_almacenes():
        if a["id"] == st.session_state.almacen_id:
            return a
    return None


def crear_almacen(nombre, icono, clave, logo_b64=None):
    slug_base = slugificar(nombre)
    slug = slug_base
    existentes = {a["slug"] for a in get_almacenes()}
    n = 2
    while slug in existentes:
        slug = f"{slug_base}-{n}"
        n += 1
    fila = {
        "nombre": nombre.strip(),
        "slug": slug,
        "icono": icono or "📦",
        "clave_hash": hash_clave(clave),
    }
    if logo_b64:
        fila["logo_b64"] = logo_b64
    res = supabase.table("paniol_almacenes").insert(fila).execute()
    get_almacenes.clear()
    return res.data[0] if res.data else None


def actualizar_almacen(almacen_id, **campos):
    supabase.table("paniol_almacenes").update(campos).eq("id", almacen_id).execute()
    get_almacenes.clear()


def verificar_clave_almacen(almacen_id, clave) -> bool:
    try:
        res = supabase.table("paniol_almacenes").select("clave_hash").eq("id", almacen_id).single().execute()
        if not res.data:
            return False
        return res.data["clave_hash"] == hash_clave(clave)
    except Exception:
        return False


def clave_valida(almacen_id, clave) -> bool:
    """La contraseña del almacén o la del administrador general."""
    return verificar_clave_almacen(almacen_id, clave) or verificar_admin(clave)


def eliminar_almacen(almacen_id):
    # Las tablas relacionadas tienen ON DELETE CASCADE: se borran ítems,
    # movimientos, unidades y columnas personalizadas del almacén.
    supabase.table("paniol_almacenes").delete().eq("id", almacen_id).execute()
    get_almacenes.clear()
    invalidar_cache()


def campos_ocultos(alm) -> set:
    return set((alm.get("config") or {}).get("ocultos", []))


# ─────────────────────────────────────────
# HELPERS DE DB — ÍTEMS / MOVIMIENTOS / UNIDADES / COLUMNAS
# ─────────────────────────────────────────
@st.cache_data(ttl=10)
def get_items(almacen_id):
    try:
        res = (supabase.table("paniol_items")
               .select("*").eq("almacen_id", almacen_id)
               .order("categoria").order("subcategoria").order("nombre").execute())
        return res.data or []
    except Exception as e:
        st.error(f"❌ Error al conectar con Supabase: `{type(e).__name__}`\n\nVerificá tu URL y key en los Secrets.")
        st.stop()


@st.cache_data(ttl=10)
def get_movimientos(almacen_id):
    try:
        res = (supabase.table("paniol_movimientos")
               .select("*").eq("almacen_id", almacen_id)
               .order("fecha", desc=True).limit(300).execute())
        return res.data or []
    except Exception as e:
        st.error(f"❌ Error al obtener historial: `{type(e).__name__}`")
        return []


@st.cache_data(ttl=10)
def get_unidades(id_item=None):
    try:
        q = supabase.table("paniol_unidades").select("*").order("marca")
        if id_item is not None:
            q = q.eq("id_item", id_item)
        res = q.execute()
        return res.data or []
    except Exception as e:
        st.error(f"❌ Error al obtener unidades: `{type(e).__name__}`")
        return []


@st.cache_data(ttl=10)
def get_columnas(almacen_id):
    try:
        res = (supabase.table("paniol_columnas").select("*").eq("almacen_id", almacen_id)
               .order("orden").order("id").execute())
        return res.data or []
    except Exception as e:
        st.error(f"❌ Error al obtener columnas: `{type(e).__name__}`")
        return []


@st.cache_data(ttl=10)
def get_prestamos_abiertos(almacen_id):
    try:
        res = (supabase.table("paniol_prestamos").select("*").eq("almacen_id", almacen_id)
               .is_("devuelto_en", "null").execute())
        return res.data or []
    except Exception as e:
        st.error(f"❌ Error al obtener préstamos: `{type(e).__name__}`")
        return []


@st.cache_data(ttl=10)
def get_prestamos_historial(almacen_id):
    try:
        res = (supabase.table("paniol_prestamos").select("*").eq("almacen_id", almacen_id)
               .order("prestado_en", desc=True).limit(300).execute())
        return res.data or []
    except Exception as e:
        st.error(f"❌ Error al obtener el historial de préstamos: `{type(e).__name__}`")
        return []


def invalidar_cache():
    get_items.clear()
    get_movimientos.clear()
    get_unidades.clear()
    get_columnas.clear()
    get_prestamos_abiertos.clear()
    get_prestamos_historial.clear()


def personas_conocidas(almacen_id):
    """Personas a las que ya se les prestó algo en este almacén (alimenta el menú de selección)."""
    nombres = {}
    for p in get_prestamos_abiertos(almacen_id) + get_prestamos_historial(almacen_id):
        n = (p.get("persona") or "").strip()
        if n:
            nombres.setdefault(n.lower(), n)
    return sorted(nombres.values(), key=str.lower)


def prestar(almacen_id, item, persona, cantidad, cuando, unidad=None):
    """Registra un préstamo de `cantidad` unidades del ítem. `unidad` (opcional) identifica una marca/patrimonio."""
    supabase.table("paniol_prestamos").insert({
        "almacen_id": almacen_id, "id_item": item["id"],
        "id_unidad": unidad["id"] if unidad else None,
        "cantidad": 1 if unidad else int(cantidad),
        "nombre_item": item["nombre"],
        "marca": (unidad.get("marca") or "") if unidad else "",
        "numero_patrimonio": (unidad.get("numero_patrimonio") or "") if unidad else "",
        "persona": persona, "prestado_en": cuando.strftime("%Y-%m-%d %H:%M:00"),
    }).execute()
    invalidar_cache()


def devolver_prestamo(prestamo, cantidad, cuando):
    """Devuelve todo el préstamo o solo una parte (el resto sigue en curso)."""
    total = int(prestamo.get("cantidad") or 1)
    fin = cuando.strftime("%Y-%m-%d %H:%M:00")
    if cantidad >= total:
        supabase.table("paniol_prestamos").update({"devuelto_en": fin}).eq("id", prestamo["id"]).execute()
    else:
        supabase.table("paniol_prestamos").update({"cantidad": total - cantidad}).eq("id", prestamo["id"]).execute()
        supabase.table("paniol_prestamos").insert({
            "almacen_id": prestamo["almacen_id"], "id_item": prestamo.get("id_item"),
            "id_unidad": prestamo.get("id_unidad"), "cantidad": cantidad,
            "nombre_item": prestamo.get("nombre_item"), "marca": prestamo.get("marca"),
            "numero_patrimonio": prestamo.get("numero_patrimonio"), "persona": prestamo.get("persona"),
            "prestado_en": prestamo.get("prestado_en"), "devuelto_en": fin,
        }).execute()
    invalidar_cache()


def agregar_item(almacen_id, datos: dict):
    supabase.table("paniol_items").insert({"almacen_id": almacen_id, **datos}).execute()
    invalidar_cache()


def editar_item(id_, datos: dict):
    supabase.table("paniol_items").update(datos).eq("id", id_).execute()
    invalidar_cache()


def eliminar_item(id_):
    supabase.table("paniol_items").delete().eq("id", id_).execute()
    invalidar_cache()


def agregar_unidad(id_item, marca, numero_patrimonio):
    supabase.table("paniol_unidades").insert({
        "id_item": id_item, "marca": marca, "numero_patrimonio": numero_patrimonio,
    }).execute()
    invalidar_cache()


def eliminar_unidad(id_unidad):
    # Los préstamos que la referenciaban quedan como préstamos por cantidad (conservan marca y patrimonio)
    supabase.table("paniol_prestamos").update({"id_unidad": None}).eq("id_unidad", id_unidad).execute()
    supabase.table("paniol_unidades").delete().eq("id", id_unidad).execute()
    invalidar_cache()


def registrar_movimiento(almacen_id, item, tipo, cantidad, responsable):
    nuevo = item["cantidad"] + cantidad if tipo == "entrada" else item["cantidad"] - cantidad
    supabase.table("paniol_items").update({"cantidad": nuevo}).eq("id", item["id"]).execute()
    supabase.table("paniol_movimientos").insert({
        "almacen_id": almacen_id,
        "id_item": item["id"], "nombre_item": item["nombre"],
        "tipo": tipo, "cantidad": cantidad,
        "responsable": responsable or "—",
        "stock_resultante": nuevo,
        "fecha": ts(),
    }).execute()
    invalidar_cache()
    return nuevo


def agregar_columna(almacen_id, nombre, tipo, opciones, orden):
    supabase.table("paniol_columnas").insert({
        "almacen_id": almacen_id, "nombre": nombre, "tipo": tipo,
        "opciones": opciones or None, "orden": orden,
    }).execute()
    get_columnas.clear()


def editar_columna(id_, nombre, tipo, opciones):
    supabase.table("paniol_columnas").update({
        "nombre": nombre, "tipo": tipo, "opciones": opciones or None,
    }).eq("id", id_).execute()
    get_columnas.clear()


def eliminar_columna(id_):
    supabase.table("paniol_columnas").delete().eq("id", id_).execute()
    get_columnas.clear()


def mover_columna(columnas, idx, delta):
    destino = idx + delta
    if destino < 0 or destino >= len(columnas):
        return
    ids = [c["id"] for c in columnas]
    ids[idx], ids[destino] = ids[destino], ids[idx]
    for orden, id_ in enumerate(ids):
        supabase.table("paniol_columnas").update({"orden": orden}).eq("id", id_).execute()
    get_columnas.clear()


# ─────────────────────────────────────────
# COLUMNAS PERSONALIZADAS — widgets y formato
# ─────────────────────────────────────────
def _vacio(v):
    return v is None or v == ""


def opciones_de(col):
    return [o.strip() for o in (col.get("opciones") or "").split(",") if o.strip()]


def widget_columna(col, valor, key):
    """Dibuja el campo de una columna personalizada y devuelve el valor ingresado."""
    tipo = col.get("tipo") or "texto"
    etiqueta = col["nombre"]

    if tipo == "numero":
        try:
            actual = float(valor) if not _vacio(valor) else None
        except (TypeError, ValueError):
            actual = None
        r = st.number_input(etiqueta, value=actual, format="%g", key=key)
        if r is None:
            return None
        return int(r) if float(r).is_integer() else r

    if tipo == "fecha":
        try:
            actual = date.fromisoformat(str(valor)) if not _vacio(valor) else None
        except ValueError:
            actual = None
        r = st.date_input(etiqueta, value=actual, format="DD/MM/YYYY", key=key)
        return r.isoformat() if r else None

    if tipo == "lista":
        opts = opciones_de(col)
        if not _vacio(valor) and valor not in opts:
            opts.append(valor)  # no perder valores viejos si se cambió la lista
        todas = ["—"] + opts
        idx = todas.index(valor) if valor in todas else 0
        r = st.selectbox(etiqueta, todas, index=idx, key=key)
        return None if r == "—" else r

    if tipo == "si_no":
        todas = ["—", "Sí", "No"]
        idx = todas.index(valor) if valor in todas else 0
        r = st.selectbox(etiqueta, todas, index=idx, key=key)
        return None if r == "—" else r

    r = st.text_input(etiqueta, value=str(valor) if not _vacio(valor) else "", key=key)
    return r.strip() or None


def formulario_extras(columnas, extras_actuales, prefijo):
    """Dibuja los campos de todas las columnas personalizadas. Devuelve {id_columna: valor}."""
    nuevos = {}
    if not columnas:
        return nuevos
    st.markdown("<div class='pn-section'>Datos adicionales</div>", unsafe_allow_html=True)
    cols_ui = st.columns(2)
    for n, c in enumerate(columnas):
        with cols_ui[n % 2]:
            k = str(c["id"])
            nuevos[k] = widget_columna(c, (extras_actuales or {}).get(k), f"{prefijo}_x_{c['id']}")
    return nuevos


def combinar_extras(base, nuevos):
    out = dict(base or {})
    for k, v in nuevos.items():
        if _vacio(v):
            out.pop(k, None)
        else:
            out[k] = v
    return out


def fmt_extra(col, v):
    if _vacio(v):
        return "—"
    tipo = col.get("tipo")
    if tipo == "fecha":
        try:
            return date.fromisoformat(str(v)).strftime("%d/%m/%Y")
        except ValueError:
            pass
    if tipo == "numero":
        try:
            f = float(v)
            return str(int(f)) if f.is_integer() else f"{f:g}"
        except (TypeError, ValueError):
            pass
    return str(v)


# ─────────────────────────────────────────
# SUBCATEGORÍAS
# ─────────────────────────────────────────
def subcategorias_de(items, categoria):
    subs = {i.get("subcategoria") or "" for i in items if i.get("categoria") == categoria}
    subs.discard("")
    return sorted(subs)


def selector_subcategoria(items, categoria, valor_actual="", key_prefix=""):
    """Selectbox con las subcategorías ya usadas en la categoría, más la opción de crear una nueva."""
    existentes = subcategorias_de(items, categoria)
    opciones = ["(sin subcategoría)"] + existentes + [NUEVA_SUBCAT_OPCION]

    if valor_actual and valor_actual in existentes:
        idx = opciones.index(valor_actual)
    elif valor_actual:
        idx = len(opciones) - 1
    else:
        idx = 0

    elegido = st.selectbox("Subcategoría", opciones, index=idx, key=f"{key_prefix}_subcat_sel")

    if elegido == NUEVA_SUBCAT_OPCION:
        nueva = st.text_input(
            "Nombre de la nueva subcategoría",
            value=valor_actual if (valor_actual and valor_actual not in existentes) else "",
            placeholder="ej: Medición, Redes, Protección personal",
            key=f"{key_prefix}_subcat_nueva",
        )
        return nueva.strip()
    if elegido == "(sin subcategoría)":
        return ""
    return elegido


# ─────────────────────────────────────────
# COMPONENTES VISUALES
# ─────────────────────────────────────────
def brand_html(cfg):
    logo = logo_app(cfg)
    chip = (f'<div class="pn-logo-chip"><img src="data:image/png;base64,{logo}" alt=""></div>' if logo else "")
    return (f'<div class="pn-brand">{chip}<div>'
            f'<div class="pn-title">{esc(cfg["app_nombre"])}</div>'
            f'<div class="pn-sub">{esc(cfg["app_subtitulo"])}</div></div></div>')


def media_almacen(a):
    if a.get("logo_b64"):
        return f'<div class="alm-media has-logo"><img src="data:image/png;base64,{a["logo_b64"]}" alt=""></div>'
    return f'<div class="alm-media">{esc(a.get("icono") or "📦")}</div>'


def pill_almacen(a):
    if a.get("logo_b64"):
        media = f'<span class="pn-pill-media has-logo"><img src="data:image/png;base64,{a["logo_b64"]}" alt=""></span>'
    else:
        media = f'<span class="pn-pill-media">{esc(a.get("icono") or "📦")}</span>'
    return f'<div class="pn-pill">{media}{esc(a["nombre"])}</div>'


def mostrar_flash():
    if st.session_state.msg:
        tipo, texto = st.session_state.msg
        {"ok": st.success, "error": st.error, "warn": st.warning}.get(tipo, st.info)(texto)
        st.session_state.msg = None


def etiqueta_unidad(u):
    return f"{u.get('marca') or 'Sin marca'} · {u.get('numero_patrimonio') or 'sin patrimonio'}"


def detalle_prestamo(p):
    partes = [x for x in (p.get("marca"), p.get("numero_patrimonio")) if x]
    if partes:
        return " · ".join(partes)
    cant = int(p.get("cantidad") or 1)
    return f"×{cant}" if cant > 1 else ""


def render_tabla(items, columnas, ocultos, filtro="", almacen_id=None):
    unidades_por_item = {}
    for u in get_unidades():
        unidades_por_item.setdefault(u["id_item"], []).append(u)
    prest_por_item = {}
    for p in get_prestamos_abiertos(almacen_id):
        prest_por_item.setdefault(p["id_item"], []).append(p)

    def es_prestable(i):
        return bool(i.get("prestable")) or bool(prest_por_item.get(i["id"]))

    def n_prestados(i):
        return sum(int(p.get("cantidad") or 1) for p in prest_por_item.get(i["id"], []))

    if filtro:
        f = filtro.lower()

        def coincide(i):
            extras = i.get("extras") or {}
            partes = [i["nombre"], i.get("categoria"), i.get("subcategoria"), i.get("ubicacion"),
                      i.get("numero_patrimonio"), i.get("descripcion")]
            partes += [fmt_extra(c, extras.get(str(c["id"]))) for c in columnas]
            for p in prest_por_item.get(i["id"], []):
                partes += [p.get("persona"), p.get("marca"), p.get("numero_patrimonio")]
            for u in unidades_por_item.get(i["id"], []):
                partes += [u.get("marca"), u.get("numero_patrimonio")]
            return any(f in (str(p) if p else "").lower() for p in partes)

        items = [i for i in items if coincide(i)]

    if not items:
        st.info("Sin resultados.")
        return

    if "subcategoria" in ocultos:
        items = sorted(items, key=lambda i: ((i.get("categoria") or "otro"), i["nombre"].lower()))

    def resumen_prestamos(item):
        if not es_prestable(item):
            return '<span class="pn-muted">—</span>'
        k = n_prestados(item)
        total = max(int(item["cantidad"]), k)
        if k == 0:
            if total == 0:
                return '<span class="pn-muted">Sin unidades</span>'
            return f'<span class="pn-badge pn-badge-ok">{total} disponible{"s" if total != 1 else ""}</span>'
        clase = "pn-badge-low" if k >= total else "pn-badge-loan"
        head = f'<span class="pn-badge {clase}">{k} de {total} prestado{"s" if k != 1 else ""}</span>'
        lineas = []
        abiertos = sorted(prest_por_item.get(item["id"], []), key=lambda p: str(p.get("prestado_en")))
        for p in abiertos[:3]:
            det = detalle_prestamo(p)
            d = parse_dt(p.get("prestado_en"))
            cuando = d.strftime("%d/%m %H:%M") if d else "—"
            texto = f'<b>{esc(p.get("persona") or "—")}</b>' + (f" · {esc(det)}" if det else "") + f" · {cuando}"
            lineas.append(f'<div class="pn-loan">{texto}</div>')
        if len(abiertos) > 3:
            lineas.append(f'<div class="pn-loan">+{len(abiertos) - 3} más</div>')
        return head + "".join(lineas)

    visible = lambda k: k not in ocultos
    mostrar_prest = any(es_prestable(i) for i in items)

    # Columnas del stock, siempre todas y en el mismo orden: (clave, encabezado, ancho)
    cols_def = [("nombre", "Nombre", "minmax(0,2.2fr)"), ("categoria", "Categoría", "minmax(0,1.1fr)")]
    if visible("numero_patrimonio"): cols_def.append(("patrimonio", "N° patrimonio", "minmax(0,1.1fr)"))
    cols_def.append(("cantidad", "Cantidad", "minmax(0,.8fr)"))
    if visible("minimo"): cols_def.append(("minimo", "Mínimo", "minmax(0,.7fr)"))
    if visible("ubicacion"): cols_def.append(("ubicacion", "Ubicación", "minmax(0,1.1fr)"))
    if visible("descripcion"): cols_def.append(("descripcion", "Descripción", "minmax(0,1.6fr)"))
    for c in columnas:
        cols_def.append((f"x{c['id']}", c["nombre"], "minmax(0,1.1fr)"))
    if mostrar_prest: cols_def.append(("prestamos", "Préstamos", "minmax(0,2.4fr)"))
    cols_def.append(("estado", "Estado", "112px"))
    plantilla = " ".join(w for _, _, w in cols_def)

    def sin_dato(v):
        return f'<span class="pn-muted">{esc(v) if not _vacio(v) else "—"}</span>'

    def valor_celda(clave, i, est, num_cls):
        extras = i.get("extras") or {}
        if clave == "nombre": return f'<span class="pn-name">{esc(i["nombre"])}</span>'
        if clave == "categoria": return f'<span class="pn-chip">{esc(i.get("categoria") or "—")}</span>'
        if clave == "patrimonio": return sin_dato(i.get("numero_patrimonio"))
        if clave == "cantidad": return f'<span class="pn-num {num_cls}">{i["cantidad"]}</span>'
        if clave == "minimo": return f'<span class="pn-muted">{i.get("minimo") or 0}</span>'
        if clave == "ubicacion": return sin_dato(i.get("ubicacion"))
        if clave == "descripcion": return sin_dato(i.get("descripcion"))
        if clave == "prestamos": return resumen_prestamos(i)
        if clave == "estado": return est
        col = next(c for c in columnas if f"x{c['id']}" == clave)
        return sin_dato(fmt_extra(col, extras.get(str(col["id"]))) if not _vacio(extras.get(str(col["id"]))) else None)

    personas = personas_conocidas(almacen_id)
    puede = st.session_state.autenticado or st.session_state.admin_global

    if mostrar_prest and not puede:
        st.caption("Para prestar o registrar devoluciones, ingresá primero en la pestaña Administrar.")

    # Encabezado de columnas (en un contenedor igual al de las filas, para que alineen)
    encabezado = "".join(f"<div>{esc(h)}</div>" for _, h, _ in cols_def)
    try:
        contenedor_head = st.container(border=True, key="pn_head")
    except TypeError:  # Streamlit antiguo sin key en container
        contenedor_head = st.container(border=True)
    with contenedor_head:
        st.markdown(f'<div class="pn-head" style="grid-template-columns:{plantilla}">{encabezado}</div>',
                    unsafe_allow_html=True)

    # Agrupar por (categoría, subcategoría) respetando el orden recibido
    grupos = []
    for i in items:
        clave = (i.get("categoria") or "otro", "" if "subcategoria" in ocultos else (i.get("subcategoria") or ""))
        if not grupos or grupos[-1][0] != clave:
            grupos.append((clave, []))
        grupos[-1][1].append(i)

    for (categoria, subcategoria), items_grupo in grupos:
        etiqueta_grupo = categoria if not subcategoria else f"{categoria} · {subcategoria}"
        st.markdown(f'<div class="pn-group-title">{esc(etiqueta_grupo)}</div>', unsafe_allow_html=True)

        for i in items_grupo:
            cant = i["cantidad"]
            mn = i.get("minimo") or 0
            if cant == 0:
                est = '<span class="pn-badge pn-badge-agotado">Agotado</span>'
                num_cls = "pn-zero"
            elif cant <= mn:
                est = '<span class="pn-badge pn-badge-low">Stock bajo</span>'
                num_cls = "pn-low"
            else:
                est = '<span class="pn-badge pn-badge-ok">Disponible</span>'
                num_cls = "pn-ok"

            celdas = "".join(
                f'<div class="pn-cell"><div class="pn-cell-lbl">{esc(h)}</div>{valor_celda(k_, i, est, num_cls)}</div>'
                for k_, h, _ in cols_def)
            prestable = es_prestable(i)

            with st.container(border=True):
                st.markdown(f'<div class="pn-row" style="grid-template-columns:{plantilla}">{celdas}</div>',
                            unsafe_allow_html=True)
                if prestable:
                    k = n_prestados(i)
                    total = max(int(cant), k)
                    etiqueta = (f"Préstamos · {k} de {total} prestado(s)" if k
                                else f"Préstamos · {total} disponible(s)")
                    with st.expander(etiqueta):
                        ui_prestamos_item(i, unidades_por_item.get(i["id"], []), prest_por_item.get(i["id"], []),
                                          personas, puede, almacen_id)


# ─────────────────────────────────────────
# PRÉSTAMOS DE EQUIPOS (salen de la cantidad ya cargada)
# ─────────────────────────────────────────
NUEVA_PERSONA_OPCION = "➕ Otra persona…"


def _hora_redondeada(dt, paso=15):
    return dt.time().replace(minute=(dt.minute // paso) * paso, second=0, microsecond=0)


def ui_prestamos_item(item, unidades, prestamos, personas, puede, almacen_id):
    ahora = ahora_ar()
    k = sum(int(p.get("cantidad") or 1) for p in prestamos)
    total = max(int(item["cantidad"]), k)
    disp = max(0, total - k)

    st.markdown(f'<div class="pn-loan" style="font-size:13px"><b>Total</b> {total} · '
                f'<b>Prestados</b> {k} · <b>Disponibles</b> {disp}</div>', unsafe_allow_html=True)

    # ── Prestados ahora: cada préstamo en una sola línea con sus controles ──
    for p in sorted(prestamos, key=lambda x: str(x.get("prestado_en"))):
        pid = p["id"]
        cant = int(p.get("cantidad") or 1)
        det = detalle_prestamo(p)
        c0, c1, c2, c3, c4 = st.columns([2.6, 1, 1.8, 1.4, 2], vertical_alignment="bottom")
        with c0:
            st.markdown(
                f'<div style="font-size:14px;color:var(--text)"><b>{esc(p.get("persona") or "—")}</b>'
                + (f' · {esc(det)}' if det else '')
                + f'<div class="pn-loan">desde el {esc(fmt_dt(p.get("prestado_en")))}</div></div>',
                unsafe_allow_html=True)
        if puede:
            with c1:
                n_dev = (st.number_input("Cantidad", min_value=1, max_value=cant, value=cant, key=f"dev_c_{pid}")
                         if cant > 1 else 1)
            with c2:
                f_dev = st.date_input("Día de devolución", value=ahora.date(), format="DD/MM/YYYY", key=f"dev_f_{pid}")
            with c3:
                h_dev = st.time_input("Hora", value=_hora_redondeada(ahora), step=900, key=f"dev_h_{pid}")
            with c4:
                if st.button("Devolver", key=f"dev_b_{pid}", type="primary", use_container_width=True):
                    cuando = datetime.combine(f_dev, h_dev)
                    inicio = parse_dt(p.get("prestado_en"))
                    if inicio and cuando < inicio:
                        st.error("La devolución no puede ser anterior al préstamo.")
                    else:
                        devolver_prestamo(p, int(n_dev), cuando)
                        flash("ok", f"✓ Devolución registrada ({p.get('persona')}).", toast=True)
                        st.rerun()

    # ── Prestar ──
    if puede:
        if prestamos:
            st.markdown("<hr class='pn-divider' style='margin:8px 0'>", unsafe_allow_html=True)
        if disp == 0:
            st.caption("No quedan unidades disponibles para prestar.")
        else:
            unidades_en_uso = {p.get("id_unidad") for p in prestamos if p.get("id_unidad") is not None}
            libres = {u["id"]: u for u in unidades if u["id"] not in unidades_en_uso}
            iid = item["id"]
            c1, c2, c3, c4, c5 = st.columns([2.6, 1, 1.8, 1.4, 2], vertical_alignment="bottom")
            with c1:
                sel = st.selectbox("Prestar a", personas + [NUEVA_PERSONA_OPCION], index=None,
                                   placeholder="Elegí a quién se lo prestás", key=f"pr_p_{iid}")
            with c2:
                cantidad = st.number_input("Cantidad", min_value=1, max_value=disp, value=1, key=f"pr_c_{iid}")
            with c3:
                f_pre = st.date_input("Día", value=ahora.date(), format="DD/MM/YYYY", key=f"pr_f_{iid}")
            with c4:
                h_pre = st.time_input("Hora", value=_hora_redondeada(ahora), step=900, key=f"pr_h_{iid}")
            nueva = ""
            if sel == NUEVA_PERSONA_OPCION:
                nueva = st.text_input("Nombre y apellido de la persona", key=f"pr_n_{iid}")
            unidad = None
            if libres:
                elegida = st.selectbox("Marca o patrimonio específico (opcional)", list(libres), index=None,
                                       format_func=lambda uid: etiqueta_unidad(libres[uid]),
                                       placeholder="Dejalo vacío si no importa cuál", key=f"pr_u_{iid}")
                if elegida is not None:
                    unidad = libres[elegida]
                    st.caption("Al elegir una unidad específica se presta de a una.")
            with c5:
                if st.button("Prestar", key=f"pr_b_{iid}", type="primary", use_container_width=True):
                    persona = nueva.strip() if sel == NUEVA_PERSONA_OPCION else (sel or "")
                    if not persona:
                        st.error("Elegí a quién se lo prestás.")
                    else:
                        prestar(almacen_id, item, persona, cantidad, datetime.combine(f_pre, h_pre), unidad)
                        n = 1 if unidad else int(cantidad)
                        flash("ok", f"✓ {n} × {item['nombre']} prestado a {persona}.", toast=True)
                        st.rerun()
    elif not prestamos:
        st.caption("Sin préstamos en curso.")


def render_historial_prestamos(prestamos):
    filas = []
    for p in prestamos:
        det = " · ".join(x for x in (p.get("marca"), p.get("numero_patrimonio")) if x)
        devuelto = (esc(fmt_dt(p["devuelto_en"])) if p.get("devuelto_en")
                    else '<span class="pn-badge pn-badge-loan">En préstamo</span>')
        filas.append(
            f'<tr><td><span class="pn-name">{esc(p.get("nombre_item") or "—")}</span></td>'
            f'<td><span class="pn-muted">{esc(det or "—")}</span></td>'
            f'<td><span class="pn-num">{int(p.get("cantidad") or 1)}</span></td>'
            f'<td>{esc(p.get("persona") or "—")}</td>'
            f'<td><span class="pn-muted">{esc(fmt_dt(p.get("prestado_en")))}</span></td>'
            f'<td><span class="pn-muted">{devuelto}</span></td></tr>')
    st.markdown(
        '<div class="pn-table-wrap"><table class="pn-table"><thead><tr>'
        '<th>Equipo</th><th>Marca / patrimonio</th><th>Cantidad</th><th>Prestado a</th><th>Prestado el</th><th>Devuelto el</th>'
        f'</tr></thead><tbody>{"".join(filas)}</tbody></table></div>',
        unsafe_allow_html=True)


def render_historial(movs):
    filas = []
    for m in movs:
        es_ent = m.get("tipo") == "entrada"
        chip = ('<span class="pn-badge pn-mov-ent">Entrada</span>' if es_ent
                else '<span class="pn-badge pn-mov-sal">Salida</span>')
        fecha = str(m.get("fecha") or "")[:16].replace("T", " ")
        filas.append(
            f'<tr><td><span class="pn-muted">{esc(fecha)}</span></td><td>{chip}</td>'
            f'<td><span class="pn-name">{esc(m.get("nombre_item") or "—")}</span></td>'
            f'<td><span class="pn-num">{m.get("cantidad", "")}</span></td>'
            f'<td><span class="pn-muted">{m.get("stock_resultante", "")}</span></td>'
            f'<td><span class="pn-muted">{esc(m.get("responsable") or "—")}</span></td></tr>')
    st.markdown(
        '<div class="pn-table-wrap"><table class="pn-table"><thead><tr>'
        '<th>Fecha</th><th>Tipo</th><th>Ítem</th><th>Cantidad</th><th>Stock resultante</th><th>Responsable</th>'
        f'</tr></thead><tbody>{"".join(filas)}</tbody></table></div>',
        unsafe_allow_html=True)


# ─────────────────────────────────────────
# EDITORES REUTILIZABLES (identidad, campos, columnas)
# ─────────────────────────────────────────
def ui_identidad_almacen(a, key):
    """Nombre, ícono y logo de un almacén."""
    c1, c2 = st.columns([3, 1])
    with c1:
        nombre = st.text_input("Nombre del almacén", value=a["nombre"], key=f"{key}_nombre")
    with c2:
        icono = st.text_input("Ícono (emoji)", value=a.get("icono") or "📦", max_chars=4, key=f"{key}_icono")
    st.caption("El ícono se muestra cuando el almacén no tiene logo.")

    quitar = False
    if a.get("logo_b64"):
        st.markdown(f'<div class="pn-logo-chip" style="display:inline-flex">'
                    f'<img src="data:image/png;base64,{a["logo_b64"]}" alt=""></div>', unsafe_allow_html=True)
        quitar = st.checkbox("Quitar el logo actual", key=f"{key}_quitar")
    archivo = st.file_uploader("Subir logo (PNG, JPG o WebP)", type=["png", "jpg", "jpeg", "webp"], key=f"{key}_logo")

    if st.button("Guardar identidad", type="primary", key=f"{key}_guardar"):
        if not nombre.strip():
            st.error("El nombre no puede quedar vacío.")
            return
        campos = {"nombre": nombre.strip(), "icono": icono.strip() or "📦"}
        try:
            if archivo is not None:
                campos["logo_b64"] = procesar_logo(archivo)
            elif quitar:
                campos["logo_b64"] = None
        except Exception:
            st.error("No se pudo leer la imagen. Probá con otro archivo PNG, JPG o WebP.")
            return
        actualizar_almacen(a["id"], **campos)
        flash("ok", "✓ Identidad del almacén actualizada.")
        st.rerun()


def ui_campos_visibles(a):
    st.markdown("##### Campos propios del ítem")
    st.caption("Desmarcá los campos que este almacén no necesita. Se ocultan de la tabla y de los formularios; "
               "los datos ya cargados no se borran.")
    ocultos = campos_ocultos(a)
    visibles_actuales = [k for k in BASE_OPCIONALES if k not in ocultos]
    elegidos = st.multiselect("Campos que usa este almacén", list(BASE_OPCIONALES),
                              default=visibles_actuales, format_func=BASE_OPCIONALES.get,
                              key=f"campos_vis_{a['id']}")
    if st.button("Guardar campos", type="primary", key=f"campos_guardar_{a['id']}"):
        nuevo_cfg = dict(a.get("config") or {})
        nuevo_cfg["ocultos"] = [k for k in BASE_OPCIONALES if k not in elegidos]
        actualizar_almacen(a["id"], config=nuevo_cfg)
        flash("ok", "✓ Campos actualizados.")
        st.rerun()


def ui_columnas(a):
    almacen_id = a["id"]
    columnas = get_columnas(almacen_id)
    st.markdown("##### Columnas personalizadas")
    st.caption("Agregá todas las que necesites. Solo existen en este almacén y aparecen en la tabla "
               "y en los formularios de ítems.")

    if not columnas:
        st.info("Este almacén todavía no tiene columnas propias. Creá la primera abajo.")

    tipos = list(TIPOS)
    for idx, c in enumerate(columnas):
        with st.expander(f"{c['nombre']} — {TIPOS.get(c['tipo'], 'Texto')}"):
            n = st.text_input("Nombre", value=c["nombre"], key=f"col_n_{c['id']}")
            t = st.selectbox("Tipo", tipos, index=tipos.index(c["tipo"]) if c["tipo"] in tipos else 0,
                             format_func=TIPOS.get, key=f"col_t_{c['id']}")
            o = c.get("opciones") or ""
            if t == "lista":
                o = st.text_input("Opciones (separadas por coma)", value=o, key=f"col_o_{c['id']}",
                                  placeholder="ej: Nuevo, Usado, En reparación")
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("Guardar cambios", key=f"col_g_{c['id']}", type="primary", use_container_width=True):
                    if not n.strip():
                        st.error("El nombre no puede quedar vacío.")
                    elif t == "lista" and not [x for x in o.split(",") if x.strip()]:
                        st.error("Cargá al menos una opción para la lista.")
                    else:
                        editar_columna(c["id"], n.strip(), t, o.strip() if t == "lista" else None)
                        flash("ok", f"✓ Columna '{n.strip()}' actualizada.")
                        st.rerun()
            with b2:
                if st.button("Subir", key=f"col_up_{c['id']}", disabled=idx == 0, use_container_width=True):
                    mover_columna(columnas, idx, -1)
                    st.rerun()
            with b3:
                if st.button("Bajar", key=f"col_dn_{c['id']}", disabled=idx == len(columnas) - 1,
                             use_container_width=True):
                    mover_columna(columnas, idx, +1)
                    st.rerun()
            st.markdown("<hr class='pn-divider'>", unsafe_allow_html=True)
            conf = st.checkbox("Confirmo que quiero eliminar esta columna y sus datos", key=f"col_c_{c['id']}")
            if st.button("Eliminar columna", key=f"col_d_{c['id']}", use_container_width=True):
                if not conf:
                    st.error("Marcá la casilla de confirmación primero.")
                else:
                    eliminar_columna(c["id"])
                    flash("ok", f"Columna '{c['nombre']}' eliminada.")
                    st.rerun()

    st.markdown("<div class='pn-section'>Nueva columna</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        nombre = st.text_input("Nombre de la columna", placeholder="ej: Fecha de calibración", key=f"nc_nombre_{almacen_id}")
    with c2:
        tipo = st.selectbox("Tipo de dato", tipos, format_func=TIPOS.get, key=f"nc_tipo_{almacen_id}")
    opciones = ""
    if tipo == "lista":
        opciones = st.text_input("Opciones (separadas por coma)", placeholder="ej: Nuevo, Usado, En reparación",
                                 key=f"nc_opc_{almacen_id}")
    if st.button("Agregar columna", type="primary", use_container_width=True, key=f"nc_add_{almacen_id}"):
        if not nombre.strip():
            st.error("Escribí un nombre para la columna.")
        elif nombre.strip().lower() in {c["nombre"].lower() for c in columnas}:
            st.error("Ya existe una columna con ese nombre en este almacén.")
        elif tipo == "lista" and not [x for x in opciones.split(",") if x.strip()]:
            st.error("Cargá al menos una opción para la lista.")
        else:
            orden = max([c.get("orden") or 0 for c in columnas], default=-1) + 1
            agregar_columna(almacen_id, nombre.strip(), tipo, opciones.strip() if tipo == "lista" else None, orden)
            flash("ok", f"✓ Columna '{nombre.strip()}' agregada.")
            st.rerun()


# ─────────────────────────────────────────
# PANTALLA: AJUSTES DEL ADMINISTRADOR GENERAL
# ─────────────────────────────────────────
def pantalla_config(cfg):
    col_t, col_b = st.columns([5, 1], vertical_alignment="center")
    with col_t:
        st.markdown(brand_html(cfg), unsafe_allow_html=True)
    with col_b:
        if st.button("← Volver", use_container_width=True):
            st.session_state.vista = None
            st.rerun()
    st.markdown("<hr class='pn-divider'>", unsafe_allow_html=True)
    mostrar_flash()

    # ── Acceso ───────────────────────────
    if not st.session_state.admin_global:
        _, centro, _ = st.columns([1, 2, 1])
        with centro:
            if not admin_configurada():
                st.markdown("<div class='pn-login'><div class='pn-login-title'>Creá la contraseña de administrador</div>"
                            "<div class='pn-login-sub'>Con ella vas a poder cambiar el logo, los colores y la "
                            "tipografía, y gestionar todos los almacenes.</div></div>", unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)
                c1 = st.text_input("Contraseña nueva", type="password", key="adm_new1")
                c2 = st.text_input("Repetir contraseña", type="password", key="adm_new2")
                if st.button("Crear contraseña y entrar", type="primary", use_container_width=True):
                    if len(c1) < 6:
                        st.error("Usá al menos 6 caracteres.")
                    elif c1 != c2:
                        st.error("Las contraseñas no coinciden.")
                    else:
                        definir_clave_admin(c1)
                        st.session_state.admin_global = True
                        st.rerun()
            else:
                st.markdown("<div class='pn-login'><div class='pn-login-title'>Administrador general</div>"
                            "<div class='pn-login-sub'>Ingresá la contraseña para modificar la apariencia "
                            "y los almacenes.</div></div>", unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)
                clave = st.text_input("Contraseña", type="password", key="adm_login")
                if st.button("Ingresar", type="primary", use_container_width=True):
                    if verificar_admin(clave):
                        st.session_state.admin_global = True
                        st.rerun()
                    else:
                        st.error("Contraseña incorrecta.")
        return

    if st.button("Cerrar sesión de administrador"):
        st.session_state.admin_global = False
        st.rerun()

    tab_apariencia, tab_almacenes, tab_seguridad = st.tabs(["Apariencia", "Almacenes", "Seguridad"])

    # ── Apariencia ───────────────────────
    with tab_apariencia:
        st.markdown("<br>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            app_nombre = st.text_input("Nombre de la aplicación", value=cfg["app_nombre"])
            app_sub = st.text_input("Subtítulo", value=cfg["app_subtitulo"])
            tema = st.selectbox("Tema", list(TEMAS), index=list(TEMAS).index(cfg["tema"]) if cfg["tema"] in TEMAS else 0)
        with c2:
            color = st.color_picker("Color de acento", value=cfg["color_acento"] if _hex_valido(cfg["color_acento"]) else CFG_DEFAULT["color_acento"])
            fuente = st.selectbox("Tipografía", FUENTES, index=FUENTES.index(cfg["fuente"]) if cfg["fuente"] in FUENTES else 0)

        st.markdown("<div class='pn-section'>Logo de la aplicación</div>", unsafe_allow_html=True)
        actual = logo_app(cfg)
        if actual:
            st.markdown(f'<div class="pn-logo-chip" style="display:inline-flex">'
                        f'<img src="data:image/png;base64,{actual}" alt=""></div>', unsafe_allow_html=True)
        else:
            st.caption("La aplicación no tiene logo cargado.")
        archivo = st.file_uploader("Subir un logo nuevo (PNG, JPG o WebP)", type=["png", "jpg", "jpeg", "webp"], key="cfg_logo")
        quitar = st.checkbox("Mostrar la aplicación sin logo") if actual else False

        b1, b2 = st.columns(2)
        with b1:
            if st.button("Guardar apariencia", type="primary", use_container_width=True):
                if not app_nombre.strip():
                    st.error("El nombre de la aplicación no puede quedar vacío.")
                else:
                    pares = {"app_nombre": app_nombre.strip(), "app_subtitulo": app_sub.strip(),
                             "tema": tema, "color_acento": color, "fuente": fuente}
                    try:
                        if archivo is not None:
                            pares["logo_b64"] = procesar_logo(archivo)
                        elif quitar:
                            pares["logo_b64"] = ""
                    except Exception:
                        st.error("No se pudo leer la imagen. Probá con otro archivo PNG, JPG o WebP.")
                        st.stop()
                    guardar_config(pares)
                    flash("ok", "✓ Apariencia guardada.")
                    st.rerun()
        with b2:
            if st.button("Restaurar valores originales", use_container_width=True):
                borrar_config(list(CFG_DEFAULT))
                flash("ok", "✓ Apariencia restaurada.")
                st.rerun()

    # ── Almacenes ────────────────────────
    with tab_almacenes:
        st.markdown("<br>", unsafe_allow_html=True)
        almacenes = get_almacenes()
        if not almacenes:
            st.info("Todavía no hay almacenes. Creá el primero desde la pantalla de inicio.")
        for a in almacenes:
            with st.expander(a["nombre"]):
                ui_identidad_almacen(a, key=f"cfg_alm_{a['id']}")
                st.markdown("<hr class='pn-divider'>", unsafe_allow_html=True)
                st.markdown("##### Borrar almacén")
                st.caption("Elimina el almacén con todo su stock, historial y columnas. No se puede deshacer.")
                conf = st.text_input(f"Escribí «{a['nombre']}» para confirmar", key=f"cfg_del_conf_{a['id']}")
                if st.button("Borrar almacén", key=f"cfg_del_{a['id']}"):
                    if conf.strip() != a["nombre"]:
                        st.error("El nombre no coincide.")
                    else:
                        eliminar_almacen(a["id"])
                        if st.session_state.almacen_id == a["id"]:
                            st.session_state.almacen_id = None
                            st.session_state.autenticado = False
                        flash("ok", f"✓ Almacén '{a['nombre']}' eliminado.")
                        st.rerun()

    # ── Seguridad ────────────────────────
    with tab_seguridad:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("##### Contraseña de administrador")
        st.caption("Da acceso a estos ajustes y a la administración de todos los almacenes.")
        if _clave_admin_secrets():
            st.info("Hay una contraseña definida en Secrets (`[admin] password`). Esa contraseña siempre es válida, "
                    "aunque cambies la que se guarda desde acá.")
        actual_c = st.text_input("Contraseña actual", type="password", key="adm_cur")
        n1 = st.text_input("Contraseña nueva", type="password", key="adm_n1")
        n2 = st.text_input("Repetir contraseña nueva", type="password", key="adm_n2")
        if st.button("Cambiar contraseña", type="primary"):
            if not verificar_admin(actual_c):
                st.error("La contraseña actual es incorrecta.")
            elif len(n1) < 6:
                st.error("Usá al menos 6 caracteres.")
            elif n1 != n2:
                st.error("Las contraseñas nuevas no coinciden.")
            else:
                definir_clave_admin(n1)
                flash("ok", "✓ Contraseña de administrador actualizada.")
                st.rerun()


# ─────────────────────────────────────────
# PANTALLA: SELECCIÓN DE ALMACÉN
# ─────────────────────────────────────────
def pantalla_seleccion_almacen(cfg):
    col_t, col_b = st.columns([5, 1], vertical_alignment="center")
    with col_t:
        st.markdown(brand_html(cfg), unsafe_allow_html=True)
    with col_b:
        if st.button("Ajustes", use_container_width=True):
            st.session_state.vista = "config"
            st.rerun()
    st.markdown("<hr class='pn-divider'>", unsafe_allow_html=True)
    mostrar_flash()

    st.markdown("#### Elegí un almacén")
    st.caption("Cada almacén tiene su propio stock, historial, columnas y contraseña de administración.")

    almacenes = get_almacenes()
    if not almacenes:
        st.info("Todavía no hay ningún almacén. Creá el primero más abajo.")
    else:
        cols = st.columns(3)
        for idx, a in enumerate(almacenes):
            with cols[idx % 3]:
                with st.container(border=True):
                    st.markdown(f'<div class="alm-head">{media_almacen(a)}'
                                f'<div class="alm-nombre">{esc(a["nombre"])}</div></div>', unsafe_allow_html=True)
                    if st.button("Ingresar", key=f"sel_{a['id']}", use_container_width=True):
                        st.session_state.almacen_id = a["id"]
                        st.session_state.autenticado = False
                        st.rerun()

    st.markdown("<hr class='pn-divider'>", unsafe_allow_html=True)

    with st.expander("Crear un almacén nuevo (por ejemplo: droguería, depósito, otra sede)"):
        c1, c2 = st.columns([3, 1])
        with c1:
            nuevo_nombre = st.text_input("Nombre del almacén", placeholder="ej: Droguería central")
        with c2:
            nuevo_icono = st.text_input("Ícono (emoji)", value="📦", max_chars=4)
        nuevo_logo = st.file_uploader("Logo del almacén (opcional)", type=["png", "jpg", "jpeg", "webp"], key="nuevo_logo")
        nueva_clave = st.text_input("Contraseña de administración de este almacén", type="password",
                                    placeholder="Elegí una contraseña segura")
        nueva_clave2 = st.text_input("Repetir contraseña", type="password")

        if st.button("Crear almacén", type="primary", use_container_width=True):
            if not nuevo_nombre.strip():
                st.error("El nombre del almacén es obligatorio.")
            elif not nueva_clave:
                st.error("Definí una contraseña de administración.")
            elif nueva_clave != nueva_clave2:
                st.error("Las contraseñas no coinciden.")
            elif len(nueva_clave) < 4:
                st.error("Usá una contraseña de al menos 4 caracteres.")
            else:
                try:
                    logo = procesar_logo(nuevo_logo) if nuevo_logo is not None else None
                except Exception:
                    st.error("No se pudo leer la imagen del logo. Probá con otro archivo.")
                    st.stop()
                nuevo = crear_almacen(nuevo_nombre.strip(), nuevo_icono.strip(), nueva_clave, logo)
                if nuevo:
                    st.session_state.almacen_id = nuevo["id"]
                    st.session_state.autenticado = False
                    flash("ok", f"✓ Almacén '{nuevo['nombre']}' creado. Guardá bien la contraseña.")
                    st.rerun()
                else:
                    st.error("No se pudo crear el almacén. Intentá de nuevo.")


# ─────────────────────────────────────────
# PANEL DE ADMINISTRACIÓN DEL ALMACÉN
# ─────────────────────────────────────────
ACCIONES = {
    "agregar": "Agregar ítem",
    "editar": "Editar ítem",
    "eliminar": "Eliminar ítem",
    "entrada": "Registrar entrada",
    "salida": "Registrar salida",
    "unidades": "Unidades (marca y patrimonio)",
    "estructura": "Campos y columnas",
    "identidad": "Nombre y logo del almacén",
    "borrar": "Borrar este almacén",
}


def render_admin(ALM, items_all, columnas, ocultos):
    ALMACEN_ID = ALM["id"]
    visible = lambda k: k not in ocultos

    if not (st.session_state.autenticado or st.session_state.admin_global):
        st.markdown(f"""<div class="pn-login"><div class="pn-login-title">Administración de {esc(ALM["nombre"])}</div>
<div class="pn-login-sub">Ingresá la contraseña de este almacén para modificar el stock.</div></div>""",
                    unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        _, col_l, _ = st.columns([1, 2, 1])
        with col_l:
            clave = st.text_input("Contraseña", type="password", placeholder="••••••••")
            if st.button("Ingresar", type="primary", use_container_width=True):
                if clave_valida(ALMACEN_ID, clave):
                    st.session_state.autenticado = True
                    st.rerun()
                else:
                    st.error("Contraseña incorrecta.")
        return

    if st.session_state.autenticado:
        col_logout, _ = st.columns([1, 5])
        with col_logout:
            if st.button("Cerrar sesión"):
                st.session_state.autenticado = False
                st.rerun()
        st.markdown("<hr class='pn-divider'>", unsafe_allow_html=True)

    accion = st.selectbox("¿Qué querés hacer?", list(ACCIONES), format_func=ACCIONES.get)
    st.markdown("<br>", unsafe_allow_html=True)

    # ── AGREGAR ───────────────────────────
    if accion == "agregar":
        st.markdown("#### Nuevo ítem")
        c1, c2 = st.columns(2)
        with c1:
            nombre = st.text_input("Nombre *")
            categoria = st.selectbox("Categoría", CATEGORIAS, key="add_categoria")
            subcategoria = selector_subcategoria(items_all, categoria, key_prefix="add") if visible("subcategoria") else ""
            ubicacion = st.text_input("Ubicación", placeholder="ej: Estante A3") if visible("ubicacion") else ""
        with c2:
            numero_patrimonio = st.text_input("N° de patrimonio", placeholder="ej: PAT-0001") if visible("numero_patrimonio") else ""
            cantidad = st.number_input("Cantidad inicial", min_value=0, value=0)
            minimo = st.number_input("Stock mínimo de alerta", min_value=0, value=0) if visible("minimo") else 0
            descripcion = st.text_input("Descripción") if visible("descripcion") else ""
        prestable = st.checkbox("Se puede prestar (habilita el registro de préstamos de este ítem)", key="add_prestable")
        extras_nuevos = formulario_extras(columnas, {}, "add")

        if st.button("Guardar ítem", type="primary", use_container_width=True):
            if not nombre.strip():
                st.error("El nombre es obligatorio.")
            else:
                agregar_item(ALMACEN_ID, {
                    "nombre": nombre.strip(), "categoria": categoria, "subcategoria": subcategoria,
                    "ubicacion": ubicacion.strip(), "numero_patrimonio": numero_patrimonio.strip(),
                    "cantidad": cantidad, "minimo": minimo, "descripcion": descripcion.strip(),
                    "prestable": prestable, "extras": combinar_extras({}, extras_nuevos),
                })
                flash("ok", f"✓ '{nombre.strip()}' agregado correctamente.")
                st.rerun()

    # ── EDITAR ────────────────────────────
    elif accion == "editar":
        st.markdown("#### Editar ítem")
        if not items_all:
            st.info("No hay ítems cargados.")
        else:
            opciones = {f"[{i['id']}] {i['nombre']}": i for i in items_all}
            sel = st.selectbox("Ítem a editar", list(opciones.keys()))
            item = opciones[sel]

            c1, c2 = st.columns(2)
            with c1:
                nombre = st.text_input("Nombre *", value=item["nombre"], key=f"edit_nombre_{item['id']}")
                cat_idx = CATEGORIAS.index(item["categoria"]) if item.get("categoria") in CATEGORIAS else len(CATEGORIAS) - 1
                categoria = st.selectbox("Categoría", CATEGORIAS, index=cat_idx, key=f"edit_categoria_{item['id']}")
                if visible("subcategoria"):
                    subcategoria = selector_subcategoria(items_all, categoria,
                                                         valor_actual=item.get("subcategoria") or "",
                                                         key_prefix=f"edit_{item['id']}")
                else:
                    subcategoria = item.get("subcategoria") or ""
                ubicacion = (st.text_input("Ubicación", value=item.get("ubicacion") or "", key=f"edit_ubic_{item['id']}")
                             if visible("ubicacion") else (item.get("ubicacion") or ""))
            with c2:
                numero_patrimonio = (st.text_input("N° de patrimonio", value=item.get("numero_patrimonio") or "", key=f"edit_pat_{item['id']}")
                                     if visible("numero_patrimonio") else (item.get("numero_patrimonio") or ""))
                cantidad = st.number_input("Cantidad", min_value=0, value=int(item["cantidad"]), key=f"edit_cant_{item['id']}")
                minimo = (st.number_input("Stock mínimo", min_value=0, value=int(item.get("minimo") or 0), key=f"edit_min_{item['id']}")
                          if visible("minimo") else int(item.get("minimo") or 0))
                descripcion = (st.text_input("Descripción", value=item.get("descripcion") or "", key=f"edit_desc_{item['id']}")
                               if visible("descripcion") else (item.get("descripcion") or ""))
            prestable = st.checkbox("Se puede prestar (habilita el registro de préstamos de este ítem)",
                                    value=bool(item.get("prestable")), key=f"edit_prestable_{item['id']}")
            extras_nuevos = formulario_extras(columnas, item.get("extras") or {}, f"edit_{item['id']}")

            if st.button("Guardar cambios", type="primary", use_container_width=True):
                if not nombre.strip():
                    st.error("El nombre es obligatorio.")
                else:
                    editar_item(item["id"], {
                        "nombre": nombre.strip(), "categoria": categoria, "subcategoria": subcategoria,
                        "ubicacion": ubicacion.strip(), "numero_patrimonio": numero_patrimonio.strip(),
                        "cantidad": cantidad, "minimo": minimo, "descripcion": descripcion.strip(),
                        "prestable": prestable, "extras": combinar_extras(item.get("extras"), extras_nuevos),
                    })
                    flash("ok", f"✓ '{nombre.strip()}' actualizado.")
                    st.rerun()

    # ── ELIMINAR ──────────────────────────
    elif accion == "eliminar":
        st.markdown("#### Eliminar ítem")
        if not items_all:
            st.info("No hay ítems cargados.")
        else:
            opciones = {f"[{i['id']}] {i['nombre']}": i for i in items_all}
            sel = st.selectbox("Ítem a eliminar", list(opciones.keys()))
            item = opciones[sel]
            st.warning(f"Vas a eliminar **{item['nombre']}** (stock actual: {item['cantidad']}). No se puede deshacer.")
            confirmar = st.checkbox("Confirmo que quiero eliminar este ítem")
            if st.button("Eliminar definitivamente", use_container_width=True):
                if not confirmar:
                    st.error("Marcá la casilla de confirmación primero.")
                else:
                    eliminar_item(item["id"])
                    flash("ok", f"'{item['nombre']}' eliminado.")
                    st.rerun()

    # ── ENTRADA ───────────────────────────
    elif accion == "entrada":
        st.markdown("#### Registrar entrada de stock")
        if not items_all:
            st.info("No hay ítems cargados.")
        else:
            opciones = {f"[{i['id']}] {i['nombre']} (stock: {i['cantidad']})": i for i in items_all}
            sel = st.selectbox("Ítem", list(opciones.keys()))
            item = opciones[sel]
            c1, c2 = st.columns(2)
            with c1:
                cantidad = st.number_input("Cantidad a ingresar", min_value=1, value=1)
            with c2:
                responsable = st.text_input("Responsable / observación")
            if st.button("Confirmar entrada", type="primary", use_container_width=True):
                nuevo = registrar_movimiento(ALMACEN_ID, item, "entrada", cantidad, responsable)
                flash("ok", f"✓ Entrada de {cantidad} ud. registrada. Stock nuevo: {nuevo}")
                st.rerun()

    # ── SALIDA ────────────────────────────
    elif accion == "salida":
        st.markdown("#### Registrar salida de stock")
        if not items_all:
            st.info("No hay ítems cargados.")
        else:
            opciones = {f"[{i['id']}] {i['nombre']} (stock: {i['cantidad']})": i for i in items_all}
            sel = st.selectbox("Ítem", list(opciones.keys()))
            item = opciones[sel]
            c1, c2 = st.columns(2)
            with c1:
                cantidad = st.number_input("Cantidad a retirar", min_value=1, value=1,
                                           max_value=max(1, item["cantidad"]))
            with c2:
                responsable = st.text_input("Responsable / observación")
            if item["cantidad"] == 0:
                st.error("Este ítem está agotado.")
            elif st.button("Confirmar salida", type="primary", use_container_width=True):
                if cantidad > item["cantidad"]:
                    st.error(f"Stock insuficiente. Disponible: {item['cantidad']}")
                else:
                    nuevo = registrar_movimiento(ALMACEN_ID, item, "salida", cantidad, responsable)
                    tipo = "warn" if nuevo <= (item.get("minimo") or 0) else "ok"
                    flash(tipo, f"✓ Salida de {cantidad} ud. registrada. Stock nuevo: {nuevo}")
                    st.rerun()

    # ── UNIDADES ──────────────────────────
    elif accion == "unidades":
        st.markdown("#### Unidades individuales por ítem")
        st.caption("Opcional. Sirve para detallar de qué marca es cada equipo y su número de patrimonio "
                   "(ej: Osciloscopio digital → 3 Tektronix, 2 Rigol). No hace falta para prestar: los préstamos "
                   "usan la cantidad que ya cargaste. Si detallás unidades, al prestar podés elegir una específica. "
                   "No modifica la cantidad del ítem.")
        if not items_all:
            st.info("No hay ítems cargados.")
        else:
            opciones = {f"[{i['id']}] {i['nombre']}": i for i in items_all}
            sel = st.selectbox("Ítem", list(opciones.keys()))
            item = opciones[sel]
            unidades_item = get_unidades(item["id"])

            st.markdown(f"**{len(unidades_item)}** unidad(es) cargada(s) para este ítem.")
            for u in sorted(unidades_item, key=lambda x: (x.get("marca") or "", x.get("numero_patrimonio") or "")):
                cu1, cu2, cu3 = st.columns([3, 3, 1], vertical_alignment="center")
                with cu1:
                    st.markdown(f"<span class='pn-name'>{esc(u.get('marca') or '—')}</span>", unsafe_allow_html=True)
                with cu2:
                    st.markdown(f"<span class='pn-muted'>{esc(u.get('numero_patrimonio') or '—')}</span>", unsafe_allow_html=True)
                with cu3:
                    if st.button("Quitar", key=f"del_unidad_{u['id']}", use_container_width=True):
                        eliminar_unidad(u["id"])
                        flash("ok", "✓ Unidad eliminada.")
                        st.rerun()

            st.markdown("<hr class='pn-divider'>", unsafe_allow_html=True)
            st.markdown("##### Agregar unidad")
            c1, c2 = st.columns(2)
            with c1:
                marca_nueva = st.text_input("Marca", placeholder="ej: Tektronix")
            with c2:
                patrimonio_nuevo = st.text_input("N° de patrimonio", placeholder="ej: PAT-1001", key="unidad_pat")
            if st.button("Agregar unidad", type="primary", use_container_width=True):
                if not marca_nueva.strip() and not patrimonio_nuevo.strip():
                    st.error("Completá al menos la marca o el número de patrimonio.")
                else:
                    agregar_unidad(item["id"], marca_nueva.strip(), patrimonio_nuevo.strip())
                    flash("ok", "✓ Unidad agregada.")
                    st.rerun()

    # ── CAMPOS Y COLUMNAS ─────────────────
    elif accion == "estructura":
        st.markdown("#### Estructura del almacén")
        ui_campos_visibles(ALM)
        st.markdown("<hr class='pn-divider'>", unsafe_allow_html=True)
        ui_columnas(ALM)

    # ── IDENTIDAD ─────────────────────────
    elif accion == "identidad":
        st.markdown("#### Nombre y logo del almacén")
        ui_identidad_almacen(ALM, key=f"alm_{ALMACEN_ID}")

    # ── BORRAR ALMACÉN ────────────────────
    elif accion == "borrar":
        st.markdown("#### Borrar este almacén")
        st.error(f"Esto elimina **{ALM['nombre']}** con **todo** su stock ({len(items_all)} ítems), "
                 "su historial y sus columnas. No se puede deshacer.")
        st.caption("Para confirmar, ingresá la contraseña de administración dos veces.")
        c1, c2 = st.columns(2)
        with c1:
            clave1 = st.text_input("Contraseña", type="password", key="borrar_alm_clave1")
        with c2:
            clave2 = st.text_input("Repetí la contraseña", type="password", key="borrar_alm_clave2")
        confirmar = st.checkbox(f"Confirmo que quiero borrar '{ALM['nombre']}' definitivamente")

        if st.button("Borrar almacén definitivamente", use_container_width=True):
            if not confirmar:
                st.error("Marcá la casilla de confirmación primero.")
            elif not clave1 or not clave2:
                st.error("Completá la contraseña en los dos campos.")
            elif clave1 != clave2:
                st.error("Las dos contraseñas no coinciden.")
            elif not clave_valida(ALMACEN_ID, clave1):
                st.error("Contraseña incorrecta.")
            else:
                nombre_borrado = ALM["nombre"]
                eliminar_almacen(ALMACEN_ID)
                st.session_state.almacen_id = None
                st.session_state.autenticado = False
                flash("ok", f"✓ Almacén '{nombre_borrado}' eliminado.")
                st.rerun()


# ─────────────────────────────────────────
# BUSCADOR GLOBAL (botón flotante)
# ─────────────────────────────────────────
def _norm(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def buscar_global(consulta, almacenes):
    """Busca todas las palabras (sin importar tildes ni mayúsculas) en ítems, columnas personalizadas,
    unidades, préstamos (personas y fechas) y movimientos de los almacenes indicados."""
    tokens = [t for t in _norm(consulta).split() if t]
    res = {"items": [], "prestamos": [], "movimientos": []}
    if not tokens:
        return res

    def coincide(*partes):
        texto = _norm(" ".join(str(x) for x in partes if not _vacio(x)))
        return all(t in texto for t in tokens)

    todas_unidades = get_unidades()
    for a in almacenes:
        aid, nom = a["id"], a["nombre"]
        items, cols = get_items(aid), get_columnas(aid)
        abiertos = get_prestamos_abiertos(aid)
        ids = {i["id"] for i in items}
        unidades = {}
        for u in todas_unidades:
            if u["id_item"] in ids:
                unidades.setdefault(u["id_item"], []).append(u)
        prest_item = {}
        for p in abiertos:
            prest_item.setdefault(p["id_item"], []).append(p)

        for i in items:
            extras = i.get("extras") or {}
            datos = [f"{c['nombre']} {fmt_extra(c, extras.get(str(c['id'])))}" for c in cols
                     if not _vacio(extras.get(str(c["id"])))]
            partes = [nom, i["nombre"], i.get("categoria"), i.get("subcategoria"), i.get("ubicacion"),
                      i.get("numero_patrimonio"), i.get("descripcion")] + datos
            for u in unidades.get(i["id"], []):
                partes += [u.get("marca"), u.get("numero_patrimonio")]
            for p in prest_item.get(i["id"], []):
                partes += [p.get("persona"), fmt_dt(p.get("prestado_en")), "prestado"]
            if coincide(*partes):
                res["items"].append((a, i, prest_item.get(i["id"], []), datos))

        vistos = set()
        for p in abiertos + get_prestamos_historial(aid):
            if p["id"] in vistos:
                continue
            vistos.add(p["id"])
            estado = "devuelto" if p.get("devuelto_en") else "en prestamo prestado"
            if coincide(nom, p.get("persona"), p.get("nombre_item"), p.get("marca"), p.get("numero_patrimonio"),
                        fmt_dt(p.get("prestado_en")), fmt_dt(p.get("devuelto_en")) if p.get("devuelto_en") else "", estado):
                res["prestamos"].append((a, p))

        for m in get_movimientos(aid):
            if coincide(nom, m.get("nombre_item"), m.get("tipo"), m.get("responsable"), m.get("fecha")):
                res["movimientos"].append((a, m))
    return res


def _tabla_html(headers, filas):
    thead = "".join(f"<th>{esc(h)}</th>" for h in headers)
    return ('<div class="pn-table-wrap"><table class="pn-table"><thead><tr>' + thead + '</tr></thead><tbody>'
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in fila) + "</tr>" for fila in filas)
            + "</tbody></table></div>")


LIMITE_RESULTADOS = 50


@st.dialog("Buscar en todo", width="large")
def dialogo_busqueda(almacen_id):
    almacenes = get_almacenes()
    q = st.text_input("Buscar", placeholder="Nombre, marca, patrimonio, persona, fecha, ubicación, columnas…",
                      label_visibility="collapsed", key="gs_q")
    todos = True
    if almacen_id is not None:
        alcance = st.radio("Dónde buscar", ["Este almacén", "Todos los almacenes"], horizontal=True, key="gs_alcance")
        todos = alcance == "Todos los almacenes"
    objetivo = almacenes if todos else [a for a in almacenes if a["id"] == almacen_id]
    mostrar_alm = len(objetivo) > 1

    if not q.strip():
        st.caption("Escribí una o más palabras. Se busca en ítems, columnas personalizadas, marcas y patrimonios, "
                   "préstamos (personas y fechas) y movimientos. Con varias palabras tienen que aparecer todas.")
        return

    res = buscar_global(q, objetivo)
    if not any(res.values()):
        st.info("Sin resultados. Probá con menos palabras.")
        return

    def seccion(titulo, lista, headers, armar):
        if not lista:
            return
        st.markdown(f"##### {titulo} ({len(lista)})")
        st.markdown(_tabla_html(headers, [armar(x) for x in lista[:LIMITE_RESULTADOS]]), unsafe_allow_html=True)
        if len(lista) > LIMITE_RESULTADOS:
            st.caption(f"Se muestran los primeros {LIMITE_RESULTADOS}. Agregá palabras para afinar la búsqueda.")

    def fila_item(x):
        a, i, prest, datos = x
        k = sum(int(p.get("cantidad") or 1) for p in prest)
        prest_txt = (f'<span class="pn-badge pn-badge-loan">{k} prestado{"s" if k != 1 else ""}</span> '
                     f'<span class="pn-muted">{esc(", ".join(sorted({p.get("persona") or "—" for p in prest})))}</span>'
                     if prest else '<span class="pn-muted">—</span>')
        fila = []
        if mostrar_alm:
            fila.append(f'<span class="pn-muted">{esc(a["nombre"])}</span>')
        fila += [f'<span class="pn-name">{esc(i["nombre"])}</span>',
                 f'<span class="pn-chip">{esc(i.get("categoria") or "—")}</span>',
                 f'<span class="pn-num">{i["cantidad"]}</span>',
                 f'<span class="pn-muted">{esc(i.get("ubicacion") or "—")}</span>',
                 f'<span class="pn-muted">{esc(" · ".join(datos)) if datos else "—"}</span>',
                 prest_txt]
        return fila

    h_item = (["Almacén"] if mostrar_alm else []) + ["Ítem", "Categoría", "Cantidad", "Ubicación", "Datos adicionales", "Préstamos"]
    seccion("Ítems", res["items"], h_item, fila_item)

    def fila_prest(x):
        a, p = x
        det = " · ".join(v for v in (p.get("marca"), p.get("numero_patrimonio")) if v)
        dev = (esc(fmt_dt(p["devuelto_en"])) if p.get("devuelto_en")
               else '<span class="pn-badge pn-badge-loan">En préstamo</span>')
        fila = []
        if mostrar_alm:
            fila.append(f'<span class="pn-muted">{esc(a["nombre"])}</span>')
        fila += [f'<span class="pn-name">{esc(p.get("nombre_item") or "—")}</span>',
                 f'<span class="pn-muted">{esc(det or "—")}</span>',
                 f'<span class="pn-num">{int(p.get("cantidad") or 1)}</span>',
                 esc(p.get("persona") or "—"),
                 f'<span class="pn-muted">{esc(fmt_dt(p.get("prestado_en")))}</span>',
                 f'<span class="pn-muted">{dev}</span>']
        return fila

    h_prest = (["Almacén"] if mostrar_alm else []) + ["Equipo", "Marca / patrimonio", "Cantidad", "Prestado a", "Prestado el", "Devuelto el"]
    seccion("Préstamos", res["prestamos"], h_prest, fila_prest)

    def fila_mov(x):
        a, m = x
        chip = ('<span class="pn-badge pn-mov-ent">Entrada</span>' if m.get("tipo") == "entrada"
                else '<span class="pn-badge pn-mov-sal">Salida</span>')
        fila = []
        if mostrar_alm:
            fila.append(f'<span class="pn-muted">{esc(a["nombre"])}</span>')
        fila += [f'<span class="pn-muted">{esc(str(m.get("fecha") or "")[:16].replace("T", " "))}</span>', chip,
                 f'<span class="pn-name">{esc(m.get("nombre_item") or "—")}</span>',
                 f'<span class="pn-num">{m.get("cantidad", "")}</span>',
                 f'<span class="pn-muted">{esc(m.get("responsable") or "—")}</span>']
        return fila

    h_mov = (["Almacén"] if mostrar_alm else []) + ["Fecha", "Tipo", "Ítem", "Cantidad", "Responsable"]
    seccion("Movimientos de stock", res["movimientos"], h_mov, fila_mov)


def render_fab(almacen_id):
    """Botón redondo flotante con lupa que abre el buscador global."""
    try:
        cont = st.container(key="pn_fab")
    except TypeError:  # Streamlit antiguo: sin botón flotante
        return
    with cont:
        abrir = st.button("Buscar", key="pn_fab_btn", help="Buscar en todo")
    if abrir:
        dialogo_busqueda(almacen_id)


# ══════════════════════════════════════════
# MÓDULO PAÑOL — flujo principal
# ══════════════════════════════════════════
def main_panol():
    if supabase is None:
        error_supabase_panol()
        return

    _db_cfg, _migrado = get_config_db()
    cfg = get_cfg()
    inyectar_css(cfg)

    if not _migrado:
        st.error("⚠️ **Falta actualizar la base de datos.**")
        st.markdown("Ejecutá los archivos `migracion_v2.sql` y `migracion_v3.sql` (en ese orden) en "
                    "**Supabase → SQL Editor** y recargá la página. Crean la configuración, las columnas "
                    "personalizadas y la tabla de préstamos de equipos. Se pueden volver a ejecutar sin problema.")
        return

    if st.session_state.vista == "config":
        pantalla_config(cfg)
        return

    if st.session_state.almacen_id is None:
        pantalla_seleccion_almacen(cfg)
        render_fab(None)
        return

    ALM = almacen_actual()
    if ALM is None:  # el almacén fue borrado desde otra sesión
        st.session_state.almacen_id = None
        st.session_state.autenticado = False
        st.rerun()

    ALMACEN_ID = ALM["id"]
    columnas = get_columnas(ALMACEN_ID)
    ocultos = campos_ocultos(ALM)

    items_all = get_items(ALMACEN_ID)
    n_total = len(items_all)
    n_alertas = sum(1 for i in items_all if i["cantidad"] <= (i.get("minimo") or 0))
    n_ok = n_total - n_alertas
    alerta_cls = "warn" if n_alertas else "ok"

    _prestables = [i for i in items_all if i.get("prestable")]
    n_prestados = sum(int(p.get("cantidad") or 1) for p in get_prestamos_abiertos(ALMACEN_ID))
    n_prestables = sum(int(i["cantidad"]) for i in _prestables)
    kpi_prestamos = (f'<div class="pn-kpi"><div class="pn-kpi-num">{n_prestados}</div>'
                     f'<div class="pn-kpi-lbl">Equipos prestados (de {max(n_prestables, n_prestados)})</div></div>'
                     if (_prestables or n_prestados) else "")

    # ── Encabezado ───────────────────────────
    st.markdown(
        f'<div class="pn-top">{brand_html(cfg)}{pill_almacen(ALM)}</div>'
        '<div class="pn-kpis">'
        f'<div class="pn-kpi"><div class="pn-kpi-num">{n_total}</div><div class="pn-kpi-lbl">Ítems</div></div>'
        f'<div class="pn-kpi {alerta_cls}"><div class="pn-kpi-num">{n_alertas}</div><div class="pn-kpi-lbl">Con alerta de stock</div></div>'
        f'<div class="pn-kpi ok"><div class="pn-kpi-num">{n_ok}</div><div class="pn-kpi-lbl">Con stock suficiente</div></div>'
        f'{kpi_prestamos}'
        '</div>',
        unsafe_allow_html=True)

    col_cambiar, col_ajustes, _ = st.columns([1.3, 1, 4])
    with col_cambiar:
        if st.button("Cambiar de almacén", use_container_width=True):
            st.session_state.almacen_id = None
            st.session_state.autenticado = False
            st.rerun()
    with col_ajustes:
        if st.button("Ajustes", use_container_width=True):
            st.session_state.vista = "config"
            st.rerun()

    mostrar_flash()
    if st.session_state.toast:
        st.toast(st.session_state.toast)
        st.session_state.toast = None

    tab_stock, tab_admin, tab_historial = st.tabs(["Stock", "Administrar", "Historial"])

    # ── STOCK (vista pública) ────────────────
    with tab_stock:
        st.markdown("<br>", unsafe_allow_html=True)
        col_buscar, col_refresh = st.columns([5, 1])
        with col_buscar:
            filtro = st.text_input("Buscar", placeholder="Buscar por nombre, categoría, ubicación o cualquier columna",
                                   label_visibility="collapsed")
        with col_refresh:
            if st.button("Actualizar", use_container_width=True):
                invalidar_cache()
                st.rerun()

        render_tabla(items_all, columnas, ocultos, filtro, ALMACEN_ID)

        if n_alertas:
            st.markdown("<br>", unsafe_allow_html=True)
            st.warning(f"Hay **{n_alertas}** ítem(s) con stock bajo o agotado.")

    # ── ADMINISTRAR ──────────────────────────
    with tab_admin:
        st.markdown("<br>", unsafe_allow_html=True)
        render_admin(ALM, items_all, columnas, ocultos)

    # ── HISTORIAL ────────────────────────────
    with tab_historial:
        st.markdown("<br>", unsafe_allow_html=True)
        col_h1, col_h2 = st.columns([5, 1])
        with col_h2:
            if st.button("Actualizar ", use_container_width=True):
                invalidar_cache()
                st.rerun()
        h_stock, h_prest = st.tabs(["Movimientos de stock", "Préstamos de equipos"])
        with h_stock:
            movs = get_movimientos(ALMACEN_ID)
            if not movs:
                st.info("Todavía no hay movimientos registrados.")
            else:
                st.markdown(f"**{len(movs)}** movimientos registrados.")
                render_historial(movs)
        with h_prest:
            prestamos = get_prestamos_historial(ALMACEN_ID)
            if not prestamos:
                st.info("Todavía no hay préstamos registrados.")
            else:
                en_curso = sum(1 for p in prestamos if not p.get("devuelto_en"))
                st.markdown(f"**{len(prestamos)}** préstamos registrados, **{en_curso}** en curso.")
                render_historial_prestamos(prestamos)

    render_fab(ALMACEN_ID)

# ══════════════════════════════════════════
# MÓDULO HOPSIE — comanda de mesas + stock + admin
# (los nombres que chocaban con Pañol llevan prefijo hop_ / HOP_)
# ══════════════════════════════════════════
# ─────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────
TZ = ZoneInfo("America/Argentina/Buenos_Aires")

T_USU, T_LOG, T_CFG = "hopsie_usuarios", "hopsie_log", "hopsie_config"
T_INS, T_PROD, T_REC = "hopsie_insumos", "hopsie_productos", "hopsie_recetas"
T_MESAS, T_COM, T_ITEMS = "hopsie_mesas", "hopsie_comandas", "hopsie_items"
T_PAGOS, T_MOV = "hopsie_pagos", "hopsie_movs"
T_CLI = "hopsie_clientes"

P_SALON, P_COMANDA, P_COBRO = "🍽️ Salón", "🧾 Comanda", "💳 Cobro"
P_COCINA, P_BARRA, P_ADMIN = "👨‍🍳 Cocina", "🍺 Barra", "⚙️ Admin"
NAV = [P_SALON, P_COMANDA, P_COBRO, P_COCINA, P_BARRA, P_ADMIN]

ROLES = {"dueno": "Dueño", "encargado": "Encargado"}
SECTORES = ["Barra", "Cocina"]
UNIDADES = ["lt", "ml", "kg", "g", "un"]
CAT_INSUMOS = ["Cerveza (litros)", "Cocina", "Bebidas", "Descartables", "Limpieza", "Otros"]
ICONO_ESTADO = {"pendiente": "🟡", "preparando": "🔥", "servido": "✅"}

# slug, nombre, color de respaldo (aprox.; se reemplaza por el logo real en /logos)
PROVEEDORES = [
    ("mercadopago", "Mercado Pago", "#009EE3"), ("uala", "Ualá", "#3E4EF2"),
    ("naranjax", "Naranja X", "#FF6B00"), ("cuentadni", "Cuenta DNI", "#00A859"),
    ("modo", "MODO", "#00B7A8"), ("bna", "Banco Nación", "#00539F"),
    ("galicia", "Galicia", "#F26B21"), ("santander", "Santander", "#EC0000"),
    ("bbva", "BBVA", "#004481"), ("macro", "Macro", "#0C3C8C"),
    ("brubank", "Brubank", "#6C3CE9"), ("lemon", "Lemon", "#1DBF73"),
]
PROV_NOMBRE = {s: n for s, n, _ in PROVEEDORES}
PROV_COLOR = {s: c for s, _, c in PROVEEDORES}

_V = tuple(int(x) for x in st.__version__.split(".")[:2] if x.isdigit())
STRETCH = {"width": "stretch"} if _V >= (1, 50) else {"use_container_width": True}
ICON_DEL = {"icon": ":material/delete:"} if _V >= (1, 40) else {}
ICON_OK = _V >= (1, 40)
ICONOS_IB = {"menos": (":material/remove:", "−"), "mas": (":material/add:", "+"),
             "borrar": (":material/delete:", "🗑"), "editar": (":material/edit:", "✎")}


def ib(kind, key, ayuda=""):
    """Botón cuadrado solo con ícono (se ve igual en PC y celular)."""
    ic, fb = ICONOS_IB[kind]
    if ICON_OK:
        return st.button("", icon=ic, key=f"ib_{kind}_{key}", help=ayuda or None)
    return st.button(fb, key=f"ib_{kind}_{key}", help=ayuda or None)


def ib_popover(kind, key, ayuda=""):
    ic, fb = ICONOS_IB[kind]
    if ICON_OK:
        with st.container(key=f"ib_{kind}_{key}"):
            return st.popover("", icon=ic, help=ayuda or None)
    return st.popover(fb, help=ayuda or None)

# ─────────────────────────────────────────
# ESTILO (fondo loquísimo: amarillo · turquesa · rosa · negro · verde)
# ─────────────────────────────────────────
HOP_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bungee&family=Poppins:wght@400;600;800&display=swap');
:root{--y:#FFE600;--t:#00E5CF;--p:#FF2E93;--k:#0B0B10;--g:#39FF14;--panel:#12121a}
html,body,[class*="css"],.stApp{font-family:'Poppins',sans-serif}
.stApp{
  background:linear-gradient(120deg,#FFE600 0%,#00E5CF 22%,#FF2E93 45%,#0B0B10 62%,#39FF14 82%,#FFE600 100%);
  background-size:320% 320%;animation:hopmove 22s ease infinite}
@keyframes hopmove{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
.stApp::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:
   radial-gradient(circle at 12% 18%,rgba(255,46,147,.55) 0 110px,transparent 111px),
   radial-gradient(circle at 88% 12%,rgba(57,255,20,.45) 0 150px,transparent 151px),
   radial-gradient(circle at 74% 86%,rgba(0,229,207,.55) 0 180px,transparent 181px),
   radial-gradient(circle at 8% 88%,rgba(255,230,0,.55) 0 130px,transparent 131px),
   radial-gradient(circle at 50% 50%,rgba(11,11,16,.35) 0 90px,transparent 91px),
   repeating-linear-gradient(45deg,rgba(0,0,0,.07) 0 14px,transparent 14px 28px)}
header[data-testid="stHeader"]{background:transparent}
.block-container{position:relative;z-index:1;max-width:1250px;margin-top:3.4rem;padding:1.4rem 2rem 2.5rem;
  background:rgba(10,10,16,.86);backdrop-filter:blur(6px);border:3px solid var(--y);border-radius:22px;
  box-shadow:8px 8px 0 var(--p),16px 16px 0 var(--t)}
.block-container, .block-container p, .block-container label, .block-container li,
.block-container h1,.block-container h2,.block-container h3,.block-container h4,
.block-container [data-testid="stMarkdownContainer"], .block-container [data-testid="stCaptionContainer"],
.block-container [data-testid="stWidgetLabel"] p{color:#fff !important}
.block-container h2,.block-container h3,.block-container h4{font-family:'Bungee',cursive;color:var(--y) !important;letter-spacing:.5px}
.hop-head{display:flex;align-items:center;gap:18px;margin-bottom:6px}
.hop-head img{max-height:84px;max-width:240px;object-fit:contain;filter:drop-shadow(3px 3px 0 var(--p))}
.hop-title{font-family:'Bungee',cursive;font-size:2.6rem;line-height:1;
  background:linear-gradient(90deg,var(--y),var(--t),var(--p),var(--g));-webkit-background-clip:text;
  background-clip:text;color:transparent !important;-webkit-text-fill-color:transparent}
.hop-sub{letter-spacing:.35em;font-weight:800;color:var(--t) !important;font-size:.8rem}
.stButton>button,.stDownloadButton>button,[data-testid^="stBaseButton"]{
  background:#111 !important;color:#fff !important;border:2px solid var(--t) !important;border-radius:12px !important;
  font-weight:700 !important;transition:all .12s}
.stButton>button:hover,.stDownloadButton>button:hover,[data-testid^="stBaseButton"]:hover{
  background:var(--y) !important;color:#000 !important;border-color:var(--p) !important;
  transform:translate(-2px,-2px);box-shadow:3px 3px 0 var(--p)}
.stButton>button p,[data-testid^="stBaseButton"] p{color:inherit !important}
button[kind="primary"],[data-testid="stBaseButton-primary"],[data-testid="stBaseButton-primaryFormSubmit"]{
  background:var(--p) !important;border-color:var(--y) !important}
div[data-baseweb="input"],div[data-baseweb="base-input"],div[data-baseweb="textarea"],
div[data-baseweb="select"]>div,.stNumberInput input,.stTextInput input,.stTextArea textarea{
  background:#15151d !important;color:#fff !important;border-color:var(--t) !important;border-radius:10px !important}
.stTextInput input,.stNumberInput input,.stTextArea textarea{color:#fff !important;-webkit-text-fill-color:#fff !important}
div[data-baseweb="select"] *{color:#fff !important}
div[data-baseweb="popover"] ul,div[data-baseweb="popover"] li,div[data-baseweb="menu"]{background:#15151d !important;color:#fff !important}
div[data-baseweb="popover"] li:hover{background:var(--p) !important}
div[data-baseweb="popover"] *{color:#fff}
.block-container [class*="st-key-del_"] button,.block-container [class*="st-key-del_"] [data-testid^="stBaseButton"]{background:#B3122D !important;border-color:#FF4D6D !important;color:#fff !important;box-shadow:4px 4px 0 #000 !important}
.block-container [class*="st-key-del_"] button:hover{background:#FF1F3D !important;color:#fff !important}
.block-container [class*="st-key-del_"] button p{color:#fff !important}
.draft{border-left:8px dashed var(--y);background:rgba(255,230,0,.08);border-radius:10px;padding:6px 12px;margin:6px 0}
.sent{border-left:8px solid var(--t);background:rgba(0,229,207,.07);border-radius:10px;padding:6px 12px;margin:6px 0}
/* ── Botones grandes, vistosos y legibles ── */
.block-container .stButton>button,.block-container .stDownloadButton>button,.block-container .stLinkButton>a,
.block-container [data-testid^="stBaseButton"]{min-height:3.2rem !important;padding:.6rem 1.2rem !important;font-size:1.1rem !important;
  font-weight:800 !important;letter-spacing:.3px;border-radius:14px !important;border:3px solid var(--t) !important;box-shadow:4px 4px 0 var(--t)}
.block-container .stButton>button p,.block-container .stDownloadButton>button p,.block-container [data-testid^="stBaseButton"] p{
  font-size:1.1rem !important;font-weight:800 !important;line-height:1.15;color:inherit !important}
.block-container .stButton>button:hover,.block-container .stDownloadButton>button:hover,.block-container [data-testid^="stBaseButton"]:hover{
  transform:translate(-2px,-2px);box-shadow:6px 6px 0 var(--p) !important;background:var(--y) !important;color:#000 !important}
.block-container .stButton>button:active,.block-container [data-testid^="stBaseButton"]:active{transform:translate(3px,3px);box-shadow:0 0 0 var(--p) !important}
.block-container button[kind="primary"],.block-container [data-testid="stBaseButton-primary"],.block-container [data-testid="stBaseButton-primaryFormSubmit"]{
  background:linear-gradient(135deg,var(--p),#FF6A3D) !important;border-color:var(--y) !important;box-shadow:4px 4px 0 var(--y);
  min-height:3.5rem !important;font-size:1.2rem !important;text-transform:uppercase}
.block-container [data-testid="stBaseButton-primary"] p,.block-container [data-testid="stBaseButton-primaryFormSubmit"] p{font-size:1.2rem !important}
.block-container input,.block-container textarea{font-size:1.08rem !important}
[data-testid="stMetricValue"]{font-size:2.1rem !important;font-weight:800}
/* ── Cobro: medios de pago como botones grandes ── */
/* ── Cobro v2: tres botones enormes, banner del medio elegido y panel de confirmación ── */
.cobro-titulo{font-family:'Bungee',cursive;font-size:1.7rem;color:var(--y);margin:10px 0 6px;text-transform:uppercase}
.cobro-sel{border:4px solid #000;border-radius:18px;padding:14px 18px;margin:14px 0;font-family:'Bungee',cursive;font-size:1.7rem;text-align:center;color:#000 !important}
.cobro-conf{background:#000;border:5px solid var(--y);border-radius:22px;padding:18px 20px;margin:14px 0;text-align:center;color:#fff}
.cobro-conf .c1{font-family:'Bungee',cursive;font-size:1.5rem;color:var(--y)}
.cobro-conf .c2{font-family:'Bungee',cursive;font-size:3.2rem;line-height:1.1;color:#fff}
.cobro-conf .c3{font-size:1.5rem;font-weight:800;margin-top:6px}
.cobro-conf .c4{font-size:1.1rem;opacity:.9;margin-top:4px}
/* ── Vidrio esmerilado (blur): menú principal, medios de cobro y botones con ícono ── */
.block-container [class*="st-key-nav_"] button{min-height:3.6rem !important;border-radius:18px !important;padding:.5rem .6rem !important;
  background:linear-gradient(135deg,rgba(0,229,207,.22),rgba(255,255,255,.06)) !important;
  -webkit-backdrop-filter:blur(14px) saturate(170%);backdrop-filter:blur(14px) saturate(170%);
  border:2px solid rgba(0,229,207,.8) !important;box-shadow:0 8px 24px rgba(0,0,0,.4), inset 0 1px 0 rgba(255,255,255,.35) !important}
.block-container [class*="st-key-nav_"] button p{font-size:1.12rem !important;font-weight:800 !important;color:#fff !important;white-space:nowrap !important}
.block-container [class*="st-key-nav_"] button:hover{background:linear-gradient(135deg,rgba(255,230,0,.4),rgba(255,255,255,.12)) !important;
  transform:translateY(-2px);box-shadow:0 12px 28px rgba(0,229,207,.4), inset 0 1px 0 rgba(255,255,255,.5) !important;color:#fff !important}
.block-container [class*="st-key-nav_"] button:hover p{color:#fff !important}
.block-container [class*="st-key-nav_"] button[kind="primary"]{background:linear-gradient(135deg,rgba(255,46,147,.85),rgba(255,138,0,.8)) !important;
  border-color:rgba(255,230,0,.95) !important;box-shadow:0 0 26px rgba(255,46,147,.55), inset 0 1px 0 rgba(255,255,255,.5) !important}
.block-container [class*="st-key-nav_"] button p{text-transform:none !important}
@media (max-width:640px){
  .st-key-navbar [data-testid="stHorizontalBlock"]{flex-wrap:wrap !important;gap:8px !important}
  .st-key-navbar [data-testid="stColumn"]{flex:1 1 calc(33% - 8px) !important;min-width:calc(33% - 8px) !important}
  .st-key-navbar button p{font-size:.95rem !important;white-space:normal !important}
}
.block-container [class*="st-key-cmb_"] button{min-height:8.5rem !important;border-radius:26px !important;border-width:3px !important;white-space:normal;
  -webkit-backdrop-filter:blur(16px) saturate(180%);backdrop-filter:blur(16px) saturate(180%);
  box-shadow:0 10px 30px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.4) !important}
.block-container [class*="st-key-cmb_"] button p{font-size:1.7rem !important;font-weight:900 !important;line-height:1.1;color:#fff !important;
  white-space:normal !important;overflow:visible !important;text-overflow:clip !important}
.block-container [class*="st-key-cmb_"][class*="_efectivo"] button{background:linear-gradient(135deg,rgba(57,255,20,.28),rgba(255,255,255,.05)) !important;border-color:#39FF14 !important}
.block-container [class*="st-key-cmb_"][class*="_qr"] button{background:linear-gradient(135deg,rgba(0,229,207,.28),rgba(255,255,255,.05)) !important;border-color:#00E5CF !important}
.block-container [class*="st-key-cmb_"][class*="_tarjeta"] button{background:linear-gradient(135deg,rgba(255,46,147,.30),rgba(255,255,255,.05)) !important;border-color:#FF2E93 !important}
.block-container [class*="st-key-cmb_"][class*="_efectivo"] button[kind="primary"]{background:linear-gradient(135deg,#39FF14,#B6FF8A) !important;box-shadow:0 0 34px #39FF14 !important}
.block-container [class*="st-key-cmb_"][class*="_qr"] button[kind="primary"]{background:linear-gradient(135deg,#00E5CF,#9CFFF4) !important;box-shadow:0 0 34px #00E5CF !important}
.block-container [class*="st-key-cmb_"][class*="_tarjeta"] button[kind="primary"]{background:linear-gradient(135deg,#FF2E93,#FF9BC8) !important;box-shadow:0 0 34px #FF2E93 !important}
.block-container [class*="st-key-cmb_"] button[kind="primary"] p{color:#000 !important}
.block-container [class*="st-key-cmb_"] button:hover{transform:translateY(-3px)}
/* botones solo con ícono: menos, más, editar, borrar */
.block-container [class*="st-key-ib_"] button,.block-container [class*="st-key-ib_"] [data-testid="stPopoverButton"]{
  min-width:3.1rem !important;min-height:3.1rem !important;padding:.3rem !important;border-radius:16px !important;display:flex;align-items:center;justify-content:center;
  background:linear-gradient(135deg,rgba(255,255,255,.16),rgba(255,255,255,.05)) !important;-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);
  border:2px solid rgba(0,229,207,.85) !important;color:#fff !important;box-shadow:0 5px 14px rgba(0,0,0,.4), inset 0 1px 0 rgba(255,255,255,.35) !important}
.block-container [class*="st-key-ib_"] [data-testid="stIconMaterial"],.block-container [class*="st-key-ib_"] button span{font-size:1.9rem !important;color:#fff !important;opacity:1 !important}
.block-container [class*="st-key-ib_"] button:hover,.block-container [class*="st-key-ib_"] [data-testid="stPopoverButton"]:hover{background:var(--y) !important;transform:translateY(-2px)}
.block-container [class*="st-key-ib_"] button:hover span,.block-container [class*="st-key-ib_"] [data-testid="stPopoverButton"]:hover span{color:#000 !important}
.block-container [class*="st-key-ib_borrar"] button{border-color:#FF4D6D !important;background:linear-gradient(135deg,rgba(255,46,61,.35),rgba(255,255,255,.04)) !important}
.block-container [class*="st-key-ib_borrar"] button span{color:#FF9AAE !important}
.block-container [class*="st-key-ib_"] [data-testid="stPopoverButton"] > div > div[aria-hidden="true"]{display:none !important}
.block-container [class*="st-key-ib_mas"] button{border-color:#39FF14 !important}
.block-container [class*="st-key-ib_mas"] button span{color:#9BFF8A !important}
/* ── Dashboard ── */
.dcard{border:3px solid;border-radius:18px;overflow:hidden;background:rgba(255,255,255,.05);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);margin-bottom:10px}
.dcard .dh{font-family:'Bungee',cursive;font-size:1.5rem;padding:8px 16px;color:#000}
.dgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;padding:12px 16px}
.dgrid div{background:rgba(0,0,0,.38);border-radius:12px;padding:8px 12px}
.dgrid b{display:block;font-size:1.8rem;line-height:1.1;color:#fff}
.dgrid span{font-size:.95rem;opacity:.85;color:#fff}
.dbar{height:10px;background:rgba(255,255,255,.14);margin:0 16px 4px;border-radius:99px;overflow:hidden}
.dbar i{display:block;height:100%}
.dpct{padding:0 16px 12px;font-size:.95rem;opacity:.9;color:#fff}
.dtot{border:3px dashed var(--y);border-radius:14px;padding:10px 16px;margin:6px 0 14px;color:#fff;font-size:1.1rem}
/* ── Cocina / Barra: una tarjeta de color por mesa ── */
.kds-resumen{font-family:'Bungee',cursive;font-size:1.5rem;padding:10px 16px;border:3px solid var(--y);border-radius:14px;margin-bottom:6px;background:#000;color:var(--y)}
.kds-vacio{font-family:'Bungee',cursive;font-size:1.8rem;padding:40px 16px;text-align:center;border:3px dashed var(--g);border-radius:18px;color:var(--g)}
.kds-head{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 16px;border-radius:14px 14px 0 0;border:3px solid #000;margin-top:16px}
.kds-mesa{font-family:'Bungee',cursive;font-size:2.3rem;line-height:1.05;word-break:break-word}
.kds-min{font-weight:900;font-size:1.3rem;white-space:nowrap}
.kds-item{background:#16161f;padding:9px 14px;margin:0;font-size:1.25rem;font-weight:700;color:#fff;border-bottom:1px solid #000}
.kds-item.preparando{background:#34102a}
.kds-cant{font-family:'Bungee',cursive;font-size:1.5rem;margin-right:6px}
.kds-nota{display:block;font-size:1.02rem;color:#FFE600;font-weight:600}
.stRadio div[role="radiogroup"]{gap:.4rem}
.stRadio label[data-baseweb="radio"]{background:#111;border:2px solid var(--t);border-radius:999px;padding:5px 14px;margin:0}
.stRadio label[data-baseweb="radio"]>div:first-child{display:none}
.stRadio label[data-baseweb="radio"]:has(input:checked){background:var(--y);border-color:var(--p);box-shadow:3px 3px 0 var(--p)}
.stRadio label[data-baseweb="radio"]:has(input:checked) *{color:#000 !important;font-weight:800}
.stTabs [data-baseweb="tab"] p{color:#fff !important;font-weight:800}
.stTabs [aria-selected="true"] p{color:var(--y) !important}
.stTabs [data-baseweb="tab-highlight"]{background:var(--p) !important;height:4px}
[data-testid="stMetric"]{background:var(--panel);border:2px solid var(--g);border-radius:14px;padding:10px 14px}
[data-testid="stMetricValue"],[data-testid="stMetricLabel"] *{color:#fff !important}
[data-testid="stExpander"]{border:2px solid var(--p) !important;border-radius:12px;background:rgba(0,0,0,.35)}
[data-testid="stForm"]{border:2px dashed var(--t) !important;border-radius:14px}
[data-testid="stDataFrame"]{border:2px solid var(--t);border-radius:10px}
hr{border-color:var(--p) !important}
.mesa{border:3px solid var(--t);border-radius:16px;padding:12px 8px;background:var(--panel);text-align:center;
  box-shadow:4px 4px 0 var(--t);margin-bottom:6px}
.mesa.ocupada{border-color:var(--p);box-shadow:4px 4px 0 var(--p)}
.mesa .mn{font-family:'Bungee',cursive;font-size:1.25rem;color:var(--y)}
.mesa .mt{font-size:1.35rem;font-weight:800;color:#fff}
.mesa .ms{opacity:.85;font-size:.82rem;color:#fff}
.mesa .libre{color:var(--g);font-weight:800}
.kds{border-left:8px solid var(--y);background:var(--panel);border-radius:10px;padding:8px 12px;margin:6px 0}
.kds.preparando{border-left-color:var(--p)}
.pchip{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:6px 14px;margin:4px;
  border-radius:12px;background:#fff;font-weight:800;border:2px solid #000;box-shadow:3px 3px 0 #000}
.pchip img{height:32px;max-width:120px;object-fit:contain}
.totalbox{background:linear-gradient(90deg,var(--p),var(--y));color:#000 !important;border-radius:14px;padding:10px 16px;
  text-align:center;font-family:'Bungee',cursive;font-size:1.7rem;border:3px solid #000;box-shadow:4px 4px 0 #000;margin:8px 0}
.block-container .totalbox,.block-container .totalbox *{color:#000 !important}
.block-container .paper,.block-container .paper *{color:#111 !important}
.paper{background:#FFFDF2;border:2px dashed #555;border-radius:6px;padding:14px 16px;font-family:'Courier New',monospace;
  max-width:420px;margin:auto}
.paper table{width:100%;border-collapse:collapse}.paper td{padding:2px 0;vertical-align:top}
@media (max-width:760px){.block-container{padding:.8rem .7rem 2rem;box-shadow:4px 4px 0 var(--p)}
  .hop-title{font-size:1.7rem}.hop-head img{max-height:56px}}

/* ── BOTONES v3: TODOS iguales, legibles y vistosos (incluye popovers "Eliminar", link buttons, uploader) ── */
:where(button[data-testid^="stBaseButton-secondary"],button[data-testid^="stBaseButton-primary"],button[data-testid="stBaseButton-secondaryFormSubmit"],button[data-testid="stBaseButton-primaryFormSubmit"],[data-testid="stPopoverButton"],[data-testid^="stBaseLinkButton"],[data-testid="stFileUploaderDropzone"] button,.stDownloadButton button,.stButton button,.stFormSubmitButton button){
  background:linear-gradient(135deg,#23233a,#0d0d16) !important;color:#fff !important;-webkit-text-fill-color:#fff !important;
  border:3px solid var(--t) !important;border-radius:14px !important;box-shadow:4px 4px 0 var(--t) !important;
  font-weight:800 !important;opacity:1 !important;text-decoration:none !important;
  transition:transform .12s, box-shadow .12s, background .12s}
:where(button[data-testid^="stBaseButton-secondary"] *,button[data-testid^="stBaseButton-primary"] *,button[data-testid="stBaseButton-secondaryFormSubmit"] *,button[data-testid="stBaseButton-primaryFormSubmit"] *,[data-testid="stPopoverButton"] *,[data-testid^="stBaseLinkButton"] *,[data-testid="stFileUploaderDropzone"] button *,.stDownloadButton button *,.stButton button *,.stFormSubmitButton button *){color:inherit !important;-webkit-text-fill-color:currentColor !important;fill:currentColor !important;opacity:1 !important}
:where(button[data-testid^="stBaseButton-secondary"]:hover:not(:disabled),button[data-testid^="stBaseButton-primary"]:hover:not(:disabled),button[data-testid="stBaseButton-secondaryFormSubmit"]:hover:not(:disabled),button[data-testid="stBaseButton-primaryFormSubmit"]:hover:not(:disabled),[data-testid="stPopoverButton"]:hover:not(:disabled),[data-testid^="stBaseLinkButton"]:hover:not(:disabled),[data-testid="stFileUploaderDropzone"] button:hover:not(:disabled),.stDownloadButton button:hover:not(:disabled),.stButton button:hover:not(:disabled),.stFormSubmitButton button:hover:not(:disabled)){
  background:var(--y) !important;color:#000 !important;-webkit-text-fill-color:#000 !important;border-color:var(--p) !important;
  box-shadow:6px 6px 0 var(--p) !important;transform:translate(-2px,-2px)}
:where(button[data-testid^="stBaseButton-secondary"]:active:not(:disabled),button[data-testid^="stBaseButton-primary"]:active:not(:disabled),button[data-testid="stBaseButton-secondaryFormSubmit"]:active:not(:disabled),button[data-testid="stBaseButton-primaryFormSubmit"]:active:not(:disabled),[data-testid="stPopoverButton"]:active:not(:disabled),[data-testid^="stBaseLinkButton"]:active:not(:disabled),[data-testid="stFileUploaderDropzone"] button:active:not(:disabled),.stDownloadButton button:active:not(:disabled),.stButton button:active:not(:disabled),.stFormSubmitButton button:active:not(:disabled)){transform:translate(3px,3px);box-shadow:0 0 0 var(--p) !important}
:where(button[data-testid="stBaseButton-primary"],button[data-testid="stBaseButton-primaryFormSubmit"],button[kind="primary"],[data-testid="stBaseLinkButton-primary"]){
  background:linear-gradient(135deg,var(--p),#FF6A3D) !important;border-color:var(--y) !important;box-shadow:4px 4px 0 var(--y) !important;color:#fff !important}
:where(button[data-testid^="stBaseButton-secondary"]:disabled,button[data-testid^="stBaseButton-primary"]:disabled,button[data-testid="stBaseButton-secondaryFormSubmit"]:disabled,button[data-testid="stBaseButton-primaryFormSubmit"]:disabled,[data-testid="stPopoverButton"]:disabled,[data-testid^="stBaseLinkButton"]:disabled,[data-testid="stFileUploaderDropzone"] button:disabled,.stDownloadButton button:disabled,.stButton button:disabled,.stFormSubmitButton button:disabled){
  background:#242433 !important;color:#d6d6e4 !important;-webkit-text-fill-color:#d6d6e4 !important;border-color:#6b6b85 !important;box-shadow:none !important;
  opacity:.8 !important;transform:none !important;cursor:not-allowed}
:where(button[data-testid^="stBaseButton-secondary"]:focus-visible,button[data-testid^="stBaseButton-primary"]:focus-visible,button[data-testid="stBaseButton-secondaryFormSubmit"]:focus-visible,button[data-testid="stBaseButton-primaryFormSubmit"]:focus-visible,[data-testid="stPopoverButton"]:focus-visible,[data-testid^="stBaseLinkButton"]:focus-visible,[data-testid="stFileUploaderDropzone"] button:focus-visible,.stDownloadButton button:focus-visible,.stButton button:focus-visible,.stFormSubmitButton button:focus-visible){outline:3px solid var(--y) !important;outline-offset:2px}
/* eliminar (también el botón que abre el cartelito de confirmación) */
.block-container [class*="st-key-del_"] button,.block-container [class*="st-key-del_"] [data-testid="stPopoverButton"]{
  background:linear-gradient(135deg,#C4152F,#7A0A1C) !important;border-color:#FF4D6D !important;color:#fff !important;
  -webkit-text-fill-color:#fff !important;box-shadow:4px 4px 0 #000 !important}
.block-container [class*="st-key-del_"] button *,.block-container [class*="st-key-del_"] [data-testid="stPopoverButton"] *{color:#fff !important;fill:#fff !important}
.block-container [class*="st-key-del_"] button:hover,.block-container [class*="st-key-del_"] [data-testid="stPopoverButton"]:hover{
  background:#FF1F3D !important;color:#fff !important;-webkit-text-fill-color:#fff !important;border-color:#FFE600 !important}
/* cartelito (popover) oscuro, no blanco */
[data-testid="stPopoverBody"]{background:#12121a !important;border:3px solid var(--p) !important;border-radius:16px !important;color:#fff !important}
[data-testid="stPopoverBody"] *{color:#fff}
</style>
"""

# ─────────────────────────────────────────
# SUPABASE
# ─────────────────────────────────────────
@st.cache_resource
def hop_get_supabase():
    for sec in ("hopsie_supabase", "supabase"):
        if sec in st.secrets:
            url = str(st.secrets[sec].get("url", "")).strip()
            key = str(st.secrets[sec].get("key", "")).strip()
            if url and key and "XXXX" not in url:
                return create_client(url, key)
    return None


def tb(t):
    return hop_get_supabase().table(t)


def listar(t, order=None, desc=False, limit=None, **eq):
    q = tb(t).select("*")
    for k, v in eq.items():
        q = q.eq(k, v)
    if order:
        q = q.order(order, desc=desc)
    if limit:
        q = q.limit(limit)
    return q.execute().data or []


def uno(t, id_):
    r = tb(t).select("*").eq("id", id_).limit(1).execute().data
    return r[0] if r else None


def insertar(t, d):
    return tb(t).insert(d).execute().data


def actualizar(t, id_, d):
    tb(t).update(d).eq("id", id_).execute()


def borrar(t, id_):
    tb(t).delete().eq("id", id_).execute()


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def ahora_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat()


def parse_ts(s):
    return pd.to_datetime(s, utc=True).to_pydatetime()


def hop_fmt_dt(s):
    return parse_ts(s).astimezone(TZ).strftime("%d/%m %H:%M") if s else ""


def inicio_dia_utc(offset=0):
    n = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=offset)
    return n.astimezone(timezone.utc)


def peso(n):
    try:
        return "$ " + f"{round(float(n)):,}".replace(",", ".")
    except Exception:
        return "$ 0"


def go(pagina):
    st.session_state["_goto"] = pagina
    st.rerun()


def autorefresh(seg):
    def deco(fn):
        return st.fragment(run_every=seg)(fn) if hasattr(st, "fragment") else fn
    return deco


# ── configuración (clave/valor) ──
def cfg_load():
    return {r["clave"]: r["valor"] for r in listar(T_CFG)}


CFG = {}  # se completa al entrar al módulo (ver main_hopsie)


def cfg_set(k, v):
    tb(T_CFG).upsert({"clave": k, "valor": v}).execute()
    CFG[k] = v


def cfg_num(k, d=0.0):
    try:
        return float(CFG.get(k) or d)
    except Exception:
        return d


# ── auth y auditoría ──
def hash_pw(pw, salt=None):
    salt = salt or pysecrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()
    return salt, h


def check_pw(pw, salt, h):
    return hmac.compare_digest(hash_pw(pw, salt)[1], h)


def usuario_actual():
    return st.session_state.get("hs_user")


def actor():
    u = usuario_actual()
    return u["usuario"] if u else "salon"


def es_dueno():
    u = usuario_actual()
    return bool(u and u["rol"] == "dueno")


def log(accion, detalle="", quien=None):
    try:
        insertar(T_LOG, {"usuario": quien or actor(), "accion": accion, "detalle": str(detalle)[:500]})
    except Exception:
        pass


# ── logos ──
def _data_uri(path):
    return f"data:{MIME[path.suffix.lower().lstrip('.')]};base64,{base64.b64encode(path.read_bytes()).decode()}"


def logo_uri():
    if CFG.get("logo_b64"):
        return "data:image/png;base64," + CFG["logo_b64"]
    return _data_uri(_LOGO_FILE) if _LOGO_FILE else None


@st.cache_data(show_spinner=False)
def logo_proveedor(slug):
    p = _buscar_archivo([slug], [BASE_DIR / "logos", BASE_DIR / "assets" / "logos", BASE_DIR])
    return _data_uri(p) if p else None


def chip(slug, h=32):
    uri = logo_proveedor(slug)
    if uri:
        return f'<span class="pchip"><img src="{uri}" style="height:{h}px" alt="{esc(PROV_NOMBRE[slug])}"></span>'
    return (f'<span class="pchip" style="background:{PROV_COLOR[slug]};color:#fff !important;'
            f'-webkit-text-fill-color:#fff">{esc(PROV_NOMBRE[slug])}</span>')


def qr_png(data):
    if qrcode is None:
        return None
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=9, border=3)
    qr.add_data(data)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").convert("RGB").save(buf, "PNG")
    return buf.getvalue()


# ─────────────────────────────────────────
# LÓGICA: STOCK, ÍTEMS, TOTALES
# ─────────────────────────────────────────
def mover_stock(insumo_id, delta, tipo, motivo="", comanda_id=None):
    i = uno(T_INS, insumo_id)
    if not i:
        return None
    nuevo = round(float(i["stock"]) + float(delta), 3)
    actualizar(T_INS, insumo_id, {"stock": nuevo})
    insertar(T_MOV, {"insumo_id": insumo_id, "tipo": tipo, "cantidad": float(delta),
                     "stock_resultante": nuevo, "motivo": motivo, "usuario": actor(),
                     "comanda_id": comanda_id})
    return nuevo, i


def aplicar_receta(producto_id, unidades, comanda_id, motivo=""):
    """unidades>0 consume insumos; unidades<0 los devuelve. Retorna avisos de stock negativo."""
    avisos = []
    if not producto_id:
        return avisos
    for r in listar(T_REC, producto_id=producto_id):
        res = mover_stock(r["insumo_id"], -float(r["cantidad"]) * unidades,
                          "consumo" if unidades > 0 else "devolucion", motivo, comanda_id)
        if res and res[0] < 0:
            avisos.append(f"{res[1]['nombre']} quedó en {res[0]:g} {res[1]['unidad']}")
    return avisos


def items_de(ids, activos=True):
    if not ids:
        return []
    q = tb(T_ITEMS).select("*").in_("comanda_id", list(ids))
    if activos:
        q = q.eq("anulado", False)
    return q.order("id").execute().data or []


def totales(com, items):
    act = [i for i in items if not i.get("anulado")]
    sub = round(sum(float(i["precio_unit"]) * float(i["cantidad"]) for i in act))
    desc = round(sub * float(com.get("descuento_pct") or 0) / 100)
    prop = round((sub - desc) * float(com.get("propina_pct") or 0) / 100)
    return {"sub": sub, "desc": desc, "prop": prop, "total": sub - desc + prop,
            "unidades": sum(int(i["cantidad"]) for i in act)}


def hop_agregar_unidad(com, prod):
    ex = (tb(T_ITEMS).select("*").eq("comanda_id", com["id"]).eq("producto_id", prod["id"])
          .eq("anulado", False).eq("estado", "pendiente").eq("nota", "").eq("confirmado", False).limit(1).execute().data)
    if ex:
        actualizar(T_ITEMS, ex[0]["id"], {"cantidad": ex[0]["cantidad"] + 1})
    else:
        insertar(T_ITEMS, {"comanda_id": com["id"], "producto_id": prod["id"], "nombre": prod["nombre"],
                           "sector": prod["sector"], "precio_unit": float(prod["precio"]), "cantidad": 1,
                           "cargado_por": actor(), "confirmado": False})
    avisos = aplicar_receta(prod["id"], 1, com["id"], f"Comanda #{com['id']}")
    log("item_agregado", f"comanda {com['id']} · {prod['nombre']}")
    for a in avisos:
        st.toast(f"⚠️ Stock negativo: {a}")


def sumar_pedido_extra(item):
    """Suma +1 a un ítem que YA se mandó a cocina/barra: va como pedido nuevo sin confirmar (la cocina no ve cambios a escondidas)."""
    ex = (tb(T_ITEMS).select("*").eq("comanda_id", item["comanda_id"]).eq("anulado", False)
          .eq("confirmado", False).eq("nombre", item["nombre"]).eq("nota", item.get("nota") or "")
          .eq("precio_unit", float(item["precio_unit"])).limit(1).execute().data)
    if ex:
        actualizar(T_ITEMS, ex[0]["id"], {"cantidad": ex[0]["cantidad"] + 1})
    else:
        insertar(T_ITEMS, {"comanda_id": item["comanda_id"], "producto_id": item["producto_id"], "nombre": item["nombre"],
                           "sector": item["sector"], "precio_unit": float(item["precio_unit"]), "cantidad": 1,
                           "nota": item.get("nota") or "", "cargado_por": actor(), "confirmado": False})
    aplicar_receta(item["producto_id"], 1, item["comanda_id"], f"Comanda #{item['comanda_id']}")
    log("item_agregado", f"comanda {item['comanda_id']} · +1 {item['nombre']} (pendiente de confirmar)")


def confirmar_pedido(com, items):
    """La moza confirma: recién ahora el pedido llega a cocina / barra."""
    if not items:
        return
    ahora = iso(ahora_utc())
    tb(T_ITEMS).update({"confirmado": True, "confirmado_ts": ahora}).in_("id", [i["id"] for i in items]).execute()
    log("pedido_confirmado", f"comanda {com['id']} · " + ", ".join(f"{i['cantidad']}× {i['nombre']}" for i in items))
    st.toast("Pedido enviado a cocina / barra 🔥")


def sumar_cantidad(item, delta):
    nueva = item["cantidad"] + delta
    if nueva <= 0:
        return anular_item(item)
    actualizar(T_ITEMS, item["id"], {"cantidad": nueva})
    aplicar_receta(item["producto_id"], delta, item["comanda_id"], f"Comanda #{item['comanda_id']}")
    log("item_cantidad", f"comanda {item['comanda_id']} · {item['nombre']} → {nueva}")


def anular_item(item):
    actualizar(T_ITEMS, item["id"], {"anulado": True})
    aplicar_receta(item["producto_id"], -item["cantidad"], item["comanda_id"],
                   f"Anulación comanda #{item['comanda_id']}")
    log("item_anulado", f"comanda {item['comanda_id']} · {item['cantidad']}× {item['nombre']}")


def anular_comanda(com, motivo):
    for it in items_de([com["id"]]):
        aplicar_receta(it.get("producto_id"), -it["cantidad"], com["id"], f"Comanda anulada #{com['id']}")
    actualizar(T_COM, com["id"], {"estado": "cancelada", "cerrada_ts": iso(ahora_utc()), "nota": motivo})
    log("comanda_anulada", f"comanda {com['id']} · {motivo}")


def cerrar_comanda(com, tot, pagos):
    mets = ", ".join(sorted({p["metodo"] for p in pagos}))
    actualizar(T_COM, com["id"], {"estado": "pagada", "cerrada_ts": iso(ahora_utc()),
                                  "total": tot["total"], "metodo_pago": mets})
    log("comanda_cerrada", f"comanda {com['id']} · {peso(tot['total'])} · {mets}")


# ─────────────────────────────────────────
# LÓGICA: CUENTAS (mesa · barra · cliente VIP) Y CLIENTES
# ─────────────────────────────────────────
TIPOS_CUENTA = {"mesa": "🍽️ Mesa", "barra": "🍻 Barra (de pie)", "cliente": "⭐ Cliente VIP (cuenta personal)"}
METODOS = ["Efectivo", "QR / Transferencia", "Tarjeta"]


def mapa_mesas():
    return {m["id"]: m for m in listar(T_MESAS)}


def mapa_clientes():
    return {c["id"]: c for c in listar(T_CLI)}


def clientes_activos(solo_vip=False):
    q = tb(T_CLI).select("*").eq("activo", True)
    if solo_vip:
        q = q.eq("vip", True)
    return q.order("nombre").execute().data or []


def fmt_cliente(c):
    if not c:
        return "— sin cliente registrado —"
    ap = f" “{c['apodo']}”" if c.get("apodo") else ""
    tel = f" · {c['telefono']}" if c.get("telefono") else ""
    return f"{'⭐ ' if c.get('vip') else ''}{c['nombre']}{ap}{tel}"


def etiqueta_cuenta(com, mesas_map, cli_map):
    """Nombre legible de una cuenta, esté o no en una mesa."""
    tipo = com.get("tipo") or "mesa"
    m = mesas_map.get(com.get("mesa_id"))
    cli = cli_map.get(com.get("cliente_id"))
    if tipo == "cliente":
        base = "⭐ " + (cli["nombre"] if cli else (com.get("etiqueta") or "Cliente"))
        return base + (f" · {m['nombre']}" if m else "")
    if tipo == "barra":
        return "🍻 Barra · " + (com.get("etiqueta") or "sin nombre")
    if m:
        return m["nombre"]
    if tipo == "mesa" and com.get("etiqueta"):
        return com["etiqueta"]
    return "Cuenta sin mesa" if not com.get("mesa_id") else "Mesa no disponible"


def cuenta_vip_abierta(cliente_id):
    r = (tb(T_COM).select("*").eq("estado", "abierta").eq("cliente_id", cliente_id)
         .eq("tipo", "cliente").limit(1).execute().data)
    return r[0] if r else None


def registrar_cliente(nombre, telefono="", vip=False, descuento=0.0):
    """Busca por teléfono / nombre y, si no existe, lo da de alta en la base de clientes."""
    nombre, telefono = nombre.strip(), telefono.strip()
    if not nombre:
        return None
    if telefono:
        ex = listar(T_CLI, telefono=telefono)
        if ex:
            return ex[0]
    else:
        ex = [c for c in listar(T_CLI) if c["nombre"].strip().lower() == nombre.lower()]
        if ex:
            return ex[0]
    r = insertar(T_CLI, {"nombre": nombre, "telefono": telefono, "vip": bool(vip),
                         "descuento_pct": float(descuento or 0), "alta_por": actor()})[0]
    log("cliente_creado", f"{nombre} · {telefono or 's/tel'}{' · VIP' if vip else ''}")
    return r


def campos_cliente(pref, solo_vip=False, vip_default=False):
    """Selector de cliente + alta rápida. Se usa dentro de un st.form. Devuelve (sel, nuevo, tel, vip_nuevo)."""
    lista = clientes_activos(solo_vip)
    sel = st.selectbox("Cliente habitué" if solo_vip else "Cliente registrado (opcional)",
                       [None] + lista, format_func=fmt_cliente, key=f"{pref}_cli")
    st.caption("¿Cliente nuevo? Cargalo acá y queda guardado en la base de clientes.")
    a, b, c = st.columns([3, 2, 2])
    nuevo = a.text_input("Nombre (cliente nuevo)", key=f"{pref}_nn")
    tel = b.text_input("Teléfono", key=f"{pref}_nt")
    vipn = c.checkbox("Habitué VIP", value=vip_default, key=f"{pref}_nv")
    return sel, nuevo, tel, vipn


def resolver_cliente(sel, nuevo, tel, vip_nuevo):
    if sel:
        return sel
    if nuevo and nuevo.strip():
        return registrar_cliente(nuevo, tel or "", vip_nuevo)
    return None


def abrir_cuenta(tipo, mesa_id=None, comensales=1, mozo="", cliente=None, etiqueta=""):
    """Abre una cuenta. Si el cliente es habitué se le abre SU cuenta personal (o se retoma la que ya tenía)."""
    if cliente and cliente.get("vip"):
        tipo, etiqueta = "cliente", cliente["nombre"]
        ya = cuenta_vip_abierta(cliente["id"])
        if ya:
            if mesa_id and not ya.get("mesa_id"):
                actualizar(T_COM, ya["id"], {"mesa_id": mesa_id})
                log("cuenta_mesa_asignada", f"comanda {ya['id']} · {cliente['nombre']} → mesa {mesa_id}")
            st.toast(f"⭐ {cliente['nombre']} ya tenía cuenta abierta: la retomo.")
            return ya
    r = insertar(T_COM, {
        "mesa_id": mesa_id, "tipo": tipo, "etiqueta": (etiqueta or "").strip(),
        "cliente_id": cliente["id"] if cliente else None, "comensales": int(comensales), "mozo": (mozo or "").strip(),
        "propina_pct": cfg_num("propina_default", 0),
        "descuento_pct": float(cliente.get("descuento_pct") or 0) if cliente else 0,
        "abierta_por": actor()})[0]
    log("mesa_abierta" if tipo == "mesa" else "cuenta_abierta",
        f"{tipo} · {etiqueta or mesa_id} · comanda {r['id']}")
    return r


def _igual(a, b):
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return (a or "") == (b or "")


def recalcular_comanda(cid):
    """Si la cuenta ya está cobrada, actualiza total y medios de pago tras una corrección."""
    com = uno(T_COM, cid)
    if com and com["estado"] == "pagada":
        tot = totales(com, items_de([cid]))
        mets = ", ".join(sorted({p["metodo"] for p in listar(T_PAGOS, comanda_id=cid)}))
        actualizar(T_COM, cid, {"total": tot["total"], "metodo_pago": mets})


def hop_editar_item(it, cant=None, precio=None, nota=None, nombre=None, tocar_stock=True):
    cambios, partes = {}, []
    if cant is not None and int(cant) != int(it["cantidad"]):
        delta = int(cant) - int(it["cantidad"])
        cambios["cantidad"] = int(cant)
        partes.append(f"cantidad {it['cantidad']} → {int(cant)}")
        if tocar_stock:
            aplicar_receta(it.get("producto_id"), delta, it["comanda_id"], f"Edición comanda #{it['comanda_id']}")
    if precio is not None and not _igual(precio, it["precio_unit"]):
        cambios["precio_unit"] = float(precio)
        partes.append(f"precio {peso(it['precio_unit'])} → {peso(precio)}")
    if nota is not None and (nota or "") != (it.get("nota") or ""):
        cambios["nota"] = nota
        partes.append("nota")
    if nombre is not None and nombre.strip() and nombre.strip() != it["nombre"]:
        cambios["nombre"] = nombre.strip()
        partes.append(f"nombre → {nombre.strip()}")
    if cambios:
        actualizar(T_ITEMS, it["id"], cambios)
        log("item_editado", f"comanda {it['comanda_id']} · {it['nombre']} · " + ", ".join(partes))
    return bool(cambios)


def set_anulado(it, anular, estado_comanda):
    """Anula / restaura un ítem. En comandas canceladas el stock ya fue devuelto, así que no se toca."""
    actualizar(T_ITEMS, it["id"], {"anulado": bool(anular)})
    if estado_comanda != "cancelada":
        aplicar_receta(it.get("producto_id"), -it["cantidad"] if anular else it["cantidad"], it["comanda_id"],
                       ("Anulación" if anular else "Restauración") + f" comanda #{it['comanda_id']}")
    log("item_anulado" if anular else "item_restaurado", f"comanda {it['comanda_id']} · {it['cantidad']}× {it['nombre']}")


def form_datos_cuenta(com, key, importes=True):
    """Edita los datos de una cuenta: tipo, mesa, cliente, nombre, comensales, mozo, descuento, propina, nota."""
    cid = com["id"]
    abierta = com["estado"] == "abierta"
    mesas_all = listar(T_MESAS, order="orden")
    otras = ({c["mesa_id"] for c in listar(T_COM, estado="abierta") if c["id"] != cid and c.get("mesa_id")}
             if abierta else set())
    mesas_ok = [m for m in mesas_all if m["id"] not in otras and (not abierta or m["activa"] or m["id"] == com.get("mesa_id"))]
    op_mesa = [None] + mesas_ok
    idx_m = next((i for i, m in enumerate(op_mesa) if m and m["id"] == com.get("mesa_id")), 0)
    clientes = clientes_activos()
    if com.get("cliente_id") and not any(c["id"] == com["cliente_id"] for c in clientes):
        cur = uno(T_CLI, com["cliente_id"])
        if cur:
            clientes.append(cur)
    op_cli = [None] + clientes
    idx_c = next((i for i, c in enumerate(op_cli) if c and c["id"] == com.get("cliente_id")), 0)
    tipos = list(TIPOS_CUENTA)
    if com.get("mesa_id") and com["mesa_id"] not in {m["id"] for m in mesas_all}:
        st.warning("Esta cuenta apunta a una mesa que ya no existe. Elegí una mesa válida o pasala a barra / VIP.")
    elif abierta and com.get("mesa_id") and com["mesa_id"] not in {m["id"] for m in mesas_all if m["activa"]}:
        st.warning("Esta cuenta está en una mesa desactivada (por eso el salón la cuenta como ocupada). Podés moverla acá.")
    with st.form(f"edc_{key}"):
        tipo = st.selectbox("Tipo de cuenta", tipos, index=tipos.index(com.get("tipo") or "mesa"), format_func=TIPOS_CUENTA.get)
        a, b = st.columns(2)
        mesa = a.selectbox("Mesa", op_mesa, index=idx_m,
                           format_func=lambda m: "— sin mesa —" if m is None else f"{m['nombre']} ({m['zona']})")
        cli = b.selectbox("Cliente", op_cli, index=idx_c, format_func=fmt_cliente)
        etiqueta = st.text_input("Nombre / referencia (para barra o cuentas sin mesa)", value=com.get("etiqueta") or "")
        cols = st.columns(4 if importes else 2)
        comen = cols[0].number_input("Comensales", 1, 60, int(com["comensales"] or 1))
        mozo = cols[1].text_input("Adicionista / mozo", value=com.get("mozo") or "")
        desc, prop = float(com.get("descuento_pct") or 0), float(com.get("propina_pct") or 0)
        if importes:
            desc = cols[2].number_input("Descuento %", 0.0, 100.0, desc, 5.0)
            prop = cols[3].number_input("Propina %", 0.0, 100.0, prop, 5.0)
        nota = st.text_input("Nota", value=com.get("nota") or "")
        ok = st.form_submit_button("💾 Guardar cambios", type="primary")
    if not ok:
        return
    if tipo == "mesa" and mesa is None:
        st.error("Una cuenta de mesa necesita una mesa.")
        return
    if tipo == "cliente":
        if cli is None:
            st.error("Una cuenta VIP necesita un cliente.")
            return
        ya = cuenta_vip_abierta(cli["id"])
        if abierta and ya and ya["id"] != cid:
            st.error(f"{cli['nombre']} ya tiene otra cuenta VIP abierta (#{ya['id']}).")
            return
        if not etiqueta.strip():
            etiqueta = cli["nombre"]
    nuevo = {"tipo": tipo, "mesa_id": mesa["id"] if (mesa and tipo != "barra") else None,
             "cliente_id": cli["id"] if cli else None, "etiqueta": etiqueta.strip(), "comensales": int(comen),
             "mozo": mozo.strip(), "nota": nota.strip(), "descuento_pct": desc, "propina_pct": prop}
    cambios = {k: v for k, v in nuevo.items() if not _igual(com.get(k), v)}
    if not cambios:
        st.info("No hay cambios para guardar.")
        return
    actualizar(T_COM, cid, nuevo)
    mm = {m["id"]: m["nombre"] for m in mesas_all}
    det = []
    for k, v in cambios.items():
        if k == "mesa_id":
            det.append(f"mesa {mm.get(com.get('mesa_id'), '—')} → {mm.get(v, '—')}")
        elif k == "cliente_id":
            det.append("cliente cambiado")
        else:
            det.append(f"{k} {com.get(k)!s} → {v!s}")
    log("cuenta_editada", f"comanda {cid} · " + "; ".join(det))
    recalcular_comanda(cid)
    st.toast("Cuenta actualizada ✅")
    st.rerun()


# ─────────────────────────────────────────
# TICKET / PRE-CUENTA
# ─────────────────────────────────────────
TITULO_TICKET = {"abierta": "PRE-CUENTA", "pagada": "COMPROBANTE DE PAGO", "cancelada": "CUENTA ANULADA"}


def _linea_pago(p):
    prov = f" · {p['proveedor']}" if p.get("proveedor") else ""
    return f"{p['metodo']}{prov}"


def ticket_html(com, mesa, items, tot, pagos=None, cli=None):
    act = [i for i in items if not i.get("anulado")]
    filas = ""
    for i in act:
        nota = f"<br><small>📝 {esc(i['nota'])}</small>" if i.get("nota") else ""
        filas += (f"<tr><td>{i['cantidad']}×</td><td>{esc(i['nombre'])}{nota}</td>"
                  f"<td style='text-align:right'>{peso(float(i['precio_unit']) * i['cantidad'])}</td></tr>")
    extra = ""
    if tot["desc"]:
        extra += f"<tr><td colspan=2>Descuento {com['descuento_pct']:g}%</td><td style='text-align:right'>-{peso(tot['desc'])}</td></tr>"
    if tot["prop"]:
        extra += f"<tr><td colspan=2>Propina {com['propina_pct']:g}%</td><td style='text-align:right'>{peso(tot['prop'])}</td></tr>"
    pag = ""
    if pagos:
        pag = "<tr><td colspan=3><hr></td></tr><tr><td colspan=3><b>PAGOS</b></td></tr>" + "".join(
            f"<tr><td colspan=2>{esc(_linea_pago(p))}</td><td style='text-align:right'>{peso(p['monto'])}</td></tr>" for p in pagos)
    lg = logo_uri()
    img = f'<div style="text-align:center"><img src="{lg}" style="max-height:60px"></div>' if lg else ""
    nombre = esc(CFG.get("negocio_nombre") or "HOPSIE · Cerveza Artesanal")
    pie = esc(CFG.get("ticket_pie") or "¡Gracias por visitarnos! 🍻")
    titulo = TITULO_TICKET.get(com.get("estado"), "PRE-CUENTA")
    meta = [f"Comanda #{com['id']}"]
    if com.get("mozo"):
        meta.append(f"Atendió: {esc(com['mozo'])}")
    if cli:
        meta.append(f"Cliente: {esc(cli['nombre'])}")
    cerr = f" → {hop_fmt_dt(com['cerrada_ts'])}" if com.get("cerrada_ts") else ""
    return (f'<div class="paper">{img}<div style="text-align:center;font-weight:bold">{nombre}</div>'
            f'<div style="text-align:center">{titulo} · {esc(mesa["nombre"])}<br>{hop_fmt_dt(com["abierta_ts"])}{cerr}'
            f'<br><small>{" · ".join(meta)}</small></div><hr>'
            f"<table>{filas}<tr><td colspan=3><hr></td></tr>"
            f"<tr><td colspan=2>Subtotal</td><td style='text-align:right'>{peso(tot['sub'])}</td></tr>{extra}"
            f"<tr><td colspan=2><b>TOTAL</b></td><td style='text-align:right'><b>{peso(tot['total'])}</b></td></tr>{pag}"
            f'</table><hr><div style="text-align:center">{pie}</div></div>')


def ticket_txt(com, mesa, items, tot, pagos=None):
    act = [i for i in items if not i.get("anulado")]
    titulo = TITULO_TICKET.get(com.get("estado"), "PRE-CUENTA")
    L = [CFG.get("negocio_nombre") or "HOPSIE · Cerveza Artesanal",
         f"{titulo} · {mesa['nombre']} · {hop_fmt_dt(com['abierta_ts'])}", f"Comanda #{com['id']}", "-" * 34]
    for i in act:
        L.append(f"{i['cantidad']}x {i['nombre']:<20} {peso(float(i['precio_unit']) * i['cantidad']):>10}")
        if i.get("nota"):
            L.append(f"   · {i['nota']}")
    L += ["-" * 34, f"Subtotal {peso(tot['sub'])}"]
    if tot["desc"]:
        L.append(f"Descuento -{peso(tot['desc'])}")
    if tot["prop"]:
        L.append(f"Propina {peso(tot['prop'])}")
    L.append(f"TOTAL {peso(tot['total'])}")
    if pagos:
        L += ["", "PAGOS"] + [f"{_linea_pago(p)} {peso(p['monto'])}" for p in pagos]
    L += ["", CFG.get("ticket_pie") or "¡Gracias por visitarnos!"]
    return "\n".join(L)


# ─────────────────────────────────────────
# TICKET EN IMAGEN (.png) — misma información y orden que el ticket de pre-cobro
# ─────────────────────────────────────────
_TTF = {False: ["DejaVuSansMono.ttf", "LiberationMono-Regular.ttf", "NotoSansMono-Regular.ttf", "DejaVuSans.ttf"],
        True: ["DejaVuSansMono-Bold.ttf", "LiberationMono-Bold.ttf", "NotoSansMono-Bold.ttf", "DejaVuSans-Bold.ttf"]}
_TTF_DIRS = [BASE_DIR / "fonts", BASE_DIR, Path("/usr/share/fonts/truetype/dejavu"),
             Path("/usr/share/fonts/truetype/liberation"), Path("/usr/share/fonts/truetype/noto"),
             Path("/usr/share/fonts/dejavu"), Path("/usr/share/fonts/TTF")]


def _fuente(bold, size):
    for nombre in _TTF[bool(bold)]:
        for carpeta in _TTF_DIRS + [None]:
            try:
                return ImageFont.truetype(str(carpeta / nombre) if carpeta else nombre, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _alto(fo):
    return getattr(fo, "size", 16)


def _sin_emoji(t):
    """Pillow no dibuja emojis a color: se quitan del texto del .png (en pantalla se ven igual)."""
    def _ok(ch):
        o = ord(ch)
        return (o <= 0xFFFF and not (0x2300 <= o <= 0x23FF or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF)
                and ch not in "\ufe0f\u200d")
    return "".join(ch for ch in str(t or "") if _ok(ch)).strip()


def _logo_pil():
    try:
        if CFG.get("logo_b64"):
            return Image.open(io.BytesIO(base64.b64decode(CFG["logo_b64"]))).convert("RGBA")
        if _LOGO_FILE and _LOGO_FILE.suffix.lower() != ".svg":
            return Image.open(_LOGO_FILE).convert("RGBA")
    except Exception:
        pass
    return None


def ticket_png(com, nombre, items, tot, pagos=None, cli=None):
    """Genera la imagen del ticket lista para mandar por WhatsApp. Devuelve bytes PNG."""
    W, M = 760, 48
    INK, GRIS, PAPEL, AMARILLO = (20, 20, 20), (110, 110, 110), (255, 253, 242), (255, 230, 0)
    F = {"s": _fuente(False, 24), "b": _fuente(True, 25), "sm": _fuente(False, 19), "h": _fuente(True, 29),
         "n": _fuente(True, 34), "t": _fuente(True, 56)}
    img = Image.new("RGB", (W, 4200), PAPEL)
    d = ImageDraw.Draw(img)
    st_y = [44]

    def ancho(t, fo):
        return d.textlength(t, font=fo)

    def envolver(t, fo, max_w):
        lineas, act = [], ""
        for w in str(t).split():
            prueba = (act + " " + w).strip()
            if ancho(prueba, fo) <= max_w:
                act = prueba
                continue
            if act:
                lineas.append(act)
            act = w
            while ancho(act, fo) > max_w and len(act) > 1:  # palabra más larga que la línea
                k = len(act)
                while k > 1 and ancho(act[:k], fo) > max_w:
                    k -= 1
                lineas.append(act[:k])
                act = act[k:]
        if act:
            lineas.append(act)
        return lineas or [""]

    def centrado(t, fo, fill=INK):
        for ln in envolver(t, fo, W - 2 * M):
            d.text(((W - ancho(ln, fo)) / 2, st_y[0]), ln, font=fo, fill=fill)
            st_y[0] += int(_alto(fo) * 1.35)

    def fila(izq, der, fo, fill=INK, sangria=0):
        w_der = ancho(der, fo) if der else 0
        for k, ln in enumerate(envolver(izq, fo, W - 2 * M - w_der - 24 - sangria)):
            d.text((M + sangria, st_y[0]), ln, font=fo, fill=fill)
            if k == 0 and der:
                d.text((W - M - w_der, st_y[0]), der, font=fo, fill=fill)
            st_y[0] += int(_alto(fo) * 1.32)

    def sep():
        st_y[0] += 8
        x = M
        while x < W - M:
            d.line([(x, st_y[0]), (x + 10, st_y[0])], fill=GRIS, width=2)
            x += 18
        st_y[0] += 20

    act = [i for i in items if not i.get("anulado")]
    lg = _logo_pil()
    if lg:
        lg.thumbnail((380, 130))
        img.paste(lg, (int((W - lg.width) / 2), st_y[0]), lg)
        st_y[0] += lg.height + 16
    centrado(_sin_emoji(CFG.get("negocio_nombre") or "HOPSIE · Cerveza Artesanal"), F["h"])
    centrado(TITULO_TICKET.get(com.get("estado"), "PRE-CUENTA"), F["n"])
    centrado(_sin_emoji(nombre), F["b"])
    cerr = f"  →  {hop_fmt_dt(com['cerrada_ts'])}" if com.get("cerrada_ts") else ""
    centrado(f"{hop_fmt_dt(com['abierta_ts'])}{cerr}", F["sm"], GRIS)
    meta = [f"Comanda #{com['id']}"]
    if com.get("mozo"):
        meta.append(f"Atendió: {_sin_emoji(com['mozo'])}")
    if cli:
        meta.append(f"Cliente: {_sin_emoji(cli['nombre'])}")
    centrado("  ·  ".join(meta), F["sm"], GRIS)
    sep()

    for i in act:
        fila(f"{i['cantidad']}× {_sin_emoji(i['nombre'])}", peso(float(i["precio_unit"]) * i["cantidad"]), F["s"])
        if i.get("nota"):
            fila(f"• {_sin_emoji(i['nota'])}", "", F["sm"], GRIS, sangria=34)
    if not act:
        centrado("(sin consumos)", F["sm"], GRIS)
    sep()
    fila("Subtotal", peso(tot["sub"]), F["s"])
    if tot["desc"]:
        fila(f"Descuento {com['descuento_pct']:g}%", "-" + peso(tot["desc"]), F["s"])
    if tot["prop"]:
        fila(f"Propina {com['propina_pct']:g}%", peso(tot["prop"]), F["s"])
    st_y[0] += 10
    alto_b = 92
    y0 = st_y[0]
    d.rounded_rectangle([M - 10, y0, W - M + 10, y0 + alto_b], radius=16, fill=INK)
    d.text((M + 8, y0 + (alto_b - _alto(F["n"])) / 2 - 3), "TOTAL", font=F["n"], fill=AMARILLO)
    tt = peso(tot["total"])
    d.text((W - M - 8 - ancho(tt, F["t"]), y0 + (alto_b - _alto(F["t"])) / 2 - 5), tt, font=F["t"], fill=AMARILLO)
    st_y[0] = y0 + alto_b + 22

    if pagos:
        sep()
        fila("PAGOS", "", F["b"])
        for p in pagos:
            fila(_sin_emoji(_linea_pago(p)), peso(p["monto"]), F["s"])
    if com.get("estado") == "abierta" and CFG.get("negocio_alias"):
        sep()
        centrado("Podés pagar por transferencia", F["sm"], GRIS)
        centrado(f"Alias: {CFG['negocio_alias']}", F["b"])
        if CFG.get("negocio_titular"):
            centrado(f"Titular: {_sin_emoji(CFG['negocio_titular'])}", F["sm"], GRIS)
    sep()
    centrado(_sin_emoji(CFG.get("ticket_pie")) or "¡Gracias por visitarnos!", F["b"])

    H = st_y[0] + 40
    papel = img.crop((0, 0, W, H))
    mask = Image.new("L", (W, H), 255)  # borde dentado arriba y abajo, como un ticket de verdad
    md = ImageDraw.Draw(mask)
    paso, diente = 22, 12
    for x in range(0, W, paso):
        md.polygon([(x, H), (x + paso / 2, H - diente), (x + paso, H)], fill=0)
        md.polygon([(x, 0), (x + paso / 2, diente), (x + paso, 0)], fill=0)

    PAD = 56
    CW, CH = W + 2 * PAD, H + 2 * PAD
    fondo = Image.new("RGB", (CW, CH))
    fd = ImageDraw.Draw(fondo)
    tramos = [(255, 230, 0), (0, 229, 207), (255, 46, 147)]  # amarillo → turquesa → rosa (colores de HOPSIE)
    for yy in range(CH):
        t = yy / max(1, CH - 1) * (len(tramos) - 1)
        k = min(int(t), len(tramos) - 2)
        f_ = t - k
        col = tuple(int(tramos[k][c] + (tramos[k + 1][c] - tramos[k][c]) * f_) for c in range(3))
        fd.line([(0, yy), (CW, yy)], fill=col)
    sombra = Image.new("L", (CW, CH), 0)
    sombra.paste(mask, (PAD + 8, PAD + 12))
    sombra = sombra.filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.45))
    fondo.paste((0, 0, 0), (0, 0, CW, CH), sombra)
    fondo.paste(papel, (PAD, PAD), mask)
    buf = io.BytesIO()
    fondo.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ─────────────────────────────────────────
# WHATSAPP
# ─────────────────────────────────────────
def tel_wa(tel):
    """Normaliza un teléfono argentino al formato de WhatsApp (549 + área + número, sin 0 ni 15). '' si no es válido."""
    raw = str(tel or "").strip()
    d = "".join(ch for ch in raw if ch.isdigit()).lstrip("0")
    if not d:
        return ""
    if raw.startswith("+") and not d.startswith("54"):
        return d if 8 <= len(d) <= 15 else ""  # número de otro país, tal cual
    n = d[2:] if d.startswith("54") else d
    if n.startswith("9"):
        n = n[1:]
    if len(n) == 12:  # sacó el "15" del celular: 11 15 5555 1234
        for k in (2, 3, 4):
            if n[k:k + 2] == "15":
                n = n[:k] + n[k + 2:]
                break
    return "549" + n if len(n) == 10 else ""


def wa_config():
    try:
        if "whatsapp" not in st.secrets:
            return None
        sec = st.secrets["whatsapp"]
        tok, pid = str(sec.get("token", "")).strip(), str(sec.get("phone_id", "")).strip()
        if not tok or not pid:
            return None
        return {"token": tok, "phone_id": pid, "version": str(sec.get("version", "v21.0")),
                "template": str(sec.get("template", "")).strip(), "lang": str(sec.get("template_lang", "es_AR")),
                "vars": int(sec.get("template_vars", 0) or 0)}
    except Exception:
        return None


def enviar_ticket_wa(com, nombre, items, tot, pagos, cli, telefono):
    """Manda el ticket .png por la API oficial de WhatsApp (Cloud API). Devuelve (ok, mensaje)."""
    cfg, num = wa_config(), tel_wa(telefono)
    if not cfg:
        return False, "WhatsApp automático no está configurado (Secrets [whatsapp])."
    if not num:
        return False, "El teléfono del cliente no es válido."
    try:
        png = ticket_png(com, nombre, items, tot, pagos, cli)
        base = f"https://graph.facebook.com/{cfg['version']}/{cfg['phone_id']}"
        h = {"Authorization": f"Bearer {cfg['token']}"}
        r = requests.post(base + "/media", headers=h, data={"messaging_product": "whatsapp", "type": "image/png"},
                          files={"file": (f"ticket_{com['id']}.png", png, "image/png")}, timeout=30)
        if r.status_code >= 400:
            return False, "WhatsApp rechazó la imagen: " + str((r.json().get("error") or {}).get("message", r.text))[:200]
        media_id = r.json()["id"]
        negocio = CFG.get("negocio_nombre") or "HOPSIE"
        if cfg["template"]:
            comp = [{"type": "header", "parameters": [{"type": "image", "image": {"id": media_id}}]}]
            vars_ = [(cli or {}).get("nombre") or "cliente", peso(tot["total"]), negocio][:cfg["vars"]]
            if vars_:
                comp.append({"type": "body", "parameters": [{"type": "text", "text": str(v)} for v in vars_]})
            payload = {"messaging_product": "whatsapp", "to": num, "type": "template",
                       "template": {"name": cfg["template"], "language": {"code": cfg["lang"]}, "components": comp}}
        else:
            payload = {"messaging_product": "whatsapp", "to": num, "type": "image",
                       "image": {"id": media_id, "caption": f"{negocio} · {nombre} · Total {peso(tot['total'])}. ¡Gracias!"}}
        r = requests.post(base + "/messages", headers={**h, "Content-Type": "application/json"}, json=payload, timeout=30)
        if r.status_code >= 400:
            return False, "WhatsApp no pudo entregarlo: " + str((r.json().get("error") or {}).get("message", r.text))[:200]
        log("ticket_whatsapp", f"comanda {com['id']} → +{num}")
        return True, f"Ticket enviado por WhatsApp a +{num}"
    except Exception as e:
        return False, f"No pude enviar el ticket: {e}"


def boton_compartir(png, fname, texto):
    """Celulares: abre el menú de compartir del sistema con la imagen adjunta (elegís WhatsApp y el contacto)."""
    b64 = base64.b64encode(png).decode()
    html = f"""
<button id="b" style="width:100%;padding:9px 12px;border-radius:12px;border:2px solid #00E5CF;background:#111;color:#fff;
 font-weight:700;font-family:sans-serif;font-size:15px;cursor:pointer">📤 Compartir imagen (celular)</button>
<script>
const B64="{b64}", NOMBRE={json.dumps(fname)}, TEXTO={json.dumps(texto)};
document.getElementById('b').onclick = async () => {{
  try {{
    const bin = atob(B64), arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    const file = new File([arr], NOMBRE, {{type: 'image/png'}});
    if (navigator.canShare && navigator.canShare({{files: [file]}})) {{
      await navigator.share({{files: [file], text: TEXTO}});
    }} else {{
      alert('Este navegador no permite compartir la imagen directo. Descargá el .png y adjuntalo en WhatsApp.');
    }}
  }} catch (e) {{
    if (!e || e.name !== 'AbortError') alert('No se pudo abrir el menú de compartir. Descargá el .png y adjuntalo en WhatsApp.');
  }}
}};
</script>"""
    if hasattr(st, "iframe"):  # versiones nuevas de Streamlit
        st.iframe(html.strip(), height=56)
    else:
        components.html(html, height=56)


def acciones_ticket(com, nombre, items, tot, pagos, cli, key):
    """Descargar .png, enviar por WhatsApp y cargar el teléfono del cliente. Devuelve el png generado."""
    png = ticket_png(com, nombre, items, tot, pagos, cli)
    fname = f"ticket_{com['id']}_{slugificar(_sin_emoji(nombre)) or 'cuenta'}.png"
    negocio = CFG.get("negocio_nombre") or "HOPSIE"
    st.markdown("**📲 Ticket para el cliente (imagen .png)**")
    tel = st.text_input("WhatsApp del cliente", value=(cli or {}).get("telefono") or "", key=f"wt_{key}",
                        placeholder="Ej. 11 5555 1234")
    num = tel_wa(tel)
    if tel.strip() and not num:
        st.caption("⚠️ No reconozco ese número: revisá el código de área y el número.")
    elif num:
        st.caption(f"Se envía a +{num}")
    texto = f"{negocio} · {nombre} · Total {peso(tot['total'])}. ¡Gracias!"
    b1, b2 = st.columns(2)
    with b1:
        st.download_button("⬇ Descargar ticket .png", png, file_name=fname, mime="image/png", key=f"dl_{key}", **STRETCH)
    with b2:
        if wa_config():
            if st.button("📲 Enviar por WhatsApp", key=f"wsend_{key}", type="primary", disabled=not num, **STRETCH):
                ok, msg = enviar_ticket_wa(com, nombre, items, tot, pagos, cli, tel)
                (st.success if ok else st.error)(msg)
        else:
            st.link_button("📲 Abrir WhatsApp", f"https://wa.me/{num}?text={quote(texto)}", disabled=not num, **STRETCH)
    if not wa_config():
        boton_compartir(png, fname, texto)
        st.caption("Envío automático desactivado (falta `[whatsapp]` en los Secrets). Con el celular, «Compartir imagen» "
                   "adjunta el ticket; en la compu descargá el .png y adjuntalo en el chat.")
    with st.popover("➕ Guardar / cambiar el teléfono del cliente"):
        nn = st.text_input("Nombre", value=(cli or {}).get("nombre") or "", key=f"gn_{key}")
        tt = st.text_input("Teléfono", value=(cli or {}).get("telefono") or "", key=f"gt_{key}")
        if st.button("Guardar y asociar a la cuenta", key=f"gs_{key}"):
            if cli:
                actualizar(T_CLI, cli["id"], {"telefono": tt.strip()})
                log("cliente_editado", f"{cli['nombre']} · teléfono desde ticket")
            elif nn.strip():
                nuevo = registrar_cliente(nn, tt)
                if nuevo:
                    actualizar(T_COM, com["id"], {"cliente_id": nuevo["id"]})
                    log("cuenta_editada", f"comanda {com['id']} · cliente asociado desde ticket")
            else:
                st.error("Cargá el nombre del cliente.")
                return png
            st.rerun()
    return png


def ticket_de_cuenta(cid, key):
    """Ticket completo de cualquier comanda (abierta, cobrada o anulada) con sus acciones. Se usa en Operaciones y Auditoría."""
    com = uno(T_COM, cid)
    if not com:
        st.warning(f"La comanda #{cid} ya no existe (fue eliminada).")
        return
    cli = uno(T_CLI, com["cliente_id"]) if com.get("cliente_id") else None
    nombre = etiqueta_cuenta(com, mapa_mesas(), {cli["id"]: cli} if cli else {})
    items = items_de([cid])
    tot = totales(com, items)
    pagos = listar(T_PAGOS, comanda_id=cid, order="id")
    izq, der = st.columns(2, gap="large")
    with izq:
        st.markdown(ticket_html(com, {"nombre": nombre}, items, tot, pagos, cli), unsafe_allow_html=True)
    with der:
        png = acciones_ticket(com, nombre, items, tot, pagos, cli, key)
        with st.expander("👁️ Ver la imagen que recibe el cliente"):
            st.image(png, width=360)


def cerrar_y_enviar(com, tot, pagos):
    """Cierra la cuenta cobrada y, si hay WhatsApp configurado y el cliente tiene teléfono, le manda el ticket."""
    cerrar_comanda(com, tot, pagos)
    try:
        if wa_config() and CFG.get("wa_auto", "1") == "1" and com.get("cliente_id"):
            cli = uno(T_CLI, com["cliente_id"])
            if cli and tel_wa(cli.get("telefono")):
                com2 = uno(T_COM, com["id"])
                items = items_de([com["id"]])
                pagos2 = listar(T_PAGOS, comanda_id=com["id"], order="id")
                nombre = etiqueta_cuenta(com2, mapa_mesas(), {cli["id"]: cli})
                ok, msg = enviar_ticket_wa(com2, nombre, items, totales(com2, items), pagos2, cli, cli["telefono"])
                st.toast(("📲 " if ok else "⚠️ ") + msg)
    except Exception as e:
        st.toast(f"⚠️ No pude enviar el ticket: {e}")


# ─────────────────────────────────────────
# PÁGINA: SALÓN
# ─────────────────────────────────────────
def html_cuenta(titulo, com, tot, cli=None):
    mins = int((ahora_utc() - parse_ts(com["abierta_ts"])).total_seconds() // 60)
    quien = f"{'⭐' if cli.get('vip') else '👤'} {esc(cli['nombre'])} · " if cli else ""
    return (f'<div class="mesa ocupada"><div class="mn">{esc(titulo)}</div>'
            f'<div class="mt">{peso(tot["total"])}</div>'
            f'<div class="ms">{quien}👥 {com["comensales"]} · ⏱ {mins}′ · {esc(com.get("mozo") or "—")}</div></div>')


def grilla_cuentas(lista, por_com, mesas_map, clis, pref, motivos=None, boton="Ver / pedir"):
    cols = st.columns(4)
    for idx, c in enumerate(lista):
        with cols[idx % 4]:
            st.markdown(html_cuenta(etiqueta_cuenta(c, mesas_map, clis), c, totales(c, por_com[c["id"]])),
                        unsafe_allow_html=True)
            if motivos:
                st.caption(f"⚠️ {motivos[c['id']]}")
            if st.button(boton, key=f"{pref}_{c['id']}", **STRETCH):
                st.session_state["cid"] = c["id"]
                go(P_COMANDA)


def _ir_a_cuenta(c):
    st.session_state["cid"] = c["id"]
    for k in ("mesa_pend", "nueva_cuenta"):
        st.session_state.pop(k, None)
    go(P_COMANDA)


def form_abrir_mesa(mesas, ocupa):
    mp = st.session_state.get("mesa_pend")
    if not mp:
        return
    mesa = next((m for m in mesas if m["id"] == mp), None)
    if not mesa or mp in ocupa:
        st.session_state.pop("mesa_pend", None)
        return
    st.markdown(f"#### Abrir {mesa['nombre']}")
    u = usuario_actual()
    with st.form("abrir_mesa"):
        c1, c2 = st.columns(2)
        n = c1.number_input("Comensales", 1, 60, 2)
        mozo = c2.text_input("Adicionista / mozo", value=(u["nombre"] if u else ""))
        sel, nuevo, tel, vipn = campos_cliente("am")
        ok = st.form_submit_button("Abrir y tomar pedido", type="primary")
    if st.button("Cancelar", key="am_cancel"):
        st.session_state.pop("mesa_pend", None)
        st.rerun()
    if ok:
        cli = resolver_cliente(sel, nuevo, tel, vipn)
        r = abrir_cuenta("mesa", mesa_id=mp, comensales=n, mozo=mozo, cliente=cli)
        _ir_a_cuenta(r)


def form_cuenta_barra():
    st.markdown("#### 🍻 Atender en barra (sin mesa)")
    u = usuario_actual()
    with st.form("cuenta_barra"):
        c1, c2, c3 = st.columns([3, 1, 2])
        nombre = c1.text_input("Nombre o referencia (ej. “Juan”, “camisa roja”)")
        n = c2.number_input("Personas", 1, 30, 1)
        mozo = c3.text_input("Adicionista / mozo", value=(u["nombre"] if u else ""))
        sel, nuevo, tel, vipn = campos_cliente("ab")
        ok = st.form_submit_button("Abrir cuenta de barra", type="primary")
    if st.button("Cancelar", key="ab_cancel"):
        st.session_state.pop("nueva_cuenta", None)
        st.rerun()
    if ok:
        cli = resolver_cliente(sel, nuevo, tel, vipn)
        etiqueta = nombre.strip() or (cli["nombre"] if cli else f"Barra {datetime.now(TZ).strftime('%H:%M')}")
        r = abrir_cuenta("barra", comensales=n, mozo=mozo, cliente=cli, etiqueta=etiqueta)
        _ir_a_cuenta(r)


def form_cuenta_vip(mesas, ocupa):
    st.markdown("#### ⭐ Abrir cuenta VIP (habitué)")
    u = usuario_actual()
    libres = [None] + [m for m in mesas if m["id"] not in ocupa]
    with st.form("cuenta_vip"):
        sel, nuevo, tel, vipn = campos_cliente("av", solo_vip=True, vip_default=True)
        c1, c2, c3 = st.columns([3, 1, 2])
        mesa = c1.selectbox("Sentado en mesa (opcional)", libres,
                            format_func=lambda m: "— sin mesa, cuenta personal —" if m is None else f"{m['nombre']} ({m['zona']})")
        n = c2.number_input("Personas", 1, 60, 1)
        mozo = c3.text_input("Adicionista / mozo", value=(u["nombre"] if u else ""))
        ok = st.form_submit_button("Abrir cuenta VIP", type="primary")
    if st.button("Cancelar", key="av_cancel"):
        st.session_state.pop("nueva_cuenta", None)
        st.rerun()
    if ok:
        cli = resolver_cliente(sel, nuevo, tel, vipn)
        if not cli:
            st.error("Elegí un cliente habitué o cargá uno nuevo.")
            return
        if not cli.get("vip"):
            actualizar(T_CLI, cli["id"], {"vip": True})
            cli["vip"] = True
            log("cliente_vip", f"{cli['nombre']} pasó a habitué")
        r = abrir_cuenta("cliente", mesa_id=mesa["id"] if mesa else None, comensales=n, mozo=mozo, cliente=cli)
        _ir_a_cuenta(r)


# ─────────────────────────────────────────
# MAPA VISUAL DEL BAR: plano general + Salón / Galería / Patio (componente propio, sin archivos extra)
# ─────────────────────────────────────────
_MAPA_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:transparent;font-family:'Poppins',system-ui,-apple-system,sans-serif;overflow:hidden}
#piso{position:relative;width:100%;border-radius:18px;overflow:hidden;background:#1a1a22;border:3px solid #FFE600}
body.edit #piso{outline:3px dashed #FF2E93;outline-offset:-8px}
#hint{display:none;position:absolute;left:50%;top:8px;transform:translateX(-50%);z-index:60;background:#FF2E93;color:#fff;
  font-weight:800;font-size:13px;padding:5px 14px;border-radius:999px;pointer-events:none;white-space:nowrap}
body.edit #hint{display:block}
.zona{position:absolute;border-radius:16px;overflow:hidden;border:3px solid var(--zc,#FFE600);box-shadow:inset 0 0 40px rgba(0,0,0,.35)}
.z-salon{--zc:#FFB347;background-color:#5b3a22;background-image:repeating-linear-gradient(90deg,rgba(0,0,0,.20) 0 2px,transparent 2px 64px),
  repeating-linear-gradient(0deg,rgba(255,255,255,.035) 0 1px,transparent 1px 22px),linear-gradient(180deg,#6e4829,#432816)}
.z-galeria{--zc:#FF7A59;background-color:#8f4f33;background-image:repeating-linear-gradient(90deg,rgba(0,0,0,.16) 0 2px,transparent 2px 72px),
  repeating-linear-gradient(0deg,rgba(0,0,0,.16) 0 2px,transparent 2px 72px),linear-gradient(135deg,#b9754d,#8a4a30)}
.z-patio{--zc:#7CFF6B;background-color:#2f5a33;background-image:radial-gradient(rgba(255,255,255,.10) 2px,transparent 3px),linear-gradient(180deg,#46763f,#2b4d2d);background-size:30px 30px,100% 100%}
.zlab{position:absolute;left:10px;top:8px;z-index:30;background:rgba(0,0,0,.62);color:#fff;font-weight:800;font-size:13px;padding:4px 12px;border-radius:999px;
  border:2px solid var(--zc);pointer-events:none;white-space:nowrap}
.mesa{position:absolute;transform:translate(-50%,-50%) scale(var(--k,1));display:flex;align-items:center;justify-content:center;
  touch-action:manipulation;cursor:pointer;-webkit-tap-highlight-color:transparent;user-select:none;-webkit-user-select:none}
body.edit .mesa{cursor:grab;touch-action:none}
.mesa.drag{cursor:grabbing;z-index:40;filter:drop-shadow(0 14px 10px rgba(0,0,0,.55))}
.cuerpo{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;color:#fff;
  text-shadow:0 1px 3px rgba(0,0,0,.9);border:4px solid var(--borde);box-shadow:0 6px 0 rgba(0,0,0,.4);padding:3px}
.cuerpo::after{content:"";position:absolute;inset:0;border-radius:inherit;background:var(--tinte,transparent);pointer-events:none}
.libre{--borde:#39FF14}
.ocupada{--borde:#FF2E93;--tinte:rgba(255,46,147,.34)}
.n,.s,.t{position:relative;z-index:1}
.n{font-weight:800;font-size:13px;line-height:1.05}
.s{font-weight:800;font-size:13px;line-height:1.1}
.libre .s{color:#39FF14}
.ocupada .s{color:#FFE600;font-size:14px}
.t{font-size:10px;opacity:.95}
.mesa.sel .cuerpo{outline:5px dashed #FF2E3D;outline-offset:5px}
.mesa.sel::before{content:"✓";position:absolute;right:-12px;top:-14px;z-index:50;width:30px;height:30px;border-radius:50%;background:#FF2E3D;color:#fff;
  font-weight:900;font-size:18px;display:flex;align-items:center;justify-content:center;border:2px solid #fff}
.barril .cuerpo{width:88px;height:88px;border-radius:50%;background:radial-gradient(circle at 36% 30%,#d79a58,#9a5d2b 62%,#5f3716);
  box-shadow:inset 0 0 0 6px #6a3c1b,inset 0 0 0 9px #b9bcc4,inset 0 0 0 11px #4b4d55,0 6px 0 rgba(0,0,0,.4)}
.chica .cuerpo{width:76px;height:76px;border-radius:16px;background:repeating-linear-gradient(90deg,#dba96b 0 10px,#cf9b5b 10px 11px)}
.grande .cuerpo{width:200px;height:88px;border-radius:12px;background:repeating-linear-gradient(90deg,#b97a3b 0 14px,#a96d33 14px 15px)}
.grande .n{font-size:15px}.grande .s{font-size:14px}
.silla{position:absolute;width:20px;height:20px;border-radius:50%;background:#2c2c36;border:2px solid #0b0b10;box-shadow:0 2px 0 rgba(0,0,0,.4)}
.vacio{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;text-align:center;padding:20px;z-index:20}
</style></head><body>
<div id="piso"><div id="hint">✋ Arrastrá para mover · tocá para seleccionar</div></div>
<script>
let ARGS = null, CUR = {}, ULT_ALTO = 0;
function post(type, data){ window.parent.postMessage(Object.assign({isStreamlitMessage: true, type: type}, data), "*"); }
function setValue(v){ post("streamlit:setComponentValue", {value: v, dataType: "json"}); }
window.addEventListener("message", function(e){
  const d = e.data;
  if (d && d.type === "streamlit:render"){ ARGS = d.args; draw(); }
});
window.addEventListener("resize", function(){ if (ARGS) draw(); });
post("streamlit:componentReady", {apiVersion: 1});

function sillas(estilo){
  if (estilo === "chica") return '<span class="silla" style="left:-24px;top:calc(50% - 10px)"></span><span class="silla" style="right:-24px;top:calc(50% - 10px)"></span>';
  if (estilo === "grande"){
    let h = "";
    [16, 50, 84].forEach(function(p){
      h += '<span class="silla" style="left:calc(' + p + '% - 10px);top:-24px"></span>';
      h += '<span class="silla" style="left:calc(' + p + '% - 10px);bottom:-24px"></span>';
    });
    return h;
  }
  return "";
}
function esc(t){ return String(t).replace(/[&<>"]/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); }

function draw(){
  const A = ARGS, piso = document.getElementById("piso");
  document.body.classList.toggle("edit", !!A.editar);
  piso.style.height = A.alto + "px";
  piso.querySelectorAll(".zona,.vacio").forEach(function(n){ n.remove(); });
  CUR = {};
  const SEL = new Set(A.sel || []);
  const ref = A.zonas.length > 1 ? 760 : 520;
  let total = 0;
  A.zonas.forEach(function(z){
    const zd = document.createElement("div");
    zd.className = "zona z-" + z.id;
    zd.style.left = "calc(" + z.x + "% + 5px)"; zd.style.top = "calc(" + z.y + "% + 5px)";
    zd.style.width = "calc(" + z.w + "% - 10px)"; zd.style.height = "calc(" + z.h + "% - 10px)";
    zd.innerHTML = '<div class="zlab">' + esc(z.emoji) + ' ' + esc(z.nombre.toUpperCase()) + ' · ' + z.ocupadas + '/' + z.total + ' ocupadas</div>';
    piso.appendChild(zd);
    const zw = zd.clientWidth || (piso.clientWidth * z.w / 100 - 10);
    const k = Math.max(0.5, Math.min(1, zw / ref));
    A.mesas.filter(function(m){ return m.zona === z.id; }).forEach(function(m){
      total++;
      CUR[m.id] = {x: m.x, y: m.y};
      const el = document.createElement("div");
      el.className = "mesa " + m.estilo + " " + (m.ocupada ? "ocupada" : "libre") + (SEL.has(m.id) ? " sel" : "");
      el.style.left = m.x + "%"; el.style.top = m.y + "%"; el.style.setProperty("--k", k);
      const estado = m.ocupada ? '<div class="s">' + esc(m.total) + '</div><div class="t">⏱ ' + esc(m.mins) + '′ · 👥 ' + esc(m.pers) + '</div>'
                               : '<div class="s">LIBRE</div><div class="t">👥 ' + esc(m.cap) + '</div>';
      el.innerHTML = '<div class="cuerpo">' + sillas(m.estilo) + '<div class="n">' + esc(m.nombre) + '</div>' + estado + '</div>';
      el.addEventListener("click", function(){
        if (A.editar || el.dataset.moved === "1") return;
        setValue({accion: "abrir", mesa_id: m.id, nonce: Date.now()});
      });
      el.addEventListener("pointerdown", function(ev){
        if (!A.editar) return;
        ev.preventDefault();
        try { el.setPointerCapture(ev.pointerId); } catch (x) {}
        const r = zd.getBoundingClientRect();
        const x0 = ev.clientX, y0 = ev.clientY;
        let movido = false;
        function mv(e2){
          if (!movido && Math.abs(e2.clientX - x0) + Math.abs(e2.clientY - y0) < 6) return;
          movido = true; el.classList.add("drag");
          let x = (e2.clientX - r.left) / r.width * 100, y = (e2.clientY - r.top) / r.height * 100;
          x = Math.max(4, Math.min(96, Math.round(x))); y = Math.max(8, Math.min(94, Math.round(y)));
          el.style.left = x + "%"; el.style.top = y + "%"; CUR[m.id] = {x: x, y: y};
        }
        function up(){
          el.removeEventListener("pointermove", mv); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up);
          el.classList.remove("drag");
          if (movido) setValue({accion: "mover", pos: CUR, nonce: Date.now()});
          else setValue({accion: "toggle", mesa_id: m.id, nonce: Date.now()});
        }
        el.addEventListener("pointermove", mv); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
      });
      zd.appendChild(el);
    });
  });
  if (!total){
    const v = document.createElement("div"); v.className = "vacio";
    v.textContent = "No hay mesas en esta zona. Agregalas desde “Editar distribución”."; piso.appendChild(v);
  }
  if (A.alto + 8 !== ULT_ALTO){ ULT_ALTO = A.alto + 8; post("streamlit:setFrameHeight", {height: ULT_ALTO}); }
}
</script></body></html>
"""

ESTILOS_MESA = {"barril": "🛢️ Barril", "chica": "🪑 Mesa chica (2)", "grande": "🪵 Mesa grande de madera (6)"}
ZONAS_MAPA = [("salon", "Salón", "🏠"), ("galeria", "Galería", "🌿"), ("patio", "Patio", "🌳")]
NOMBRE_ZONA = {k: n for k, n, _ in ZONAS_MAPA}
BASE_ESTILO = {"barril": ("Barril", 4), "chica": ("Mesa chica", 2), "grande": ("Mesa grande", 6)}


@st.cache_resource(show_spinner=False)
def _mapa_comp():
    d = Path(tempfile.gettempdir()) / "hopsie_mapa_v2"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "index.html"
    if not f.exists() or f.read_text(encoding="utf-8") != _MAPA_HTML:
        f.write_text(_MAPA_HTML, encoding="utf-8")
    return components.declare_component("hopsie_mapa_v2", path=str(d))


def _i(v, d=0):
    try:
        return int(v)
    except Exception:
        return d


def mapa_layout():
    try:
        return json.loads(CFG.get("mapa_layout") or "{}")
    except Exception:
        return {}


def zona_mapa(m):
    z = (m.get("zona") or "").lower()
    if "gal" in z:
        return "galeria"
    if "pat" in z or "vereda" in z or "exterior" in z:
        return "patio"
    return "salon"


def estilo_mesa(m, lay):
    e = (lay.get(str(m["id"])) or {}).get("e")
    if e in ESTILOS_MESA:
        return e
    n = (m.get("nombre") or "").lower()
    if "barril" in n:
        return "barril"
    if "grande" in n or _i(m.get("capacidad")) >= 5:
        return "grande"
    return "chica"


def posiciones_mapa(mesas, lay):
    """Posición (x%, y%) dentro de su zona: la guardada o, si es nueva, un acomodo automático por estilo."""
    out, cont = {}, defaultdict(int)
    for m in mesas:
        e, z = estilo_mesa(m, lay), zona_mapa(m)
        k = cont[(z, e)]
        cont[(z, e)] += 1
        pz = lay.get(str(m["id"])) or {}
        if "x" in pz and "y" in pz:
            out[m["id"]] = (float(pz["x"]), float(pz["y"]))
        elif e == "barril":
            out[m["id"]] = (11 + (k % 6) * 14, 24 + (k // 6) * 22)
        elif e == "grande":
            out[m["id"]] = (30 + (k % 2) * 42, 82 - (k // 2) * 24)
        else:
            out[m["id"]] = (11 + (k % 6) * 15, 48 + (k // 6) * 20)
    return out


def procesar_mapa(mesas, ocupa):
    """Atiende lo que hizo el usuario en el mapa (tocar / arrastrar / seleccionar). Va ANTES de dibujar."""
    ev = st.session_state.get("mapa_salon")
    if not isinstance(ev, dict) or ev.get("nonce") == st.session_state.get("_mapa_nonce"):
        return
    st.session_state["_mapa_nonce"] = ev.get("nonce")
    accion = ev.get("accion")
    if accion == "mover" and usuario_actual():
        lay = mapa_layout()
        for mid, pz in (ev.get("pos") or {}).items():
            lay[str(mid)] = {**(lay.get(str(mid)) or {}), "x": round(float(pz["x"]), 1), "y": round(float(pz["y"]), 1)}
        cfg_set("mapa_layout", json.dumps(lay))
    elif accion == "toggle" and usuario_actual():
        cur = list(st.session_state.get("mapa_sel_ms", []))
        mid = ev.get("mesa_id")
        cur = [x for x in cur if x != mid] if mid in cur else cur + [mid]
        st.session_state["mapa_sel_ms"] = cur
    elif accion == "abrir":
        mid = ev.get("mesa_id")
        if not any(m["id"] == mid for m in mesas):
            return
        com = ocupa.get(mid)
        if com:
            st.session_state["cid"] = com["id"]
            go(P_COMANDA)
        else:
            st.session_state["mesa_pend"] = mid
            st.session_state.pop("nueva_cuenta", None)
            st.rerun()


def _crear_mesa(nombre, zona_id, estilo, lay, orden):
    """Crea una mesa y le guarda estilo y zona. Devuelve None si salió bien o el texto del error."""
    try:
        r = insertar(T_MESAS, {"nombre": nombre, "zona": NOMBRE_ZONA[zona_id], "capacidad": BASE_ESTILO[estilo][1], "orden": orden})
        lay[str(r[0]["id"])] = {"e": estilo}
        return None
    except Exception as e:
        return f"{nombre}: {e}"


def agregar_mesas(estilo, cantidad, zona_id, nombre=""):
    """Suma 'cantidad' mesas del estilo elegido a una zona.
    Sin nombre: numeración automática (Barril 6, Barril 7…). Con nombre y cantidad 1: ese nombre exacto.
    Con nombre y varias: se numeran (Mesa 11, Mesa 12…)."""
    ex = listar(T_MESAS)
    nombres = {(m["nombre"] or "").lower() for m in ex}
    orden = max([_i(m.get("orden")) for m in ex] or [0])
    nombre = (nombre or "").strip()
    lay, base, n, hechas, errores = mapa_layout(), nombre or BASE_ESTILO[estilo][0], 1, 0, []
    for _ in range(int(cantidad)):
        if nombre and int(cantidad) == 1 and nombre.lower() not in nombres:
            nuevo = nombre
        else:
            while f"{base} {n}".lower() in nombres:
                n += 1
            nuevo = f"{base} {n}"
        orden += 1
        err = _crear_mesa(nuevo, zona_id, estilo, lay, orden)
        nombres.add(nuevo.lower())
        if err:
            errores.append(err)
        else:
            hechas += 1
    cfg_set("mapa_layout", json.dumps(lay))
    log("mesas_agregadas", f"{hechas} × {base} en {NOMBRE_ZONA[zona_id]}")
    return hechas, errores


def renombrar_mesas(cambios, mesas):
    """cambios: {id: nombre_nuevo}. Cambia el nombre en la tabla de mesas (la misma que ves en Admin → Mesas)."""
    por_id = {m["id"]: m for m in mesas}
    usados = {(m["nombre"] or "").strip().lower(): m["id"] for m in mesas}
    ok_n, errs = 0, []
    for i, nuevo in cambios.items():
        m, nuevo = por_id.get(i), (nuevo or "").strip()
        if not m or not nuevo or nuevo == m["nombre"]:
            continue
        if usados.get(nuevo.lower(), i) != i:
            errs.append(f"«{nuevo}» ya existe")
            continue
        try:
            actualizar(T_MESAS, i, {"nombre": nuevo})
            usados.pop((m["nombre"] or "").strip().lower(), None)
            usados[nuevo.lower()] = i
            log("mesa_editada", f"{m['nombre']} → {nuevo} (desde el mapa)")
            ok_n += 1
        except Exception as e:
            errs.append(f"{nuevo}: {e}")
    return ok_n, errs


def crear_mesas_bar(zona_id):
    """Crea las mesas del bar que falten: 5 barriles, 11 mesas chicas y 2 mesas grandes (todas en la zona elegida)."""
    ex = listar(T_MESAS)
    nombres = {(m["nombre"] or "").lower() for m in ex}
    orden = max([_i(m.get("orden")) for m in ex] or [0])
    lay, hechas, errores = mapa_layout(), 0, []
    for estilo, cant in (("barril", 5), ("chica", 11), ("grande", 2)):
        for i in range(1, cant + 1):
            nombre = f"{BASE_ESTILO[estilo][0]} {i}"
            if nombre.lower() in nombres:
                continue
            orden += 1
            err = _crear_mesa(nombre, zona_id, estilo, lay, orden)
            if err:
                errores.append(err)
            else:
                hechas += 1
    cfg_set("mapa_layout", json.dumps(lay))
    log("mesas_bar_creadas", f"{hechas} mesas en {NOMBRE_ZONA[zona_id]}")
    return hechas, errores


def eliminar_mesas(ids):
    mapa = {m["id"]: m for m in listar(T_MESAS)}
    lay, ok_n, fallos = mapa_layout(), 0, []
    for i in ids:
        m = mapa.get(i)
        if not m:
            continue
        try:
            r, msg = eliminar_mesa(m)
        except Exception as e:
            r, msg = False, f"{m['nombre']}: {e}"
        if r:
            ok_n += 1
            lay.pop(str(i), None)
        else:
            fallos.append(msg)
    cfg_set("mapa_layout", json.dumps(lay))
    texto = f"{ok_n} mesa(s) eliminada(s)." + (" Sin eliminar: " + " | ".join(fallos) if fallos else "")
    return (ok_n > 0 or not fallos), texto


def mapa_salon(mesas, ocupa, por_com, clis):
    lay = mapa_layout()
    pos = posiciones_mapa(mesas, lay)
    msg = st.session_state.pop("_mapa_msg", None)
    if msg:
        (st.success if msg[0] else st.error)(msg[1])
    vista = st.session_state.get("mapa_vista", "general")
    cuenta = {k: [0, 0] for k, _, _ in ZONAS_MAPA}
    for m in mesas:
        c = cuenta[zona_mapa(m)]
        c[1] += 1
        c[0] += 1 if ocupa.get(m["id"]) else 0
    opciones = [("general", f"🗺️ Plano general ({sum(c[0] for c in cuenta.values())}/{len(mesas)})")] + \
               [(k, f"{ic} {n} ({cuenta[k][0]}/{cuenta[k][1]})") for k, n, ic in ZONAS_MAPA]
    for col, (k, etq) in zip(st.columns(4), opciones):
        if col.button(etq, key=f"mapa_v_{k}", type="primary" if vista == k else "secondary", **STRETCH):
            st.session_state["mapa_vista"] = k
            st.rerun()
    editar = False
    if usuario_actual():
        editar = st.toggle("✏️ Editar distribución (arrastrá las mesas, tocá para seleccionar)", key="mapa_edit")
    else:
        st.caption("Tocá una mesa para abrirla o ver su pedido. Para mover o eliminar mesas, iniciá sesión en ⚙️ Admin.")
    visibles = [m for m in mesas if vista == "general" or zona_mapa(m) == vista]
    ids_vis = [m["id"] for m in visibles]
    if "_mapa_sel_set" in st.session_state:
        st.session_state["mapa_sel_ms"] = st.session_state.pop("_mapa_sel_set")
    sel = [i for i in st.session_state.get("mapa_sel_ms", []) if i in ids_vis]
    st.session_state["mapa_sel_ms"] = sel
    if vista == "general":
        zonas = [("salon", 0, 0, 100, 52), ("galeria", 0, 52, 50, 48), ("patio", 50, 52, 50, 48)]
        alto = 820
    else:
        zonas, alto = [(vista, 0, 0, 100, 100)], 640
    emo = {k: ic for k, _, ic in ZONAS_MAPA}
    datos_z = [{"id": k, "nombre": NOMBRE_ZONA[k], "emoji": emo[k], "x": x, "y": y, "w": w, "h": h,
                "ocupadas": cuenta[k][0], "total": cuenta[k][1]} for k, x, y, w, h in zonas]
    datos = []
    for m in visibles:
        com = ocupa.get(m["id"])
        x, y = pos[m["id"]]
        d = {"id": m["id"], "nombre": m["nombre"], "estilo": estilo_mesa(m, lay), "zona": zona_mapa(m), "x": x, "y": y,
             "ocupada": bool(com), "cap": _i(m.get("capacidad"), 2)}
        if com:
            try:
                d.update(total=peso(totales(com, por_com[com["id"]])["total"]),
                         mins=int((ahora_utc() - parse_ts(com["abierta_ts"])).total_seconds() // 60), pers=_i(com.get("comensales"), 1) or 1)
            except Exception:
                d.update(total="—", mins=0, pers=1)
        datos.append(d)
    try:
        _mapa_comp()(mesas=datos, zonas=datos_z, sel=sel, editar=editar, alto=alto, key="mapa_salon", default=None)
    except Exception as e:
        st.error(f"No se pudo dibujar el mapa: {e}")
    st.caption("🟢 libre · 🟣 ocupada (muestra el total y el tiempo). Las mesas se ubican según su zona (Salón, Galería o Patio).")
    if not editar:
        return
    with st.expander("🛠️ Mesas: agregar, mover de zona, estilo y eliminar", expanded=True):
        st.markdown("**➕ Agregar mesas**")
        c1, c2, c3 = st.columns(3)
        est_n = c1.selectbox("Qué agregar", list(ESTILOS_MESA), format_func=ESTILOS_MESA.get, key="mapa_add_est")
        cant_n = c2.number_input("Cantidad", 1, 30, 1, key="mapa_add_cant")
        zona_def = vista if vista != "general" else "salon"
        zk = [k for k, _, _ in ZONAS_MAPA]
        zon_n = c3.selectbox("En la zona", zk, index=zk.index(zona_def), format_func=NOMBRE_ZONA.get, key=f"mapa_add_zona_{vista}")
        nom_n = st.text_input("Nombre (opcional)", key="mapa_add_nom", placeholder="Ej. Mesa 11 · vacío = numeración automática",
                              help="Con cantidad 1 se usa tal cual. Con varias se numeran: «Mesa 1», «Mesa 2»… "
                                   "El nombre queda igual en Admin → Mesas, porque es la misma lista.")
        b1, b2 = st.columns(2)
        if b1.button("➕ Agregar", key="mapa_add_ok", type="primary", **STRETCH):
            hechas, errs = agregar_mesas(est_n, cant_n, zon_n, nom_n)
            st.session_state["_mapa_msg"] = (not errs, f"Se agregaron {hechas} mesa(s)." + (" Errores: " + " | ".join(errs[:3]) if errs else ""))
            st.rerun()
        if b2.button("🪑 Crear las mesas del bar (5 barriles · 11 chicas · 2 grandes)", key="mapa_crear", **STRETCH):
            hechas, errs = crear_mesas_bar(zon_n)
            st.session_state["_mapa_msg"] = (not errs, f"Se crearon {hechas} mesa(s) en {NOMBRE_ZONA[zon_n]}, las que faltaban." +
                                             (" Errores: " + " | ".join(errs[:3]) if errs else ""))
            st.rerun()
        st.markdown("**☑️ Seleccionar mesas** (también podés tocarlas en el mapa)")
        por_id = {m["id"]: m for m in mesas}
        elegidas = st.multiselect("Mesas seleccionadas", ids_vis, key="mapa_sel_ms",
                                  format_func=lambda i: f"{por_id[i]['nombre']} · {NOMBRE_ZONA[zona_mapa(por_id[i])]}")
        s1, s2 = st.columns(2)
        if s1.button("☑️ Seleccionar todas las de esta vista", key="mapa_sel_todas", **STRETCH):
            st.session_state["_mapa_sel_set"] = list(ids_vis)
            st.rerun()
        if s2.button("☐ Quitar la selección", key="mapa_sel_nada", **STRETCH):
            st.session_state["_mapa_sel_set"] = []
            st.rerun()
        if elegidas:
            st.markdown(f"**Con las {len(elegidas)} seleccionada(s):**")
            m1, m2 = st.columns(2)
            zdest = m1.selectbox("Mover a la zona", zk, format_func=NOMBRE_ZONA.get, key="mapa_mover_zona")
            if m1.button("➡️ Mover de zona", key="mapa_mover_ok", **STRETCH):
                for i in elegidas:
                    actualizar(T_MESAS, i, {"zona": NOMBRE_ZONA[zdest]})
                    lay.get(str(i), {}).pop("x", None)
                    lay.get(str(i), {}).pop("y", None)
                cfg_set("mapa_layout", json.dumps(lay))
                log("mesas_zona", f"{len(elegidas)} mesas → {NOMBRE_ZONA[zdest]}")
                st.rerun()
            edest = m2.selectbox("Cambiar estilo a", list(ESTILOS_MESA), format_func=ESTILOS_MESA.get, key="mapa_estilo_sel")
            if m2.button("🎨 Aplicar estilo", key="mapa_estilo_ok", **STRETCH):
                for i in elegidas:
                    lay[str(i)] = {**(lay.get(str(i)) or {}), "e": edest}
                cfg_set("mapa_layout", json.dumps(lay))
                st.rerun()
            with st.form("mapa_ren_form", border=True) if _V >= (1, 29) else st.form("mapa_ren_form"):
                st.markdown("**✏️ Renombrar** (el nombre cambia también en Admin → Mesas)")
                nuevos = {i: st.text_input(f"{por_id[i]['nombre']} ({NOMBRE_ZONA[zona_mapa(por_id[i])]})", por_id[i]["nombre"],
                                           key=f"mapa_ren_{i}_{por_id[i]['nombre']}") for i in elegidas}
                if st.form_submit_button("💾 Guardar nombres", type="primary"):
                    n_ok, errs_r = renombrar_mesas(nuevos, mesas)
                    st.session_state["_mapa_msg"] = (not errs_r, f"Se renombraron {n_ok} mesa(s)." + (" " + " | ".join(errs_r[:3]) if errs_r else ""))
                    st.rerun()
            nombres_sel = ", ".join(por_id[i]["nombre"] for i in elegidas[:8]) + ("…" if len(elegidas) > 8 else "")
            confirmar_eliminar("mapa_del", f"Se eliminan {len(elegidas)} mesa(s): {nombres_sel}. No se puede si tienen una cuenta abierta. "
                               f"Las cuentas pasadas conservan el nombre de la mesa.",
                               lambda ids=list(elegidas): eliminar_mesas(ids), f"Eliminar seleccionadas ({len(elegidas)})")
        if st.button("↺ Reacomodar todo automático", key="mapa_auto", **STRETCH):
            cfg_set("mapa_layout", json.dumps({k: {"e": v["e"]} for k, v in lay.items() if v.get("e")}))
            st.rerun()


def pagina_salon():
    mesas = listar(T_MESAS, order="orden", activa=True)
    abiertas = sorted(listar(T_COM, estado="abierta"), key=lambda c: c["id"])
    por_com = defaultdict(list)
    for it in items_de([c["id"] for c in abiertas]):
        por_com[it["comanda_id"]].append(it)
    clis = mapa_clientes()
    mesas_map = {m["id"]: m for m in mesas}

    # Cada cuenta abierta va a UN solo lugar: su mesa, la lista VIP, la barra o "para revisar".
    ocupa, vip, barra, revisar = {}, [], [], []
    motivos = {}
    for c in abiertas:
        tipo, mid = c.get("tipo") or "mesa", c.get("mesa_id")
        if mid in mesas_map:
            if mid in ocupa:
                revisar.append(c)
                motivos[c["id"]] = "Hay otra cuenta abierta en la misma mesa."
            else:
                ocupa[mid] = c
        elif tipo == "cliente":
            vip.append(c)
        elif tipo == "barra":
            barra.append(c)
        else:
            revisar.append(c)
            motivos[c["id"]] = "Sin mesa asignada." if not mid else "Su mesa está desactivada o ya no existe."

    en_curso = sum(totales(c, por_com[c["id"]])["total"] for c in abiertas)
    a, b, c_, d = st.columns(4)
    a.metric("Mesas ocupadas", f"{len(ocupa)} / {len(mesas)}")
    b.metric("Mesas libres", len(mesas) - len(ocupa))
    c_.metric("Barra / VIP", len(vip) + len(barra))
    d.metric("Consumo en curso", peso(en_curso))
    if revisar:
        st.warning(f"Hay {len(revisar)} cuenta(s) abierta(s) que no corresponden a una mesa activa: "
                   f"están más abajo en **Cuentas para revisar**. Corregilas o anulalas desde ahí.")

    b1, b2, _ = st.columns([2, 2, 4])
    if b1.button("🍻 Atender en barra", key="btn_barra", **STRETCH):
        st.session_state["nueva_cuenta"] = "barra"
        st.session_state.pop("mesa_pend", None)
    if b2.button("⭐ Cuenta VIP", key="btn_vip", **STRETCH):
        st.session_state["nueva_cuenta"] = "vip"
        st.session_state.pop("mesa_pend", None)

    procesar_mapa(mesas, ocupa)
    form_abrir_mesa(mesas, ocupa)
    nc = st.session_state.get("nueva_cuenta")
    if nc == "barra":
        form_cuenta_barra()
    elif nc == "vip":
        form_cuenta_vip(mesas, ocupa)

    if not mesas:
        st.info("Todavía no hay mesas. Cargalas en **Admin → Mesas** (o usá los datos de ejemplo en Admin → Dashboard).")
    t_mapa, t_lista = st.tabs(["🗺️ Mapa del salón", "📋 Lista de mesas"])
    with t_mapa:
        mapa_salon(mesas, ocupa, por_com, clis)
    with t_lista:
        zonas = []
        for m in mesas:
            if m["zona"] not in zonas:
                zonas.append(m["zona"])
        for zona in zonas:
            st.markdown(f"### {zona}")
            lista = [m for m in mesas if m["zona"] == zona]
            cols = st.columns(4)
            for idx, m in enumerate(lista):
                com = ocupa.get(m["id"])
                with cols[idx % 4]:
                    if com:
                        st.markdown(html_cuenta(m["nombre"], com, totales(com, por_com[com["id"]]),
                                                cli=clis.get(com.get("cliente_id"))), unsafe_allow_html=True)
                        if st.button("Ver / pedir", key=f"mesa_{m['id']}", **STRETCH):
                            st.session_state["cid"] = com["id"]
                            go(P_COMANDA)
                    else:
                        st.markdown(
                            f'<div class="mesa"><div class="mn">{esc(m["nombre"])}</div>'
                            f'<div class="mt libre">LIBRE</div><div class="ms">👥 hasta {m["capacidad"]}</div></div>',
                            unsafe_allow_html=True)
                        if st.button("Abrir mesa", key=f"mesa_{m['id']}", **STRETCH):
                            st.session_state["mesa_pend"] = m["id"]
                            st.session_state.pop("nueva_cuenta", None)
                            st.rerun()

    if vip:
        st.markdown("### ⭐ Cuentas VIP")
        grilla_cuentas(vip, por_com, mesas_map, clis, "vip")
    if barra:
        st.markdown("### 🍻 Barra")
        grilla_cuentas(barra, por_com, mesas_map, clis, "barra")
    if revisar:
        st.markdown("### ⚠️ Cuentas para revisar")
        grilla_cuentas(revisar, por_com, mesas_map, clis, "rev", motivos, "Ver / corregir")


# ─────────────────────────────────────────
# PÁGINA: COMANDA
# ─────────────────────────────────────────
def comanda_actual():
    """Devuelve (comanda, 'mesa'). Si la cuenta no está en una mesa (barra / VIP / mesa borrada),
    'mesa' es un dict equivalente con el nombre de la cuenta, así el resto de la pantalla funciona igual."""
    cid = st.session_state.get("cid")
    com = uno(T_COM, cid) if cid else None
    if not com or com["estado"] != "abierta":
        return None, None
    mesas = mapa_mesas()
    cli = uno(T_CLI, com["cliente_id"]) if com.get("cliente_id") else None
    nombre = etiqueta_cuenta(com, mesas, {cli["id"]: cli} if cli else {})
    m = mesas.get(com.get("mesa_id"))
    return com, {"id": m["id"] if m else None, "nombre": nombre, "zona": m["zona"] if m else "—",
                 "capacidad": m["capacidad"] if m else com["comensales"]}


def grilla_productos(lista, com, pref):
    cols = st.columns(3)
    for idx, p in enumerate(lista):
        label = f"{p.get('emoji') or '🍺'} {p['nombre']} · {peso(p['precio'])}"
        if cols[idx % 3].button(label, key=f"{pref}_{p['id']}", **STRETCH):
            hop_agregar_unidad(com, p)
            st.rerun()


def pagina_comanda():
    com, mesa = comanda_actual()
    if not com:
        st.info("Elegí una mesa o una cuenta en **Salón** para tomar el pedido.")
        if st.button("Ir al salón"):
            go(P_SALON)
        return
    cid = com["id"]
    st.markdown(f"### 🧾 {mesa['nombre']}")
    st.caption(f"Abierta {hop_fmt_dt(com['abierta_ts'])} · 👥 {com['comensales']} · Adicionista: {com.get('mozo') or '—'} · Comanda #{cid}")
    cli = uno(T_CLI, com["cliente_id"]) if com.get("cliente_id") else None
    if cli:
        st.caption(f"{'⭐ Habitué' if cli['vip'] else '👤 Cliente'}: **{cli['nombre']}**"
                   + (f" · 📞 {cli['telefono']}" if cli.get("telefono") else "")
                   + (f" · Dto. {float(cli['descuento_pct']):g}%" if float(cli.get("descuento_pct") or 0) else "")
                   + (f" · 📝 {cli['notas']}" if cli.get("notas") else ""))

    izq, der = st.columns([3, 2], gap="large")

    with izq:
        prods = listar(T_PROD, order="nombre", activo=True)
        if not prods:
            st.warning("No hay productos cargados (Admin → Productos).")
        else:
            q = st.text_input("Buscar", placeholder="🔎 Buscar producto…", label_visibility="collapsed", key=f"bq_{cid}")
            if q.strip():
                f = [p for p in prods if q.strip().lower() in p["nombre"].lower()]
                grilla_productos(f, com, "qs") if f else st.caption("Sin resultados.")
            else:
                cats = sorted({p["categoria"] for p in prods})
                for tab, cat in zip(st.tabs(cats), cats):
                    with tab:
                        grilla_productos([p for p in prods if p["categoria"] == cat], com, f"c{cat}")

    with der:
        todos = listar(T_ITEMS, comanda_id=cid, order="id")
        activos = [i for i in todos if not i["anulado"]]
        borrador = [i for i in activos if not i.get("confirmado", True)]
        enviados = [i for i in activos if i.get("confirmado", True)]
        st.markdown("#### Consumo")
        if not activos:
            st.caption("Todavía no se cargó nada.")

        def fila_item(it, enviado):
            c1, c2, c3, c4, c5 = st.columns([6, 1.2, 1.2, 1.2, 1.2])
            nota = f" · 📝 {esc(it['nota'])}" if it["nota"] else ""
            icono = ICONO_ESTADO.get(it["estado"], "") if enviado else "📝"
            aviso = ""
            if enviado and it["estado"] == "preparando":
                aviso = "<br><small>🔥 Ya se está preparando: avisá a cocina/barra si hay un cambio</small>"
            elif enviado and it["estado"] == "servido":
                aviso = "<br><small>✅ Ya fue servido</small>"
            c1.markdown(
                f"{icono} **{it['cantidad']}× {esc(it['nombre'])}**<br>"
                f"<small>{peso(float(it['precio_unit']) * it['cantidad'])}{nota}</small>{aviso}", unsafe_allow_html=True)
            with c2:
                if ib("menos", it["id"], "Quitar uno"):
                    sumar_cantidad(it, -1)
                    st.rerun()
            with c3:
                if ib("mas", it["id"], "Agregar uno"):
                    if enviado:
                        sumar_pedido_extra(it)  # lo ya enviado no se toca: el extra queda sin confirmar
                    else:
                        sumar_cantidad(it, 1)
                    st.rerun()
            with c4:
                pop = ib_popover("editar", it["id"], "Editar cantidad, precio o nota")
            with pop:
                nq = st.number_input("Cantidad", 1, 999, int(it["cantidad"]), key=f"eq{it['id']}")
                npz = st.number_input("Precio unitario", 0.0, 10_000_000.0, float(it["precio_unit"]), 100.0, key=f"ep{it['id']}")
                nv = st.text_input("Nota para cocina/barra", value=it["nota"], key=f"nt{it['id']}")
                if st.button("Guardar", key=f"gn{it['id']}"):
                    hop_editar_item(it, nq, npz, nv.strip())
                    st.rerun()
            with c5:
                if ib("borrar", it["id"], "Quitar del pedido"):
                    anular_item(it)
                    st.rerun()

        if borrador:
            st.markdown("<div class='draft'><b>📝 Pedido sin confirmar</b><br>"
                        "<small>Todavía NO llegó a cocina ni a barra. Cambialo o quitá lo que haga falta; "
                        "cuando el cliente lo confirme, enviá el pedido.</small></div>", unsafe_allow_html=True)
            for it in borrador:
                fila_item(it, False)
            n_un = sum(int(i["cantidad"]) for i in borrador)
            if st.button(f"✅ Confirmar pedido y enviar a cocina / barra ({n_un})", type="primary",
                         key=f"cf{cid}", **STRETCH):
                confirmar_pedido(com, borrador)
                st.rerun()
        if enviados:
            st.markdown("<div class='sent'><b>🔥 Enviado a cocina / barra</b></div>", unsafe_allow_html=True)
            for it in enviados:
                fila_item(it, True)

        # descuento / propina
        d1, d2 = st.columns(2)
        desc = d1.number_input("Descuento %", 0.0, 100.0, float(com["descuento_pct"] or 0), 5.0, key=f"dc{cid}")
        prop = d2.number_input("Propina %", 0.0, 100.0, float(com["propina_pct"] or 0), 5.0, key=f"pp{cid}")
        if desc != float(com["descuento_pct"] or 0) or prop != float(com["propina_pct"] or 0):
            actualizar(T_COM, cid, {"descuento_pct": desc, "propina_pct": prop})
            log("comanda_ajuste", f"comanda {cid} · desc {desc:g}% · propina {prop:g}%")
            st.rerun()
        com["descuento_pct"], com["propina_pct"] = desc, prop
        tot = totales(com, activos)
        st.markdown(
            (f"<small>Subtotal {peso(tot['sub'])}"
             + (f" · Desc. -{peso(tot['desc'])}" if tot["desc"] else "")
             + (f" · Propina {peso(tot['prop'])}" if tot["prop"] else "")).replace("$", "&#36;")  # dos "$" en una línea = fórmula
            + f"</small><div class='totalbox'>{peso(tot['total'])}</div>", unsafe_allow_html=True)
        if com["comensales"] > 1 and tot["total"]:
            st.caption(f"≈ {peso(math.ceil(tot['total'] / com['comensales']))} por persona ({com['comensales']} comensales)")

        b1, b2 = st.columns(2)
        if b1.button("💳 Cobrar", type="primary", disabled=(not activos) or bool(borrador), **STRETCH):
            go(P_COBRO)
        if b2.button("⬅ Salón", **STRETCH):
            go(P_SALON)
        if borrador:
            st.caption("⚠️ Confirmá el pedido antes de cobrar: lo que no se confirma no llega a cocina/barra.")

        with st.expander("🧾 Pre-cuenta"):
            st.markdown(ticket_html(com, mesa, activos, tot, cli=cli), unsafe_allow_html=True)
            st.download_button("⬇ Descargar .txt", ticket_txt(com, mesa, activos, tot),
                               file_name=f"precuenta_{mesa['nombre'].replace(' ', '_')}.txt")
            acciones_ticket(com, mesa["nombre"], activos, tot, [], cli, f"pc{cid}")

        with st.expander("✏️ Editar cuenta (mesa, cliente, datos)"):
            form_datos_cuenta(com, f"c{cid}", importes=False)

        with st.expander("❌ Anular comanda"):
            motivo = st.text_input("Motivo", key=f"mt{cid}")
            ok = st.checkbox("Confirmo que se anula toda la comanda (el stock se devuelve)", key=f"ok{cid}")
            if st.button("Anular comanda", disabled=not (ok and motivo.strip()), key=f"an{cid}"):
                anular_comanda(com, motivo.strip())
                st.session_state.pop("cid", None)
                go(P_SALON)

        anul = [i for i in todos if i["anulado"]]
        if anul:
            with st.expander(f"Ítems anulados ({len(anul)})"):
                for i in anul:
                    st.caption(f"{i['cantidad']}× {i['nombre']} — {peso(float(i['precio_unit']) * i['cantidad'])}")


# ─────────────────────────────────────────
# PÁGINA: COBRO
# ─────────────────────────────────────────
def mp_link_dinamico(monto, titulo, ref):
    key = ("mp", ref, int(monto))
    if key in st.session_state:
        return st.session_state[key]
    try:
        token = st.secrets["mercadopago"].get("access_token", "") if "mercadopago" in st.secrets else ""
        if not token:
            return None
        r = requests.post(
            "https://api.mercadopago.com/checkout/preferences",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"items": [{"title": titulo, "quantity": 1, "unit_price": float(monto), "currency_id": "ARS"}],
                  "external_reference": ref, "statement_descriptor": "HOPSIE"}, timeout=12)
        r.raise_for_status()
        link = r.json().get("init_point")
        st.session_state[key] = link
        return link
    except Exception as e:
        st.warning(f"No pude generar el link de Mercado Pago ({e}). Uso el QR configurado.")
        return None


def qr_cuentas():
    try:
        return json.loads(CFG.get("qr_cuentas") or "[]")
    except Exception:
        return []


def qr_activos_ids():
    try:
        return json.loads(CFG.get("qr_activos") or "[]")
    except Exception:
        return []


def _bloque_qr_cuentas(com, monto, cuentas):
    """Cobro con las cuentas QR que los dueños habilitaron para hoy. Devuelve el nombre de la cuenta; False si no hay ninguna."""
    activos = set(qr_activos_ids())
    act = [c for c in cuentas if c["id"] in activos]
    if not act:
        st.error("⚠️ No hay ningún QR habilitado para hoy. Un dueño tiene que elegirlo en Admin → Pagos.")
        return False
    fecha, hoy = CFG.get("qr_activos_fecha"), datetime.now(TZ).strftime("%Y-%m-%d")
    if fecha and fecha != hoy:
        try:
            dias = (datetime.strptime(hoy, "%Y-%m-%d") - datetime.strptime(fecha, "%Y-%m-%d")).days
        except Exception:
            dias = 0
        if dias > 6:
            st.warning(f"Los QR habilitados se eligieron el {fecha[8:]}/{fecha[5:7]}. Verificá que sean los vigentes (Admin → Pagos).")
        else:
            st.caption(f"QR habilitados el {fecha[8:]}/{fecha[5:7]}.")
    if qrcode is None:
        st.warning("Para generar códigos QR falta el paquete `qrcode[pil]` en requirements.txt.")
    ck, ids = f"qs_{com['id']}", [c["id"] for c in act]
    if st.session_state.get(ck) not in ids:
        st.session_state[ck] = ids[0]
    # 1º la billetera, 2º (si hay varios) cuál de sus QR
    wallets = list(dict.fromkeys(c.get("proveedor") or "otro" for c in act))
    actual = next(c for c in act if c["id"] == st.session_state[ck])
    w_act = actual.get("proveedor") or "otro"
    if len(wallets) > 1:
        st.markdown("**¿Con qué billetera paga el cliente?**")
        cols = st.columns(min(len(wallets), 3))
        for n, w in enumerate(wallets):
            if cols[n % len(cols)].button(PROV_NOMBRE.get(w, "Otra"), key=f"qsw_{com['id']}_{w}",
                                          type="primary" if w == w_act else "secondary", **STRETCH):
                st.session_state[ck] = next(c["id"] for c in act if (c.get("proveedor") or "otro") == w)
                st.rerun()
    de_w = [c for c in act if (c.get("proveedor") or "otro") == w_act]
    if len(de_w) > 1:
        st.markdown("**¿Qué QR?**")
        cols = st.columns(min(len(de_w), 3))
        for n, c in enumerate(de_w):
            if cols[n % len(cols)].button(c["nombre"], key=f"qsb_{com['id']}_{c['id']}",
                                          type="primary" if st.session_state[ck] == c["id"] else "secondary", **STRETCH):
                st.session_state[ck] = c["id"]
                st.rerun()
    cta = next(c for c in act if c["id"] == st.session_state[ck])
    png, leyenda = None, ""
    if CFG.get(f"qrimg_{cta['id']}"):
        png, leyenda = base64.b64decode(CFG[f"qrimg_{cta['id']}"]), f"QR de la cuenta: el cliente ingresa {peso(monto)}"
    else:
        dato = cta.get("dato") or cta.get("alias") or CFG.get("negocio_alias")
        if dato:
            png, leyenda = qr_png(dato), f"QR con: {dato}"
    c1, c2 = st.columns(2)
    with c1:
        if png:
            st.image(png, width=300)
        else:
            st.warning("Esta cuenta no tiene imagen de QR ni alias cargado (Admin → Pagos).")
    with c2:
        if cta.get("proveedor") in PROV_NOMBRE:
            st.markdown(chip(cta["proveedor"]), unsafe_allow_html=True)
        st.markdown(f"<div class='totalbox'>{peso(monto)}</div>", unsafe_allow_html=True)
        st.markdown(f"**Cuenta:** {esc(cta['nombre'])}")
        st.caption(leyenda)
        if cta.get("alias"):
            st.caption("Alias / CVU")
            st.code(cta["alias"], language=None)
        if cta.get("titular"):
            st.caption(f"Titular: {cta['titular']}")
    return cta["nombre"]


def bloque_qr(com, mesa, monto):
    cuentas = qr_cuentas()
    if cuentas:
        return _bloque_qr_cuentas(com, monto, cuentas)
    hab = json.loads(CFG.get("pay_habilitados") or "[]")
    if not hab:
        st.warning("Configurá los medios de pago en **Admin → Pagos** (solo dueños).")
        return None
    if qrcode is None:
        st.warning("Para generar códigos QR falta el paquete `qrcode[pil]` en requirements.txt.")
    st.markdown("".join(chip(s) for s in hab), unsafe_allow_html=True)
    slug = st.selectbox("El cliente paga con", hab, format_func=lambda s: PROV_NOMBRE[s], key=f"prov_{com['id']}")
    png, leyenda = None, ""
    if slug == "mercadopago":
        link = mp_link_dinamico(monto, f"HOPSIE - {mesa['nombre']}", f"hopsie-{com['id']}")
        if link:
            png, leyenda = qr_png(link), f"QR de Mercado Pago por {peso(monto)} (link de pago generado)"
    if png is None:
        qr_b64 = CFG.get(f"pay_{slug}_qr")
        if qr_b64:
            png, leyenda = base64.b64decode(qr_b64), f"QR del comercio: el cliente ingresa {peso(monto)}"
        else:
            dato = CFG.get(f"pay_{slug}_dato") or CFG.get("negocio_alias")
            if dato:
                png, leyenda = qr_png(dato), f"QR con: {dato}"
    c1, c2 = st.columns([1, 1])
    with c1:
        if png:
            st.image(png, width=280)
        else:
            st.warning("No hay QR ni alias cargado para este medio (Admin → Pagos).")
    with c2:
        st.markdown(f"<div class='totalbox'>{peso(monto)}</div>", unsafe_allow_html=True)
        st.caption(leyenda)
        for k, et in (("negocio_alias", "Alias"), ("negocio_cvu", "CBU/CVU")):
            if CFG.get(k):
                st.caption(et)
                st.code(CFG[k], language=None)
        if CFG.get("negocio_titular"):
            st.caption(f"Titular: {CFG['negocio_titular']}")
    return PROV_NOMBRE[slug]


def pagina_cobro():
    com, mesa = comanda_actual()
    if not com:
        st.info("No hay una comanda abierta seleccionada. Elegí una mesa en **Salón**.")
        return
    cid = com["id"]
    items = items_de([cid])
    tot = totales(com, items)
    pagos = listar(T_PAGOS, comanda_id=cid, order="id")
    pagado = sum(float(p["monto"]) for p in pagos)
    saldo = max(0, tot["total"] - round(pagado))

    st.markdown(f"### 💳 Cobrar {mesa['nombre']}")
    a, b, c = st.columns(3)
    a.metric("Total", peso(tot["total"]))
    b.metric("Pagado", peso(pagado))
    c.metric("Saldo", peso(saldo))
    if pagos:
        st.caption(" · ".join(f"{p['metodo']}{' (' + p['proveedor'] + ')' if p['proveedor'] else ''} {peso(p['monto'])}" for p in pagos).replace("$", "&#36;"))

    if not items:
        st.warning("La comanda no tiene consumos. Anulala desde la comanda.")
        return
    if saldo <= 0:
        cerrar_y_enviar(com, tot, pagos)
        st.session_state.pop("cid", None)
        st.toast("Mesa cerrada ✅")
        go(P_SALON)

    n = st.number_input("Dividir entre (personas)", 1, 60, int(com["comensales"]), key=f"div{cid}")
    if n > 1:
        st.caption(f"Cada uno: {peso(math.ceil(saldo / n))}")
    monto = st.number_input("Monto a cobrar ahora", 1, int(saldo), int(saldo), 100,
                            key=f"monto_{cid}_{len(pagos)}")
    METS = {"efectivo": ("💵", "EFECTIVO", "Efectivo", "#39FF14"),
            "qr": ("📱", "TRANSFERENCIA / QR", "QR / Transferencia", "#00E5CF"),
            "tarjeta": ("💳", "TARJETA", "Tarjeta", "#FF2E93")}
    st.markdown("<div class='cobro-titulo'>¿Cómo paga el cliente?</div>", unsafe_allow_html=True)
    sel_k, ckey = f"cm_{cid}", f"cc_{cid}"
    sel = st.session_state.get(sel_k)
    for col, (k, (ic, et, _n, _c)) in zip(st.columns(3), METS.items()):
        if col.button(f"{ic} {et}", key=f"cmb_{cid}_{k}", type="primary" if sel == k else "secondary", **STRETCH):
            st.session_state[sel_k] = k
            st.session_state.pop(ckey, None)
            st.rerun()
    if not sel:
        st.info("👆 Elegí el medio de pago para seguir.")
    else:
        ic, et, nombre_metodo, color = METS[sel]
        st.markdown(f"<div class='cobro-sel' style='background:{color}'>VA A PAGAR CON: {ic} {et} · {peso(monto)}</div>",
                    unsafe_allow_html=True)
        proveedor, ref, bloqueado, detalle = None, "", False, ""
        if sel == "efectivo":
            rec = st.number_input("Entrega el cliente", int(monto), int(monto) * 10 + 100000, int(monto), 500, key=f"rec{cid}")
            if rec > monto:
                st.success(f"Vuelto: {peso(rec - monto)}")
                detalle = f"Entrega {peso(rec)} · Vuelto {peso(rec - monto)}"
        elif sel == "qr":
            r = bloque_qr(com, mesa, monto)
            bloqueado, proveedor = (r is False), (r or None)
            detalle = f"Cuenta: {proveedor}" if proveedor else ""
        else:
            ref = st.text_input("N° de cupón / últimos 4 (opcional)", key=f"cup{cid}")
        firma = (sel, int(monto), proveedor or "")
        if st.session_state.get(ckey) != firma:
            st.session_state.pop(ckey, None)
            if st.button("✅ REGISTRAR COBRO", key=f"rc_{cid}", type="primary", disabled=bloqueado, **STRETCH):
                st.session_state[ckey] = firma
                st.rerun()
        else:
            pregunta = ("¿Ya llegó la transferencia / el cliente ya pagó con el QR?" if sel == "qr"
                        else "Revisá que el medio de pago sea el correcto")
            st.markdown(f"<div class='cobro-conf'><div class='c1'>⚠️ Confirmá el cobro</div><div class='c2'>{peso(monto)}</div>"
                        f"<div class='c3'>{ic} {et}</div><div class='c4'>{esc(detalle)}</div><div class='c4'>{pregunta}</div></div>",
                        unsafe_allow_html=True)
            b1, b2 = st.columns(2)
            if b1.button("✅ SÍ, CONFIRMAR COBRO", key=f"rcok_{cid}", type="primary", **STRETCH):
                insertar(T_PAGOS, {"comanda_id": cid, "metodo": nombre_metodo, "proveedor": proveedor,
                                   "monto": float(monto), "usuario": actor(), "referencia": ref})
                log("pago", f"comanda {cid} · {nombre_metodo} {proveedor or ''} · {peso(monto)}")
                st.session_state.pop(ckey, None)
                st.session_state.pop(sel_k, None)
                nuevos = listar(T_PAGOS, comanda_id=cid)
                if tot["total"] - round(sum(float(p["monto"]) for p in nuevos)) <= 0:
                    cerrar_y_enviar(com, tot, nuevos)
                    st.session_state.pop("cid", None)
                    st.toast("Mesa cerrada ✅")
                    go(P_SALON)
                st.rerun()
            if b2.button("↩ CAMBIAR", key=f"rcno_{cid}", **STRETCH):
                st.session_state.pop(ckey, None)
                st.rerun()
    if st.button("⬅ Volver a la comanda"):
        go(P_COMANDA)


# ─────────────────────────────────────────
# PÁGINA: COCINA / BARRA
# ─────────────────────────────────────────
PALETA_KDS = [("#FFE600", "#000"), ("#00E5CF", "#000"), ("#FF2E93", "#fff"), ("#39FF14", "#000"), ("#FF8A00", "#000"),
              ("#8B5CF6", "#fff"), ("#3B82F6", "#fff"), ("#EF4444", "#fff"), ("#F472B6", "#000"), ("#22D3EE", "#000")]


@autorefresh(15)
def _estacion_body(sector):
    icono = "👨‍🍳" if sector == "Cocina" else "🍺"
    abiertas = {c["id"]: c for c in listar(T_COM, estado="abierta")}
    mesas, clis = mapa_mesas(), mapa_clientes()
    its = [i for i in items_de(list(abiertas)) if i["sector"] == sector and i["estado"] in ("pendiente", "preparando")
           and i.get("confirmado", True)]  # solo pedidos confirmados por la moza
    if not its:
        st.markdown(f"<div class='kds-vacio'>{icono} {sector.upper()} · TODO AL DÍA 🎉</div>", unsafe_allow_html=True)
        return
    por_com = defaultdict(list)
    for it in its:
        por_com[it["comanda_id"]].append(it)

    def desde(i):
        return parse_ts(i.get("confirmado_ts") or i["ts"])

    orden = sorted(por_com, key=lambda c: min(desde(i) for i in por_com[c]))
    st.markdown(f"<div class='kds-resumen'>{icono} {sector.upper()} · {len(orden)} mesa(s) · "
                f"{sum(int(i['cantidad']) for i in its)} ítems por preparar</div>", unsafe_allow_html=True)
    cols = st.columns(2)
    for n, cid in enumerate(orden):
        com = abiertas[cid]
        nombre = etiqueta_cuenta(com, mesas, clis)
        bg, fg = PALETA_KDS[(com.get("mesa_id") or cid) % len(PALETA_KDS)]  # el mismo color para la misma mesa
        lista = sorted(por_com[cid], key=desde)
        mins = int((ahora_utc() - min(desde(i) for i in lista)).total_seconds() // 60)
        with cols[n % 2]:
            st.markdown(f"<div class='kds-head' style='background:{bg};color:{fg}'><span class='kds-mesa'>{esc(nombre)}</span>"
                        f"<span class='kds-min'>⏱ {mins}′{' ⚠️' if mins >= 15 else ''}</span></div>", unsafe_allow_html=True)
            for it in lista:
                nota = f"<span class='kds-nota'>📝 {esc(it['nota'])}</span>" if it["nota"] else ""
                bad = " 🔥" if it["estado"] == "preparando" else ""
                st.markdown(f"<div class='kds-item {it['estado']}' style='border-left:16px solid {bg}'>"
                            f"<span class='kds-cant' style='color:{bg}'>{it['cantidad']}×</span>{esc(it['nombre'])}{bad}{nota}</div>",
                            unsafe_allow_html=True)
                b1, b2 = st.columns(2)
                if it["estado"] == "pendiente" and b1.button("🔥 Preparar", key=f"pr{it['id']}", **STRETCH):
                    actualizar(T_ITEMS, it["id"], {"estado": "preparando"})
                    st.rerun()
                if b2.button("✅ Listo", key=f"ok{it['id']}", type="primary", **STRETCH):
                    actualizar(T_ITEMS, it["id"], {"estado": "servido"})
                    st.rerun()
            if len(lista) > 1 and st.button("✅ Toda la mesa lista", key=f"all_{sector}_{cid}", **STRETCH):
                tb(T_ITEMS).update({"estado": "servido"}).in_("id", [i["id"] for i in lista]).execute()
                st.rerun()


def _pagina_estacion(sector):
    st.markdown(f"### {'👨‍🍳' if sector == 'Cocina' else '🍺'} {sector}")
    st.caption("Se actualiza solo cada 15 segundos. Solo aparecen los pedidos que la moza confirmó. "
               "Cada mesa tiene su propio color.")
    _estacion_body(sector)


def pagina_cocina():
    _pagina_estacion("Cocina")


def pagina_barra():
    _pagina_estacion("Barra")


# ─────────────────────────────────────────
# PÁGINA: ADMIN
# ─────────────────────────────────────────
def setup_primer_dueno():
    st.warning("Todavía no hay usuarios. Creá el primer **dueño** (después él crea al resto).")
    with st.form("setup"):
        usr = st.text_input("Usuario (sin espacios)")
        nom = st.text_input("Nombre y apellido")
        p1 = st.text_input("Contraseña (mín. 8)", type="password")
        p2 = st.text_input("Repetir contraseña", type="password")
        if st.form_submit_button("Crear dueño", type="primary"):
            usr = usr.strip().lower().replace(" ", "")
            if not usr or not nom.strip() or len(p1) < 8 or p1 != p2:
                st.error("Completá todo; la contraseña debe tener 8+ caracteres y coincidir.")
            else:
                s, h = hash_pw(p1)
                insertar(T_USU, {"usuario": usr, "nombre": nom.strip(), "rol": "dueno", "salt": s, "pass_hash": h})
                log("usuario_creado", f"{usr} (dueno) — primer usuario", quien=usr)
                st.success("Listo. Ya podés iniciar sesión.")
                st.rerun()


def login_ui():
    if time.time() < st.session_state.get("hs_lock", 0):
        st.error("Demasiados intentos. Esperá un minuto.")
        return
    st.markdown("#### 🔐 Acceso exclusivo dueños y encargado")
    with st.form("login"):
        usr = st.text_input("Usuario")
        pw = st.text_input("Contraseña", type="password")
        ok = st.form_submit_button("Entrar", type="primary")
    if ok:
        r = listar(T_USU, usuario=usr.strip().lower(), activo=True)
        if r and check_pw(pw, r[0]["salt"], r[0]["pass_hash"]):
            st.session_state["hs_user"] = {k: r[0][k] for k in ("id", "usuario", "nombre", "rol")}
            st.session_state["hs_fails"] = 0
            log("login", "")
            st.rerun()
        fails = st.session_state.get("hs_fails", 0) + 1
        st.session_state["hs_fails"] = fails
        log("login_fallido", usr.strip()[:40], quien="anonimo")
        if fails >= 5:
            st.session_state["hs_lock"] = time.time() + 60
            st.session_state["hs_fails"] = 0
        st.error("Usuario o contraseña incorrectos.")


def cargar_ejemplo():
    if not listar(T_INS):
        base = [("Cerveza Golden", "Cerveza (litros)", "lt", 120, 20, 1500), ("Cerveza IPA", "Cerveza (litros)", "lt", 100, 20, 1700),
                ("Cerveza Honey", "Cerveza (litros)", "lt", 80, 20, 1600), ("Cerveza Stout", "Cerveza (litros)", "lt", 60, 15, 1700),
                ("Cerveza Red Ale", "Cerveza (litros)", "lt", 60, 15, 1650), ("Pan de hamburguesa", "Cocina", "un", 60, 15, 350),
                ("Medallón de carne", "Cocina", "un", 60, 15, 1400), ("Cheddar (feta)", "Cocina", "un", 100, 20, 150),
                ("Papas", "Cocina", "kg", 30, 8, 1200), ("Queso para picada", "Cocina", "kg", 6, 2, 9000),
                ("Salame", "Cocina", "kg", 4, 1, 14000), ("Maní", "Cocina", "kg", 3, 1, 5000),
                ("Gaseosa lata", "Bebidas", "un", 48, 12, 900), ("Agua mineral", "Bebidas", "un", 48, 12, 600)]
        for n, c, u, s, mi, co in base:
            tb(T_INS).upsert({"nombre": n, "categoria": c, "unidad": u, "stock": s, "minimo": mi, "costo": co}, on_conflict="nombre").execute()
    ids = {i["nombre"]: i["id"] for i in listar(T_INS)}
    if not listar(T_PROD):
        prods = [("Pinta Golden 500cc", "Cervezas", 3800, "Barra", "🍺", [("Cerveza Golden", 0.5)]),
                 ("Pinta IPA 500cc", "Cervezas", 4200, "Barra", "🍺", [("Cerveza IPA", 0.5)]),
                 ("Pinta Honey 500cc", "Cervezas", 4000, "Barra", "🍯", [("Cerveza Honey", 0.5)]),
                 ("Pinta Stout 500cc", "Cervezas", 4200, "Barra", "🖤", [("Cerveza Stout", 0.5)]),
                 ("Pinta Red Ale 500cc", "Cervezas", 4000, "Barra", "🔴", [("Cerveza Red Ale", 0.5)]),
                 ("Chopp Golden 300cc", "Cervezas", 2600, "Barra", "🍺", [("Cerveza Golden", 0.3)]),
                 ("Jarra Golden 1L", "Cervezas", 7200, "Barra", "🍻", [("Cerveza Golden", 1.0)]),
                 ("Hamburguesa Hopsie", "Comidas", 9500, "Cocina", "🍔",
                  [("Pan de hamburguesa", 1), ("Medallón de carne", 1), ("Cheddar (feta)", 2), ("Papas", 0.25)]),
                 ("Papas fritas", "Comidas", 5000, "Cocina", "🍟", [("Papas", 0.3)]),
                 ("Picada para 2", "Comidas", 14000, "Cocina", "🧀", [("Queso para picada", 0.25), ("Salame", 0.2), ("Maní", 0.05)]),
                 ("Gaseosa", "Sin alcohol", 2200, "Barra", "🥤", [("Gaseosa lata", 1)]),
                 ("Agua mineral", "Sin alcohol", 1800, "Barra", "💧", [("Agua mineral", 1)])]
        for n, cat, pr, sec, em, rec in prods:
            r = insertar(T_PROD, {"nombre": n, "categoria": cat, "precio": pr, "sector": sec, "emoji": em})[0]
            for ins_n, q in rec:
                insertar(T_REC, {"producto_id": r["id"], "insumo_id": ids[ins_n], "cantidad": q})
    if not listar(T_MESAS):
        o = 0
        for zona, pref, cant, cap in (("Salón", "Mesa", 10, 4), ("Barra", "Barra", 4, 2), ("Vereda", "Vereda", 4, 4)):
            for i in range(1, cant + 1):
                o += 1
                insertar(T_MESAS, {"nombre": f"{pref} {i}", "zona": zona, "capacidad": cap, "orden": o})
    log("datos_ejemplo", "Se cargaron insumos, productos y mesas de ejemplo")


# ─────────────────────────────────────────
# ELIMINAR (con confirmación) — disponible en todo el módulo HOPSIE
# ─────────────────────────────────────────
def confirmar_eliminar(key, aviso, accion, etiqueta="Eliminar"):
    """Botón rojo 'Eliminar' que pide confirmación. accion() devuelve (ok, mensaje)."""
    caja = st.container(key=f"del_pop_{key}") if ICON_OK else st.container()
    with caja, st.popover(etiqueta if ICON_DEL else "🗑️ " + etiqueta, **ICON_DEL):
        st.warning(aviso)
        if st.button("Sí, eliminar definitivamente", key=f"del_{key}", type="primary", **ICON_DEL):
            try:
                ok, msg = accion()
            except Exception as e:
                ok, msg = False, f"No se pudo eliminar: {e}"
            if ok:
                st.toast("🗑️ " + msg)
                st.rerun()
            else:
                st.error(msg)


def _intentar(fn):
    try:
        fn()
        return True
    except Exception:
        return False


def eliminar_producto(p):
    if not _intentar(lambda: borrar(T_PROD, p["id"])):
        tb(T_REC).delete().eq("producto_id", p["id"]).execute()
        if not _intentar(lambda: borrar(T_PROD, p["id"])):
            actualizar(T_PROD, p["id"], {"activo": False})
            log("producto_archivado", p["nombre"])
            return True, (f"«{p['nombre']}» figura en ventas pasadas y la base no permite borrarlo: "
                          f"quedó inactivo (ya no aparece en la comanda).")
    log("producto_eliminado", p["nombre"])
    return True, f"Producto «{p['nombre']}» eliminado."


def eliminar_insumo(i):
    tb(T_REC).delete().eq("insumo_id", i["id"]).execute()
    if not _intentar(lambda: borrar(T_INS, i["id"])):
        tb(T_MOV).delete().eq("insumo_id", i["id"]).execute()
        if not _intentar(lambda: borrar(T_INS, i["id"])):
            actualizar(T_INS, i["id"], {"activo": False})
            log("insumo_archivado", i["nombre"])
            return True, f"«{i['nombre']}» no se pudo borrar de la base: quedó inactivo."
    st.session_state.pop("ei", None)
    log("insumo_eliminado", i["nombre"])
    return True, f"Insumo «{i['nombre']}» eliminado."


def eliminar_mesa(m):
    ab = [c for c in listar(T_COM, estado="abierta") if c.get("mesa_id") == m["id"]]
    if ab:
        return False, (f"No se puede eliminar: {m['nombre']} tiene una cuenta abierta (#{ab[0]['id']}). "
                       f"Cobrala, anulala o pasala a otra mesa.")
    for c in listar(T_COM, mesa_id=m["id"]):  # las cuentas históricas conservan el nombre de la mesa
        if not (c.get("etiqueta") or "").strip():
            actualizar(T_COM, c["id"], {"etiqueta": m["nombre"]})
    tb(T_COM).update({"mesa_id": None}).eq("mesa_id", m["id"]).execute()
    borrar(T_MESAS, m["id"])
    log("mesa_eliminada", m["nombre"])
    return True, f"Mesa «{m['nombre']}» eliminada."


def eliminar_cliente(c):
    ab = listar(T_COM, estado="abierta", cliente_id=c["id"])
    if ab:
        return False, f"No se puede eliminar: {c['nombre']} tiene una cuenta abierta (#{ab[0]['id']}). Cobrala o anulala primero."
    tb(T_COM).update({"cliente_id": None}).eq("cliente_id", c["id"]).execute()
    borrar(T_CLI, c["id"])
    st.session_state.pop("cl_sel", None)
    log("cliente_eliminado", f"{c['nombre']} · {c.get('telefono') or 's/tel'}")
    return True, f"Cliente «{c['nombre']}» eliminado."


def eliminar_usuario(u, users):
    yo = usuario_actual()
    if yo and u["id"] == yo["id"]:
        return False, "No podés eliminarte a vos mismo."
    quedan = [x for x in users if x["id"] != u["id"] and x["rol"] == "dueno" and x["activo"]]
    if u["rol"] == "dueno" and u["activo"] and not quedan:
        return False, "Tiene que quedar al menos un dueño activo."
    borrar(T_USU, u["id"])
    st.session_state.pop("us_sel", None)
    log("usuario_eliminado", f"{u['usuario']} ({u['rol']})")
    return True, f"Usuario «{u['usuario']}» eliminado."


def eliminar_item_def(it, estado_com):
    if not it["anulado"] and estado_com != "cancelada":  # el stock de un ítem vivo vuelve al depósito
        aplicar_receta(it.get("producto_id"), -it["cantidad"], it["comanda_id"], f"Eliminación comanda #{it['comanda_id']}")
    borrar(T_ITEMS, it["id"])
    log("item_eliminado", f"comanda {it['comanda_id']} · {it['cantidad']}× {it['nombre']}")
    recalcular_comanda(it["comanda_id"])
    return True, "Ítem eliminado."


def eliminar_comanda(com, devolver_stock):
    cid = com["id"]
    if devolver_stock and com["estado"] != "cancelada":
        for it in items_de([cid]):
            aplicar_receta(it.get("producto_id"), -it["cantidad"], cid, f"Comanda eliminada #{cid}")
    tb(T_MOV).update({"comanda_id": None}).eq("comanda_id", cid).execute()
    tb(T_PAGOS).delete().eq("comanda_id", cid).execute()
    tb(T_ITEMS).delete().eq("comanda_id", cid).execute()
    borrar(T_COM, cid)
    st.session_state.pop("op_sel", None)
    if st.session_state.get("cid") == cid:
        st.session_state.pop("cid", None)
    log("comanda_eliminada", f"comanda {cid} · {peso(com.get('total') or 0)} · estaba {com['estado']}")
    return True, f"Comanda #{cid} eliminada."


def eliminar_movimiento(m):
    borrar(T_MOV, m["id"])
    log("movimiento_eliminado", f"#{m['id']} · {m['tipo']} {float(m['cantidad']):g}")
    return True, "Movimiento eliminado del historial."


def resetear_auditoria(confirma):
    if (confirma or "").strip().upper() != "RESETEAR":
        return False, "Escribí RESETEAR para confirmar."
    tb(T_LOG).delete().gte("id", 0).execute()
    st.session_state.pop("aud_cid", None)
    log("auditoria_reseteada", "Se borró todo el historial de auditoría")
    return True, "Auditoría reseteada: arrancás desde cero."


def depurar_auditoria(lim):
    corte = datetime(lim.year, lim.month, lim.day, tzinfo=TZ).astimezone(timezone.utc)
    tb(T_LOG).delete().lt("ts", iso(corte)).execute()
    log("auditoria_depurada", f"registros anteriores al {lim:%d/%m/%Y}")
    return True, "Registros de auditoría depurados."


def seleccionar_operaciones(modo, lim):
    """modo 0: cobradas y canceladas anteriores a 'lim' · 1: todas las cerradas · 2: TODAS (incluye abiertas)."""
    estados = ["pagada", "cancelada"] if modo < 2 else ["pagada", "cancelada", "abierta"]
    out, ini = [], 0
    while True:
        q = tb(T_COM).select("id,estado").in_("estado", estados)
        if modo == 0:
            q = q.lt("abierta_ts", iso(datetime(lim.year, lim.month, lim.day, tzinfo=TZ).astimezone(timezone.utc)))
        r = q.order("id").range(ini, ini + 999).execute().data or []
        out += r
        if len(r) < 1000:
            return out
        ini += 1000


def depurar_operaciones(modo, lim, devolver_stock, confirma, borrar_log=False, borrar_movs=False):
    if modo == 2 and (confirma or "").strip().upper() != "RESETEAR":
        return False, "Escribí RESETEAR para confirmar el reseteo total."
    coms = seleccionar_operaciones(modo, lim)
    if not coms:
        return False, "No hay operaciones para borrar con ese criterio."
    if devolver_stock:
        for c in coms:
            if c["estado"] == "abierta":
                for it in items_de([c["id"]]):
                    aplicar_receta(it.get("producto_id"), -it["cantidad"], c["id"], f"Reseteo comanda #{c['id']}")
    ids = [c["id"] for c in coms]
    for k in range(0, len(ids), 80):
        ch = ids[k:k + 80]
        tb(T_MOV).update({"comanda_id": None}).in_("comanda_id", ch).execute()
        tb(T_PAGOS).delete().in_("comanda_id", ch).execute()
        tb(T_ITEMS).delete().in_("comanda_id", ch).execute()
        tb(T_COM).delete().in_("id", ch).execute()
    for k in ("cid", "op_sel", "mesa_pend"):
        st.session_state.pop(k, None)
    if modo == 2 and borrar_movs:
        tb(T_MOV).delete().gte("id", 0).execute()
    if modo == 2 and borrar_log:
        tb(T_LOG).delete().gte("id", 0).execute()
    log("operaciones_depuradas", f"{len(ids)} comandas eliminadas ({['anteriores a ' + lim.strftime('%d/%m/%Y'), 'todas las cerradas', 'RESET TOTAL'][modo]})")
    return True, f"{len(ids)} operaciones eliminadas."


def _panel_reset_operaciones():
    with st.expander("🧹 Eliminar / resetear operaciones (solo dueños)"):
        opciones = ["Cobradas y canceladas anteriores a una fecha", "Todas las cobradas y canceladas",
                    "🔥 RESETEAR TODO: todas las operaciones, incluso las abiertas (arrancar desde cero)"]
        modo = opciones.index(st.radio("¿Qué querés borrar?", opciones, key="rs_modo"))
        lim = date.today() - timedelta(days=30)
        if modo == 0:
            lim = st.date_input("Borrar lo anterior al", value=lim, key="rs_lim")
        sel = seleccionar_operaciones(modo, lim)
        cuenta = defaultdict(int)
        for c in sel:
            cuenta[c["estado"]] += 1
        abiertas_n = cuenta["abierta"]
        extra = f", {abiertas_n} abiertas" if modo == 2 else ""
        st.info(f"Se borrarían **{len(sel)}** operaciones: {cuenta['pagada']} cobradas, {cuenta['cancelada']} canceladas{extra}.")
        dev, txt, blog, bmov = False, "", False, False
        if modo == 2:
            dev = st.checkbox("Devolver al stock lo consumido en las cuentas abiertas", value=True, key="rs_dev")
            blog = st.checkbox("Borrar también TODA la auditoría", value=False, key="rs_log")
            bmov = st.checkbox("Borrar también el historial de movimientos de stock (no cambia las cantidades)", value=False, key="rs_mov")
            txt = st.text_input("Para confirmar escribí RESETEAR", key="rs_txt")
        st.caption("Se borran las cuentas con sus consumos y cobros. Cambia el dashboard, las visitas y el consumo de los clientes. "
                   "El stock de insumos no se modifica (salvo la devolución indicada) y la auditoría queda intacta.")
        confirmar_eliminar("ops", f"Se eliminan {len(sel)} operaciones para siempre. No se puede deshacer.",
                           lambda: depurar_operaciones(modo, lim, dev, txt, blog, bmov), "Eliminar operaciones")


def corte_jornada():
    try:
        return int(float(CFG.get("jornada_corte") or 6))
    except Exception:
        return 6


def inicio_jornada(offset_dias=0):
    """La jornada del bar empieza a la hora de corte (por defecto 06:00), así una noche que pasa de medianoche cuenta como una sola."""
    ahora = datetime.now(TZ)
    ini = ahora.replace(hour=corte_jornada(), minute=0, second=0, microsecond=0)
    if ahora < ini:
        ini -= timedelta(days=1)
    return (ini - timedelta(days=offset_dias)).astimezone(timezone.utc)


def _traer_todo(q_fn):
    out, ini = [], 0
    while True:
        r = q_fn().range(ini, ini + 999).execute().data or []
        out += r
        if len(r) < 1000:
            return out
        ini += 1000


def _fmt_rango(d, h):
    return f"{d.astimezone(TZ):%d/%m %H:%M} → {h.astimezone(TZ):%d/%m %H:%M}"


def admin_dashboard():
    st.markdown("### 📊 Dashboard")
    opciones = ["Jornada de hoy", "Jornada de ayer", "Últimos 7 días", "Este mes", "Elegir fechas"]
    per = st.selectbox("Período", opciones, key="dash_per")
    ini0 = inicio_jornada(0)
    if per == "Jornada de hoy":
        desde, hasta = ini0, ini0 + timedelta(days=1)
    elif per == "Jornada de ayer":
        desde, hasta = inicio_jornada(1), ini0
    elif per == "Últimos 7 días":
        desde, hasta = inicio_jornada(6), ini0 + timedelta(days=1)
    elif per == "Este mes":
        m0 = datetime.now(TZ).replace(day=1, hour=corte_jornada(), minute=0, second=0, microsecond=0)
        desde, hasta = m0.astimezone(timezone.utc), ini0 + timedelta(days=1)
    else:
        c1, c2 = st.columns(2)
        f1 = c1.date_input("Desde", value=date.today() - timedelta(days=7), key="dash_f1")
        f2 = c2.date_input("Hasta (inclusive)", value=date.today(), key="dash_f2")
        h_ = corte_jornada()
        desde = datetime(f1.year, f1.month, f1.day, h_, tzinfo=TZ).astimezone(timezone.utc)
        hasta = datetime(f2.year, f2.month, f2.day, h_, tzinfo=TZ).astimezone(timezone.utc) + timedelta(days=1)
    st.caption(f"📅 {_fmt_rango(desde, hasta)} · la jornada empieza a las {corte_jornada():02d}:00 (se cambia en Admin → Apariencia)")
    with st.expander("ℹ️ Cómo leer este tablero"):
        st.markdown(
            "- **Cobrado**: plata que realmente entró (pagos registrados en Cobro) en el período.\n"
            "- **Pendiente de cobro**: lo consumido en las cuentas que siguen abiertas ahora mismo.\n"
            "- **Ticket enviado**: cada vez que la moza toca *Confirmar pedido* se genera un ticket para Cocina y/o para Barra.\n"
            "- **Comandas**: cuántas cuentas distintas pidieron algo de ese rubro.\n"
            "- **Unidades y dinero por rubro**: lo pedido en el período (incluye cuentas todavía abiertas), "
            "a precio de lista: **sin descuentos ni propinas**. Por eso puede diferir del cobrado.")

    d_iso, h_iso = iso(desde), iso(hasta)
    cobradas = _traer_todo(lambda: tb(T_COM).select("id,total,cerrada_ts").eq("estado", "pagada")
                           .gte("cerrada_ts", d_iso).lt("cerrada_ts", h_iso))
    pagos = _traer_todo(lambda: tb(T_PAGOS).select("metodo,proveedor,monto").gte("ts", d_iso).lt("ts", h_iso))
    items = _traer_todo(lambda: tb(T_ITEMS).select("comanda_id,nombre,sector,cantidad,precio_unit,confirmado_ts,ts")
                        .eq("anulado", False).gte("ts", d_iso).lt("ts", h_iso))
    abiertas = listar(T_COM, estado="abierta")
    pend = 0.0
    if abiertas:
        its_ab = items_de([c["id"] for c in abiertas])
        por_ab = defaultdict(list)
        for it in its_ab:
            por_ab[it["comanda_id"]].append(it)
        pend = sum(totales(c, por_ab[c["id"]])["total"] for c in abiertas)

    cobrado = sum(float(x["monto"]) for x in pagos)
    st.markdown("#### 💰 Caja")
    a, b, c, d = st.columns(4)
    a.metric("Cobrado", peso(cobrado))
    b.metric("Cuentas cobradas", len(cobradas))
    c.metric("Ticket promedio", peso(sum(float(x["total"]) for x in cobradas) / len(cobradas)) if cobradas else "—")
    d.metric("Pendiente de cobro", peso(pend), f"{len(abiertas)} cuenta(s) abierta(s)", delta_color="off")

    st.markdown("#### 🍽️ Lo que salió, separado por rubro")
    df = pd.DataFrame(items)
    colores = {"Cocina": ("#FF8A00", "👨‍🍳"), "Barra": ("#00E5CF", "🍺")}
    total_din, total_uni = 0.0, 0
    resumen = {}
    for sec in SECTORES:
        sub = df[df["sector"] == sec] if len(df) else df
        if len(sub):
            din = float((sub["cantidad"] * sub["precio_unit"].astype(float)).sum())
            uni = int(sub["cantidad"].sum())
            tick = len({(r["comanda_id"], str(r["confirmado_ts"] or r["ts"])[:19]) for r in sub.to_dict("records")})
            coms = int(sub["comanda_id"].nunique())
        else:
            din, uni, tick, coms = 0.0, 0, 0, 0
        resumen[sec] = (din, uni, tick, coms)
        total_din += din
        total_uni += uni
    cols = st.columns(len(SECTORES))
    for col, sec in zip(cols, SECTORES):
        din, uni, tick, coms = resumen[sec]
        color, emo = colores.get(sec, ("#FFE600", "🍽️"))
        pct = round(din / total_din * 100) if total_din else 0
        col.markdown(
            f"<div class='dcard' style='border-color:{color}'><div class='dh' style='background:{color}'>{emo} {esc(sec.upper())}</div>"
            f"<div class='dgrid'><div><b>{tick}</b><span>Tickets enviados</span></div><div><b>{coms}</b><span>Comandas (cuentas)</span></div>"
            f"<div><b>{uni}</b><span>Unidades</span></div><div><b>{peso(din)}</b><span>Dinero</span></div></div>"
            f"<div class='dbar'><i style='width:{pct}%;background:{color}'></i></div><div class='dpct'>{pct}% del dinero pedido</div></div>",
            unsafe_allow_html=True)
    st.markdown(f"<div class='dtot'><b>Total pedido:</b> {total_uni} unidades · {peso(total_din)} (a precio de lista, sin descuentos ni propinas)</div>",
                unsafe_allow_html=True)

    if len(df):
        df["importe"] = df["cantidad"] * df["precio_unit"].astype(float)
        cs = st.columns(len(SECTORES))
        for col, sec in zip(cs, SECTORES):
            with col:
                st.markdown(f"**Más vendidos · {sec}**")
                sub = df[df["sector"] == sec]
                if len(sub):
                    top = sub.groupby("nombre").agg(unidades=("cantidad", "sum"), importe=("importe", "sum")).sort_values("unidades", ascending=False)
                    st.dataframe(top.head(10), **STRETCH)
                else:
                    st.caption("Sin pedidos en este rubro.")
    st.markdown("#### 💳 Cobros por medio")
    if pagos:
        dp = pd.DataFrame(pagos)
        dp["medio"] = dp.apply(lambda r: f"{r['metodo']}" + (f" · {r['proveedor']}" if r["proveedor"] else ""), axis=1)
        dp["monto"] = dp["monto"].astype(float)
        g = dp.groupby("medio")["monto"].agg(["sum", "count"]).sort_values("sum", ascending=False)
        g.columns = ["Monto", "Cobros"]
        g["%"] = (g["Monto"] / g["Monto"].sum() * 100).round(1)
        st.dataframe(g, **STRETCH)
    else:
        st.caption("Sin cobros en este período.")

    ult = _traer_todo(lambda: tb(T_COM).select("total,cerrada_ts").eq("estado", "pagada").gte("cerrada_ts", iso(inicio_jornada(6))))
    if ult:
        dd = pd.DataFrame(ult)
        dd["dia"] = (pd.to_datetime(dd["cerrada_ts"], utc=True).dt.tz_convert(TZ) - pd.Timedelta(hours=corte_jornada())).dt.date
        g2 = dd.groupby("dia")["total"].sum()
        g2.index = [x.strftime("%d/%m") for x in g2.index]
        st.markdown("#### 📈 Cobrado por jornada (últimos 7 días)")
        st.bar_chart(g2)

    bajos = [i for i in listar(T_INS, activo=True) if float(i["stock"]) <= float(i["minimo"])]
    if bajos:
        st.markdown("#### ⚠️ Stock bajo")
        st.dataframe(pd.DataFrame([{"Insumo": i["nombre"], "Stock": f"{float(i['stock']):g} {i['unidad']}",
                                    "Mínimo": f"{float(i['minimo']):g}"} for i in bajos]), hide_index=True, **STRETCH)

    if not listar(T_PROD) or not listar(T_MESAS):
        st.info("Faltan productos o mesas. Podés cargar un set de ejemplo (precios y stock inventados, editables).")
        if st.button("🎲 Cargar datos de ejemplo"):
            cargar_ejemplo()
            st.rerun()


def admin_productos():
    insumos = listar(T_INS, order="nombre", activo=True)
    imap = {i["id"]: i for i in insumos}
    with st.expander("➕ Nuevo producto"):
        with st.form("np"):
            c1, c2, c3 = st.columns([3, 2, 2])
            n = c1.text_input("Nombre")
            cat = c2.text_input("Categoría", value="Cervezas")
            pr = c3.number_input("Precio", 0, 10_000_000, 0, 100)
            c4, c5 = st.columns(2)
            sec = c4.selectbox("Sector", SECTORES)
            em = c5.text_input("Emoji", value="🍺")
            if st.form_submit_button("Crear", type="primary") and n.strip():
                insertar(T_PROD, {"nombre": n.strip(), "categoria": cat.strip() or "Otros", "precio": pr, "sector": sec, "emoji": em})
                log("producto_creado", f"{n.strip()} · {peso(pr)}")
                st.rerun()
    for p in listar(T_PROD, order="categoria"):
        rec = listar(T_REC, producto_id=p["id"])
        costo = sum(float(r["cantidad"]) * float(imap[r["insumo_id"]]["costo"]) for r in rec if r["insumo_id"] in imap)
        marg = f" · margen {round((float(p['precio']) - costo) / float(p['precio']) * 100)}%" if float(p["precio"]) and rec else ""
        with st.expander(f"{p['emoji'] or ''} {p['nombre']} · {peso(p['precio'])}{'' if p['activo'] else ' (inactivo)'}"):
            with st.form(f"pf{p['id']}"):
                c1, c2, c3 = st.columns([3, 2, 2])
                n = c1.text_input("Nombre", p["nombre"])
                cat = c2.text_input("Categoría", p["categoria"])
                pr = c3.number_input("Precio", 0, 10_000_000, int(float(p["precio"])), 100)
                c4, c5, c6 = st.columns(3)
                sec = c4.selectbox("Sector", SECTORES, index=SECTORES.index(p["sector"]) if p["sector"] in SECTORES else 0)
                em = c5.text_input("Emoji", p["emoji"] or "")
                act = c6.checkbox("Activo", p["activo"])
                if st.form_submit_button("Guardar"):
                    if float(p["precio"]) != pr:
                        log("precio_modificado", f"{p['nombre']}: {peso(p['precio'])} → {peso(pr)}")
                    actualizar(T_PROD, p["id"], {"nombre": n.strip(), "categoria": cat.strip(), "precio": pr,
                                                  "sector": sec, "emoji": em, "activo": act})
                    log("producto_editado", n.strip())
                    st.rerun()
            confirmar_eliminar(f"prod{p['id']}", f"Se elimina «{p['nombre']}» y su receta. Las ventas pasadas no se tocan. "
                               f"Si el producto figura en ventas y la base no permite borrarlo, queda inactivo.",
                               lambda p=p: eliminar_producto(p), "Eliminar producto")
            st.markdown(f"**Receta** (insumos que consume 1 unidad) — costo {peso(costo)}{marg}")
            for r in rec:
                i = imap.get(r["insumo_id"])
                x1, x2 = st.columns([6, 1])
                x1.caption(f"{i['nombre'] if i else '?'} — {float(r['cantidad']):g} {i['unidad'] if i else ''}")
                with x2:
                    quitar_r = ib("borrar", f"r{r['id']}", "Quitar de la receta")
                if quitar_r:
                    borrar(T_REC, r["id"])
                    log("receta_quitada", f"{p['nombre']} − {i['nombre'] if i else r['insumo_id']}")
                    st.rerun()
            if insumos:
                y1, y2, y3 = st.columns([4, 2, 2])
                ins_sel = y1.selectbox("Insumo", insumos, format_func=lambda i: f"{i['nombre']} ({i['unidad']})", key=f"ri{p['id']}")
                qty = y2.number_input("Cantidad", 0.0, 100000.0, 0.0, 0.05, key=f"rq{p['id']}")
                y3.write("")
                if y3.button("Agregar", key=f"ra{p['id']}") and qty > 0:
                    tb(T_REC).upsert({"producto_id": p["id"], "insumo_id": ins_sel["id"], "cantidad": qty},
                                     on_conflict="producto_id,insumo_id").execute()
                    log("receta_agregada", f"{p['nombre']} + {ins_sel['nombre']} {qty:g}")
                    st.rerun()


def admin_stock():
    insumos = listar(T_INS, order="nombre")
    if insumos:
        df = pd.DataFrame([{"Insumo": i["nombre"], "Categoría": i["categoria"], "Stock": float(i["stock"]), "Unidad": i["unidad"],
                            "Mínimo": float(i["minimo"]), "Costo unit.": float(i["costo"]),
                            "Estado": "🔴 Bajo" if float(i["stock"]) <= float(i["minimo"]) else "🟢 OK"} for i in insumos])
        st.dataframe(df, hide_index=True, **STRETCH)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Movimiento de stock")
        act = [i for i in insumos if i["activo"]]
        if act:
            with st.form("mov"):
                ins_sel = st.selectbox("Insumo", act, format_func=lambda i: f"{i['nombre']} — {float(i['stock']):g} {i['unidad']}")
                tipo = st.radio("Tipo", ["Ingreso (compra)", "Merma / baja", "Ajuste de inventario"], horizontal=True)
                cant = st.number_input("Cantidad (en 'Ajuste' = stock real contado)", 0.0, 1_000_000.0, 0.0, 0.5)
                motivo = st.text_input("Motivo / proveedor")
                if st.form_submit_button("Registrar", type="primary"):
                    if tipo.startswith("Ingreso"):
                        mover_stock(ins_sel["id"], cant, "ingreso", motivo)
                    elif tipo.startswith("Merma"):
                        mover_stock(ins_sel["id"], -cant, "merma", motivo)
                    else:
                        mover_stock(ins_sel["id"], cant - float(ins_sel["stock"]), "ajuste", motivo)
                    log("stock_" + tipo.split()[0].lower(), f"{ins_sel['nombre']} · {cant:g} · {motivo}")
                    st.rerun()
    with c2:
        st.markdown("#### Nuevo insumo")
        with st.form("ni"):
            n = st.text_input("Nombre")
            a1, a2 = st.columns(2)
            cat = a1.selectbox("Categoría", CAT_INSUMOS)
            uni = a2.selectbox("Unidad", UNIDADES)
            b1, b2, b3 = st.columns(3)
            s0 = b1.number_input("Stock inicial", 0.0, 1_000_000.0, 0.0, 1.0)
            mi = b2.number_input("Mínimo", 0.0, 1_000_000.0, 0.0, 1.0)
            co = b3.number_input("Costo unit.", 0.0, 10_000_000.0, 0.0, 10.0)
            if st.form_submit_button("Crear", type="primary") and n.strip():
                try:
                    insertar(T_INS, {"nombre": n.strip(), "categoria": cat, "unidad": uni, "stock": s0, "minimo": mi, "costo": co})
                    log("insumo_creado", f"{n.strip()} · stock {s0:g} {uni}")
                    st.rerun()
                except Exception:
                    st.error("Ya existe un insumo con ese nombre.")
    if insumos:
        with st.expander("✏️ Editar / eliminar insumo"):
            i = st.selectbox("Insumo a editar", insumos, format_func=lambda x: x["nombre"], key="ei")
            with st.form(f"ei{i['id']}"):
                n = st.text_input("Nombre", i["nombre"])
                a0, a00 = st.columns(2)
                cats = CAT_INSUMOS if i["categoria"] in CAT_INSUMOS else CAT_INSUMOS + [i["categoria"]]
                unis = UNIDADES if i["unidad"] in UNIDADES else UNIDADES + [i["unidad"]]
                ca = a0.selectbox("Categoría", cats, index=cats.index(i["categoria"]))
                un = a00.selectbox("Unidad", unis, index=unis.index(i["unidad"]))
                a1, a2, a3 = st.columns(3)
                mi = a1.number_input("Mínimo", 0.0, 1_000_000.0, float(i["minimo"]), 1.0)
                co = a2.number_input("Costo unit.", 0.0, 10_000_000.0, float(i["costo"]), 10.0)
                ac = a3.checkbox("Activo", i["activo"])
                st.caption("Cambiar la unidad no convierte el stock: para corregir cantidades usá un movimiento de Ajuste.")
                if st.form_submit_button("Guardar", type="primary"):
                    try:
                        actualizar(T_INS, i["id"], {"nombre": n.strip(), "categoria": ca, "unidad": un, "minimo": mi,
                                                    "costo": co, "activo": ac})
                        log("insumo_editado", n.strip())
                        st.rerun()
                    except Exception:
                        st.error("Ya existe un insumo con ese nombre.")
            confirmar_eliminar(f"ins{i['id']}", f"Se elimina «{i['nombre']}», se quita de las recetas y se borra su historial de "
                               f"movimientos. Si la base no lo permite, queda inactivo.",
                               lambda i=i: eliminar_insumo(i), "Eliminar insumo")
    st.markdown("#### Últimos movimientos")
    movs = listar(T_MOV, order="id", desc=True, limit=150)
    if movs:
        nom = {i["id"]: i["nombre"] for i in insumos}
        with st.expander("🗑️ Eliminar un movimiento del historial"):
            mv = st.selectbox("Movimiento", movs[:80], key="mv_sel", format_func=lambda m: (
                f"#{m['id']} · {hop_fmt_dt(m['ts'])} · {nom.get(m['insumo_id'], '?')} · {m['tipo']} {float(m['cantidad']):g}"))
            st.caption("Borra solo el renglón del historial: NO cambia el stock actual (para corregirlo usá un Ajuste).")
            confirmar_eliminar(f"mov{mv['id']}", "Se borra este renglón del historial de movimientos.",
                               lambda mv=mv: eliminar_movimiento(mv), "Eliminar movimiento")
        st.dataframe(pd.DataFrame([{"Fecha": hop_fmt_dt(m["ts"]), "Insumo": nom.get(m["insumo_id"], "?"), "Tipo": m["tipo"],
                                    "Cantidad": float(m["cantidad"]), "Stock result.": float(m["stock_resultante"]),
                                    "Usuario": m["usuario"], "Motivo": m["motivo"]} for m in movs]), hide_index=True, **STRETCH)


def admin_mesas():
    mesas = listar(T_MESAS, order="orden")
    if mesas:
        st.dataframe(pd.DataFrame([{"Mesa": m["nombre"], "Zona": m["zona"], "Capacidad": m["capacidad"],
                                    "Activa": "Sí" if m["activa"] else "No"} for m in mesas]), hide_index=True, **STRETCH)
    with st.form("nm"):
        c1, c2, c3 = st.columns(3)
        n = c1.text_input("Nombre (ej. Mesa 11)")
        z = c2.text_input("Zona", value="Salón")
        cap = c3.number_input("Capacidad", 1, 40, 4)
        if st.form_submit_button("Agregar mesa", type="primary") and n.strip():
            try:
                insertar(T_MESAS, {"nombre": n.strip(), "zona": z.strip() or "Salón", "capacidad": int(cap),
                                   "orden": (max([m["orden"] for m in mesas]) + 1) if mesas else 1})
                log("mesa_creada", n.strip())
                st.rerun()
            except Exception:
                st.error("Ya existe una mesa con ese nombre.")
    if mesas:
        m = st.selectbox("Editar / activar / desactivar", mesas, format_func=lambda x: f"{x['nombre']} ({'activa' if x['activa'] else 'inactiva'})")
        with st.form(f"em{m['id']}"):
            c1, c2, c3 = st.columns(3)
            nn = c1.text_input("Nombre", m["nombre"])
            zz = c2.text_input("Zona", m["zona"])
            cp = c3.number_input("Capacidad", 1, 40, int(m["capacidad"]))
            if st.form_submit_button("Guardar mesa") and nn.strip():
                try:
                    actualizar(T_MESAS, m["id"], {"nombre": nn.strip(), "zona": zz.strip() or "Salón", "capacidad": int(cp)})
                    log("mesa_editada", f"{m['nombre']} → {nn.strip()} · {zz.strip()} · cap. {cp}")
                    st.rerun()
                except Exception:
                    st.error("Ya existe una mesa con ese nombre.")
        if st.button("Desactivar mesa" if m["activa"] else "Activar mesa"):
            abierta = [c for c in listar(T_COM, estado="abierta") if c.get("mesa_id") == m["id"]]
            if m["activa"] and abierta:
                st.error(f"No se puede desactivar: {m['nombre']} tiene una cuenta abierta (#{abierta[0]['id']}). "
                         f"Cobrala, anulala o pasala a otra mesa desde Admin → Operaciones.")
            else:
                actualizar(T_MESAS, m["id"], {"activa": not m["activa"]})
                log("mesa_estado", f"{m['nombre']} → {'inactiva' if m['activa'] else 'activa'}")
                st.rerun()
        confirmar_eliminar(f"mesa{m['id']}", f"Se elimina «{m['nombre']}». Las cuentas pasadas conservan el nombre de la mesa. "
                           f"No se puede si tiene una cuenta abierta.", lambda m=m: eliminar_mesa(m), "Eliminar mesa")


def _img_qr_b64(up):
    img = Image.open(up).convert("RGB")
    img.thumbnail((900, 900))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def eliminar_qr_cuenta(c):
    cfg_set("qr_cuentas", json.dumps([x for x in qr_cuentas() if x["id"] != c["id"]]))
    cfg_set("qr_activos", json.dumps([i for i in qr_activos_ids() if i != c["id"]]))
    tb(T_CFG).delete().eq("clave", f"qrimg_{c['id']}").execute()
    CFG.pop(f"qrimg_{c['id']}", None)
    log("qr_eliminado", c["nombre"])
    return True, f"QR «{c['nombre']}» eliminado."


def _nom_qr(cuentas, i):
    return next((c["nombre"] for c in cuentas if c["id"] == i), "")


def admin_qr_cuentas():
    cuentas = qr_cuentas()
    activos = [i for i in qr_activos_ids() if any(c["id"] == i for c in cuentas)]
    provs = [s_ for s_, _, _ in PROVEEDORES]
    st.markdown("#### 📱 QR por billetera virtual")
    st.caption("Cargá **todos los QR que quieran** en cada billetera (Mercado Pago, MODO, Ualá, etc.), por ejemplo uno distinto por fin de semana. "
               "Después elegí cuáles se muestran en Cobro: el mozo solo ve los habilitados.")

    # ── 1) Elegir qué QR se muestran, ordenados por billetera ──
    con_qr = [p_ for p_ in provs if any(c.get("proveedor") == p_ for c in cuentas)]
    con_qr += [p_ for p_ in {c.get("proveedor") for c in cuentas} if p_ not in provs]
    if cuentas:
        st.markdown("##### ✅ ¿Qué QR se muestran?")
        with st.form("qr_hoy_form"):
            elegidos = []
            for pv in con_qr:
                del_pv = [c for c in cuentas if c.get("proveedor") == pv]
                st.markdown(chip(pv) if pv in PROV_NOMBRE else f"**{pv}**", unsafe_allow_html=True)
                elegidos += st.multiselect(f"{PROV_NOMBRE.get(pv, pv)} · {len(del_pv)} QR cargado(s)", [c["id"] for c in del_pv],
                                           default=[i for i in activos if any(c["id"] == i for c in del_pv)],
                                           format_func=lambda i: _nom_qr(cuentas, i), key=f"qr_hoy_{pv}_{'-'.join(c['id'] for c in del_pv)}",
                                           placeholder="Ninguno habilitado")
            guardar = st.form_submit_button("💾 Guardar QR habilitados", type="primary")
        if guardar:
            cfg_set("qr_activos", json.dumps(elegidos))
            cfg_set("qr_activos_fecha", datetime.now(TZ).strftime("%Y-%m-%d"))
            log("qr_jornada", ", ".join(_nom_qr(cuentas, i) for i in elegidos) or "ninguno")
            st.toast("QR habilitados guardados ✅")
            st.rerun()
        f = CFG.get("qr_activos_fecha")
        st.caption(f"Última selección: {f[8:]}/{f[5:7]}" if f else "Todavía no elegiste qué QR mostrar.")
        if not activos:
            st.warning("Ahora no hay ningún QR habilitado: el cobro por QR queda bloqueado hasta que elijas uno.")

    # ── 2) Agregar QR (uno o varios de una vez) ──
    with st.expander("➕ Agregar QR a una billetera", expanded=not cuentas):
        with st.form("qr_nuevo", clear_on_submit=True):
            c1, c2 = st.columns(2)
            prov = c1.selectbox("Billetera / banco", provs, format_func=lambda x: PROV_NOMBRE[x])
            nom = c2.text_input("Nombre del QR", placeholder="Ej. Fin de semana 7-8 nov · Juan")
            ups = st.file_uploader("Imagen(es) del QR de cobro: podés subir varias juntas", type=["png", "jpg", "jpeg"],
                                   accept_multiple_files=True)
            c3, c4 = st.columns(2)
            tit = c3.text_input("Titular de la cuenta (opcional)")
            ali = c4.text_input("Alias / CVU (opcional)")
            dato = st.text_input("Link o dato para generar el QR (solo si no subís imagen)")
            if st.form_submit_button("Agregar", type="primary"):
                if not nom.strip():
                    st.error("Poné un nombre para identificar el QR.")
                elif not ups and not dato.strip() and not ali.strip():
                    st.error("Subí la imagen del QR o cargá un link/alias.")
                else:
                    for k, up in enumerate(ups or [None], 1):
                        nid = pysecrets.token_hex(3)
                        nombre = nom.strip() if len(ups or []) <= 1 else f"{nom.strip()} {k}"
                        cuentas.append({"id": nid, "nombre": nombre, "proveedor": prov, "titular": tit.strip(),
                                        "alias": ali.strip(), "dato": dato.strip()})
                        if up:
                            cfg_set(f"qrimg_{nid}", _img_qr_b64(up))
                        log("qr_creado", f"{PROV_NOMBRE[prov]} · {nombre}")
                    cfg_set("qr_cuentas", json.dumps(cuentas))
                    st.rerun()

    # ── 3) Editar / eliminar, agrupado por billetera ──
    for pv in con_qr:
        del_pv = [c for c in cuentas if c.get("proveedor") == pv]
        with st.expander(f"{PROV_NOMBRE.get(pv, pv)} · {len(del_pv)} QR"):
            for c in del_pv:
                marca = "🟢 " if c["id"] in activos else "⚪ "
                with st.expander(f"{marca}{c['nombre']}"):
                    if CFG.get(f"qrimg_{c['id']}"):
                        st.image(base64.b64decode(CFG[f"qrimg_{c['id']}"]), width=170)
                    with st.form(f"qr_ed_{c['id']}"):
                        c1, c2 = st.columns(2)
                        nom = c1.text_input("Nombre del QR", c["nombre"])
                        prov = c2.selectbox("Billetera / banco", provs, index=provs.index(c["proveedor"]) if c.get("proveedor") in provs else 0,
                                            format_func=lambda x: PROV_NOMBRE[x])
                        c3, c4 = st.columns(2)
                        tit = c3.text_input("Titular", c.get("titular") or "")
                        ali = c4.text_input("Alias / CVU", c.get("alias") or "")
                        dato = st.text_input("Link o dato para generar el QR", c.get("dato") or "")
                        up = st.file_uploader("Reemplazar imagen del QR", type=["png", "jpg", "jpeg"], key=f"qr_up_{c['id']}")
                        quitar = st.checkbox("Quitar la imagen actual", key=f"qr_q_{c['id']}")
                        if st.form_submit_button("💾 Guardar cambios", type="primary") and nom.strip():
                            c.update({"nombre": nom.strip(), "proveedor": prov, "titular": tit.strip(), "alias": ali.strip(), "dato": dato.strip()})
                            if up:
                                cfg_set(f"qrimg_{c['id']}", _img_qr_b64(up))
                            elif quitar:
                                cfg_set(f"qrimg_{c['id']}", "")
                            cfg_set("qr_cuentas", json.dumps(cuentas))
                            log("qr_editado", nom.strip())
                            st.rerun()
                    confirmar_eliminar(f"qr{c['id']}", f"Se elimina el QR «{c['nombre']}» y su imagen.",
                                       lambda c=c: eliminar_qr_cuenta(c), "Eliminar QR")
    st.divider()


def admin_pagos():
    if not es_dueno():
        st.warning("Esta sección es solo para dueños.")
        return
    admin_qr_cuentas()
    st.markdown("#### Datos de cobro del local")
    with st.form("datos_pago"):
        c1, c2 = st.columns(2)
        alias = c1.text_input("Alias", CFG.get("negocio_alias", ""))
        cvu = c2.text_input("CBU / CVU", CFG.get("negocio_cvu", ""))
        c3, c4 = st.columns(2)
        tit = c3.text_input("Titular", CFG.get("negocio_titular", ""))
        cuit = c4.text_input("CUIT", CFG.get("negocio_cuit", ""))
        hab = st.multiselect("Medios habilitados para QR", [s for s, _, _ in PROVEEDORES],
                             default=json.loads(CFG.get("pay_habilitados") or "[]"), format_func=lambda s: PROV_NOMBRE[s])
        if st.form_submit_button("Guardar", type="primary"):
            for k, v in (("negocio_alias", alias), ("negocio_cvu", cvu), ("negocio_titular", tit),
                         ("negocio_cuit", cuit), ("pay_habilitados", json.dumps(hab))):
                cfg_set(k, v)
            log("pagos_config", "Datos de cobro actualizados")
            st.rerun()
    with st.expander("QR por medio (modo anterior: se usa solo si no cargaste cuentas QR arriba)"):
        st.markdown("#### QR propio por medio")
        st.caption("Para que las apps de bancos y billeteras lo lean directo, subí el QR de cobro que te da cada app "
                   "(Mercado Pago, MODO, Ualá, etc.). Si no subís nada, se genera un QR con el link/alias que cargues.")
        for slug in json.loads(CFG.get("pay_habilitados") or "[]"):
            with st.expander(PROV_NOMBRE[slug]):
                st.markdown(chip(slug), unsafe_allow_html=True)
                dato = st.text_input("Link, alias o CVU para el QR", CFG.get(f"pay_{slug}_dato", ""), key=f"pd_{slug}")
                up = st.file_uploader("Subir QR del comercio (imagen)", type=["png", "jpg", "jpeg"], key=f"pu_{slug}")
                c1, c2 = st.columns(2)
                if c1.button("Guardar", key=f"ps_{slug}"):
                    cfg_set(f"pay_{slug}_dato", dato.strip())
                    if up:
                        buf = io.BytesIO()
                        Image.open(up).convert("RGB").save(buf, "PNG")
                        cfg_set(f"pay_{slug}_qr", base64.b64encode(buf.getvalue()).decode())
                    log("pagos_qr", PROV_NOMBRE[slug])
                    st.rerun()
                if CFG.get(f"pay_{slug}_qr"):
                    st.image(base64.b64decode(CFG[f"pay_{slug}_qr"]), width=160)
                    if c2.button("Quitar QR subido", key=f"pq_{slug}"):
                        cfg_set(f"pay_{slug}_qr", "")
                        st.rerun()
    st.info("El link de Mercado Pago con monto exacto (`[mercadopago] access_token` en Secrets) se usa solo en el modo anterior; "
            "con cuentas QR cargadas se muestra el QR de la cuenta elegida.")


def admin_usuarios():
    users = listar(T_USU, order="id")
    st.dataframe(pd.DataFrame([{"Usuario": u["usuario"], "Nombre": u["nombre"], "Rol": ROLES[u["rol"]],
                                "Activo": "Sí" if u["activo"] else "No"} for u in users]), hide_index=True, **STRETCH)
    st.caption(f"Dueños: {sum(u['rol'] == 'dueno' and u['activo'] for u in users)} · "
               f"Encargados: {sum(u['rol'] == 'encargado' and u['activo'] for u in users)}")
    with st.form("nu"):
        c1, c2 = st.columns(2)
        usr = c1.text_input("Usuario")
        nom = c2.text_input("Nombre y apellido")
        c3, c4 = st.columns(2)
        rol = c3.selectbox("Rol", list(ROLES), format_func=lambda r: ROLES[r])
        pw = c4.text_input("Contraseña inicial (mín. 8)", type="password")
        if st.form_submit_button("Crear usuario", type="primary"):
            usr = usr.strip().lower().replace(" ", "")
            if not usr or not nom.strip() or len(pw) < 8:
                st.error("Completá todo (contraseña de 8+ caracteres).")
            else:
                try:
                    s, h = hash_pw(pw)
                    insertar(T_USU, {"usuario": usr, "nombre": nom.strip(), "rol": rol, "salt": s, "pass_hash": h})
                    log("usuario_creado", f"{usr} ({rol})")
                    st.rerun()
                except Exception:
                    st.error("Ese usuario ya existe.")
    mapa_u = {x["id"]: x for x in users}
    uid = st.selectbox("Gestionar usuario", list(mapa_u), key="us_sel",
                       format_func=lambda i: f"{mapa_u[i]['usuario']} — {mapa_u[i]['nombre']}")
    u = mapa_u[uid]
    yo = usuario_actual()
    mismo = u["id"] == yo["id"]
    st.markdown("**✏️ Editar usuario**")
    with st.form(f"eu{uid}"):
        c1, c2 = st.columns(2)
        nu = c1.text_input("Usuario (para iniciar sesión)", u["usuario"])
        nn = c2.text_input("Nombre y apellido", u["nombre"])
        c3, c4 = st.columns(2)
        roles = list(ROLES)
        nr = c3.selectbox("Rol", roles, index=roles.index(u["rol"]), format_func=ROLES.get, disabled=mismo)
        na = c4.checkbox("Activo", u["activo"], disabled=mismo)
        if mismo:
            st.caption("Tu propio rol y estado no se pueden cambiar desde acá, pero sí tu usuario y nombre.")
        if st.form_submit_button("💾 Guardar cambios", type="primary"):
            nu = nu.strip().lower().replace(" ", "")
            quedan = [x for x in users if x["id"] != uid and x["rol"] == "dueno" and x["activo"]]
            if not nu or not nn.strip():
                st.error("Completá usuario y nombre.")
            elif u["rol"] == "dueno" and u["activo"] and (nr != "dueno" or not na) and not quedan:
                st.error("Tiene que quedar al menos un dueño activo.")
            else:
                try:
                    actualizar(T_USU, uid, {"usuario": nu, "nombre": nn.strip(), "rol": nr, "activo": na})
                    log("usuario_editado", f"{u['usuario']} → {nu} · {nn.strip()} · {nr}{'' if na else ' · inactivo'}")
                    if mismo:
                        st.session_state["hs_user"].update({"usuario": nu, "nombre": nn.strip()})
                    st.rerun()
                except Exception:
                    st.error("Ya existe otro usuario con ese nombre de acceso.")
    npw = st.text_input("Nueva contraseña (mín. 8)", type="password", key="rpw")
    if st.button("🔑 Cambiar contraseña") and len(npw) >= 8:
        s_, h_ = hash_pw(npw)
        actualizar(T_USU, uid, {"salt": s_, "pass_hash": h_})
        log("password_cambiada", u["usuario"])
        st.success("Contraseña actualizada.")
    if mismo:
        st.caption("No podés eliminarte a vos mismo.")
    else:
        confirmar_eliminar(f"usr{uid}", f"Se elimina el usuario «{u['usuario']}». Lo que cargó antes sigue figurando en la "
                           f"auditoría con su nombre de acceso.", lambda: eliminar_usuario(u, users), "Eliminar usuario")


def admin_auditoria():
    st.caption("Todo lo que se carga o modifica queda registrado con usuario y hora. "
               "Tocá un renglón que tenga **Comanda** (o elegila abajo) para ver su ticket completo.")
    rows = listar(T_LOG, order="id", desc=True, limit=600)
    if not rows:
        st.info("Sin registros.")
    else:
        def _cid(r):
            m = re.search(r"(?:comanda\s+#?|#)(\d+)", str(r.get("detalle") or ""))
            return int(m.group(1)) if m else None

        df = pd.DataFrame([{"Fecha": hop_fmt_dt(r["ts"]), "Usuario": r["usuario"], "Acción": r["accion"],
                            "Comanda": _cid(r), "Detalle": r["detalle"]} for r in rows])
        df["Comanda"] = df["Comanda"].astype("Int64")
        f = st.multiselect("Filtrar por usuario", sorted(df["Usuario"].unique()))
        if f:
            df = df[df["Usuario"].isin(f)]
        elegida = None
        if _V >= (1, 35):
            ev = st.dataframe(df, hide_index=True, on_select="rerun", selection_mode="single-row", key="aud_tbl", **STRETCH)
            filas = list(ev.selection.rows) if ev is not None and ev.selection is not None else []
            if filas and not pd.isna(df.iloc[filas[0]]["Comanda"]):
                elegida = int(df.iloc[filas[0]]["Comanda"])
        else:
            st.dataframe(df, hide_index=True, **STRETCH)
        ids = sorted({int(x) for x in df["Comanda"].dropna()}, reverse=True)
        manual = st.selectbox("Ver ticket de la comanda", [None] + ids, key="aud_cid",
                              format_func=lambda x: "— elegir —" if x is None else f"Comanda #{x}")
        cid = elegida or manual
        if cid:
            st.markdown(f"#### 🧾 Comanda #{cid}")
            ticket_de_cuenta(cid, f"au{cid}")
    if es_dueno():
        with st.expander("🧹 Depurar registros viejos (solo dueños)"):
            lim = st.date_input("Eliminar los registros anteriores al", value=date.today() - timedelta(days=90), key="aud_lim")
            confirmar_eliminar("aud", f"Se borran TODOS los registros de auditoría anteriores al {lim:%d/%m/%Y}. No se puede deshacer.",
                               lambda: depurar_auditoria(lim), "Depurar auditoría")
        with st.expander("🔥 Resetear TODA la auditoría (arrancar desde cero, solo dueños)"):
            st.caption("Borra absolutamente todos los registros. Queda un único renglón que avisa del reseteo.")
            ctxt = st.text_input("Para confirmar escribí RESETEAR", key="aud_rs_txt")
            confirmar_eliminar("aud_all", "Se borra TODO el historial de auditoría. No se puede deshacer.",
                               lambda: resetear_auditoria(ctxt), "Resetear toda la auditoría")


def admin_apariencia():
    with st.form("ap"):
        nom = st.text_input("Nombre en ticket", CFG.get("negocio_nombre", "HOPSIE · Cerveza Artesanal"))
        pie = st.text_input("Pie del ticket", CFG.get("ticket_pie", "¡Gracias por visitarnos! 🍻"))
        prop = st.number_input("Propina sugerida por defecto (%)", 0.0, 30.0, cfg_num("propina_default", 0), 1.0)
        jc = st.number_input("La jornada de trabajo empieza a las (hora, 0-12)", 0, 12, int(cfg_num("jornada_corte", 6)), 1,
                             help="Una noche que pasa de medianoche cuenta como una sola jornada en el Dashboard.")
        wa_auto = st.checkbox("Enviar el ticket por WhatsApp automáticamente al cobrar (si el cliente tiene teléfono)",
                              value=CFG.get("wa_auto", "1") == "1")
        st.caption("✅ WhatsApp automático configurado." if wa_config() else
                   "ℹ️ WhatsApp automático necesita `[whatsapp]` en los Secrets (ver instrucciones al inicio del archivo). "
                   "Mientras tanto el ticket se comparte con el botón de cada cuenta.")
        up = st.file_uploader("Logo de HOPSIE (png/jpg)", type=["png", "jpg", "jpeg", "webp"])
        if st.form_submit_button("Guardar", type="primary"):
            cfg_set("negocio_nombre", nom)
            cfg_set("ticket_pie", pie)
            cfg_set("propina_default", str(prop))
            cfg_set("wa_auto", "1" if wa_auto else "0")
            cfg_set("jornada_corte", str(int(jc)))
            if up:
                img = Image.open(up).convert("RGBA")
                img.thumbnail((700, 700))
                buf = io.BytesIO()
                img.save(buf, "PNG")
                cfg_set("logo_b64", base64.b64encode(buf.getvalue()).decode())
            log("apariencia", "Configuración general actualizada")
            st.rerun()
    if CFG.get("logo_b64") and st.button("Quitar logo subido"):
        cfg_set("logo_b64", "")
        st.rerun()


def admin_operaciones():
    st.caption("Corregí cualquier operación del sistema: cuentas abiertas, cobradas o canceladas. "
               "Todo cambio queda registrado en Auditoría con usuario y hora.")
    if es_dueno():
        _panel_reset_operaciones()
    f1, f2, f3 = st.columns([2, 2, 3])
    est = f1.selectbox("Estado", ["Todas", "Abiertas", "Cobradas", "Canceladas"], key="op_est")
    per = f2.selectbox("Período", ["Hoy", "Ayer", "Últimos 7 días", "Últimos 30 días", "Todo"], index=2, key="op_per")
    busca = f3.text_input("Buscar", placeholder="🔎 cuenta, cliente, mozo o #", key="op_q").strip().lower()

    q = tb(T_COM).select("*")
    if est != "Todas":
        q = q.eq("estado", {"Abiertas": "abierta", "Cobradas": "pagada", "Canceladas": "cancelada"}[est])
    if est != "Abiertas":  # las abiertas se muestran siempre, sin importar la fecha
        dias = {"Hoy": 0, "Ayer": 1, "Últimos 7 días": 6, "Últimos 30 días": 29}.get(per)
        if dias is not None:
            q = q.gte("abierta_ts", iso(inicio_dia_utc(dias)))
        if per == "Ayer":
            q = q.lt("abierta_ts", iso(inicio_dia_utc(0)))
    coms = q.order("id", desc=True).limit(300).execute().data or []
    if est == "Todas":
        vistos = {c["id"] for c in coms}
        coms += [c for c in listar(T_COM, estado="abierta") if c["id"] not in vistos]
        coms.sort(key=lambda c: c["id"], reverse=True)

    mesas_map, cli_map = mapa_mesas(), mapa_clientes()
    ids_ab = [c["id"] for c in coms if c["estado"] == "abierta"]
    por_com = defaultdict(list)
    for it in items_de(ids_ab):
        por_com[it["comanda_id"]].append(it)

    def total_de(c):
        return totales(c, por_com[c["id"]])["total"] if c["estado"] == "abierta" else float(c.get("total") or 0)

    ESTADO = {"abierta": "🟢 Abierta", "pagada": "✅ Cobrada", "cancelada": "❌ Cancelada"}
    filas = []
    for c in coms:
        nombre = etiqueta_cuenta(c, mesas_map, cli_map)
        cli = cli_map.get(c.get("cliente_id"))
        if busca and busca not in f"{c['id']} {nombre} {(cli or {}).get('nombre', '')} {c.get('mozo') or ''}".lower():
            continue
        filas.append({"#": c["id"], "Cuenta": nombre, "Cliente": cli["nombre"] if cli else "",
                      "Estado": ESTADO.get(c["estado"], c["estado"]), "Abierta": hop_fmt_dt(c["abierta_ts"]),
                      "Cerrada": hop_fmt_dt(c.get("cerrada_ts")), "Mozo": c.get("mozo") or "",
                      "Total": peso(total_de(c)), "Medios": c.get("metodo_pago") or ""})
    if not filas:
        st.info("No hay operaciones con esos filtros.")
        return
    st.dataframe(pd.DataFrame(filas), hide_index=True, **STRETCH)

    desc = {f["#"]: f"#{f['#']} · {f['Cuenta']} · {f['Estado']} · {f['Abierta']} · {f['Total']}" for f in filas}
    cid = st.selectbox("Operación a corregir", list(desc), format_func=desc.get, key="op_sel")
    com = uno(T_COM, cid)
    if not com:
        return
    items_act = items_de([cid])
    tot = totales(com, items_act)
    pagos = listar(T_PAGOS, comanda_id=cid, order="id")
    pagado = round(sum(float(p["monto"]) for p in pagos))
    st.markdown(f"#### {etiqueta_cuenta(com, mesas_map, cli_map)} · #{cid}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Estado", ESTADO.get(com["estado"], com["estado"]))
    m2.metric("Total de la cuenta", peso(tot["total"]))
    m3.metric("Cobrado", peso(pagado))
    m4.metric("Diferencia", peso(tot["total"] - pagado))
    if com["estado"] == "pagada" and tot["total"] != pagado:
        st.warning("Lo cobrado no coincide con el total de la cuenta. Ajustá los cobros en la pestaña **Pagos**.")

    t_tkt, t_datos, t_cons, t_pagos, t_estado = st.tabs(["🧾 Ticket", "📝 Datos", "🍺 Consumo", "💵 Pagos", "🔁 Estado"])

    with t_tkt:
        ticket_de_cuenta(cid, f"op{cid}")

    with t_datos:
        form_datos_cuenta(com, f"op{cid}", importes=True)

    with t_cons:
        todos = listar(T_ITEMS, comanda_id=cid, order="id")
        tocar = com["estado"] != "cancelada"
        if not todos:
            st.caption("Esta cuenta no tiene consumos.")
        for it in todos:
            sub = float(it["precio_unit"]) * it["cantidad"]
            with st.expander(f"{'🚫 ' if it['anulado'] else ''}{'📝 ' if not it.get('confirmado', True) else ''}"
                             f"{it['cantidad']}× {it['nombre']} · {peso(sub)}"):
                with st.form(f"opi{it['id']}"):
                    a, b, c = st.columns([3, 1, 2])
                    nn = a.text_input("Descripción", it["nombre"])
                    nq = b.number_input("Cantidad", 1, 999, int(it["cantidad"]))
                    npz = c.number_input("Precio unitario", 0.0, 10_000_000.0, float(it["precio_unit"]), 100.0)
                    nt = st.text_input("Nota", it.get("nota") or "")
                    if st.form_submit_button("Guardar ítem"):
                        if hop_editar_item(it, nq, npz, nt.strip(), nn, tocar_stock=tocar and not it["anulado"]):
                            recalcular_comanda(cid)
                        st.rerun()
                if it["anulado"]:
                    if st.button("↩️ Restaurar ítem", key=f"ors{it['id']}"):
                        set_anulado(it, False, com["estado"])
                        recalcular_comanda(cid)
                        st.rerun()
                elif st.button("🚫 Anular ítem", key=f"oan{it['id']}"):
                    set_anulado(it, True, com["estado"])
                    recalcular_comanda(cid)
                    st.rerun()
                confirmar_eliminar(f"it{it['id']}", "Se borra el renglón de la comanda para siempre (el stock vuelve al depósito si correspondía).",
                                   lambda it=it: eliminar_item_def(it, com["estado"]), "Eliminar ítem")
        prods = listar(T_PROD, order="nombre", activo=True)
        if prods:
            st.markdown("**Agregar producto a esta cuenta**")
            with st.form(f"opadd{cid}"):
                a, b = st.columns([4, 1])
                p = a.selectbox("Producto", prods, format_func=lambda x: f"{x['nombre']} · {peso(x['precio'])}")
                n = b.number_input("Cant.", 1, 99, 1)
                if st.form_submit_button("Agregar"):
                    insertar(T_ITEMS, {"comanda_id": cid, "producto_id": p["id"], "nombre": p["nombre"],
                                       "sector": p["sector"], "precio_unit": float(p["precio"]), "cantidad": int(n),
                                       "estado": "pendiente" if com["estado"] == "abierta" else "servido",
                                       "cargado_por": actor(), "confirmado": True})
                    if tocar:
                        aplicar_receta(p["id"], int(n), cid, f"Corrección comanda #{cid}")
                    log("item_agregado", f"comanda {cid} · {n}× {p['nombre']} (desde Operaciones)")
                    recalcular_comanda(cid)
                    st.rerun()

    with t_pagos:
        if not pagos:
            st.caption("Esta cuenta no tiene cobros registrados.")
        for p in pagos:
            with st.expander(f"{p['metodo']}{' · ' + p['proveedor'] if p.get('proveedor') else ''} · "
                             f"{peso(p['monto'])} · {hop_fmt_dt(p['ts'])}"):
                with st.form(f"opp{p['id']}"):
                    a, b, c = st.columns([2, 2, 2])
                    met = a.selectbox("Medio", METODOS, index=METODOS.index(p["metodo"]) if p["metodo"] in METODOS else 0)
                    prov = b.text_input("Proveedor (Mercado Pago, banco…)", p.get("proveedor") or "")
                    mon = c.number_input("Monto", 0.0, 100_000_000.0, float(p["monto"]), 100.0)
                    ref = st.text_input("Referencia / cupón", p.get("referencia") or "")
                    if st.form_submit_button("Guardar cobro"):
                        actualizar(T_PAGOS, p["id"], {"metodo": met, "proveedor": prov.strip() or None,
                                                      "monto": mon, "referencia": ref.strip()})
                        log("pago_editado", f"comanda {cid} · {p['metodo']} {peso(p['monto'])} → {met} {peso(mon)}")
                        recalcular_comanda(cid)
                        st.rerun()
                if st.button("🗑️ Eliminar cobro", key=f"opd{p['id']}"):
                    borrar(T_PAGOS, p["id"])
                    log("pago_eliminado", f"comanda {cid} · {p['metodo']} {peso(p['monto'])}")
                    recalcular_comanda(cid)
                    st.rerun()
        st.markdown("**Registrar un cobro**")
        with st.form(f"opnp{cid}"):
            a, b, c = st.columns(3)
            met = a.selectbox("Medio", METODOS)
            prov = b.text_input("Proveedor (opcional)")
            mon = c.number_input("Monto", 0.0, 100_000_000.0, float(max(0, tot["total"] - pagado)), 100.0)
            ref = st.text_input("Referencia (opcional)")
            if st.form_submit_button("Agregar cobro") and mon > 0:
                insertar(T_PAGOS, {"comanda_id": cid, "metodo": met, "proveedor": prov.strip() or None,
                                   "monto": mon, "usuario": actor(), "referencia": ref.strip()})
                log("pago_agregado", f"comanda {cid} · {met} {peso(mon)} (desde Operaciones)")
                recalcular_comanda(cid)
                st.rerun()

    with t_estado:
        st.markdown(f"Estado actual: **{ESTADO.get(com['estado'], com['estado'])}**")
        if com["estado"] == "abierta":
            if tot["total"] > 0 and pagado >= tot["total"]:
                if st.button("✅ Cerrar como cobrada", type="primary", key=f"ocl{cid}"):
                    cerrar_comanda(com, tot, pagos)
                    st.rerun()
            else:
                st.caption("Para cerrarla como cobrada, el total cobrado tiene que cubrir la cuenta (pestaña Pagos).")
            motivo = st.text_input("Motivo de la anulación", key=f"omo{cid}")
            ok = st.checkbox("Confirmo que se anula toda la cuenta (el stock se devuelve)", key=f"ook{cid}")
            if st.button("❌ Anular cuenta", disabled=not (ok and motivo.strip()), key=f"oan_c{cid}"):
                anular_comanda(com, motivo.strip())
                st.rerun()
        else:
            st.caption("Reabrir deja la cuenta de nuevo en el salón para seguir cargando consumos. "
                       "Los cobros registrados se mantienen: corregilos en la pestaña Pagos si hace falta.")
            if st.button("↩️ Reabrir cuenta", type="primary", key=f"ore{cid}"):
                tipo, mid = com.get("tipo") or "mesa", com.get("mesa_id")
                choque = [c for c in listar(T_COM, estado="abierta") if c["id"] != cid and (
                    (mid and c.get("mesa_id") == mid) or
                    (tipo == "cliente" and com.get("cliente_id") and c.get("cliente_id") == com["cliente_id"]
                     and (c.get("tipo") == "cliente"))) ]
                if choque:
                    st.error(f"No se puede reabrir: ya hay una cuenta abierta en el mismo lugar (#{choque[0]['id']}). "
                             f"Cerrala o cambiale la mesa primero.")
                else:
                    if com["estado"] == "cancelada":
                        for it in items_de([cid]):
                            aplicar_receta(it.get("producto_id"), it["cantidad"], cid, f"Reapertura comanda #{cid}")
                    actualizar(T_COM, cid, {"estado": "abierta", "cerrada_ts": None, "total": 0, "metodo_pago": ""})
                    log("comanda_reabierta", f"comanda {cid} (estaba {com['estado']})")
                    st.session_state["cid"] = cid
                    st.toast("Cuenta reabierta ✅")
                    st.rerun()
        _zona_eliminar_comanda(com)


def _zona_eliminar_comanda(com):
    cid = com["id"]
    st.divider()
    st.markdown("##### 🗑️ Eliminar esta comanda")
    dev = False
    if com["estado"] != "cancelada":
        dev = st.checkbox("Devolver al stock los insumos de esta comanda", value=(com["estado"] == "abierta"), key=f"edv{cid}")
    confirmar_eliminar(f"com{cid}", f"Se elimina la comanda #{cid} con todos sus consumos y cobros. No se puede deshacer.",
                       lambda: eliminar_comanda(com, dev), "Eliminar comanda")


def cuentas_con_cliente():
    out, ini = [], 0
    while True:
        r = (tb(T_COM).select("id,cliente_id,total,estado,abierta_ts,cerrada_ts").gt("cliente_id", 0)
             .order("id").range(ini, ini + 999).execute().data or [])
        out += r
        if len(r) < 1000:
            return out
        ini += 1000


def admin_clientes():
    st.caption("Base de clientes. Se completa sola cuando asignás mesa o abrís una cuenta, y desde acá la ordenás. "
               "Los **habitué (VIP)** reciben cuenta personal al llegar y su descuento automático.")
    clis = listar(T_CLI, order="nombre")
    stats = defaultdict(lambda: {"visitas": 0, "gasto": 0.0, "ultima": None})
    for c in cuentas_con_cliente():
        s = stats[c["cliente_id"]]
        if c["estado"] != "cancelada":
            s["visitas"] += 1
        if c["estado"] == "pagada":
            s["gasto"] += float(c["total"] or 0)
        if not s["ultima"] or c["abierta_ts"] > s["ultima"]:
            s["ultima"] = c["abierta_ts"]

    a, b, c_ = st.columns(3)
    a.metric("Clientes registrados", len(clis))
    b.metric("Habitués VIP", sum(1 for c in clis if c["vip"] and c["activo"]))
    c_.metric("Consumo histórico", peso(sum(s["gasto"] for s in stats.values())))

    f1, f2 = st.columns([4, 1.4])
    busca = f1.text_input("Buscar", placeholder="🔎 nombre, apodo o teléfono", key="cl_q").strip().lower()
    solo_vip = f2.checkbox("Solo VIP", key="cl_vip")
    filas = []
    for c in clis:
        if solo_vip and not c["vip"]:
            continue
        if busca and busca not in f"{c['nombre']} {c.get('apodo') or ''} {c.get('telefono') or ''}".lower():
            continue
        s = stats[c["id"]]
        filas.append({"Cliente": c["nombre"], "Apodo": c.get("apodo") or "", "Teléfono": c.get("telefono") or "",
                      "VIP": "⭐" if c["vip"] else "", "Dto %": float(c.get("descuento_pct") or 0),
                      "Visitas": s["visitas"], "Consumo total": peso(s["gasto"]),
                      "Última visita": hop_fmt_dt(s["ultima"]), "Notas": c.get("notas") or "",
                      "Estado": "" if c["activo"] else "inactivo"})
    if filas:
        st.dataframe(pd.DataFrame(filas), hide_index=True, **STRETCH)
    else:
        st.info("Todavía no hay clientes con esos filtros.")

    with st.expander("➕ Nuevo cliente"):
        with st.form("cl_nuevo"):
            c1, c2, c3 = st.columns([3, 2, 2])
            n = c1.text_input("Nombre y apellido")
            ap = c2.text_input("Apodo")
            tel = c3.text_input("Teléfono")
            c4, c5 = st.columns([1, 1])
            vip = c4.checkbox("Habitué VIP")
            dto = c5.number_input("Descuento automático %", 0.0, 100.0, 0.0, 5.0)
            nt = st.text_area("Notas (gustos, alergias, preferencias…)")
            if st.form_submit_button("Guardar cliente", type="primary"):
                if not n.strip():
                    st.error("Falta el nombre.")
                else:
                    insertar(T_CLI, {"nombre": n.strip(), "apodo": ap.strip(), "telefono": tel.strip(), "vip": vip,
                                     "descuento_pct": dto, "notas": nt.strip(), "alta_por": actor()})
                    log("cliente_creado", f"{n.strip()}{' · VIP' if vip else ''}")
                    st.rerun()

    if clis:
        mapa = {c["id"]: c for c in clis}
        sel = st.selectbox("Cliente a editar / ver historial", list(mapa), format_func=lambda i: fmt_cliente(mapa[i]), key="cl_sel")
        c = mapa[sel]
        with st.form(f"cl_ed{sel}"):
            c1, c2, c3 = st.columns([3, 2, 2])
            n = c1.text_input("Nombre y apellido", c["nombre"])
            ap = c2.text_input("Apodo", c.get("apodo") or "")
            tel = c3.text_input("Teléfono", c.get("telefono") or "")
            c4, c5, c6 = st.columns(3)
            vip = c4.checkbox("Habitué VIP", c["vip"])
            dto = c5.number_input("Descuento automático %", 0.0, 100.0, float(c.get("descuento_pct") or 0), 5.0)
            act = c6.checkbox("Activo", c["activo"])
            nt = st.text_area("Notas", c.get("notas") or "")
            if st.form_submit_button("Guardar cambios", type="primary") and n.strip():
                actualizar(T_CLI, sel, {"nombre": n.strip(), "apodo": ap.strip(), "telefono": tel.strip(), "vip": vip,
                                        "descuento_pct": dto, "activo": act, "notas": nt.strip()})
                log("cliente_editado", f"{n.strip()}{' · VIP' if vip else ''}{'' if act else ' · inactivo'}")
                st.rerun()
        confirmar_eliminar(f"cli{sel}", f"Se elimina a «{c['nombre']}» de la base de clientes. Sus cuentas pasadas quedan en el "
                           f"historial sin ficha ni teléfono. No se puede si tiene una cuenta abierta.",
                           lambda c=c: eliminar_cliente(c), "Eliminar cliente")
        hist = listar(T_COM, cliente_id=sel, order="id", desc=True, limit=60)
        st.markdown("**Historial de visitas**")
        if hist:
            mm, cm = mapa_mesas(), mapa_clientes()
            st.dataframe(pd.DataFrame([{"Fecha": hop_fmt_dt(h["abierta_ts"]), "Cuenta": etiqueta_cuenta(h, mm, cm),
                                        "Estado": h["estado"], "Total": peso(h.get("total") or 0),
                                        "Medios": h.get("metodo_pago") or ""} for h in hist]),
                         hide_index=True, **STRETCH)
        else:
            st.caption("Todavía no tiene visitas registradas.")


def pagina_admin():
    try:
        hay_usuarios = bool(listar(T_USU, limit=1))
    except Exception:
        hay_usuarios = False
    if not hay_usuarios:
        setup_primer_dueno()
        return
    u = usuario_actual()
    if not u:
        login_ui()
        return
    st.caption(f"Sesión: **{u['nombre']}** ({ROLES[u['rol']]})")
    secciones = [("📊 Dashboard", admin_dashboard), ("🧾 Operaciones", admin_operaciones), ("⭐ Clientes", admin_clientes),
                 ("🍺 Productos", admin_productos), ("📦 Stock", admin_stock),
                 ("🪑 Mesas", admin_mesas), ("🕵️ Auditoría", admin_auditoria)]
    if es_dueno():
        secciones += [("💸 Pagos", admin_pagos), ("👥 Usuarios", admin_usuarios), ("🎨 Apariencia", admin_apariencia)]
    for tab, (_, fn) in zip(st.tabs([n for n, _ in secciones]), secciones):
        with tab:
            fn()


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def header():
    lg = logo_uri()
    img = f'<img src="{lg}" alt="HOPSIE">' if lg else ""
    st.markdown(f'<div class="hop-head">{img}<div><div class="hop-title">HOPSIE</div>'
                f'<div class="hop-sub">CERVEZA ARTESANAL</div></div></div>', unsafe_allow_html=True)


def main_hopsie():
    st.markdown(HOP_CSS, unsafe_allow_html=True)
    if hop_get_supabase() is None:
        st.error("⚠️ No se pudo conectar a Supabase. Cargá los Secrets `[hopsie_supabase]` (url y key).")
        return
    try:  # también verifica que existan las tablas y que la key sea la correcta
        CFG.clear()
        CFG.update(cfg_load())
    except Exception as e:
        st.error("No encuentro las tablas de HOPSIE. Ejecutá **hopsie_schema.sql** en Supabase "
                 "y revisá que la key sea la *service_role*.")
        st.code(str(e))
        return
    header()
    if not st.session_state.get("hs_schema_ok"):
        try:
            tb(T_CLI).select("id").limit(1).execute()
            tb(T_COM).select("id,tipo,cliente_id,etiqueta").limit(1).execute()
            tb(T_ITEMS).select("id,confirmado,confirmado_ts").limit(1).execute()
            st.session_state["hs_schema_ok"] = True
        except Exception as e:
            st.error("Falta actualizar la base de datos: ejecutá **hopsie_migracion_clientes.sql** y **hopsie_migracion_v3.sql** "
                     "en el SQL Editor de Supabase y recargá la página.")
            st.code(str(e))
            return
    if st.session_state.get("nav") not in NAV:  # sesión abierta antes de separar Cocina y Barra
        st.session_state.pop("nav", None)
    if "_goto" in st.session_state:
        st.session_state["nav"] = st.session_state.pop("_goto")
    elif "nav" not in st.session_state:
        st.session_state["nav"] = P_SALON
    c1, c2 = st.columns([5, 1.3])
    pagina = st.session_state["nav"]
    with c1:
        with st.container(key="navbar"):
            for col, pg in zip(st.columns(len(NAV)), NAV):
                if col.button(pg, key=f"nav_{NAV.index(pg)}", type="primary" if pagina == pg else "secondary", **STRETCH):
                    st.session_state["nav"] = pg
                    st.rerun()
    with c2:
        u = usuario_actual()
        if u:
            st.caption(f"👤 {u['nombre']}")
            if st.button("Salir", key="logout"):
                log("logout", "")
                st.session_state.pop("hs_user", None)
                st.rerun()
    st.divider()
    {P_SALON: pagina_salon, P_COMANDA: pagina_comanda, P_COBRO: pagina_cobro,
     P_COCINA: pagina_cocina, P_BARRA: pagina_barra, P_ADMIN: pagina_admin}[pagina]()


# ══════════════════════════════════════════
# NAVEGACIÓN PRINCIPAL: Pañol | HOPSIE
# Solo se ejecuta el módulo activo (su estilo y sus consultas), el otro queda en reposo.
# ══════════════════════════════════════════
st.markdown(f"<style>{MODULE_BAR_CSS}</style>", unsafe_allow_html=True)
with st.container(key="modbar"):
    _mc = st.columns([1, 1, 3])
for _col, _mod, _k in zip(_mc, MODULOS, ("panol", "hopsie")):
    if _col.button(_mod, key=f"nav_mod_{_k}", type="primary" if st.session_state["app_modulo"] == _mod else "secondary", **STRETCH):
        st.session_state["app_modulo"] = _mod
        st.rerun()
_hopsie_activo = st.session_state["app_modulo"] == MOD_HOPSIE
st.query_params["modulo"] = "hopsie" if _hopsie_activo else "panol"  # el enlace y F5 conservan el módulo

if _hopsie_activo:
    main_hopsie()
else:
    main_panol()
