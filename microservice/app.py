import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

import yt_dlp
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel


MAX_BYTES = 150 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 90
DOWNLOAD_ROOT = Path("/tmp/reels")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")
# Allowlist también evita SSRF: solo se descargan links de estas redes.
ALLOWED_DOMAINS = ("instagram.com", "tiktok.com", "youtube.com", "youtu.be", "facebook.com", "fb.watch")

# Instagram y YouTube bloquean a yt-dlp cuando la petición sale de un centro de datos
# (comprobado el 16/09/2026: el mismo link baja desde una casa y falla desde el VPS).
# Apify lo pide desde IP residenciales y devuelve el enlace directo al MP4.
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
APIFY_ACTOR = os.environ.get("APIFY_ACTOR", "apify~instagram-reel-scraper")
APIFY_TIMEOUT_SECONDS = 150
# ponytail: bajamos el MP4 del CDN nosotros ($0). Dejar que Apify lo descargue cuesta
# $0,02 por MB, o sea ~$0,30 por reel: sale más caro que el análisis entero.
CDN_USER_AGENT = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148")

app = FastAPI(title="JR360 Reel Downloader", docs_url=None, redoc_url=None)


# ponytail: almacén en memoria; se pierde al redeploy. Usar Redis si hace falta persistir.
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
MAX_JOBS = 2000


class JobPayload(BaseModel):
    model_config = {"extra": "allow"}


def _require_internal_token(token: str | None) -> None:
    if not INTERNAL_TOKEN or token != INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail={"code": "unauthorized"})


def _is_expired(job: dict, now: datetime) -> bool:
    try:
        expires_at = datetime.fromisoformat(str(job["expires_at"]).replace("Z", "+00:00"))
        return expires_at <= now
    except (KeyError, TypeError, ValueError):
        return True


def _purge_jobs(now: datetime) -> None:
    for key in [key for key, value in JOBS.items() if _is_expired(value, now)]:
        JOBS.pop(key, None)


@app.put("/v1/jobs/{job_id}")
def put_job(
    job_id: str,
    payload: JobPayload,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> dict:
    _require_internal_token(x_internal_token)
    incoming = payload.model_dump(exclude_none=False)
    now = datetime.now(timezone.utc)
    with JOBS_LOCK:
        _purge_jobs(now)
        current = JOBS.get(job_id, {})
        JOBS[job_id] = {
            **current,
            **incoming,
            "job_id": job_id,
            "_created_at": current.get("_created_at", time.time()),
        }
        if len(JOBS) > MAX_JOBS:
            oldest = sorted(JOBS, key=lambda key: JOBS[key].get("_created_at", 0))
            for key in oldest[:len(JOBS) - MAX_JOBS]:
                JOBS.pop(key, None)
        return {key: value for key, value in JOBS[job_id].items() if key != "_created_at"}


@app.get("/v1/jobs/{job_id}")
def get_job(
    job_id: str,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> dict:
    _require_internal_token(x_internal_token)
    now = datetime.now(timezone.utc)
    with JOBS_LOCK:
        requested = JOBS.get(job_id)
        requested_expired = requested is not None and _is_expired(requested, now)
        _purge_jobs(now)
        if requested_expired:
            raise HTTPException(status_code=404, detail={"code": "job_expired"})
        job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail={"code": "job_not_found"})
        return {key: value for key, value in job.items() if key != "_created_at"}


class DownloadRequest(BaseModel):
    url: str
    job_id: str


def _blocked_code(message: str) -> str:
    text = message.lower()
    if "private" in text:
        return "private"
    if any(value in text for value in ("login", "log in", "cookies", "checkpoint")):
        return "login_required"
    if any(value in text for value in ("unsupported url", "not a valid url")):
        return "unsupported"
    return "download_blocked"


def _ensure_h264(video: Path, force: bool = False) -> Path:
    # Instagram sirve muchos Reels en VP9 dentro de MP4 y Gemini no los procesa
    # ("The file failed to be processed"). Se normaliza a H.264/AAC 720p.
    codec = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name", "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    if codec == "h264" and not force:
        return video
    out = video.with_name("normalized.mp4")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-c:v", "libx264",
         "-preset", "ultrafast", "-crf", "28", "-vf", "scale=-2:'min(1280,ih)'",
         "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)],
        check=True, timeout=200,
    )
    video.unlink(missing_ok=True)
    return out


