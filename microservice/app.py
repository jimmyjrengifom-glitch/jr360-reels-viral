import asyncio
import base64
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

import yt_dlp
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel


MAX_BYTES = 150 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 120
DOWNLOAD_ROOT = Path("/tmp/reels")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")

app = FastAPI(title="JR360 Reel Downloader", docs_url=None, redoc_url=None)


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
    video = candidates[0]
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
    if not INTERNAL_TOKEN or x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail={"code": "unauthorized"})

    parsed = urlparse(payload.url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not (
        host == "instagram.com" or host.endswith(".instagram.com")
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
