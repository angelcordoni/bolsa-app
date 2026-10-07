# Bag Scanner

Escáner de acciones y ETFs con medias móviles (20, 50, 100, 200), RSI(14), score de compra (0-100) y gestión de cartera. Datos de Yahoo Finance.

- `index.html`: la interfaz (mercado, favoritos, cartera y detalle; se actualiza cada 30 s).
- `lists.js`: listas de valores (S&P 500, Nasdaq 100, Dow 30, IBEX 35, ETFs), generadas con `tools/build_lists.py`.
- `api/`: funciones de Vercel que descargan los precios y calculan indicadores y score (`api/_lib.js`).
- `local/`: versión anterior para ejecutar en el PC con Python (`python bolsa_app.py`), sin favoritos ni listas completas.

Se publica en Vercel importando este repositorio (sin configuración extra). Cada cambio subido a `main` se publica solo.

El score es un indicador técnico orientativo y no constituye asesoramiento financiero.
