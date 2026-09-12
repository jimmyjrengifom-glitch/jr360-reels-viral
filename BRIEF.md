# Brief — SaaS "Reel Viral" (nombre de trabajo) · 12/09/2026

Usa $jr360-builder-studio. Clasificación: **MVP vendible que sale a producción HOY.**

## Problema y usuario
Personas de 50+ años que publican en redes pero no saben qué hace viral un video.
Pegan la URL de un Reel (propio o ajeno) y reciben un diagnóstico y un guion listo para grabar.
La interfaz tiene que ser muy sencilla: una caja, un botón, letra grande y todo en español neutro.

## Concepto: "Multiplicador de Reels"
No empezar desde cero: partir de un Reel que ya funcionó (propio o ajeno) y recrearlo con el tema,
el formato y el escenario del usuario, en varias versiones. Es el mismo principio del "Ad Multiplier"
de Higgsfield para anuncios, pero aplicado a Reels y entregado como guiones y planes de grabación (costo $0),
no como video generado.

## Flujo en DOS pasos (el video se procesa una sola vez)
**Paso 1 — Analizar (una llamada a Gemini con el video):**
1. Entrada: URL de Instagram (principal) **o** subir el archivo de video (respaldo que siempre funciona).
   Opcional: foto de las estadísticas del Reel (captura de Insights), para leer compartidos, guardados y retención.
2. Obtener el video y las métricas públicas (vistas, likes, comentarios).
3. Transcripción + **"ADN del video"**: escena por escena, con tiempos (gancho de los primeros 3 s,
   texto en pantalla, plano, cortes, voz, giro, CTA). Es JSON reutilizable.
4. Veredicto con semáforo (viral / medio / no viral), con el criterio explícito y los datos que se usaron.
   Si fue viral: qué lo hizo viral. Si no: las razones concretas y lo que le faltó.

**Paso 2 — Multiplicar (llamada solo de texto sobre el JSON del ADN, barata; se puede repetir con "dame más"):**
5. La app pregunta **qué mantener y qué cambiar**. Son botones, no texto libre (usuarios de 50+):
   - Tema: "¿De qué trata tu cuenta?" (texto corto: "vendo seguros", "cocina casera").
   - Formato: con mi cara / sin cara con voz en off / solo texto en pantalla.
   - Escenario: casa / negocio / calle / el mismo del original.
   - Idioma: español / inglés.
   - Versiones: 3 o 6.
   Si no elige nada, se proponen opciones por defecto para que las apruebe.
6. Salida: N versiones. Cada una trae gancho, guion calcado de la estructura y los tiempos del original
   (o corregido si no fue viral), plan de grabación escena por escena (qué se ve, dónde, texto en pantalla)
   y caption listo para pegar. Cada versión con un ángulo distinto.

**Fuera de hoy, pero dejar el hueco en el contrato:**
- "Mis ganadores": pegar 3-5 Reels propios, ordenarlos por métricas, sacar el patrón común y multiplicarlo.
- Plan premium de video generado con IA (Higgsfield Ad Multiplier u otro). Cuesta créditos por video;
  arranca como servicio hecho a mano por Jimmy, no automatizado.

## Stack fijo (no proponer otro)
- VPS Contabo propio con EasyPanel y n8n ya corriendo: `https://jr360iaagency-n8n.rjyuex.easypanel.host`.
  **n8n es el backend y el orquestador.**
- Si hace falta descargar el video: un microservicio pequeño en EasyPanel (Docker con yt-dlp + ffmpeg) al que llama n8n.
- IA: **Gemini Flash, nivel gratuito** (ve el video nativo; transcribe y analiza en una sola llamada). Salida en JSON estricto.
- Frontend: página estática servida por EasyPanel. La construye Claude; tú solo defines el contrato.
- Cobro: Stripe Payment Link (sin backend de pagos). Hoy no hay cuentas de usuario.
- Presupuesto: **$0 adicional** a lo que ya se paga.

## Riesgos que la arquitectura debe resolver
- Instagram puede bloquear la descarga desde la IP de Contabo (datacenter). Diseña un plan B automático
  que caiga a "sube tu video" sin que el usuario vea un error técnico. Si sirve, evalúa cookies de una cuenta secundaria.
- Los seguidores no vienen con el Reel: define cómo se calcula "viral" con los datos disponibles y qué se le dice al usuario.
- Cuota diaria del nivel gratuito de Gemini, tiempos de 20-90 s, límite de tamaño del video, abuso del webhook
  (sin llave expuesta en el navegador, rate limit por IP) y borrar los videos después de analizarlos.

## Entrega (UN solo archivo Markdown, máximo ~200 líneas, sin código de implementación todavía)
1. Diagrama de componentes y flujo (texto o mermaid).
2. **Contrato API front ↔ n8n:** los DOS endpoints (`/analizar` y `/multiplicar`), el request
   (URL o multipart) y el response JSON completo con ejemplo (incluido cómo viaja el ADN del paso 1 al 2).
   Es la pieza crítica: Claude construye el front en paralelo contra este contrato.
3. Lista de nodos del workflow n8n en orden, con la ramificación de errores.
4. API del microservicio yt-dlp (si aplica) y su Dockerfile en 10 líneas.
5. Los DOS prompts de Gemini completos (analizar con video, multiplicar solo con texto) + el schema JSON de salida de cada uno.
6. Criterio de viralidad.
7. Seguridad mínima y límites.
8. Pasos de despliegue en EasyPanel y la prueba de verificación (qué URL de prueba y qué se espera ver).
9. Qué queda fuera de hoy y cuándo agregarlo.
10. **Tu opinión libre (sección aparte, máximo 3 ideas):** si ves algo que Jimmy y Claude no vieron y que
    le sume valor real al producto (una función, un ángulo de venta, un riesgo, una forma más simple de
    hacer algo), dilo. Por cada idea: qué es, por qué suma, cuánto cuesta y si cabe hoy.
    No la metas en la arquitectura: Jimmy decide si entra.
