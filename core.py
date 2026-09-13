"""
core.py
Lógica de negocio para el Dashboard de Recuperación de Clientes.
Separada de la capa Streamlit para poder probarla de forma aislada.
"""
from __future__ import annotations

import unicodedata
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------
def _normalize(text: str) -> str:
    """Minúsculas, sin acentos, sin espacios extra. Para comparar nombres de columnas."""
    if text is None:
        return ""
    text = str(text).strip().lower()
    text = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    return text


# ---------------------------------------------------------------------------
# Auto-detección de columnas
# ---------------------------------------------------------------------------
# Cada campo lógico tiene una lista de "candidatos" (nombres típicos que puede
# traer el archivo de ventas). Se hace match parcial y normalizado.
FIELD_SYNONYMS: dict[str, list[str]] = {
    "unidad_negocio": [
        "unidad de negocio", "unidad negocio", "u. negocio", "negocio",
        "business unit", "bu", "sucursal", "division",
    ],
    "ruta": ["ruta", "route", "cod ruta", "codigo ruta", "clave ruta"],
    "cliente_id": [
        "numero cliente", "num cliente", "no. cliente", "id cliente",
        "codigo cliente", "clave cliente", "cliente id",
    ],
    "cliente_nombre": ["cliente", "nombre cliente", "razon social", "nombre"],
    "venta_mes": [
        "vta mes", "venta mes", "vtas mens", "venta mensual", "vtas mensuales",
        "venta del mes", "ventas", "vta del dia", "venta actual", "importe venta",
    ],
    "frecuencia": [
        "frecuencia de visita", "frecuencia visita", "frecuencia", "freq visita",
    ],
    "venta_promedio_hist": [
        "venta promedio", "promedio de compra", "compra promedio",
        "venta promedio historica", "ticket promedio", "promedio historico",
        "venta promedio mensual",
    ],
    "status": ["status", "estatus", "estado"],
}


import re


def guess_column_mapping(columns: list[str]) -> dict[str, str | None]:
    """
    Intenta adivinar, para cada campo lógico, cuál columna real del archivo
    le corresponde. Devuelve dict campo_logico -> nombre_columna_real (o None).

    Reglas:
    - Se compara por coincidencia de palabra completa (no substring suelto),
      para evitar que "cliente" matchee "numero cliente" cuando ya hay un
      candidato más específico.
    - Se procesan primero los campos con sinónimos más largos/específicos
      (numero cliente, frecuencia de visita, etc.) para que no les "roben"
      la columna los campos más genéricos (cliente, ruta).
    - Una columna ya asignada no se vuelve a ofrecer a otro campo.
    """
    norm_cols = {col: _normalize(col) for col in columns}
    used_cols: set[str] = set()
    mapping: dict[str, str | None] = {}

    # Orden: campos con sinónimos más específicos/largos primero.
    field_order = sorted(
        FIELD_SYNONYMS.keys(),
        key=lambda f: max(len(s) for s in FIELD_SYNONYMS[f]),
        reverse=True,
    )

    for field in field_order:
        synonyms = sorted(FIELD_SYNONYMS[field], key=len, reverse=True)
        best_match = None
        best_score = -1
        for col, norm_col in norm_cols.items():
            if col in used_cols:
                continue
            for syn in synonyms:
                score = None
                if norm_col == syn:
                    score = 100 + len(syn)
                elif re.search(rf"\b{re.escape(syn)}\b", norm_col):
                    score = 50 + len(syn)
                if score is not None and score > best_score:
                    best_score = score
                    best_match = col
        if best_match:
            used_cols.add(best_match)
        mapping[field] = best_match

    # Reordenar el dict de salida según el orden original de FIELD_SYNONYMS
    return {field: mapping[field] for field in FIELD_SYNONYMS.keys()}


# ---------------------------------------------------------------------------
# Carga y limpieza
# ---------------------------------------------------------------------------
def coerce_numeric(series: pd.Series) -> pd.Series:
    """Convierte una columna de venta que puede venir como texto ('$1,234.50') a float."""
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0)
    cleaned = (
        series.astype(str)
        .str.replace(r"[^\d\.\-]", "", regex=True)
        .replace("", "0")
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0)


