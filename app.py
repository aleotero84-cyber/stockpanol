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
  2) HOPSIE → ejecutar hopsie_schema.sql en el SQL Editor de Supabase (crea las tablas hopsie_*).
  3) Secrets de Streamlit Cloud:

        [supabase]                        # Pañol (anon public)
        url = "https://TU-PROYECTO.supabase.co"
        key = "TU_ANON_KEY"

        [hopsie_supabase]                 # HOPSIE (service_role: sus tablas tienen RLS y no son públicas)
        url = "https://TU-PROYECTO.supabase.co"
        key = "TU_SERVICE_ROLE_KEY"

        [mercadopago]                     # opcional: QR dinámico con el monto exacto
        access_token = "APP_USR-..."

        [admin]                           # opcional: contraseña de rescate del administrador de Pañol
        password = "..."

  4) Logo de HOPSIE: hopsie_logo.png junto a este archivo
     (o subirlo desde HOPSIE → Admin → Apariencia).
  5) Logos de bancos/billeteras (opcional): carpeta logos/ con mercadopago.png, uala.png, naranjax.png,
     cuentadni.png, modo.png, bna.png, galicia.png, santander.png, bbva.png, macro.png, brubank.png,
     lemon.png (png/jpg/webp/svg). Si falta alguno se muestra una etiqueta de color.

