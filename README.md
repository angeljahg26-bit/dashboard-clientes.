# Dashboard de Recuperación de Clientes — GDL 2

App en Streamlit para detectar y priorizar clientes sin venta en el mes,
enfocada en la Unidad de Negocio **GDL 2** y las rutas **BVA116, BVA117,
BVA118, BVA124**.

## 1. Instalación

Requiere Python 3.9+. En una terminal, dentro de esta carpeta:

```bash
pip install -r requirements.txt
```

## 2. Ejecutar la app

```bash
streamlit run app.py
```

Se abrirá automáticamente en tu navegador (por defecto en `http://localhost:8501`).

## 3. Uso

1. **Sube tu archivo** de ventas del día (.csv, .xlsx o .xlsm) en el panel izquierdo.
   Puedes probar primero con `sample_data.csv` (incluido) para ver el dashboard
   funcionando con datos de ejemplo.
2. La app **detecta automáticamente** qué columna corresponde a Unidad de
   Negocio, Ruta, Cliente, Venta del mes, Frecuencia de visita, etc. Si algo
   no se detecta bien, ábrelo en **"Ajustar mapeo automático"** y corrígelo
   manualmente — no necesitas que los nombres de columna sean exactos.
3. Selecciona la **Unidad de Negocio** (GDL 2 por defecto si existe) y las
   **Rutas** a analizar (BVA116/117/118/124 por defecto si existen en tu archivo).
4. El dashboard muestra:
   - Clientes sin venta / total de cartera / avance del día (%)
   - Venta en riesgo ($) estimada
   - Clientes sin venta por frecuencia de visita
   - Estatus con venta vs. sin venta por ruta
   - Top 10 clientes urgentes por impacto económico
   - Tabla de detalle descargable en Excel y CSV

## Notas sobre "Venta en riesgo" y el Top 10

Si tu archivo trae una columna de **venta promedio histórica** por cliente,
la app la usa directamente para calcular cuánto dinero se está dejando de
ganar. Si no la trae, la app **estima** ese valor usando el promedio de venta
de los clientes que sí compraron este mes (segmentado por frecuencia de
visita cuando es posible). Esto se indica claramente en el dashboard con
un aviso ⚠️.

## Columnas que reconoce automáticamente

| Campo | Nombres de columna que reconoce (ejemplos) |
|---|---|
| Unidad de negocio | Unidad de Negocio, Sucursal, BU |
| Ruta | Ruta, Route |
| No. de cliente | Numero Cliente, Id Cliente |
| Nombre del cliente | Cliente, Razón Social |
| Venta del mes | Venta Mensual, Vtas Mens., Ventas |
| Frecuencia de visita | Frecuencia de Visita |
| Venta promedio histórica (opcional) | Venta Promedio, Ticket Promedio |

## Archivos del proyecto

- `app.py` — interfaz Streamlit (lo que ejecutas)
- `core.py` — lógica de negocio (detección de columnas, filtros, cálculo de KPIs)
- `requirements.txt` — dependencias
- `sample_data.csv` — datos de ejemplo para probar la app
