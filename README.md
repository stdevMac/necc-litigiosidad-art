# NECC · Litigiosidad ART

Extracción automática y verificable de los indicadores de litigiosidad que las ART informan en sus Notas a los
Estados Contables (RGAA 33.4.1.6.1.6 y 30.1.1.3 d). Trabajo final de Text Mining, Maestría en Ciencia de Datos,
Universidad Austral (octubre 2026).

**En línea:** <https://tm.marcosmaceo.com>, con la [presentación](https://tm.marcosmaceo.com/presentacion/) y la
[prueba de concepto](https://tm.marcosmaceo.com/poc/) en modo demo (solo lectura, consultas con tope diario).

| Entregable | Dónde |
|---|---|
| Presentación (reveal.js, funciona sin internet) | `presentacion/index.html`: abrirla en el navegador; `S` muestra las notas del orador. Versión PDF: `presentacion/NECC_Litigiosidad_ART.pdf` (se regenera abriendo `index.html?print-pdf` en Chrome → Guardar como PDF, márgenes "Ninguno", con gráficos de fondo) |
| Documento de resumen | `documentos/resumen_ejecutivo.md` / `.docx` |
| MVP (pipeline de punta a punta + interfaz web) | `mvp/`: ver `mvp/README.md` |
| Despliegue de la demo pública | `deploy/`: Cloudflare Worker + Container |

Las notas de ejemplo (`mvp/data/muestras/`) son públicas: se presentan ante la SSN. El requerimiento del cliente
(Info NECC) y el material del curso no se publican.

Inicio rápido:

```bash
cd mvp && uv sync && cp .env.example .env   # completar GEMINI_API_KEY
npm --prefix web install && npm --prefix web run build
uv run necc ejecutar data/muestras && uv run necc ui   # http://localhost:8000
```

## Despliegue (tm.marcosmaceo.com)

Un Worker de Cloudflare sirve los estáticos (inicio, `/presentacion`, `/poc`) y reenvía `/poc/api/*` a un
Cloudflare Container con el backend (`mvp/Dockerfile`, modo demo `NECC_DEMO=1`). El Worker lleva el tope diario
de consultas (`CONSULTAS_POR_DIA`). Requiere el plan Workers Paid y Docker corriendo.

```bash
cd mvp && uv run necc ejecutar data/muestras   # la imagen incluye la base ya procesada
cd ../deploy && npm install
npx wrangler login
npx wrangler secret put GEMINI_API_KEY
./construir.sh && npx wrangler deploy
```