requirements.txt:  streamlit  supabase  pillow  pandas  requests  qrcode[pil]
"""

import base64
import hashlib
import hmac
import io
import json
import math
import os
import secrets as pysecrets
import time
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from html import escape as esc
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
from PIL import Image
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
.block-container { padding-top: 2rem !important; padding-bottom: 4rem !important; max-width: 1180px; }

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

/* Barra de módulos (Pañol / HOPSIE): se ve como una fila de pestañas */
.st-key-app_modulo { border-bottom: 1px solid var(--border, #DCE0E8); margin-bottom: 16px; }
.st-key-app_modulo div[role="radiogroup"] { gap: 6px; }
.st-key-app_modulo label[data-baseweb="radio"] { padding: 10px 18px; margin: 0; border-bottom: 2px solid transparent; border-radius: 0; cursor: pointer; }
.st-key-app_modulo label[data-baseweb="radio"] > div:first-child { display: none; }
.st-key-app_modulo label[data-baseweb="radio"] p { color: var(--muted, #647085) !important; font-weight: 600; font-size: 15px; }
.st-key-app_modulo label[data-baseweb="radio"]:has(input:checked) { border-bottom-color: var(--accent, #1F5FBF); }
.st-key-app_modulo label[data-baseweb="radio"]:has(input:checked) p { color: var(--accent, #1F5FBF) !important; }
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

P_SALON, P_COMANDA, P_COBRO = "🍽️ Salón", "🧾 Comanda", "💳 Cobro"
P_COCINA, P_ADMIN = "👨‍🍳 Cocina / Barra", "⚙️ Admin"
NAV = [P_SALON, P_COMANDA, P_COBRO, P_COCINA, P_ADMIN]

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
.block-container{position:relative;z-index:1;max-width:1250px;margin-top:.8rem;padding:1.4rem 2rem 2.5rem;
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
          .eq("anulado", False).eq("estado", "pendiente").eq("nota", "").limit(1).execute().data)
    if ex:
        actualizar(T_ITEMS, ex[0]["id"], {"cantidad": ex[0]["cantidad"] + 1})
    else:
        insertar(T_ITEMS, {"comanda_id": com["id"], "producto_id": prod["id"], "nombre": prod["nombre"],
                           "sector": prod["sector"], "precio_unit": float(prod["precio"]), "cantidad": 1,
                           "cargado_por": actor()})
    avisos = aplicar_receta(prod["id"], 1, com["id"], f"Comanda #{com['id']}")
    log("item_agregado", f"comanda {com['id']} · {prod['nombre']}")
    for a in avisos:
        st.toast(f"⚠️ Stock negativo: {a}")


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
        aplicar_receta(it["producto_id"], -it["cantidad"], com["id"], f"Comanda anulada #{com['id']}")
    actualizar(T_COM, com["id"], {"estado": "cancelada", "cerrada_ts": iso(ahora_utc()), "nota": motivo})
    log("comanda_anulada", f"comanda {com['id']} · {motivo}")


def cerrar_comanda(com, tot, pagos):
    mets = ", ".join(sorted({p["metodo"] for p in pagos}))
    actualizar(T_COM, com["id"], {"estado": "pagada", "cerrada_ts": iso(ahora_utc()),
                                  "total": tot["total"], "metodo_pago": mets})
    log("comanda_cerrada", f"comanda {com['id']} · {peso(tot['total'])} · {mets}")


# ─────────────────────────────────────────
# TICKET / PRE-CUENTA
# ─────────────────────────────────────────
def ticket_html(com, mesa, items, tot):
    act = [i for i in items if not i.get("anulado")]
    filas = "".join(
        f"<tr><td>{i['cantidad']}×</td><td>{esc(i['nombre'])}</td>"
        f"<td style='text-align:right'>{peso(float(i['precio_unit']) * i['cantidad'])}</td></tr>" for i in act)
    extra = ""
    if tot["desc"]:
        extra += f"<tr><td colspan=2>Descuento {com['descuento_pct']:g}%</td><td style='text-align:right'>-{peso(tot['desc'])}</td></tr>"
    if tot["prop"]:
        extra += f"<tr><td colspan=2>Propina {com['propina_pct']:g}%</td><td style='text-align:right'>{peso(tot['prop'])}</td></tr>"
    lg = logo_uri()
    img = f'<div style="text-align:center"><img src="{lg}" style="max-height:60px"></div>' if lg else ""
    nombre = esc(CFG.get("negocio_nombre") or "HOPSIE · Cerveza Artesanal")
    pie = esc(CFG.get("ticket_pie") or "¡Gracias por visitarnos! 🍻")
    return (f'<div class="paper">{img}<div style="text-align:center;font-weight:bold">{nombre}</div>'
            f'<div style="text-align:center">PRE-CUENTA · {esc(mesa["nombre"])}<br>{hop_fmt_dt(com["abierta_ts"])}</div><hr>'
            f"<table>{filas}<tr><td colspan=3><hr></td></tr>"
            f"<tr><td colspan=2>Subtotal</td><td style='text-align:right'>{peso(tot['sub'])}</td></tr>{extra}"
            f"<tr><td colspan=2><b>TOTAL</b></td><td style='text-align:right'><b>{peso(tot['total'])}</b></td></tr>"
            f'</table><hr><div style="text-align:center">{pie}</div></div>')


def ticket_txt(com, mesa, items, tot):
    act = [i for i in items if not i.get("anulado")]
    L = [CFG.get("negocio_nombre") or "HOPSIE · Cerveza Artesanal",
         f"PRE-CUENTA · {mesa['nombre']} · {hop_fmt_dt(com['abierta_ts'])}", "-" * 34]
    L += [f"{i['cantidad']}x {i['nombre']:<20} {peso(float(i['precio_unit']) * i['cantidad']):>10}" for i in act]
    L += ["-" * 34, f"Subtotal {peso(tot['sub'])}"]
    if tot["desc"]:
        L.append(f"Descuento -{peso(tot['desc'])}")
    if tot["prop"]:
        L.append(f"Propina {peso(tot['prop'])}")
    L += [f"TOTAL {peso(tot['total'])}", "", CFG.get("ticket_pie") or "¡Gracias por visitarnos!"]
    return "\n".join(L)


# ─────────────────────────────────────────
# PÁGINA: SALÓN
# ─────────────────────────────────────────
def pagina_salon():
    mesas = listar(T_MESAS, order="orden", activa=True)
    if not mesas:
        st.info("Todavía no hay mesas. Cargalas en **Admin → Mesas** (o usá los datos de ejemplo en Admin → Dashboard).")
        return
    abiertas = {c["mesa_id"]: c for c in listar(T_COM, estado="abierta")}
    por_com = defaultdict(list)
    for it in items_de([c["id"] for c in abiertas.values()]):
        por_com[it["comanda_id"]].append(it)

    en_mesas = sum(totales(c, por_com[c["id"]])["total"] for c in abiertas.values())
    a, b, c_ = st.columns(3)
    a.metric("Mesas ocupadas", f"{len(abiertas)} / {len(mesas)}")
    b.metric("Mesas libres", len(mesas) - len(abiertas))
    c_.metric("Consumo en curso", peso(en_mesas))

    zonas = []
    for m in mesas:
        if m["zona"] not in zonas:
            zonas.append(m["zona"])
    for zona in zonas:
        st.markdown(f"### {zona}")
        lista = [m for m in mesas if m["zona"] == zona]
        cols = st.columns(4)
        for idx, m in enumerate(lista):
            com = abiertas.get(m["id"])
            with cols[idx % 4]:
                if com:
                    tot = totales(com, por_com[com["id"]])
                    mins = int((ahora_utc() - parse_ts(com["abierta_ts"])).total_seconds() // 60)
                    st.markdown(
                        f'<div class="mesa ocupada"><div class="mn">{esc(m["nombre"])}</div>'
                        f'<div class="mt">{peso(tot["total"])}</div>'
                        f'<div class="ms">👥 {com["comensales"]} · ⏱ {mins}′ · {esc(com.get("mozo") or "—")}</div></div>',
                        unsafe_allow_html=True)
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

    mp = st.session_state.get("mesa_pend")
    if mp and mp not in abiertas:
        mesa = next((m for m in mesas if m["id"] == mp), None)
        if mesa:
            st.markdown(f"#### Abrir {mesa['nombre']}")
            u = usuario_actual()
            with st.form("abrir_mesa"):
                c1, c2 = st.columns(2)
                n = c1.number_input("Comensales", 1, 60, 2)
                mozo = c2.text_input("Adicionista / mozo", value=(u["nombre"] if u else ""))
                if st.form_submit_button("Abrir y tomar pedido", type="primary"):
                    r = insertar(T_COM, {"mesa_id": mp, "comensales": int(n), "mozo": mozo.strip(),
                                         "propina_pct": cfg_num("propina_default", 0), "abierta_por": actor()})[0]
                    log("mesa_abierta", f"{mesa['nombre']} · comanda {r['id']}")
                    st.session_state["cid"] = r["id"]
                    st.session_state.pop("mesa_pend", None)
                    go(P_COMANDA)


# ─────────────────────────────────────────
# PÁGINA: COMANDA
# ─────────────────────────────────────────
def comanda_actual():
    cid = st.session_state.get("cid")
    com = uno(T_COM, cid) if cid else None
    if not com or com["estado"] != "abierta":
        return None, None
    return com, uno(T_MESAS, com["mesa_id"])


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
        st.info("Elegí una mesa en **Salón** para tomar el pedido.")
        if st.button("Ir al salón"):
            go(P_SALON)
        return
    cid = com["id"]
    st.markdown(f"### 🧾 {mesa['nombre']}")
    st.caption(f"Abierta {hop_fmt_dt(com['abierta_ts'])} · 👥 {com['comensales']} · Adicionista: {com.get('mozo') or '—'} · Comanda #{cid}")

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
        st.markdown("#### Consumo")
        if not activos:
            st.caption("Todavía no se cargó nada.")
        for it in activos:
            c1, c2, c3, c4, c5 = st.columns([6, 1.2, 1.2, 1.2, 1.2])
            nota = f" · 📝 {esc(it['nota'])}" if it["nota"] else ""
            c1.markdown(
                f"{ICONO_ESTADO.get(it['estado'], '')} **{it['cantidad']}× {esc(it['nombre'])}**<br>"
                f"<small>{peso(float(it['precio_unit']) * it['cantidad'])}{nota}</small>", unsafe_allow_html=True)
            if c2.button("➖", key=f"mn{it['id']}"):
                sumar_cantidad(it, -1)
                st.rerun()
            if c3.button("➕", key=f"mas{it['id']}"):
                sumar_cantidad(it, 1)
                st.rerun()
            with c4.popover("📝"):
                nv = st.text_input("Nota para cocina/barra", value=it["nota"], key=f"nt{it['id']}")
                if st.button("Guardar nota", key=f"gn{it['id']}"):
                    actualizar(T_ITEMS, it["id"], {"nota": nv.strip()})
                    st.rerun()
            if c5.button("🗑️", key=f"del{it['id']}"):
                anular_item(it)
                st.rerun()

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
            f"<small>Subtotal {peso(tot['sub'])}"
            + (f" · Desc. -{peso(tot['desc'])}" if tot["desc"] else "")
            + (f" · Propina {peso(tot['prop'])}" if tot["prop"] else "")
            + f"</small><div class='totalbox'>{peso(tot['total'])}</div>", unsafe_allow_html=True)
        if com["comensales"] > 1 and tot["total"]:
            st.caption(f"≈ {peso(math.ceil(tot['total'] / com['comensales']))} por persona ({com['comensales']} comensales)")

        b1, b2 = st.columns(2)
        if b1.button("💳 Cobrar", type="primary", disabled=not activos, **STRETCH):
            go(P_COBRO)
        if b2.button("⬅ Salón", **STRETCH):
            go(P_SALON)

        with st.expander("🧾 Pre-cuenta"):
            st.markdown(ticket_html(com, mesa, activos, tot), unsafe_allow_html=True)
            st.download_button("⬇ Descargar .txt", ticket_txt(com, mesa, activos, tot),
                               file_name=f"precuenta_{mesa['nombre'].replace(' ', '_')}.txt")

        with st.expander("🔀 Cambiar de mesa"):
            ocupadas = {c["mesa_id"] for c in listar(T_COM, estado="abierta")}
            libres = [m for m in listar(T_MESAS, order="orden", activa=True) if m["id"] not in ocupadas]
            if libres:
                dest = st.selectbox("Pasar a", libres, format_func=lambda m: f"{m['nombre']} ({m['zona']})", key=f"cm{cid}")
                if st.button("Mover", key=f"mv{cid}"):
                    actualizar(T_COM, cid, {"mesa_id": dest["id"]})
                    log("mesa_cambiada", f"comanda {cid}: {mesa['nombre']} → {dest['nombre']}")
                    st.rerun()
            else:
                st.caption("No hay mesas libres.")

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


def bloque_qr(com, mesa, monto):
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
        st.caption(" · ".join(f"{p['metodo']}{' (' + p['proveedor'] + ')' if p['proveedor'] else ''} {peso(p['monto'])}" for p in pagos))

    if not items:
        st.warning("La comanda no tiene consumos. Anulala desde la comanda.")
        return
    if saldo <= 0:
        cerrar_comanda(com, tot, pagos)
        st.session_state.pop("cid", None)
        st.toast("Mesa cerrada ✅")
        go(P_SALON)

    n = st.number_input("Dividir entre (personas)", 1, 60, int(com["comensales"]), key=f"div{cid}")
    if n > 1:
        st.caption(f"Cada uno: {peso(math.ceil(saldo / n))}")
    monto = st.number_input("Monto a cobrar ahora", 1, int(saldo), int(saldo), 100,
                            key=f"monto_{cid}_{len(pagos)}")
    metodo = st.radio("Medio", ["💵 Efectivo", "📱 QR / Transferencia", "💳 Tarjeta (posnet)"],
                      horizontal=True, key=f"met_{cid}")
    proveedor, ref = None, ""
    if metodo.startswith("💵"):
        rec = st.number_input("Entrega el cliente", int(monto), int(monto) * 10 + 100000, int(monto), 500, key=f"rec{cid}")
        if rec > monto:
            st.success(f"Vuelto: {peso(rec - monto)}")
    elif metodo.startswith("📱"):
        proveedor = bloque_qr(com, mesa, monto)
    else:
        ref = st.text_input("N° de cupón / últimos 4 (opcional)", key=f"cup{cid}")

    nombre_metodo = {"💵": "Efectivo", "📱": "QR / Transferencia", "💳": "Tarjeta"}[metodo[:1]]
    label = "✅ Recibí el pago" if metodo.startswith("📱") else "✅ Registrar cobro"
    if st.button(label, type="primary", **STRETCH):
        insertar(T_PAGOS, {"comanda_id": cid, "metodo": nombre_metodo, "proveedor": proveedor,
                           "monto": float(monto), "usuario": actor(), "referencia": ref})
        log("pago", f"comanda {cid} · {nombre_metodo} {proveedor or ''} · {peso(monto)}")
        nuevos = listar(T_PAGOS, comanda_id=cid)
        if tot["total"] - round(sum(float(p["monto"]) for p in nuevos)) <= 0:
            cerrar_comanda(com, tot, nuevos)
            st.session_state.pop("cid", None)
            st.toast("Mesa cerrada ✅")
            go(P_SALON)
        st.rerun()
    if st.button("⬅ Volver a la comanda"):
        go(P_COMANDA)


# ─────────────────────────────────────────
# PÁGINA: COCINA / BARRA
# ─────────────────────────────────────────
@autorefresh(15)
def _cocina_body():
    abiertas = {c["id"]: c for c in listar(T_COM, estado="abierta")}
    if not abiertas:
        st.info("Sin comandas abiertas.")
        return
    mesas = {m["id"]: m for m in listar(T_MESAS)}
    its = [i for i in items_de(list(abiertas)) if i["estado"] in ("pendiente", "preparando")]
    cols = st.columns(2)
    for col, sec in zip(cols, ["Cocina", "Barra"]):
        with col:
            st.markdown(f"### {'👨‍🍳' if sec == 'Cocina' else '🍺'} {sec}")
            lista = sorted([i for i in its if i["sector"] == sec], key=lambda i: i["ts"])
            if not lista:
                st.caption("Todo al día 🎉")
            for it in lista:
                mesa = mesas.get(abiertas[it["comanda_id"]]["mesa_id"], {"nombre": "?"})
                mins = int((ahora_utc() - parse_ts(it["ts"])).total_seconds() // 60)
                nota = f"<br>📝 {esc(it['nota'])}" if it["nota"] else ""
                st.markdown(
                    f"<div class='kds {it['estado']}'><b>{esc(mesa['nombre'])}</b> · {it['cantidad']}× {esc(it['nombre'])}"
                    f" <small>({mins}′)</small>{nota}</div>", unsafe_allow_html=True)
                b1, b2 = st.columns(2)
                if it["estado"] == "pendiente" and b1.button("🔥 Preparar", key=f"pr{it['id']}"):
                    actualizar(T_ITEMS, it["id"], {"estado": "preparando"})
                    st.rerun()
                if b2.button("✅ Listo", key=f"ok{it['id']}"):
                    actualizar(T_ITEMS, it["id"], {"estado": "servido"})
                    st.rerun()


def pagina_cocina():
    st.markdown("### 👨‍🍳 Cocina / Barra")
    st.caption("Se actualiza solo cada 15 segundos.")
    _cocina_body()


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


def admin_dashboard():
    hoy = iso(inicio_dia_utc())
    pagadas = tb(T_COM).select("*").eq("estado", "pagada").gte("cerrada_ts", hoy).execute().data or []
    ventas = sum(float(c["total"]) for c in pagadas)
    a, b, c, d = st.columns(4)
    a.metric("Ventas de hoy", peso(ventas))
    b.metric("Mesas cobradas", len(pagadas))
    c.metric("Ticket promedio", peso(ventas / len(pagadas)) if pagadas else "—")
    d.metric("Mesas abiertas", len(listar(T_COM, estado="abierta")))

    rows = (tb(T_COM).select("total,cerrada_ts").eq("estado", "pagada")
            .gte("cerrada_ts", iso(inicio_dia_utc(6))).execute().data or [])
    if rows:
        df = pd.DataFrame(rows)
        df["dia"] = pd.to_datetime(df["cerrada_ts"], utc=True).dt.tz_convert(TZ).dt.date
        g = df.groupby("dia")["total"].sum()
        g.index = [x.strftime("%d/%m") for x in g.index]
        st.markdown("#### Ventas últimos 7 días")
        st.bar_chart(g)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Más vendidos hoy")
        its = tb(T_ITEMS).select("nombre,cantidad,precio_unit").eq("anulado", False).gte("ts", hoy).execute().data or []
        if its:
            df = pd.DataFrame(its)
            df["importe"] = df["cantidad"] * df["precio_unit"].astype(float)
            top = df.groupby("nombre").agg(unidades=("cantidad", "sum"), importe=("importe", "sum")).sort_values("unidades", ascending=False)
            st.dataframe(top.head(10), **STRETCH)
        else:
            st.caption("Sin ventas todavía.")
    with c2:
        st.markdown("#### Cobros de hoy por medio")
        pg = tb(T_PAGOS).select("metodo,proveedor,monto").gte("ts", hoy).execute().data or []
        if pg:
            df = pd.DataFrame(pg)
            df["medio"] = df.apply(lambda r: f"{r['metodo']}" + (f" · {r['proveedor']}" if r["proveedor"] else ""), axis=1)
            df["monto"] = df["monto"].astype(float)
            st.dataframe(df.groupby("medio")["monto"].sum().sort_values(ascending=False), **STRETCH)
        else:
            st.caption("Sin cobros todavía.")

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
            st.markdown(f"**Receta** (insumos que consume 1 unidad) — costo {peso(costo)}{marg}")
            for r in rec:
                i = imap.get(r["insumo_id"])
                x1, x2 = st.columns([6, 1])
                x1.caption(f"{i['nombre'] if i else '?'} — {float(r['cantidad']):g} {i['unidad'] if i else ''}")
                if x2.button("🗑️", key=f"dr{r['id']}"):
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
        with st.expander("✏️ Editar insumo"):
            i = st.selectbox("Insumo a editar", insumos, format_func=lambda x: x["nombre"], key="ei")
            with st.form(f"ei{i['id']}"):
                n = st.text_input("Nombre", i["nombre"])
                a1, a2, a3 = st.columns(3)
                mi = a1.number_input("Mínimo", 0.0, 1_000_000.0, float(i["minimo"]), 1.0)
                co = a2.number_input("Costo unit.", 0.0, 10_000_000.0, float(i["costo"]), 10.0)
                ac = a3.checkbox("Activo", i["activo"])
                if st.form_submit_button("Guardar"):
                    actualizar(T_INS, i["id"], {"nombre": n.strip(), "minimo": mi, "costo": co, "activo": ac})
                    log("insumo_editado", n.strip())
                    st.rerun()
    st.markdown("#### Últimos movimientos")
    movs = listar(T_MOV, order="id", desc=True, limit=150)
    if movs:
        nom = {i["id"]: i["nombre"] for i in insumos}
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
        m = st.selectbox("Activar / desactivar", mesas, format_func=lambda x: f"{x['nombre']} ({'activa' if x['activa'] else 'inactiva'})")
        if st.button("Cambiar estado"):
            actualizar(T_MESAS, m["id"], {"activa": not m["activa"]})
            log("mesa_estado", f"{m['nombre']} → {'inactiva' if m['activa'] else 'activa'}")
            st.rerun()


def admin_pagos():
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
    st.info("Mercado Pago con monto exacto: cargá `[mercadopago] access_token` en los Secrets.")


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
    u = st.selectbox("Gestionar usuario", users, format_func=lambda x: f"{x['usuario']} — {x['nombre']}")
    c1, c2 = st.columns(2)
    with c1:
        npw = st.text_input("Nueva contraseña (mín. 8)", type="password", key="rpw")
        if st.button("Cambiar contraseña") and len(npw) >= 8:
            s, h = hash_pw(npw)
            actualizar(T_USU, u["id"], {"salt": s, "pass_hash": h})
            log("password_cambiada", u["usuario"])
            st.success("Contraseña actualizada.")
    with c2:
        mismo = u["id"] == usuario_actual()["id"]
        if st.button("Desactivar" if u["activo"] else "Activar", disabled=mismo):
            actualizar(T_USU, u["id"], {"activo": not u["activo"]})
            log("usuario_estado", f"{u['usuario']} → {'inactivo' if u['activo'] else 'activo'}")
            st.rerun()
        if mismo:
            st.caption("No podés desactivarte a vos mismo.")


def admin_auditoria():
    st.caption("Todo lo que se carga o modifica queda registrado con usuario y hora.")
    rows = listar(T_LOG, order="id", desc=True, limit=600)
    if not rows:
        st.info("Sin registros.")
        return
    df = pd.DataFrame([{"Fecha": hop_fmt_dt(r["ts"]), "Usuario": r["usuario"], "Acción": r["accion"], "Detalle": r["detalle"]} for r in rows])
    f = st.multiselect("Filtrar por usuario", sorted(df["Usuario"].unique()))
    if f:
        df = df[df["Usuario"].isin(f)]
    st.dataframe(df, hide_index=True, **STRETCH)


def admin_apariencia():
    with st.form("ap"):
        nom = st.text_input("Nombre en ticket", CFG.get("negocio_nombre", "HOPSIE · Cerveza Artesanal"))
        pie = st.text_input("Pie del ticket", CFG.get("ticket_pie", "¡Gracias por visitarnos! 🍻"))
        prop = st.number_input("Propina sugerida por defecto (%)", 0.0, 30.0, cfg_num("propina_default", 0), 1.0)
        up = st.file_uploader("Logo de HOPSIE (png/jpg)", type=["png", "jpg", "jpeg", "webp"])
        if st.form_submit_button("Guardar", type="primary"):
            cfg_set("negocio_nombre", nom)
            cfg_set("ticket_pie", pie)
            cfg_set("propina_default", str(prop))
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
    secciones = [("📊 Dashboard", admin_dashboard), ("🍺 Productos", admin_productos), ("📦 Stock", admin_stock),
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
    if "_goto" in st.session_state:
        st.session_state["nav"] = st.session_state.pop("_goto")
    elif "nav" not in st.session_state:
        st.session_state["nav"] = P_SALON
    c1, c2 = st.columns([5, 1.3])
    with c1:
        pagina = st.radio("Navegación", NAV, horizontal=True, key="nav", label_visibility="collapsed")
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
     P_COCINA: pagina_cocina, P_ADMIN: pagina_admin}[pagina]()


# ══════════════════════════════════════════
# NAVEGACIÓN PRINCIPAL: Pañol | HOPSIE
# Solo se ejecuta el módulo activo (su estilo y sus consultas), el otro queda en reposo.
# ══════════════════════════════════════════
st.radio("Módulo", MODULOS, horizontal=True, key="app_modulo", label_visibility="collapsed")
_hopsie_activo = st.session_state["app_modulo"] == MOD_HOPSIE
st.query_params["modulo"] = "hopsie" if _hopsie_activo else "panol"  # el enlace y F5 conservan el módulo

if _hopsie_activo:
    main_hopsie()
else:
    main_panol()
