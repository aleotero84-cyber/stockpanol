"""
Pañol — Control de Stock (Multi-almacén)
Streamlit + Supabase
"""

import streamlit as st
from supabase import create_client, Client
from datetime import datetime
import pandas as pd
import hashlib
import base64
import os

# ─────────────────────────────────────────
# CONFIGURACIÓN DE PÁGINA
# ─────────────────────────────────────────
st.set_page_config(
    page_title="Pañol — Control de Stock",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────
# ESTILOS
# ─────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

/* Reset y fondo */
html, body, [data-testid="stAppViewContainer"] {
    background-color: #0d0f14 !important;
    color: #e0e4f5;
}
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stSidebar"] { background: #0d0f14 !important; }
.block-container { padding-top: 1.5rem !important; max-width: 1200px; }

/* Tipografía */
h1, h2, h3 { font-family: 'IBM Plex Mono', monospace !important; }
p, div, label, span { font-family: 'IBM Plex Sans', sans-serif; }

/* Header personalizado */
.pn-header {
    background: linear-gradient(135deg, #151821 0%, #1c2030 100%);
    border: 1px solid #2c3050;
    border-radius: 12px;
    padding: 20px 28px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.pn-logo { font-family: 'IBM Plex Mono', monospace; font-size: 22px; font-weight: 600; color: #f0c040; letter-spacing: 4px; }
.pn-subtitle { font-size: 12px; color: #5e6585; letter-spacing: 1px; margin-top: 2px; }
.pn-stat-box { text-align: center; }
.pn-stat-num { font-family: 'IBM Plex Mono', monospace; font-size: 26px; font-weight: 600; color: #f0c040; }
.pn-stat-lbl { font-size: 11px; color: #5e6585; text-transform: uppercase; letter-spacing: 1px; }
.pn-stat-num.warn { color: #ff8c42; }
.pn-stat-num.ok   { color: #3dca7a; }

/* Selector de almacén activo (pill en el header) */
.pn-almacen-pill {
    display: inline-flex; align-items: center; gap: 8px;
    background: #1c2030; border: 1px solid #2c3050;
    border-radius: 20px; padding: 6px 16px;
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
    color: #f0c040; letter-spacing: .5px;
}

/* Tabs */
[data-testid="stTabs"] button {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 12px !important;
    letter-spacing: 1px !important;
    color: #5e6585 !important;
}
[data-testid="stTabs"] button[aria-selected="true"] {
    color: #f0c040 !important;
    border-bottom-color: #f0c040 !important;
}

/* Tabla de stock */
.pn-table-wrap { overflow-x: auto; border-radius: 10px; border: 1px solid #2c3050; }
.pn-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.pn-table thead tr { background: #151821; border-bottom: 2px solid #2c3050; }
.pn-table th {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px; font-weight: 600;
    color: #5e6585; text-transform: uppercase;
    letter-spacing: 1.2px; padding: 12px 16px; text-align: left;
}
.pn-table td { padding: 11px 16px; border-bottom: 1px solid #14172200; }
.pn-table tbody tr { border-bottom: 1px solid #1a1d2e; transition: background .15s; }
.pn-table tbody tr:hover { background: #181c2e; }
.pn-name { font-weight: 600; color: #e0e4f5; }
.pn-muted { color: #5e6585; font-size: 12px; }
.pn-cat {
    font-family: 'IBM Plex Mono', monospace; font-size: 11px; font-weight: 600;
    background: #1e2235; color: #5e6585;
    padding: 3px 9px; border-radius: 4px; letter-spacing: .4px;
}
.pn-num { font-family: 'IBM Plex Mono', monospace; font-size: 15px; font-weight: 700; }
.pn-ok   { color: #3dca7a; }
.pn-low  { color: #ff8c42; }
.pn-zero { color: #ff4f4f; }
.pn-badge { display: inline-flex; align-items: center; gap: 6px; font-family: 'IBM Plex Mono', monospace; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 4px; }
.pn-badge-ok      { background: #0d2b1a; color: #3dca7a; }
.pn-badge-low     { background: #2b1800; color: #ff8c42; }
.pn-badge-agotado { background: #2b0000; color: #ff4f4f; }

/* Formularios */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stSelectbox"] select {
    background: #1c2030 !important;
    border: 1px solid #2c3050 !important;
    color: #e0e4f5 !important;
    border-radius: 6px !important;
    font-family: 'IBM Plex Mono', monospace !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus {
    border-color: #3d9eff !important;
    box-shadow: 0 0 0 2px rgba(61,158,255,.15) !important;
}

/* Botones */
.stButton button {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    letter-spacing: .5px !important;
    border-radius: 6px !important;
    border: none !important;
    transition: filter .15s, transform .1s !important;
    width: 100%;
}
.stButton button:hover  { filter: brightness(1.15) !important; }
.stButton button:active { transform: scale(.97) !important; }

/* Cajas de alerta y éxito */
[data-testid="stAlert"] {
    border-radius: 8px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 13px !important;
}

/* Password input */
[data-testid="stTextInput"][data-type="password"] input {
    letter-spacing: 4px;
}

/* Historial */
.hist-ent { color: #3d9eff; font-family: 'IBM Plex Mono', monospace; font-size: 12px; }
.hist-sal { color: #ff8c42; font-family: 'IBM Plex Mono', monospace; font-size: 12px; }
.hist-row { padding: 8px 0; border-bottom: 1px solid #1a1d2e; }

/* Login box */
.login-box {
    background: #151821;
    border: 1px solid #2c3050;
    border-radius: 12px;
    padding: 32px;
    text-align: center;
    max-width: 400px;
    margin: 0 auto;
}
.login-icon { font-size: 40px; margin-bottom: 10px; }
.login-title { font-family: 'IBM Plex Mono', monospace; font-size: 16px; color: #f0c040; margin-bottom: 6px; }
.login-sub   { font-size: 13px; color: #5e6585; margin-bottom: 20px; }

/* Tarjetas de almacén (pantalla de selección) */
.alm-card {
    background: #151821;
    border: 1px solid #2c3050;
    border-radius: 12px;
    padding: 22px;
    text-align: center;
    transition: border-color .15s;
}
.alm-card:hover { border-color: #f0c040; }
.alm-icon { font-size: 34px; margin-bottom: 8px; }
.alm-nombre { font-family: 'IBM Plex Mono', monospace; font-size: 15px; color: #e0e4f5; font-weight: 600; }

/* Divider */
.pn-divider { border: none; border-top: 1px solid #2c3050; margin: 16px 0; }

/* Scrollbar */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #151821; }
::-webkit-scrollbar-thumb { background: #2c3050; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)

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

# ─────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────
if "almacen_id" not in st.session_state:
    st.session_state.almacen_id = None
if "almacen_nombre" not in st.session_state:
    st.session_state.almacen_nombre = None
if "almacen_icono" not in st.session_state:
    st.session_state.almacen_icono = "📦"
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "msg" not in st.session_state:
    st.session_state.msg = None   # ("tipo", "texto")
if "confirmar_borrado_id" not in st.session_state:
    st.session_state.confirmar_borrado_id = None  # id del almacén que se está intentando borrar

# ─────────────────────────────────────────
# HELPERS DE DB — ALMACENES
# ─────────────────────────────────────────
@st.cache_data(ttl=10)
def get_almacenes():
    try:
        res = supabase.table("paniol_almacenes").select("id,nombre,slug,icono,creado").order("nombre").execute()
        return res.data or []
    except Exception as e:
        st.error(f"❌ Error al obtener almacenes: `{type(e).__name__}`")
        return []

def crear_almacen(nombre, icono, clave):
    slug_base = slugificar(nombre)
    slug = slug_base
    existentes = {a["slug"] for a in get_almacenes()}
    n = 2
    while slug in existentes:
        slug = f"{slug_base}-{n}"
        n += 1
    res = supabase.table("paniol_almacenes").insert({
        "nombre": nombre.strip(),
        "slug": slug,
        "icono": icono or "📦",
        "clave_hash": hash_clave(clave),
    }).execute()
    get_almacenes.clear()
    return res.data[0] if res.data else None

def verificar_clave_almacen(almacen_id, clave) -> bool:
    try:
        res = supabase.table("paniol_almacenes").select("clave_hash").eq("id", almacen_id).single().execute()
        if not res.data:
            return False
        return res.data["clave_hash"] == hash_clave(clave)
    except Exception:
        return False

def eliminar_almacen(almacen_id):
    # Las tablas relacionadas tienen ON DELETE CASCADE, así que borrar el
    # almacén borra automáticamente todos sus ítems y movimientos.
    supabase.table("paniol_almacenes").delete().eq("id", almacen_id).execute()
    get_almacenes.clear()
    invalidar_cache()

# ─────────────────────────────────────────
# HELPERS DE DB — ÍTEMS / MOVIMIENTOS (filtrados por almacén)
# ─────────────────────────────────────────
@st.cache_data(ttl=10)
def get_items(almacen_id):
    try:
        res = (supabase.table("paniol_items")
               .select("*").eq("almacen_id", almacen_id)
               .order("nombre").execute())
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

def invalidar_cache():
    get_items.clear()
    get_movimientos.clear()

def agregar_item(almacen_id, nombre, categoria, ubicacion, cantidad, minimo, descripcion):
    supabase.table("paniol_items").insert({
        "almacen_id": almacen_id,
        "nombre": nombre, "categoria": categoria, "ubicacion": ubicacion,
        "cantidad": cantidad, "minimo": minimo, "descripcion": descripcion,
    }).execute()
    invalidar_cache()

def editar_item(id_, nombre, categoria, ubicacion, cantidad, minimo, descripcion):
    supabase.table("paniol_items").update({
        "nombre": nombre, "categoria": categoria, "ubicacion": ubicacion,
        "cantidad": cantidad, "minimo": minimo, "descripcion": descripcion,
    }).eq("id", id_).execute()
    invalidar_cache()

def eliminar_item(id_):
    supabase.table("paniol_items").delete().eq("id", id_).execute()
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

# ─────────────────────────────────────────
# RENDER DE TABLA
# ─────────────────────────────────────────
def render_tabla(items, filtro=""):
    if filtro:
        f = filtro.lower()
        items = [i for i in items if
                 f in i["nombre"].lower() or
                 f in (i.get("categoria") or "").lower() or
                 f in (i.get("ubicacion") or "").lower()]

    if not items:
        st.info("Sin resultados.")
        return

    filas = []
    for i in items:
        cant = i["cantidad"]
        mn   = i.get("minimo") or 0
        if cant == 0:
            est = '<span class="pn-badge pn-badge-agotado">● AGOTADO</span>'
            num_cls = "pn-zero"
        elif cant <= mn:
            est = '<span class="pn-badge pn-badge-low">● BAJO</span>'
            num_cls = "pn-low"
        else:
            est = '<span class="pn-badge pn-badge-ok">● OK</span>'
            num_cls = "pn-ok"

        filas.append(f"""
        <tr>
          <td><span class="pn-name">{i['nombre']}</span></td>
          <td><span class="pn-cat">{i.get('categoria') or '—'}</span></td>
          <td><span class="pn-num {num_cls}">{cant}</span></td>
          <td><span class="pn-muted">{mn}</span></td>
          <td><span class="pn-muted">{i.get('ubicacion') or '—'}</span></td>
          <td>{est}</td>
        </tr>""")

    html = f"""
    <div class="pn-table-wrap">
      <table class="pn-table">
        <thead><tr>
          <th>Nombre</th><th>Categoría</th><th>Cantidad</th>
          <th>Mínimo</th><th>Ubicación</th><th>Estado</th>
        </tr></thead>
        <tbody>{''.join(filas)}</tbody>
      </table>
    </div>"""
    st.markdown(html, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# PANTALLA: SELECCIÓN DE ALMACÉN
# (se muestra si todavía no se eligió ninguno)
# ══════════════════════════════════════════════════════
def pantalla_seleccion_almacen():
    logo_base64 = get_base64_image("iacilog.png")
    logo_html = (f'<img src="data:image/png;base64,{logo_base64}" style="height: 55px; width: auto; max-height: 55px;">'
                 if logo_base64 else '<div class="pn-logo">PAÑOL</div>')

    st.markdown(f"""
    <div class="pn-header" style="justify-content:flex-start;gap:15px;">
        {logo_html}
        <div>
          <div style="font-family:'IBM Plex Mono',monospace;font-size:14px;font-weight:600;color:#f0c040;letter-spacing:2px;">PAÑOL</div>
          <div class="pn-subtitle">CONTROL DE STOCK · MULTI-ALMACÉN</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("#### Elegí un almacén")
    st.caption("Cada almacén tiene su propio stock, historial y contraseña de administración independiente.")

    almacenes = get_almacenes()

    if not almacenes:
        st.info("Todavía no hay ningún almacén creado. Creá el primero abajo.")
    else:
        cols = st.columns(3)
        for idx, a in enumerate(almacenes):
            with cols[idx % 3]:
                st.markdown(f"""
                <div class="alm-card">
                  <div class="alm-icon">{a.get('icono') or '📦'}</div>
                  <div class="alm-nombre">{a['nombre']}</div>
                </div>
                """, unsafe_allow_html=True)
                if st.button("Ingresar →", key=f"sel_{a['id']}", use_container_width=True):
                    st.session_state.almacen_id = a["id"]
                    st.session_state.almacen_nombre = a["nombre"]
                    st.session_state.almacen_icono = a.get("icono") or "📦"
                    st.rerun()

                if st.session_state.confirmar_borrado_id == a["id"]:
                    # ── Panel de confirmación: pide la contraseña DOS VECES ──
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.warning(f"⚠ Vas a borrar **{a['nombre']}** junto con todo su stock e historial. Esta acción no se puede deshacer.")
                    clave1 = st.text_input("Contraseña del almacén", type="password",
                                            key=f"del_clave1_{a['id']}")
                    clave2 = st.text_input("Repetí la contraseña", type="password",
                                            key=f"del_clave2_{a['id']}")
                    cb1, cb2 = st.columns(2)
                    with cb1:
                        if st.button("🗑️ Confirmar borrado", key=f"del_confirm_{a['id']}", use_container_width=True):
                            if not clave1 or not clave2:
                                st.error("Completá la contraseña en los dos campos.")
                            elif clave1 != clave2:
                                st.error("Las dos contraseñas ingresadas no coinciden.")
                            elif not verificar_clave_almacen(a["id"], clave1):
                                st.error("Contraseña incorrecta.")
                            else:
                                eliminar_almacen(a["id"])
                                # Si el almacén borrado era el activo en la sesión, lo limpiamos
                                if st.session_state.almacen_id == a["id"]:
                                    st.session_state.almacen_id = None
                                    st.session_state.almacen_nombre = None
                                    st.session_state.autenticado = False
                                st.session_state.confirmar_borrado_id = None
                                st.session_state.msg = ("ok", f"✓ Almacén '{a['nombre']}' eliminado.")
                                st.rerun()
                    with cb2:
                        if st.button("Cancelar", key=f"del_cancel_{a['id']}", use_container_width=True):
                            st.session_state.confirmar_borrado_id = None
                            st.rerun()
                else:
                    if st.button("🗑️ Borrar almacén", key=f"del_{a['id']}", use_container_width=True):
                        st.session_state.confirmar_borrado_id = a["id"]
                        st.rerun()

                st.markdown("<br>", unsafe_allow_html=True)

    st.markdown("<hr class='pn-divider'>", unsafe_allow_html=True)

    with st.expander("➕  Crear nuevo almacén (ej: droguería, depósito, otra sede...)"):
        c1, c2 = st.columns([3, 1])
        with c1:
            nuevo_nombre = st.text_input("Nombre del almacén", placeholder="ej: Droguería Central")
        with c2:
            nuevo_icono = st.text_input("Ícono (emoji)", value="📦", max_chars=4)
        nueva_clave  = st.text_input("Contraseña de administración para este almacén", type="password",
                                      placeholder="Elegí una contraseña segura")
        nueva_clave2 = st.text_input("Repetir contraseña", type="password")

        if st.button("Crear almacén", use_container_width=True):
            if not nuevo_nombre.strip():
                st.error("El nombre del almacén es obligatorio.")
            elif not nueva_clave:
                st.error("Definí una contraseña de administración.")
            elif nueva_clave != nueva_clave2:
                st.error("Las contraseñas no coinciden.")
            elif len(nueva_clave) < 4:
                st.error("Usá una contraseña de al menos 4 caracteres.")
            else:
                nuevo = crear_almacen(nuevo_nombre.strip(), nuevo_icono.strip(), nueva_clave)
                if nuevo:
                    st.session_state.almacen_id = nuevo["id"]
                    st.session_state.almacen_nombre = nuevo["nombre"]
                    st.session_state.almacen_icono = nuevo.get("icono") or "📦"
                    st.session_state.msg = ("ok", f"✓ Almacén '{nuevo['nombre']}' creado. ¡Guardá bien la contraseña!")
                    st.rerun()
                else:
                    st.error("No se pudo crear el almacén. Intentá de nuevo.")


# Si todavía no hay almacén elegido, mostrar selector y detener acá.
if st.session_state.almacen_id is None:
    pantalla_seleccion_almacen()
    st.stop()

ALMACEN_ID = st.session_state.almacen_id

# ─────────────────────────────────────────
# HEADER (con almacén activo)
# ─────────────────────────────────────────
logo_base64 = get_base64_image("iacilog.png")

items_all = get_items(ALMACEN_ID)
n_total   = len(items_all)
n_alertas = sum(1 for i in items_all if i["cantidad"] <= (i.get("minimo") or 0))
n_ok      = n_total - n_alertas
alerta_cls = "warn" if n_alertas else "ok"

if logo_base64:
    logo_html = f'<img src="data:image/png;base64,{logo_base64}" style="height: 55px; width: auto; max-height: 55px; vertical-align: middle;">'
else:
    logo_html = '<div class="pn-logo">PAÑOL</div>'

st.markdown(f"""
<div class="pn-header">
  <div style="display: flex; align-items: center; gap: 15px;">
    {logo_html}
    <div>
      <div style="font-family: 'IBM Plex Mono', monospace; font-size: 14px; font-weight: 600; color: #f0c040; letter-spacing: 2px; line-height: 1.2;">PAÑOL</div>
      <div class="pn-subtitle" style="margin-top: 0px;">CONTROL DE STOCK</div>
    </div>
    <div class="pn-almacen-pill">{st.session_state.almacen_icono} {st.session_state.almacen_nombre}</div>
  </div>
  <div style="display:flex;gap:40px;align-items:center">
    <div class="pn-stat-box">
      <div class="pn-stat-num">{n_total}</div>
      <div class="pn-stat-lbl">ítems</div>
    </div>
    <div class="pn-stat-box">
      <div class="pn-stat-num {alerta_cls}">{n_alertas}</div>
      <div class="pn-stat-lbl">alertas</div>
    </div>
    <div class="pn-stat-box">
      <div class="pn-stat-num ok">{n_ok}</div>
      <div class="pn-stat-lbl">en stock</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

col_cambiar, _ = st.columns([1, 5])
with col_cambiar:
    if st.button("⇄  Cambiar de almacén", use_container_width=True):
        st.session_state.almacen_id = None
        st.session_state.almacen_nombre = None
        st.session_state.autenticado = False
        st.rerun()

# Mostrar mensajes flash
if st.session_state.msg:
    tipo, texto = st.session_state.msg
    if tipo == "ok":
        st.success(texto)
    elif tipo == "error":
        st.error(texto)
    elif tipo == "warn":
        st.warning(texto)
    st.session_state.msg = None

# ─────────────────────────────────────────
# TABS
# ─────────────────────────────────────────
tab_stock, tab_admin, tab_historial = st.tabs([
    "📦  STOCK",
    "🔧  ADMINISTRAR",
    "📋  HISTORIAL",
])

# ══════════════════════════════════════════
# TAB STOCK — vista pública
# ══════════════════════════════════════════
with tab_stock:
    st.markdown("<br>", unsafe_allow_html=True)
    col_buscar, col_refresh = st.columns([5, 1])
    with col_buscar:
        filtro = st.text_input("", placeholder="🔍  Buscar por nombre, categoría o ubicación...",
                               label_visibility="collapsed")
    with col_refresh:
        if st.button("↺  Actualizar", use_container_width=True):
            invalidar_cache()
            st.rerun()

    items_all = get_items(ALMACEN_ID)
    render_tabla(items_all, filtro)

    if n_alertas:
        st.markdown("<br>", unsafe_allow_html=True)
        st.warning(f"⚠ Hay **{n_alertas}** ítem(s) con stock bajo o agotado.")

# ══════════════════════════════════════════
# TAB ADMIN — requiere contraseña del almacén activo
# ══════════════════════════════════════════
with tab_admin:
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Login ────────────────────────────
    if not st.session_state.autenticado:
        st.markdown(f"""
        <div class="login-box">
          <div class="login-icon">🔒</div>
          <div class="login-title">ADMINISTRACIÓN · {st.session_state.almacen_nombre}</div>
          <div class="login-sub">Ingresá la contraseña de este almacén para modificar el stock.</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

        col_c, col_l, col_r = st.columns([1, 2, 1])
        with col_l:
            clave = st.text_input("Contraseña", type="password",
                                  placeholder="••••••••••••••••",
                                  label_visibility="visible")
            if st.button("Ingresar →", use_container_width=True):
                if verificar_clave_almacen(ALMACEN_ID, clave):
                    st.session_state.autenticado = True
                    st.rerun()
                else:
                    st.error("Contraseña incorrecta.")
        st.stop()

    # ── Panel admin (autenticado) ─────────
    col_logout, _ = st.columns([1, 5])
    with col_logout:
        if st.button("🔓 Cerrar sesión"):
            st.session_state.autenticado = False
            st.rerun()

    st.markdown("<hr class='pn-divider'>", unsafe_allow_html=True)

    accion = st.selectbox("Acción", [
        "➕  Agregar ítem",
        "✎   Editar ítem",
        "✕   Eliminar ítem",
        "▲   Registrar entrada",
        "▼   Registrar salida",
        "🗑️  Borrar este almacén",
    ], label_visibility="visible")

    st.markdown("<br>", unsafe_allow_html=True)
    items_all = get_items(ALMACEN_ID)

    # ── AGREGAR ───────────────────────────
    if "Agregar" in accion:
        st.markdown("#### Nuevo ítem")
        c1, c2 = st.columns(2)
        with c1:
            nombre   = st.text_input("Nombre *")
            ubicacion= st.text_input("Ubicación", placeholder="ej: Estante A3")
            descripcion = st.text_input("Descripción")
        with c2:
            categoria = st.selectbox("Categoría", ["herramienta","material","equipo","consumible","otro"])
            cantidad  = st.number_input("Cantidad inicial", min_value=0, value=0)
            minimo    = st.number_input("Stock mínimo de alerta", min_value=0, value=0)

        if st.button("💾  Guardar ítem", use_container_width=True):
            if not nombre.strip():
                st.error("El nombre es obligatorio.")
            else:
                agregar_item(ALMACEN_ID, nombre.strip(), categoria, ubicacion.strip(),
                             cantidad, minimo, descripcion.strip())
                st.session_state.msg = ("ok", f"✓ '{nombre}' agregado correctamente.")
                st.rerun()

    # ── EDITAR ────────────────────────────
    elif "Editar" in accion:
        st.markdown("#### Editar ítem")
        if not items_all:
            st.info("No hay ítems cargados.")
        else:
            opciones = {f"[{i['id']}] {i['nombre']}": i for i in items_all}
            sel = st.selectbox("Seleccioná el ítem a editar", list(opciones.keys()))
            item = opciones[sel]

            c1, c2 = st.columns(2)
            with c1:
                nombre    = st.text_input("Nombre *",    value=item["nombre"])
                ubicacion = st.text_input("Ubicación",   value=item.get("ubicacion") or "")
                descripcion = st.text_input("Descripción", value=item.get("descripcion") or "")
            with c2:
                cats = ["herramienta","material","equipo","consumible","otro"]
                cat_idx = cats.index(item.get("categoria","otro")) if item.get("categoria") in cats else 4
                categoria = st.selectbox("Categoría", cats, index=cat_idx)
                cantidad  = st.number_input("Cantidad", min_value=0, value=int(item["cantidad"]))
                minimo    = st.number_input("Stock mínimo", min_value=0, value=int(item.get("minimo") or 0))

            if st.button("💾  Guardar cambios", use_container_width=True):
                if not nombre.strip():
                    st.error("El nombre es obligatorio.")
                else:
                    editar_item(item["id"], nombre.strip(), categoria,
                                ubicacion.strip(), cantidad, minimo, descripcion.strip())
                    st.session_state.msg = ("ok", f"✓ '{nombre}' actualizado.")
                    st.rerun()

    # ── ELIMINAR ──────────────────────────
    elif "Eliminar" in accion:
        st.markdown("#### Eliminar ítem")
        if not items_all:
            st.info("No hay ítems cargados.")
        else:
            opciones = {f"[{i['id']}] {i['nombre']}": i for i in items_all}
            sel  = st.selectbox("Seleccioná el ítem a eliminar", list(opciones.keys()))
            item = opciones[sel]
            st.warning(f"Vas a eliminar **{item['nombre']}** (stock actual: {item['cantidad']}). Esta acción no se puede deshacer.")
            confirmar = st.checkbox("Confirmo que quiero eliminar este ítem")
            if st.button("🗑️  Eliminar definitivamente", use_container_width=True):
                if not confirmar:
                    st.error("Marcá la casilla de confirmación primero.")
                else:
                    eliminar_item(item["id"])
                    st.session_state.msg = ("ok", f"'{item['nombre']}' eliminado.")
                    st.rerun()

    # ── ENTRADA ───────────────────────────
    elif "entrada" in accion:
        st.markdown("#### Registrar entrada de stock")
        if not items_all:
            st.info("No hay ítems cargados.")
        else:
            opciones = {f"[{i['id']}] {i['nombre']} (stock: {i['cantidad']})": i for i in items_all}
            sel  = st.selectbox("Ítem", list(opciones.keys()))
            item = opciones[sel]
            c1, c2 = st.columns(2)
            with c1:
                cantidad = st.number_input("Cantidad a ingresar", min_value=1, value=1)
            with c2:
                responsable = st.text_input("Responsable / Observación")
            if st.button("▲  Confirmar entrada", use_container_width=True):
                nuevo = registrar_movimiento(ALMACEN_ID, item, "entrada", cantidad, responsable)
                st.session_state.msg = ("ok", f"✓ Entrada de {cantidad} ud. registrada. Stock nuevo: {nuevo}")
                st.rerun()

    # ── SALIDA ────────────────────────────
    elif "salida" in accion:
        st.markdown("#### Registrar salida de stock")
        if not items_all:
            st.info("No hay ítems cargados.")
        else:
            opciones = {f"[{i['id']}] {i['nombre']} (stock: {i['cantidad']})": i for i in items_all}
            sel  = st.selectbox("Ítem", list(opciones.keys()))
            item = opciones[sel]
            c1, c2 = st.columns(2)
            with c1:
                cantidad = st.number_input("Cantidad a retirar", min_value=1, value=1,
                                           max_value=max(1, item["cantidad"]))
            with c2:
                responsable = st.text_input("Responsable / Observación")
            if item["cantidad"] == 0:
                st.error("Este ítem está agotado.")
            elif st.button("▼  Confirmar salida", use_container_width=True):
                if cantidad > item["cantidad"]:
                    st.error(f"Stock insuficiente. Disponible: {item['cantidad']}")
                else:
                    nuevo = registrar_movimiento(ALMACEN_ID, item, "salida", cantidad, responsable)
                    txt = f"✓ Salida de {cantidad} ud. registrada. Stock nuevo: {nuevo}"
                    tipo = "warn" if nuevo <= (item.get("minimo") or 0) else "ok"
                    st.session_state.msg = (tipo, txt)
                    st.rerun()

    # ── BORRAR ESTE ALMACÉN ───────────────
    elif "Borrar este almacén" in accion:
        st.markdown("#### Borrar este almacén")
        st.error(
            f"⚠ Esto va a eliminar **{st.session_state.almacen_nombre}** junto con **todo** su stock "
            f"({n_total} ítems) y su historial de movimientos. **Esta acción no se puede deshacer.**"
        )
        st.caption("Para confirmar, ingresá la contraseña de administración dos veces.")

        c1, c2 = st.columns(2)
        with c1:
            clave_borrar_1 = st.text_input("Contraseña", type="password", key="borrar_alm_clave1")
        with c2:
            clave_borrar_2 = st.text_input("Repetí la contraseña", type="password", key="borrar_alm_clave2")

        confirmar_borrado = st.checkbox(f"Confirmo que quiero borrar '{st.session_state.almacen_nombre}' definitivamente")

        if st.button("🗑️  Borrar almacén definitivamente", use_container_width=True):
            if not confirmar_borrado:
                st.error("Marcá la casilla de confirmación primero.")
            elif not clave_borrar_1 or not clave_borrar_2:
                st.error("Completá la contraseña en los dos campos.")
            elif clave_borrar_1 != clave_borrar_2:
                st.error("Las dos contraseñas ingresadas no coinciden.")
            elif not verificar_clave_almacen(ALMACEN_ID, clave_borrar_1):
                st.error("Contraseña incorrecta.")
            else:
                nombre_borrado = st.session_state.almacen_nombre
                eliminar_almacen(ALMACEN_ID)
                st.session_state.almacen_id = None
                st.session_state.almacen_nombre = None
                st.session_state.autenticado = False
                st.session_state.msg = ("ok", f"✓ Almacén '{nombre_borrado}' eliminado.")
                st.rerun()

# ══════════════════════════════════════════
# TAB HISTORIAL
# ══════════════════════════════════════════
with tab_historial:
    st.markdown("<br>", unsafe_allow_html=True)
    col_h1, col_h2 = st.columns([5, 1])
    with col_h2:
        if st.button("↺  Actualizar ", use_container_width=True):
            invalidar_cache()
            st.rerun()

    movs = get_movimientos(ALMACEN_ID)
    if not movs:
        st.info("Aún no hay movimientos registrados.")
    else:
        df = pd.DataFrame(movs)
        df = df[["fecha","tipo","nombre_item","cantidad","stock_resultante","responsable"]]
        df.columns = ["Fecha","Tipo","Ítem","Cantidad","Stock result.","Responsable"]
        df["Tipo"] = df["Tipo"].map({"entrada": "▲ Entrada", "salida": "▼ Salida"})

        st.markdown(f"**{len(df)}** movimientos registrados.")
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Fecha":       st.column_config.TextColumn("Fecha", width="medium"),
                "Tipo":        st.column_config.TextColumn("Tipo",  width="small"),
                "Ítem":        st.column_config.TextColumn("Ítem",  width="large"),
                "Cantidad":    st.column_config.NumberColumn("Cant.", width="small"),
                "Stock result.": st.column_config.NumberColumn("Stock result.", width="small"),
                "Responsable": st.column_config.TextColumn("Responsable", width="medium"),
            }
        )