# ---------------------------------------------------------------------------
# Filtrado
# ---------------------------------------------------------------------------
def apply_filters(
    df: pd.DataFrame,
    mapping: dict[str, str],
    unidad_negocio_valor: str | None,
    rutas_valores: list[str] | None,
) -> pd.DataFrame:
    out = df.copy()

    if unidad_negocio_valor and mapping.get("unidad_negocio"):
        col = mapping["unidad_negocio"]
        out = out[out[col].astype(str).str.strip() == str(unidad_negocio_valor).strip()]

    if rutas_valores and mapping.get("ruta"):
        col = mapping["ruta"]
        out = out[out[col].astype(str).str.strip().isin([str(r).strip() for r in rutas_valores])]

    return out


# ---------------------------------------------------------------------------
# Cálculo de KPIs
# ---------------------------------------------------------------------------
def compute_kpis(
    df: pd.DataFrame,
    mapping: dict[str, str],
    venta_threshold: float = 0.0,
) -> dict:
    """
    df: ya filtrado por unidad de negocio y rutas.
    mapping: dict campo_logico -> nombre columna real. Debe incluir al menos
             'venta_mes'. Los demás son opcionales y degradan con gracia.
    """
    col_venta = mapping["venta_mes"]
    df = df.copy()
    df["_venta_mes_num"] = coerce_numeric(df[col_venta])

    sin_venta = df[df["_venta_mes_num"] <= venta_threshold].copy()
    con_venta = df[df["_venta_mes_num"] > venta_threshold].copy()

    total_clientes = len(df)
    n_sin_venta = len(sin_venta)
    n_con_venta = len(con_venta)
    avance_pct = (n_con_venta / total_clientes * 100) if total_clientes else 0.0

    # --- Frecuencia de visita ---
    frecuencia_breakdown = None
    col_freq = mapping.get("frecuencia")
    if col_freq and col_freq in df.columns:
        frecuencia_breakdown = (
            sin_venta.groupby(col_freq).size().sort_values(ascending=False)
        )

    # --- Venta promedio histórica / estimación de riesgo ---
    col_avg = mapping.get("venta_promedio_hist")
    avg_source = "columna_real"
    if col_avg and col_avg in df.columns:
        sin_venta["_avg_hist"] = coerce_numeric(sin_venta[col_avg])
    else:
        # Fallback: no hay columna de histórico -> se estima con el promedio de
        # venta de los clientes que SÍ compraron este mes, segmentado por
        # frecuencia de visita si existe (si no, promedio global).
        avg_source = "estimado"
        if col_freq and col_freq in df.columns and len(con_venta):
            promedio_por_freq = con_venta.groupby(col_freq)["_venta_mes_num"].mean()
            global_avg = con_venta["_venta_mes_num"].mean() if len(con_venta) else 0.0
            sin_venta["_avg_hist"] = sin_venta[col_freq].map(promedio_por_freq).fillna(global_avg)
        else:
            global_avg = con_venta["_venta_mes_num"].mean() if len(con_venta) else 0.0
            sin_venta["_avg_hist"] = global_avg
        sin_venta["_avg_hist"] = sin_venta["_avg_hist"].fillna(0)

    venta_en_riesgo = float(sin_venta["_avg_hist"].sum())

    # --- Top 10 urgentes ---
    cols_top10 = []
    for key in ("cliente_id", "cliente_nombre", "ruta", "frecuencia"):
        c = mapping.get(key)
        if c and c in sin_venta.columns:
            cols_top10.append(c)
    top10 = (
        sin_venta.sort_values("_avg_hist", ascending=False)
        .head(10)[cols_top10 + ["_avg_hist"]]
        .rename(columns={"_avg_hist": "Venta prom. estimada ($)"})
        if len(sin_venta)
        else pd.DataFrame(columns=cols_top10 + ["Venta prom. estimada ($)"])
    )

    # --- Status por ruta ---
    ruta_status = None
    col_ruta = mapping.get("ruta")
    if col_ruta and col_ruta in df.columns:
        df["_con_venta_flag"] = df["_venta_mes_num"] > venta_threshold
        ruta_status = (
            df.groupby(col_ruta)["_con_venta_flag"]
            .agg(con_venta="sum", total="count")
            .assign(sin_venta=lambda d: d["total"] - d["con_venta"])
            .reset_index()
        )

    return {
        "total_clientes": total_clientes,
        "n_sin_venta": n_sin_venta,
        "n_con_venta": n_con_venta,
        "avance_pct": avance_pct,
        "frecuencia_breakdown": frecuencia_breakdown,
        "venta_en_riesgo": venta_en_riesgo,
        "avg_source": avg_source,
        "top10": top10,
        "ruta_status": ruta_status,
        "sin_venta_detalle": sin_venta,
        "con_venta_detalle": con_venta,
    }