def _apify_reel(url: str) -> dict:
    """Pide a Apify los datos del reel. Devuelve el item tal cual o {} si no sirve."""
    peticion = urllib.request.Request(
        f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"
        f"?token={APIFY_TOKEN}&timeout={APIFY_TIMEOUT_SECONDS}",
        data=json.dumps({"username": [url], "resultsLimit": 1}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(peticion, timeout=APIFY_TIMEOUT_SECONDS) as respuesta:
        items = json.load(respuesta)
    return items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}


def _descargar_archivo(url: str, destino: Path) -> None:
    """Baja el MP4 del CDN en trozos, cortando si se pasa del tope."""
    peticion = urllib.request.Request(url, headers={"User-Agent": CDN_USER_AGENT})
    with urllib.request.urlopen(peticion, timeout=DOWNLOAD_TIMEOUT_SECONDS) as respuesta:
        escrito = 0
        with destino.open("wb") as archivo:
            while trozo := respuesta.read(256 * 1024):
                escrito += len(trozo)
                if escrito > MAX_BYTES:
                    raise OverflowError("download exceeds size limit")
                archivo.write(trozo)
    if escrito == 0:
        raise RuntimeError("download_blocked: empty file from cdn")


def _metadatos_apify(item: dict) -> dict:
    numero = lambda v: v if isinstance(v, (int, float)) else None
    return {
        "views": numero(item.get("videoPlayCount")) or numero(item.get("videoViewCount")),
        "likes": numero(item.get("likesCount")),
        "comments": numero(item.get("commentsCount")),
        "caption": (item.get("caption") or None),
        "source": "apify",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _download_apify(url: str, directory: Path) -> tuple[Path, dict]:
    item = _apify_reel(url)
    enlace = item.get("videoUrl")
    if not enlace:
        raise RuntimeError("download_blocked: apify sin videoUrl")
    destino = directory / "video.mp4"
    _descargar_archivo(enlace, destino)
    video = _ensure_h264(destino)
    if video.stat().st_size > MAX_BYTES:
        raise OverflowError("download exceeds size limit")
    return video, _metadatos_apify(item)


def _obtener_video(url: str, directory: Path) -> tuple[Path, dict]:
    """Apify primero para Instagram; yt-dlp para el resto y como respaldo."""
    host = (urlparse(url).hostname or "").lower()
    if APIFY_TOKEN and (host == "instagram.com" or host.endswith(".instagram.com")):
        try:
            return _download_apify(url, directory)
        except OverflowError:
            raise
        except Exception as exc:  # el respaldo es yt-dlp: Apify puede fallar o quedarse corto
            print(f"apify falló, se intenta yt-dlp: {exc}", flush=True)
            for resto in directory.glob("video.*"):
                resto.unlink(missing_ok=True)
    return _download(url, directory)


def _download(url: str, directory: Path) -> tuple[Path, dict]:
    output = str(directory / "video.%(ext)s")
    options = {
        "format": "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
        "outtmpl": output,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 1,
        "max_filesize": MAX_BYTES,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)

    candidates = sorted(directory.glob("video.*"))
    if not candidates:
        raise RuntimeError("download_blocked: output file missing")
    video = _ensure_h264(candidates[0])
    if video.stat().st_size > MAX_BYTES:
        raise OverflowError("download exceeds size limit")

    metadata = {
        "views": info.get("view_count"),
        "likes": info.get("like_count"),
        "comments": info.get("comment_count"),
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    return video, metadata


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/v1/download")
async def download(
    payload: DownloadRequest,
    background_tasks: BackgroundTasks,
    x_internal_token: Annotated[str | None, Header()] = None,
):
    _require_internal_token(x_internal_token)

    parsed = urlparse(payload.url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not any(
        host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS
    ):
        raise HTTPException(status_code=422, detail={"code": "unsupported"})

    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="reel-", dir=DOWNLOAD_ROOT))
    try:
        video, metadata = await asyncio.wait_for(
            asyncio.to_thread(_download, payload.url, directory),
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(status_code=504, detail={"code": "timeout"})
    except OverflowError:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(status_code=413, detail={"code": "too_large"})
    except Exception as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(status_code=422, detail={"code": _blocked_code(str(exc))})

    encoded = base64.b64encode(
        json.dumps(metadata, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    background_tasks.add_task(shutil.rmtree, directory, True)
    return FileResponse(
        path=video,
        media_type="video/mp4",
        filename=f"{payload.job_id}.mp4",
        headers={"X-Metadata-Base64": encoded},
        background=background_tasks,
    )


# --- /v1/prepare: descarga (o recibe) el video, lo normaliza y lo sube a Gemini ---
# n8n corrompe los binarios al subirlos a Gemini ("The file failed to be processed"),
# así que todo el manejo de bytes vive aquí y n8n solo recibe la referencia del archivo.

GEMINI = "https://generativelanguage.googleapis.com/"
MAX_UPLOAD_BYTES = 40 * 1024 * 1024  # ponytail: el video subido viaja en base64 por n8n; subir el tope exige subida directa del navegador


class PrepareRequest(BaseModel):
    job_id: str
    url: str | None = None
    video_b64: str | None = None


class GeminiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _gemini_call(req: urllib.request.Request, timeout: int) -> urllib.request.addinfourl:
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        try:
            body = json.load(exc)
            message = body.get("error", {}).get("message", "")
        except Exception:
            message = ""
        raise GeminiError(exc.code, message[:300]) from None  # sin la URL: lleva la llave


def _gemini_upload(video: Path, key: str, display_name: str) -> dict:
    size = video.stat().st_size
    start = urllib.request.Request(
        f"{GEMINI}upload/v1beta/files?key={key}", method="POST",
        data=json.dumps({"file": {"display_name": display_name}}).encode(),
        headers={"X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                 "X-Goog-Upload-Header-Content-Length": str(size),
                 "X-Goog-Upload-Header-Content-Type": "video/mp4",
                 "Content-Type": "application/json"},
    )
    with _gemini_call(start, 15) as r:
        upload_url = r.headers["X-Goog-Upload-URL"]
    with video.open("rb") as stream:
        upload = urllib.request.Request(
            upload_url, method="POST", data=stream,
            headers={"X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize",
                     "Content-Length": str(size)},
        )
        with _gemini_call(upload, 60) as r:
            file = json.load(r)["file"]
    deadline = time.monotonic() + 80  # videos de 2 min tardan en procesarse
    while time.monotonic() < deadline:
        if file.get("state") == "ACTIVE":
            return file
        if file.get("state") == "FAILED":
            raise GeminiError(502, "file_failed: " + json.dumps(file.get("error", {}))[:200])
        time.sleep(2)
        with _gemini_call(urllib.request.Request(f"{GEMINI}v1beta/{file['name']}?key={key}"), 10) as r:
            file = json.load(r)
    raise GeminiError(504, "file_processing_timeout")


def _save_upload(video_b64: str, directory: Path) -> Path:
    estimated_size = len(video_b64.rstrip("=")) * 3 // 4
    if estimated_size > MAX_UPLOAD_BYTES:
        raise OverflowError("upload exceeds size limit")
    src = directory / "upload.bin"
    written = 0
    chunk_chars = 1024 * 1024
    with src.open("wb") as output:
        for offset in range(0, len(video_b64), chunk_chars):
            raw = base64.b64decode(video_b64[offset:offset + chunk_chars], validate=True)
            written += len(raw)
            if written > MAX_UPLOAD_BYTES:
                raise OverflowError("upload exceeds size limit")
            output.write(raw)
    return _ensure_h264(src, force=True)  # .mov/HEVC de celular -> MP4 H.264 real


@app.post("/v1/prepare")
async def prepare(
    payload: PrepareRequest,
    x_internal_token: Annotated[str | None, Header()] = None,
    x_gemini_key: Annotated[str | None, Header()] = None,
):
    _require_internal_token(x_internal_token)
    if not x_gemini_key:
        raise HTTPException(status_code=400, detail={"code": "missing_gemini_key"})
    if bool(payload.url) == bool(payload.video_b64):
        raise HTTPException(status_code=422, detail={"code": "unsupported"})

    metadata = {"views": None, "likes": None, "comments": None,
                "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="prep-", dir=DOWNLOAD_ROOT))
    try:
        try:
            if payload.url:
                parsed = urlparse(payload.url)
                host = (parsed.hostname or "").lower()
                if parsed.scheme not in {"http", "https"} or not any(
                    host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS
                ):
                    raise HTTPException(status_code=422, detail={"code": "unsupported"})
                video, metadata = await asyncio.wait_for(
                    asyncio.to_thread(_obtener_video, payload.url, directory),
                    timeout=DOWNLOAD_TIMEOUT_SECONDS + APIFY_TIMEOUT_SECONDS,
                )
            else:
                video = await asyncio.to_thread(_save_upload, payload.video_b64, directory)
        except HTTPException:
            raise
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail={"code": "timeout"})
        except OverflowError:
            raise HTTPException(status_code=413, detail={"code": "too_large"})
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"code": _blocked_code(str(exc))})

        try:
            file = await asyncio.to_thread(_gemini_upload, video, x_gemini_key, payload.job_id)
        except GeminiError as exc:
            status = 429 if exc.status == 429 else 502
            raise HTTPException(status_code=status, detail={"code": "gemini_error", "status": exc.status, "message": str(exc)})
    finally:
        shutil.rmtree(directory, ignore_errors=True)

    return {"file_name": file["name"], "file_uri": file["uri"],
            "mime_type": file.get("mimeType", "video/mp4"), "metrics": metadata}
