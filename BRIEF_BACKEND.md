Ya tienes el contrato completo en ARQUITECTURA.md de esta misma carpeta (léelo, no lo reinventes). Ahora construye el CÓDIGO REAL, no más especificación. Meta: 3-4 horas de trabajo humano total para dejarlo corriendo en un subdominio de EasyPanel (sin dominio propio, sin rate-limit ni SSRF hoy — eso queda para cuando haya tráfico real, ponytail: agregar cuando cobre el primer cliente).

Entrega EXACTAMENTE estos archivos, cada uno en su propia ruta (usa tu herramienta de escritura de archivos directamente, uno por uno):

1. `microservice/app.py` — FastAPI con `POST /v1/download` (yt-dlp descarga el video de la URL de Instagram, header `X-Internal-Token` para auth simple, devuelve el MP4 en streaming + header `X-Metadata-Base64` con views/likes/comments si yt-dlp los trae; si Instagram bloquea devuelve 422 con `download_blocked`) y `GET /health`.
2. `microservice/Dockerfile` — el de la sección 4 de ARQUITECTURA.md, tal cual.
3. `n8n/workflow_analizar.json` — el workflow de n8n IMPORTABLE (JSON exportado real de n8n, con sus nodos, conexiones y credenciales como placeholders) para `POST/GET /analizar` según la sección 3 de ARQUITECTURA.md: valida entrada, llama al microservicio o recibe el video subido, sube a Gemini Files API, espera ACTIVE, llama a generateContent con el schema y el prompt de la sección 5, calcula el score determinista, responde. Simplifica lo que no sea esencial para que corra hoy (por ejemplo: guarda el job en memoria/variable estática de n8n en vez de una base de datos aparte).
4. `n8n/workflow_multiplicar.json` — igual para `POST /multiplicar` (solo texto, sin video).
5. `DEPLOY_EASYPANEL.md` — pasos concretos de clic en EasyPanel para: crear el servicio Docker del microservicio, crear las credenciales de Gemini en n8n, importar los dos workflows y activarlos. Máximo 20 líneas, sin relleno.

No expliques de más en el chat: solo lista los 5 archivos que creaste y una línea de qué falta probar a mano.
