1. EasyPanel → Project → **Create Service** → **App** → **Dockerfile**.
2. Selecciona este repositorio; contexto `microservice` y Dockerfile `Dockerfile`.
3. Nombre: `reel-downloader`; puerto interno: `8080`; 1 CPU y 512 MB RAM.
4. No agregues dominio público al microservicio.
5. Environment → agrega `INTERNAL_TOKEN` con un secreto largo y guarda.
6. Deploy → espera estado **Healthy**; prueba `http://reel-downloader:8080/health` desde la red interna.
7. Abre el servicio n8n → Environment.
8. Agrega `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-2.5-flash`, `DOWNLOADER_URL=http://reel-downloader:8080` y `DOWNLOADER_TOKEN` con el mismo secreto.
9. Define `N8N_PAYLOAD_SIZE_MAX=150` y reinicia n8n.
10. n8n → Workflows → menú **…** → **Import from File**.
11. Importa `n8n/workflow_analizar.json`.
12. Abre sus nodos Code y confirma que n8n permite leer variables `$env`.
13. Guarda y activa **JR360 - Analizar Reel v1**.
14. Importa `n8n/workflow_multiplicar.json`.
15. Guarda y activa **JR360 - Multiplicar Reel v1**.
16. Copia las Production URLs mostradas por ambos Webhook; deben terminar en `/webhook/v1/analizar` y `/webhook/v1/multiplicar`.
17. Ejecuta una carga MP4 autorizada, una URL pública y una multiplicación de 3 versiones antes de conectar el front.
