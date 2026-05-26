"""
Pañol — Control de Stock
Streamlit + Supabase
"""

import streamlit as st
from supabase import create_client, Client
from datetime import datetime
import pandas as pd

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
    # Verificar que los secrets existen
    if "supabase" not in st.secrets:
        return None
    url = st.secrets["supabase"].get("url", "").strip()
    key = st.secrets["supabase"].get("key", "").strip()
    if not url or not key or url == "https://XXXXXXXXXXXXXXXXXX.supabase.co":
        return None
    return create_client(url, key)

supabase = get_supabase()

# Mostrar error claro si no hay conexión
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
# CONSTANTE DE CONTRASEÑA
# ─────────────────────────────────────────
CLAVE_ADMIN = "panol.unqui.iaci"

# ─────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "msg" not in st.session_state:
    st.session_state.msg = None   # ("tipo", "texto")

# ─────────────────────────────────────────
# HELPERS DE DB
# ─────────────────────────────────────────
def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@st.cache_data(ttl=10)
def get_items():
    try:
        res = supabase.table("paniol_items").select("*").order("nombre").execute()
        return res.data or []
    except Exception as e:
        st.error(f"❌ Error al conectar con Supabase: `{type(e).__name__}`\n\nVerificá tu URL y key en los Secrets.")
        st.stop()

@st.cache_data(ttl=10)
def get_movimientos():
    try:
        res = supabase.table("paniol_movimientos").select("*").order("fecha", desc=True).limit(300).execute()
        return res.data or []
    except Exception as e:
        st.error(f"❌ Error al obtener historial: `{type(e).__name__}`")
        return []

def invalidar_cache():
    get_items.clear()
    get_movimientos.clear()

def agregar_item(nombre, categoria, ubicacion, cantidad, minimo, descripcion):
    supabase.table("paniol_items").insert({
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

def registrar_movimiento(item, tipo, cantidad, responsable):
    nuevo = item["cantidad"] + cantidad if tipo == "entrada" else item["cantidad"] - cantidad
    supabase.table("paniol_items").update({"cantidad": nuevo}).eq("id", item["id"]).execute()
    supabase.table("paniol_movimientos").insert({
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

# ─────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────
items_all = get_items()
n_total   = len(items_all)
n_alertas = sum(1 for i in items_all if i["cantidad"] <= (i.get("minimo") or 0))
n_ok      = n_total - n_alertas
alerta_cls = "warn" if n_alertas else "ok"
estado_txt = f"⚠ {n_alertas} alerta(s)" if n_alertas else "✓ Todo normal"

LOGO_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/4gHYSUNDX1BST0ZJTEUAAQEAAAHIAAAAAAQwAABtbnRyUkdCIFhZWiAH4AABAAEAAAAAAABhY3NwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAA9tYAAQAAAADTLQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAlkZXNjAAAA8AAAACRyWFlaAAABFAAAABRnWFlaAAABKAAAABRiWFlaAAABPAAAABR3dHB0AAABUAAAABRyVFJDAAABZAAAAChnVFJDAAABZAAAAChiVFJDAAABZAAAAChjcHJ0AAABjAAAADxtbHVjAAAAAAAAAAEAAAAMZW5VUwAAAAgAAAAcAHMAUgBHAEJYWVogAAAAAAAAb6IAADj1AAADkFhZWiAAAAAAAABimQAAt4UAABjaWFlaIAAAAAAAACSgAAAPhAAAts9YWVogAAAAAAAA9tYAAQAAAADTLXBhcmEAAAAAAAQAAAACZmYAAPKnAAANWQAAE9AAAApbAAAAAAAAAABtbHVjAAAAAAAAAAEAAAAMZW5VUwAAACAAAAAcAEcAbwBvAGcAbABlACAASQBuAGMALgAgADIAMAAxADb/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCADIAMgDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AIyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//Z"

st.markdown(f"""
<div class="pn-header">
  <div style="display:flex;align-items:center;gap:16px">
    <img src="data:image/png;base64,{LOGO_B64}"
         style="height:56px;width:auto;object-fit:contain;filter:brightness(0) invert(71%) sepia(29%) saturate(731%) hue-rotate(103deg) brightness(97%) contrast(87%);">
    <div class="pn-subtitle">CONTROL DE STOCK · UNQUI · IACI</div>
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

    items_all = get_items()
    render_tabla(items_all, filtro)

    if n_alertas:
        st.markdown("<br>", unsafe_allow_html=True)
        st.warning(f"⚠ Hay **{n_alertas}** ítem(s) con stock bajo o agotado.")

# ══════════════════════════════════════════
# TAB ADMIN — requiere contraseña
# ══════════════════════════════════════════
with tab_admin:
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Login ────────────────────────────
    if not st.session_state.autenticado:
        st.markdown("""
        <div class="login-box">
          <div class="login-icon">🔒</div>
          <div class="login-title">ÁREA DE ADMINISTRACIÓN</div>
          <div class="login-sub">Ingresá la contraseña para modificar el stock.</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

        col_c, col_l, col_r = st.columns([1, 2, 1])
        with col_l:
            clave = st.text_input("Contraseña", type="password",
                                  placeholder="••••••••••••••••",
                                  label_visibility="visible")
            if st.button("Ingresar →", use_container_width=True):
                if clave == CLAVE_ADMIN:
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
    ], label_visibility="visible")

    st.markdown("<br>", unsafe_allow_html=True)
    items_all = get_items()

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
                agregar_item(nombre.strip(), categoria, ubicacion.strip(),
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
                nuevo = registrar_movimiento(item, "entrada", cantidad, responsable)
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
                    nuevo = registrar_movimiento(item, "salida", cantidad, responsable)
                    txt = f"✓ Salida de {cantidad} ud. registrada. Stock nuevo: {nuevo}"
                    tipo = "warn" if nuevo <= (item.get("minimo") or 0) else "ok"
                    st.session_state.msg = (tipo, txt)
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

    movs = get_movimientos()
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
