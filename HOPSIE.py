"""
HOPSIE · Cerveza Artesanal — Comanda de mesas + Stock + Admin
Streamlit + Supabase   (app independiente: no depende de app.py / Pañol)

Antes de desplegar:
  1) Ejecutá hopsie_schema.sql en el SQL Editor de Supabase (crea tablas hopsie_*).
  2) Secrets de Streamlit Cloud:

        [hopsie_supabase]
        url = "https://TU-PROYECTO.supabase.co"
        key = "TU_SERVICE_ROLE_KEY"      # service_role: las tablas tienen RLS y no son públicas

        [mercadopago]                     # opcional: QR dinámico con el monto exacto
        access_token = "APP_USR-..."

  3) Logo: poné el archivo como  hopsie_logo.png  junto a este .py
     (o subilo desde Admin → Apariencia).
  4) Logos de bancos/billeteras: carpeta  logos/  con nombres
     mercadopago.png, uala.png, naranjax.png, cuentadni.png, modo.png, bna.png,
     galicia.png, santander.png, bbva.png, macro.png, brubank.png, lemon.png
     (png/jpg/webp/svg). Si falta alguno se muestra una etiqueta de color.

requirements.txt:  streamlit  supabase  pillow  pandas  requests  qrcode[pil]
"""

import base64
import hashlib
import hmac
import io
import json
import math
import secrets as pysecrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape as esc
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import qrcode
import requests
import streamlit as st
from PIL import Image
from supabase import create_client

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
_ICON = "🍺"
if _LOGO_FILE and _LOGO_FILE.suffix.lower() != ".svg":
    try:
        _ICON = Image.open(_LOGO_FILE)
    except Exception:
        _ICON = "🍺"

st.set_page_config(page_title="HOPSIE · Cerveza Artesanal", page_icon=_ICON,
                   layout="wide", initial_sidebar_state="collapsed")

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
CSS = """
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
st.markdown(CSS, unsafe_allow_html=True)

# ─────────────────────────────────────────
# SUPABASE
# ─────────────────────────────────────────
@st.cache_resource
def get_supabase():
    for sec in ("hopsie_supabase", "supabase"):
        if sec in st.secrets:
            url = str(st.secrets[sec].get("url", "")).strip()
            key = str(st.secrets[sec].get("key", "")).strip()
            if url and key and "XXXX" not in url:
                return create_client(url, key)
    return None


supabase = get_supabase()
if supabase is None:
    st.error("⚠️ No se pudo conectar a Supabase. Cargá los Secrets `[hopsie_supabase]` (url y key).")
    st.stop()


def tb(t):
    return supabase.table(t)


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


try:
    tb(T_CFG).select("clave").limit(1).execute()
except Exception as e:  # tablas inexistentes o key incorrecta
    st.error("No encuentro las tablas de HOPSIE. Ejecutá **hopsie_schema.sql** en Supabase "
             "y revisá que la key sea la *service_role*.")
    st.code(str(e))
    st.stop()

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def ahora_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat()


def parse_ts(s):
    return pd.to_datetime(s, utc=True).to_pydatetime()


def fmt_dt(s):
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


CFG = cfg_load()


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


def agregar_unidad(com, prod):
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
            f'<div style="text-align:center">PRE-CUENTA · {esc(mesa["nombre"])}<br>{fmt_dt(com["abierta_ts"])}</div><hr>'
            f"<table>{filas}<tr><td colspan=3><hr></td></tr>"
            f"<tr><td colspan=2>Subtotal</td><td style='text-align:right'>{peso(tot['sub'])}</td></tr>{extra}"
            f"<tr><td colspan=2><b>TOTAL</b></td><td style='text-align:right'><b>{peso(tot['total'])}</b></td></tr>"
            f'</table><hr><div style="text-align:center">{pie}</div></div>')


def ticket_txt(com, mesa, items, tot):
    act = [i for i in items if not i.get("anulado")]
    L = [CFG.get("negocio_nombre") or "HOPSIE · Cerveza Artesanal",
         f"PRE-CUENTA · {mesa['nombre']} · {fmt_dt(com['abierta_ts'])}", "-" * 34]
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
            agregar_unidad(com, p)
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
    st.caption(f"Abierta {fmt_dt(com['abierta_ts'])} · 👥 {com['comensales']} · Adicionista: {com.get('mozo') or '—'} · Comanda #{cid}")

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
        st.dataframe(pd.DataFrame([{"Fecha": fmt_dt(m["ts"]), "Insumo": nom.get(m["insumo_id"], "?"), "Tipo": m["tipo"],
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
    df = pd.DataFrame([{"Fecha": fmt_dt(r["ts"]), "Usuario": r["usuario"], "Acción": r["accion"], "Detalle": r["detalle"]} for r in rows])
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


def main():
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


main()
