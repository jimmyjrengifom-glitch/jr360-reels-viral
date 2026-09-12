FROM python:3.12-alpine
RUN apk add --no-cache ffmpeg curl
RUN pip install --no-cache-dir yt-dlp fastapi uvicorn
WORKDIR /app
COPY app.py .
RUN adduser -D app && mkdir /tmp/reels && chown app /tmp/reels
USER app
EXPOSE 8080
HEALTHCHECK CMD curl -f http://localhost:8080/health || exit 1
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8080"]
