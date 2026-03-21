import ast
import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Backend directory — added to PYTHONPATH so generated scenes can import KokoroService
_BACKEND_DIR = str(Path(__file__).parent.parent)

from config import settings
from services.llm import generate_manim_code, repair_manim_code, generate_scene_graph
from scene_graph.layout import compute_layout, LayoutError
from scene_graph.codegen import generate_manim_from_scene

logger = logging.getLogger(__name__)


@dataclass
class RenderResult:
    success: bool
    video_path: Optional[str] = None
    stderr: str = ""


def validate_syntax(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, str(e)


async def run_manim(code: str, job_id: str) -> RenderResult:
    base_dir = Path(settings.manim_output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    # Each job gets its own subdirectory so the voiceover TTS cache JSON is
    # isolated — a corrupted shared cache was causing JSONDecodeError failures.
    job_dir = base_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    scene_file = job_dir / f"scene_{job_id}.py"
    scene_file.write_text(code)

    output_file = f"{job_id}.mp4"

    cmd = [
        "manim",
        "-ql",
        "--output_file", output_file,
        "--media_dir", str(job_dir),
        "--disable_caching",
        str(scene_file),
        "GeneratedScene",
    ]

    # Inherit environment and add backend to PYTHONPATH so generated scenes
    # can do `from services.kokoro_service import KokoroService`
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_BACKEND_DIR}:{existing_pp}" if existing_pp else _BACKEND_DIR

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(job_dir),
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=settings.manim_timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return RenderResult(success=False, stderr="Render timed out")

        stderr_text = stderr.decode("utf-8", errors="replace")
        stdout_text = stdout.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            logger.error("Manim render failed (rc=%d):\nSTDERR:\n%s\nSTDOUT:\n%s",
                         proc.returncode, stderr_text[-3000:], stdout_text[-1000:])
            return RenderResult(success=False, stderr=stderr_text + "\n" + stdout_text)

        video_path = _find_video(job_dir, output_file)
        if video_path:
            # Move the video out of the job subdir to base_dir so serve_video can find it,
            # then delete the job subdir (removes TTS cache, scene file, etc.)
            final_path = base_dir / output_file
            Path(video_path).rename(final_path)
            video_path = final_path

            # Move moov atom to front so browser can seek before full download
            try:
                faststart_path = str(video_path) + ".fast.mp4"
                fs_proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-i", str(video_path),
                    "-movflags", "faststart", "-c", "copy", faststart_path,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                await fs_proc.wait()
                if fs_proc.returncode == 0:
                    Path(video_path).unlink(missing_ok=True)
                    Path(faststart_path).rename(video_path)
            except Exception as ffmpeg_err:
                logger.warning("ffmpeg faststart failed (video still usable): %s", ffmpeg_err)
            return RenderResult(success=True, video_path=str(video_path))
        else:
            return RenderResult(success=False, stderr=f"Video not found.\n{stderr_text}")

    except Exception as e:
        return RenderResult(success=False, stderr=str(e))
    finally:
        # Clean up job subdir (TTS cache, scene file, intermediate renders)
        shutil.rmtree(job_dir, ignore_errors=True)


def _find_video(output_dir: Path, filename: str) -> Optional[Path]:
    for root, _, files in os.walk(output_dir):
        for f in files:
            if f == filename:
                return Path(root) / f
    stem = filename.replace(".mp4", "")
    for root, _, files in os.walk(output_dir):
        for f in files:
            if stem in f and f.endswith(".mp4"):
                return Path(root) / f
    return None


# Errors that mean the environment is broken — retrying won't help
FATAL_PATTERNS = [
    "No module named",
    "ModuleNotFoundError",
    "sox: not found",
    "command not found",
    "ImportError",
    "cannot import name",
    "plugin_manager",
    # TTS infrastructure — code regeneration can't fix these
    "Kokoro TTS server unreachable",
    "Kokoro TTS error",
    "Kokoro TTS timed out",
    # Manim version mismatch — environment issue, not a code bug
    "total run_time of 0",
    # System-level failures
    "CalledProcessError",
    "no space left on device",
    # LaTeX not installed — MathTex/Tex used in generated code
    "No such file or directory: 'latex'",
    "No such file or directory: 'xelatex'",
]

def _is_fatal(stderr: str) -> bool:
    return any(p in stderr for p in FATAL_PATTERNS)


async def render_with_healing(
    topic: str, job_id: str, sse_queue: asyncio.Queue,
    provider: str = "Anthropic", model: str = "claude-sonnet-4-6", api_key: str = "",
) -> tuple[str, str]:
    """Generate code → validate → render → self-heal. Voiceover is embedded in the Manim code."""

    await sse_queue.put({"step": "generating_code"})
    code = await generate_manim_code(topic, provider=provider, model=model, api_key=api_key, sse_queue=sse_queue)

    await sse_queue.put({"step": "validating_code"})
    valid, syntax_err = validate_syntax(code)
    if not valid:
        await sse_queue.put({"step": "repair", "attempt": 1, "error": syntax_err})
        code = await repair_manim_code(topic, code, f"SyntaxError: {syntax_err}", 1,
                                       provider=provider, model=model, api_key=api_key, sse_queue=sse_queue)
        valid, syntax_err = validate_syntax(code)
        if not valid:
            await sse_queue.put({"step": "error", "error": f"Syntax error persists after repair: {syntax_err}"})
            raise RuntimeError(f"Syntax error not fixed: {syntax_err}")

    for attempt in range(1, settings.max_self_heal_attempts + 1):
        await sse_queue.put({"step": "rendering", "attempt": attempt})
        result = await run_manim(code, job_id)

        if result.success:
            await sse_queue.put({
                "step": "complete",
                "video_url": f"/api/video/{job_id}",
                "code": code,
            })
            return result.video_path, code

        if _is_fatal(result.stderr):
            await sse_queue.put({
                "step": "error",
                "error": f"Server environment error (not fixable by retrying):\n{result.stderr[-800:]}",
            })
            raise RuntimeError("Fatal render environment error")

        if attempt < settings.max_self_heal_attempts:
            await sse_queue.put({
                "step": "repair",
                "attempt": attempt + 1,
                "error": result.stderr[-500:],
            })
            code = await repair_manim_code(topic, code, result.stderr, attempt,
                                           provider=provider, model=model, api_key=api_key, sse_queue=sse_queue)
            valid, syntax_err = validate_syntax(code)
            if not valid:
                await sse_queue.put({"step": "error", "error": f"Repair introduced syntax error: {syntax_err}"})
                raise RuntimeError(f"Repair introduced syntax error: {syntax_err}")
        else:
            await sse_queue.put({
                "step": "error",
                # Take the TAIL of stderr — the actual Python exception is always at the end
                "error": f"Failed after {settings.max_self_heal_attempts} attempts.\n\n{result.stderr[-2000:]}",
            })
            raise RuntimeError(f"Render failed after {settings.max_self_heal_attempts} attempts")

    raise RuntimeError("Unreachable")


async def render_with_healing_v2(
    topic: str, job_id: str, sse_queue: asyncio.Queue,
    provider: str = "Anthropic", model: str = "claude-sonnet-4-6", api_key: str = "",
) -> tuple[str, str]:
    """Layout-engine path: LLM → JSON scene graph → layout → code gen → Manim.
    Falls back to render_with_healing() on any pre-render failure."""

    await sse_queue.put({"step": "generating_scene_graph"})
    try:
        scene = await generate_scene_graph(
            topic, provider=provider, model=model, api_key=api_key,
            max_repair_attempts=1,
        )
        await sse_queue.put({"step": "computing_layout"})
        plan = compute_layout(scene)
        await sse_queue.put({"step": "generating_code"})
        code = generate_manim_from_scene(scene, plan)
        valid, syntax_err = validate_syntax(code)
        if not valid:
            raise RuntimeError(f"Code generator produced invalid syntax: {syntax_err}")
        logger.info("Layout engine produced code (%d chars) for job %s", len(code), job_id)
    except Exception as e:
        logger.warning("Layout engine path failed (%s) — falling back to direct LLM code gen", e)
        await sse_queue.put({"step": "generating_code"})
        return await render_with_healing(topic, job_id, sse_queue, provider, model, api_key)

    # Render the layout-engine generated code (up to 2 attempts, then fall back)
    for attempt in range(1, 3):
        await sse_queue.put({"step": "rendering", "attempt": attempt})
        result = await run_manim(code, job_id)

        if result.success:
            await sse_queue.put({
                "step": "complete",
                "video_url": f"/api/video/{job_id}",
                "code": code,
            })
            return result.video_path, code

        if _is_fatal(result.stderr):
            await sse_queue.put({
                "step": "error",
                "error": f"Server environment error (not fixable by retrying):\n{result.stderr[-800:]}",
            })
            raise RuntimeError("Fatal render environment error")

        logger.warning(
            "Layout-engine render failed (attempt %d), falling back to direct LLM code gen. stderr: %s",
            attempt, result.stderr[-300:],
        )
        await sse_queue.put({"step": "generating_code"})
        return await render_with_healing(topic, job_id, sse_queue, provider, model, api_key)

    raise RuntimeError("Unreachable")
