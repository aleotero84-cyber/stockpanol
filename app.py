"""
Pañol — Control de stock
Streamlit + Supabase

Multi-almacén · subcategorías · unidades · columnas personalizadas por almacén
Apariencia editable por el administrador general (logo, colores, tipografía, tema)

Antes de desplegar esta versión ejecutá migracion_v2.sql en el SQL Editor de Supabase.
"""

import base64
import hashlib
import hmac
import io
import os
from datetime import date, datetime
from html import escape as esc

import streamlit as st
from PIL import Image
from supabase import create_client

# ─────────────────────────────────────────
# CONFIGURACIÓN DE PÁGINA
# ─────────────────────────────────────────
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

if supabase is None:
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
    st.stop()

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


def flash(tipo, texto):
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
        supabase.table("paniol_items").select("extras").limit(1).execute()
        supabase.table("paniol_columnas").select("id").limit(1).execute()
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
[data-testid="stHeader"] { background: transparent !important; }
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
[data-testid="stVerticalBlockBorderWrapper"] { background: var(--surface); border-color: var(--border) !important; border-radius: 12px !important; box-shadow: var(--shadow); }
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
.pn-kpis { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 20px; }
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


def invalidar_cache():
    get_items.clear()
    get_movimientos.clear()
    get_unidades.clear()
    get_columnas.clear()


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


