"""
Dashboard de Recuperación de Clientes - GDL 2
================================================
App Streamlit para detectar clientes sin venta en el mes y priorizar
la recuperación de cartera en las rutas BVA116, BVA117, BVA118 y BVA124.

Ejecutar con:
    streamlit run app.py
"""
import io
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import (
    guess_column_mapping, apply_filters, compute_kpis, coerce_numeric,
    detect_month_columns, detect_status_column, determine_current_month,
    compute_kpis_sap,
)

# ---------------------------------------------------------------------------
# Config general
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Recuperación de Clientes GDL 2",
    page_icon="🎯",
    layout="wide",
)

RUTAS_OBJETIVO_DEFAULT = ["BVA116", "BVA117", "BVA118", "BVA124"]
UNIDAD_NEGOCIO_DEFAULT = "GDL 2"

st.markdown(
    """
    <style>
    div[data-testid="stMetric"] {
        background-color: #f7f7f9;
        border: 1px solid #e6e6e6;
        border-radius: 10px;
        padding: 14px 10px 8px 10px;
    }
    div[data-testid="stMetricLabel"] { font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🎯 Dashboard de Recuperación de Clientes")
st.caption("Unidad de Negocio GDL 2 · Rutas BVA116, BVA117, BVA118, BVA124")


# ---------------------------------------------------------------------------
# 1. Carga de archivo
# ---------------------------------------------------------------------------
st.sidebar.header("1️⃣ Cargar archivo")
uploaded_file = st.sidebar.file_uploader(
    "Archivo de ventas diario (.csv, .xlsx, .xlsm)",
    type=["csv", "xlsx", "xlsm"],
)

if uploaded_file is None:
    st.info(
        "⬅️ Sube tu archivo de ventas del día (.csv o .xlsx) en el panel izquierdo "
        "para generar el reporte."
    )
    with st.expander("¿Qué columnas necesita el archivo?"):
        st.markdown(
            """
            El archivo debe tener **una fila por cliente**, con columnas como:

            | Campo | Ejemplos de nombre de columna aceptados |
            |---|---|
            | Unidad de negocio | `Unidad de Negocio`, `Sucursal`, `BU` |
            | Ruta | `Ruta`, `Route` |
            | No. de cliente | `Numero Cliente`, `Id Cliente` |
            | Nombre del cliente | `Cliente`, `Razón Social` |
            | Venta del mes | `Venta Mensual`, `Vtas Mens.`, `Ventas` |
            | Frecuencia de visita | `Frecuencia de Visita` |
            | Venta promedio histórica *(opcional)* | `Venta Promedio`, `Ticket Promedio` |

            No necesitas que los nombres sean exactos: la app intenta
            reconocerlos automáticamente y te deja corregir el mapeo manualmente.
            """
        )
    st.stop()


def _detect_header_row(xls: pd.ExcelFile, sheet_name: str, max_scan: int = 6) -> int:
    """
    Algunos exports (ej. tablas de SAP/BI) traen una fila de título arriba del
    encabezado real. Se detecta la fila de encabezado como la que tiene más
    celdas no vacías dentro de las primeras `max_scan` filas.
    """
    try:
        raw = pd.read_excel(xls, sheet_name=sheet_name, header=None, nrows=max_scan)
    except Exception:
        return 0
    counts = raw.notna().sum(axis=1)
    return int(counts.idxmax())


@st.cache_data(show_spinner=False)
def load_file(file, sheet_name=None) -> dict:
    """Devuelve {'sheets': [...], 'data': {sheet: df}} para poder elegir hoja si es Excel."""
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
        return {"sheets": ["(csv)"], "data": {"(csv)": df}}
    else:
        xls = pd.ExcelFile(file, engine="openpyxl")
        data = {}
        # Ignoramos hojas ocultas técnicas típicas de exports de SAP/BI.
        candidate_sheets = [s for s in xls.sheet_names if "hiddensheet" not in s.lower()]
        for sh in candidate_sheets:
            try:
                header_row = _detect_header_row(xls, sh)
                data[sh] = pd.read_excel(xls, sheet_name=sh, header=header_row)
            except Exception:
                continue
        return {"sheets": list(data.keys()), "data": data}


try:
    loaded = load_file(uploaded_file)
except Exception as e:
    st.error(f"No se pudo leer el archivo: {e}")
    st.stop()

def _pick_default_sheet(data: dict) -> str:
    """Prioriza la hoja con más columnas de meses (ene-26, feb-26...) — suele
    ser la de datos crudos por cliente ('BDD') y no un resumen/pivote."""
    best_sheet, best_score = list(data.keys())[0], -1
    for sh, d in data.items():
        score = len(detect_month_columns(d.columns.tolist())) * 1000 + len(d)
        if score > best_score:
            best_sheet, best_score = sh, score
    return best_sheet


sheet_choice = _pick_default_sheet(loaded["data"])
if len(loaded["sheets"]) > 1:
    sheet_choice = st.sidebar.selectbox(
        "Hoja de Excel a usar", loaded["sheets"],
        index=loaded["sheets"].index(sheet_choice),
    )

df_raw = loaded["data"][sheet_choice].copy()
df_raw.columns = [str(c).strip() for c in df_raw.columns]
df_raw = df_raw.dropna(how="all")

if df_raw.empty:
    st.error("La hoja seleccionada no tiene datos.")
    st.stop()


# ---------------------------------------------------------------------------
# 2. Mapeo de columnas + detección de modo (genérico vs. SAP/BDD)
# ---------------------------------------------------------------------------
st.sidebar.header("2️⃣ Confirmar columnas")
auto_mapping = guess_column_mapping(df_raw.columns.tolist())
cols_options = ["(ninguna)"] + df_raw.columns.tolist()

month_cols = detect_month_columns(df_raw.columns.tolist())
status_col_auto = detect_status_column(df_raw) if len(month_cols) >= 3 else None
current_month_col_auto = (
    determine_current_month(df_raw, status_col_auto, month_cols) if month_cols else None
)
sap_mode = len(month_cols) >= 3 and status_col_auto is not None and current_month_col_auto is not None

FIELD_LABELS = {
    "unidad_negocio": "Unidad de negocio",
    "ruta": "Ruta",
    "cliente_id": "No. de cliente",
    "cliente_nombre": "Nombre del cliente",
    "venta_mes": "Venta del mes" + ("" if sap_mode else " (REQUERIDO)"),
    "frecuencia": "Frecuencia de visita / de compra",
    "venta_promedio_hist": "Venta promedio histórica (opcional)",
    "status": "Status del cliente (CCC/CSC, opcional)",
}

if sap_mode:
    auto_mapping["venta_mes"] = auto_mapping.get("venta_mes") or current_month_col_auto
    auto_mapping["status"] = status_col_auto

with st.sidebar.expander("Ajustar mapeo automático", expanded=False):
    if sap_mode:
        st.success(
            f"📅 Archivo tipo SAP/BDD detectado — mes actual identificado: **{current_month_col_auto}**. "
            "Se usará el histórico mensual real para calcular la venta promedio."
        )
        status_col = st.selectbox(
            "Columna de estatus (CCC/CSC)", cols_options,
            index=cols_options.index(status_col_auto) if status_col_auto in cols_options else 0,
        )
        current_month_col = st.selectbox(
            "Columna del mes actual", list(month_cols.keys()),
            index=list(month_cols.keys()).index(current_month_col_auto),
        )
    final_mapping = {}
    for field, label in FIELD_LABELS.items():
        guess = auto_mapping.get(field)
        default_idx = cols_options.index(guess) if guess in cols_options else 0
        choice = st.selectbox(label, cols_options, index=default_idx, key=f"map_{field}")
        final_mapping[field] = None if choice == "(ninguna)" else choice

if sap_mode:
    final_mapping["status"] = status_col
else:
    if not final_mapping.get("venta_mes"):
        st.error(
            "No se detectó la columna de **venta del mes**. Selecciónala manualmente "
            "en '2️⃣ Confirmar columnas' → 'Ajustar mapeo automático'."
        )
        st.stop()


# ---------------------------------------------------------------------------
# 3. Filtros: Unidad de negocio y rutas
# ---------------------------------------------------------------------------
st.sidebar.header("3️⃣ Filtros")

col_bu = final_mapping.get("unidad_negocio")
if col_bu:
    bu_values = sorted(df_raw[col_bu].dropna().astype(str).str.strip().unique().tolist())
    default_bu = UNIDAD_NEGOCIO_DEFAULT if UNIDAD_NEGOCIO_DEFAULT in bu_values else (
        bu_values[0] if bu_values else None
    )
    unidad_negocio_sel = st.sidebar.selectbox(
        "Unidad de negocio", bu_values, index=bu_values.index(default_bu) if default_bu in bu_values else 0
    )
else:
    unidad_negocio_sel = None
    st.sidebar.caption("No hay columna de unidad de negocio mapeada; no se filtrará por este campo.")

col_ruta = final_mapping.get("ruta")
if col_ruta:
    ruta_values = sorted(df_raw[col_ruta].dropna().astype(str).str.strip().unique().tolist())
    default_rutas = [r for r in RUTAS_OBJETIVO_DEFAULT if r in ruta_values] or ruta_values
    rutas_sel = st.sidebar.multiselect("Rutas", ruta_values, default=default_rutas)
else:
    rutas_sel = None
    st.sidebar.caption("No hay columna de ruta mapeada; no se filtrará por este campo.")

if not sap_mode:
    umbral_venta = st.sidebar.number_input(
        "Umbral para considerar 'sin venta' (venta ≤ este valor)",
        value=0.0, step=100.0,
        help="Por defecto, un cliente se considera 'sin venta' si su venta del mes es menor o igual a 0.",
    )
else:
    st.sidebar.caption(
        "El estatus 'sin venta' / 'con venta' se toma directamente de la columna "
        f"de estatus (**{final_mapping['status']}**), no de un umbral manual."
    )

if not col_bu and not sap_mode:
    pass
elif not col_bu and sap_mode:
    st.sidebar.caption(
        "Este archivo no trae una columna de 'Unidad de negocio' explícita, pero las "
        "rutas seleccionadas ya identifican de forma exclusiva a GDL 2, así que el "
        "filtro por Ruta es suficiente."
    )


# ---------------------------------------------------------------------------
# 4. Cálculo
# ---------------------------------------------------------------------------
df_filtered = apply_filters(df_raw, final_mapping, unidad_negocio_sel, rutas_sel)

if df_filtered.empty:
    st.warning("No hay clientes que cumplan con la unidad de negocio y rutas seleccionadas.")
    st.stop()

if sap_mode:
    kpis = compute_kpis_sap(
        df_filtered, final_mapping, final_mapping["status"], month_cols, current_month_col
    )
else:
    kpis = compute_kpis(df_filtered, final_mapping, venta_threshold=umbral_venta)


# ---------------------------------------------------------------------------
# 3b. Columnas a ocultar en las tablas (gerentes, supervisores, técnicas, etc.)
# ---------------------------------------------------------------------------
COLUMNAS_RUIDO_TIPICAS = {
    "gerente regional", "gerente venta", "spv", "horario de cliente",
    "clasificacion", "clasificación", "visitas", "fe.factura", "orgvt", "cdis",
    "tp.doc.", "clfac", "solicit.", "doc.fact.", "valor neto", "impte.imp.",
    "resp.pago", "mes", "acumulado", "fecha", "avance cliente por dia",
    "avance cliente por día", "psv", "frec. compra", "frec compra",
}
cols_ruido_detectadas = [
    c for c in df_filtered.columns
    if c.strip().lower() in COLUMNAS_RUIDO_TIPICAS or c.strip().lower().startswith("unnamed")
]
cols_vacias = [c for c in df_filtered.columns if df_filtered[c].isna().all()]
cols_ruido_detectadas = list(dict.fromkeys(cols_ruido_detectadas + cols_vacias))  # sin duplicados
with st.sidebar.expander("4️⃣ Ocultar columnas en las tablas", expanded=False):
    cols_ocultar = st.multiselect(
        "Columnas que NO quieres ver en el Top 10 / detalle / descargas",
        options=df_filtered.columns.tolist(),
        default=cols_ruido_detectadas,
        help="Por defecto ya se ocultan columnas técnicas típicas (gerentes, supervisores, "
             "horarios, facturación). Agrega o quita las que necesites.",
    )

st.caption(f"Reporte generado el {datetime.now().strftime('%d/%m/%Y %H:%M')} · "
           f"{kpis['total_clientes']} clientes en cartera analizados")


# ---------------------------------------------------------------------------
# 5. KPIs principales
# ---------------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔴 Clientes SIN venta", f"{kpis['n_sin_venta']:,}")
c2.metric("👥 Total cartera", f"{kpis['total_clientes']:,}")
c3.metric("📈 Avance del día", f"{kpis['avance_pct']:.1f}%",
          help="Clientes con venta / Total de clientes")
c4.metric(
    "💸 Venta en riesgo",
    f"${kpis['venta_en_riesgo']:,.0f}",
    help=(
        "Estimado con el promedio histórico real del cliente."
        if kpis["avg_source"] == "columna_real"
        else "Estimado: no se encontró columna de histórico, se usó el promedio de "
             "venta de clientes activos (por frecuencia de visita) como proxy."
    ),
)
if kpis["avg_source"] == "estimado":
    st.caption("⚠️ *Venta en riesgo* es una estimación (no se detectó columna de venta promedio histórica).")

st.divider()

# ---------------------------------------------------------------------------
# 6. Gráfico: Estatus por ruta
# ---------------------------------------------------------------------------
st.subheader("Estatus por ruta: con venta vs. sin venta")
ruta_status = kpis["ruta_status"]
if ruta_status is not None and len(ruta_status):
    col_ruta_name = final_mapping["ruta"]
    fig2 = go.Figure()
    fig2.add_bar(name="Con venta", x=ruta_status[col_ruta_name], y=ruta_status["con_venta"],
                 marker_color="#2ca02c")
    fig2.add_bar(name="Sin venta", x=ruta_status[col_ruta_name], y=ruta_status["sin_venta"],
                 marker_color="#d62728")
    fig2.update_layout(barmode="group", margin=dict(t=10), legend=dict(orientation="h"))
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No hay columna de 'ruta' mapeada.")

st.divider()

# ---------------------------------------------------------------------------
# 7. Top 10 clientes urgentes
# ---------------------------------------------------------------------------
st.subheader("🔥 Top 10 clientes urgentes (mayor impacto económico sin venta)")
top10 = kpis["top10"].drop(columns=[c for c in cols_ocultar if c in kpis["top10"].columns], errors="ignore")
if len(top10):
    st.dataframe(
        top10.style.format({top10.columns[-1]: "${:,.0f}"}),
        use_container_width=True, hide_index=True,
    )
else:
    st.info("No hay clientes sin venta en la selección actual, o falta mapear 'venta promedio histórica'.")

st.divider()

# ---------------------------------------------------------------------------
# 8. Detalle descargable
# ---------------------------------------------------------------------------
st.subheader("📋 Detalle de clientes sin venta")
detalle = kpis["sin_venta_detalle"].drop(columns=["_venta_mes_num"], errors="ignore")
detalle = detalle.drop(columns=[c for c in detalle.columns if c.startswith("_")], errors="ignore")
detalle = detalle.drop(columns=[c for c in cols_ocultar if c in detalle.columns], errors="ignore")
st.dataframe(detalle, use_container_width=True, hide_index=True)


def to_excel_bytes(dataframes: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        for sheet, d in dataframes.items():
            d.to_excel(writer, sheet_name=sheet[:31], index=False)
    return buffer.getvalue()


excel_bytes = to_excel_bytes({
    "Sin venta - detalle": detalle,
    "Top 10 urgentes": top10,
})

dl1, dl2 = st.columns(2)
with dl1:
    st.download_button(
        "⬇️ Descargar reporte en Excel",
        data=excel_bytes,
        file_name=f"reporte_recuperacion_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
with dl2:
    st.download_button(
        "⬇️ Descargar detalle en CSV",
        data=detalle.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"clientes_sin_venta_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
