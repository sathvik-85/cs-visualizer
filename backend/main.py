import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path

import aiofiles
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from services.email_sender import send_completion_email
from services.job_store import create_job, get_job
from services.manim_runner import render_with_healing, render_with_healing_v2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="CS Visualizer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response models ────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    topic: str
    notify_email: str | None = None


class GenerateResponse(BaseModel):
    job_id: str


# ── Background task ────────────────────────────────────────────────────────────

async def run_pipeline(
    job_id: str, topic: str, provider: str, model: str, api_key: str,
    notify_email: str | None = None,
) -> None:
    job = get_job(job_id)
    if not job:
        return
    try:
        pipeline = render_with_healing_v2 if settings.use_layout_engine else render_with_healing
        video_path, code = await pipeline(
            topic, job_id, job.sse_queue,
            provider=provider, model=model, api_key=api_key,
        )
        job.video_path = video_path
        job.code = code
        job.status = "complete"
        if notify_email:
            await send_completion_email(
                notify_email, topic,
                f"/api/video/{job_id}",
            )
    except Exception as exc:
        logger.error("Pipeline failed for job %s: %s", job_id, exc)
        job.status = "error"
        await job.sse_queue.put({
            "step": "error",
            "error": str(exc)[:800],
        })


# ── API endpoints ──────────────────────────────────────────────────────────────

@app.post("/api/generate", response_model=GenerateResponse)
async def generate(
    req: GenerateRequest,
    background_tasks: BackgroundTasks,
    x_api_key: str | None = Header(default=None),
    x_model: str | None = Header(default=None),
    x_provider: str | None = Header(default=None),
):
    if not req.topic or len(req.topic.strip()) < 3:
        raise HTTPException(status_code=400, detail="Topic too short")

    provider = x_provider or "Anthropic"
    model = x_model or "claude-sonnet-4-6"
    api_key = x_api_key or ""

    job_id = str(uuid.uuid4())
    create_job(job_id)
    background_tasks.add_task(
        run_pipeline, job_id, req.topic.strip(), provider, model, api_key,
        req.notify_email,
    )
    return GenerateResponse(job_id=job_id)


@app.get("/api/stream/{job_id}")
async def stream(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        # Send a comment to keep connection alive initially
        yield ": connected\n\n"
        while True:
            try:
                event = await asyncio.wait_for(job.sse_queue.get(), timeout=1.0)
                data = json.dumps(event)
                yield f"data: {data}\n\n"
                if event.get("step") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                # heartbeat
                yield ": ping\n\n"
                if job.status in ("complete", "error"):
                    break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/video/{job_id}")
async def serve_video(job_id: str, request: Request):
    job = get_job(job_id)
    if not job or not job.video_path:
        raise HTTPException(status_code=404, detail="Video not found")
    path = Path(job.video_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Video file missing from disk")

    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else file_size - 1
            end = min(end, file_size - 1)
            length = end - start + 1

            async def ranged():
                async with aiofiles.open(path, "rb") as f:
                    await f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = await f.read(min(65536, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            return StreamingResponse(
                ranged(), status_code=206, media_type="video/mp4",
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(length),
                    "Content-Disposition": f'inline; filename="{job_id}.mp4"',
                },
            )

    return FileResponse(
        path, media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{job_id}.mp4"',
        },
    )


# ── Startup: verify Manim is installed ────────────────────────────────────────

@app.on_event("startup")
async def startup_check():
    proc = await asyncio.create_subprocess_exec(
        "manim", "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode == 0:
        logger.info("Manim OK — %s", stdout.decode().strip())
    else:
        logger.warning("Manim not found — rendering will fail!")


# ── Serve frontend (production single-server mode) ────────────────────────────

_frontend_dist = Path(__file__).parent / "static"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="static")