def render_tabla(items, columnas, ocultos, filtro=""):
    if filtro:
        f = filtro.lower()

        def coincide(i):
            extras = i.get("extras") or {}
            partes = [i["nombre"], i.get("categoria"), i.get("subcategoria"), i.get("ubicacion"),
                      i.get("numero_patrimonio"), i.get("descripcion")]
            partes += [fmt_extra(c, extras.get(str(c["id"]))) for c in columnas]
            return any(f in (str(p) if p else "").lower() for p in partes)

        items = [i for i in items if coincide(i)]

    if not items:
        st.info("Sin resultados.")
        return

    if "subcategoria" in ocultos:
        items = sorted(items, key=lambda i: ((i.get("categoria") or "otro"), i["nombre"].lower()))

    unidades_por_item = {}
    for u in get_unidades():
        unidades_por_item.setdefault(u["id_item"], []).append(u)

    visible = lambda k: k not in ocultos

    # Encabezados, en el mismo orden en que se arman las filas
    headers = ["Nombre", "Categoría"]
    if visible("numero_patrimonio"): headers.append("N° patrimonio")
    headers.append("Cantidad")
    if visible("minimo"): headers.append("Mínimo")
    if visible("ubicacion"): headers.append("Ubicación")
    if visible("descripcion"): headers.append("Descripción")
    headers += [c["nombre"] for c in columnas]
    headers.append("Estado")

    # Agrupar por (categoría, subcategoría) respetando el orden recibido
    grupos = []
    for i in items:
        clave = (i.get("categoria") or "otro", "" if "subcategoria" in ocultos else (i.get("subcategoria") or ""))
        if not grupos or grupos[-1][0] != clave:
            grupos.append((clave, []))
        grupos[-1][1].append(i)

    filas = []
    for (categoria, subcategoria), items_grupo in grupos:
        etiqueta = categoria if not subcategoria else f"{categoria} · {subcategoria}"
        filas.append(f'<tr class="pn-group"><td colspan="{len(headers)}">{esc(etiqueta)}</td></tr>')

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

            nombre_celda = esc(i["nombre"])
            if unidades_por_item.get(i["id"]):
                nombre_celda += f" <span class='pn-muted'>· {len(unidades_por_item[i['id']])} unidades</span>"

            celdas = [f'<td><span class="pn-name">{nombre_celda}</span></td>',
                      f'<td><span class="pn-chip">{esc(i.get("categoria") or "—")}</span></td>']
            if visible("numero_patrimonio"):
                celdas.append(f'<td><span class="pn-muted">{esc(i.get("numero_patrimonio") or "—")}</span></td>')
            celdas.append(f'<td><span class="pn-num {num_cls}">{cant}</span></td>')
            if visible("minimo"):
                celdas.append(f'<td><span class="pn-muted">{mn}</span></td>')
            if visible("ubicacion"):
                celdas.append(f'<td><span class="pn-muted">{esc(i.get("ubicacion") or "—")}</span></td>')
            if visible("descripcion"):
                celdas.append(f'<td><span class="pn-muted">{esc(i.get("descripcion") or "—")}</span></td>')
            extras = i.get("extras") or {}
            for c in columnas:
                celdas.append(f'<td>{esc(fmt_extra(c, extras.get(str(c["id"]))))}</td>')
            celdas.append(f"<td>{est}</td>")
            filas.append("<tr>" + "".join(celdas) + "</tr>")

    thead = "".join(f"<th>{esc(h)}</th>" for h in headers)
    st.markdown(
        f'<div class="pn-table-wrap"><table class="pn-table"><thead><tr>{thead}</tr></thead>'
        f'<tbody>{"".join(filas)}</tbody></table></div>',
        unsafe_allow_html=True)

    items_con_unidades = [i for i in items if unidades_por_item.get(i["id"])]
    if items_con_unidades:
        st.markdown("<div class='pn-section'>Detalle de unidades por marca</div>", unsafe_allow_html=True)
        for i in items_con_unidades:
            unidades = sorted(unidades_por_item[i["id"]],
                              key=lambda u: (u.get("marca") or "", u.get("numero_patrimonio") or ""))
            with st.expander(f"{i['nombre']} — {len(unidades)} unidad(es)"):
                filas_u = "".join(
                    f'<tr><td><span class="pn-name">{esc(u.get("marca") or "—")}</span></td>'
                    f'<td><span class="pn-muted">{esc(u.get("numero_patrimonio") or "—")}</span></td></tr>'
                    for u in unidades)
                st.markdown(
                    '<div class="pn-table-wrap"><table class="pn-table">'
                    '<thead><tr><th>Marca</th><th>N° patrimonio</th></tr></thead>'
                    f'<tbody>{filas_u}</tbody></table></div>',
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
        extras_nuevos = formulario_extras(columnas, {}, "add")

        if st.button("Guardar ítem", type="primary", use_container_width=True):
            if not nombre.strip():
                st.error("El nombre es obligatorio.")
            else:
                agregar_item(ALMACEN_ID, {
                    "nombre": nombre.strip(), "categoria": categoria, "subcategoria": subcategoria,
                    "ubicacion": ubicacion.strip(), "numero_patrimonio": numero_patrimonio.strip(),
                    "cantidad": cantidad, "minimo": minimo, "descripcion": descripcion.strip(),
                    "extras": combinar_extras({}, extras_nuevos),
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
            extras_nuevos = formulario_extras(columnas, item.get("extras") or {}, f"edit_{item['id']}")

            if st.button("Guardar cambios", type="primary", use_container_width=True):
                if not nombre.strip():
                    st.error("El nombre es obligatorio.")
                else:
                    editar_item(item["id"], {
                        "nombre": nombre.strip(), "categoria": categoria, "subcategoria": subcategoria,
                        "ubicacion": ubicacion.strip(), "numero_patrimonio": numero_patrimonio.strip(),
                        "cantidad": cantidad, "minimo": minimo, "descripcion": descripcion.strip(),
                        "extras": combinar_extras(item.get("extras"), extras_nuevos),
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
        st.caption("Útil para ítems tipo equipo que agrupan varias unidades de distinta marca, cada una con su "
                   "propio número de patrimonio (ej: Osciloscopio digital → 3 Tektronix, 2 Rigol, 1 Hantek). "
                   "Es solo informativo y no afecta la cantidad de stock del ítem.")
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


# ══════════════════════════════════════════
# FLUJO PRINCIPAL
# ══════════════════════════════════════════
_db_cfg, _migrado = get_config_db()
cfg = get_cfg()
inyectar_css(cfg)

if not _migrado:
    st.error("⚠️ **Falta actualizar la base de datos.**")
    st.markdown("Ejecutá el archivo `migracion_v2.sql` en **Supabase → SQL Editor** y recargá la página. "
                "Crea la tabla de configuración y la de columnas personalizadas, y agrega las columnas "
                "nuevas de logo, configuración y datos adicionales.")
    st.stop()

if st.session_state.vista == "config":
    pantalla_config(cfg)
    st.stop()

if st.session_state.almacen_id is None:
    pantalla_seleccion_almacen(cfg)
    st.stop()

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

# ── Encabezado ───────────────────────────
st.markdown(
    f'<div class="pn-top">{brand_html(cfg)}{pill_almacen(ALM)}</div>'
    '<div class="pn-kpis">'
    f'<div class="pn-kpi"><div class="pn-kpi-num">{n_total}</div><div class="pn-kpi-lbl">Ítems</div></div>'
    f'<div class="pn-kpi {alerta_cls}"><div class="pn-kpi-num">{n_alertas}</div><div class="pn-kpi-lbl">Con alerta de stock</div></div>'
    f'<div class="pn-kpi ok"><div class="pn-kpi-num">{n_ok}</div><div class="pn-kpi-lbl">Con stock suficiente</div></div>'
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

    render_tabla(items_all, columnas, ocultos, filtro)

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
    movs = get_movimientos(ALMACEN_ID)
    if not movs:
        st.info("Todavía no hay movimientos registrados.")
    else:
        st.markdown(f"**{len(movs)}** movimientos registrados.")
        render_historial(movs)
