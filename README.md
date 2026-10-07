# Bolsa App

Escáner de acciones y ETFs con medias móviles (20, 50, 100, 200), RSI(14), score de compra (0-100) y gestión de cartera. Datos de Yahoo Finance.

- `index.html`: la interfaz.
- `api/`: funciones de Vercel que descargan los precios y calculan indicadores y score (`api/_lib.js`).
- `local/`: versión para ejecutar en el PC con Python (`python bolsa_app.py`).

Se publica en Vercel importando este repositorio (sin configuración extra). Cada cambio subido a `main` se publica solo.

El score es un indicador técnico orientativo y no constituye asesoramiento financiero.
