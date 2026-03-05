import asyncio
import json
from pathlib import Path

VOICE = "Daniel"  # Built-in macOS male voice (deep, natural)


async def generate_audio(narration: str, output_path: str) -> bool:
    """Convert narration to audio using macOS say command. Returns True on success."""
    if not narration or not narration.strip():
        print("TTS skipped: narration is empty")
        return False

    aiff_path = output_path.replace(".mp3", ".aiff")

    try:
        # macOS say → AIFF
        proc = await asyncio.create_subprocess_exec(
            "/usr/bin/say", "-v", VOICE, "-o", aiff_path, narration.strip(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)

        if not Path(aiff_path).exists():
            print("TTS failed: say command produced no output")
            return False

        # Convert AIFF → MP3 via ffmpeg
        proc2 = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", aiff_path, output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc2.communicate(), timeout=60)
        Path(aiff_path).unlink(missing_ok=True)

        exists = Path(output_path).exists()
        print(f"TTS {'succeeded' if exists else 'failed'}: {output_path}")
        return exists

    except Exception as e:
        print(f"TTS exception: {e}")
        return False


async def get_audio_duration(audio_path: str) -> float:
    """Get duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        audio_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        info = json.loads(stdout.decode())
        return float(info["format"]["duration"])
    except Exception:
        return 0.0


async def get_video_duration(video_path: str) -> float:
    return await get_audio_duration(video_path)


async def merge_audio_video(video_path: str, audio_path: str, output_path: str) -> bool:
    """Merge audio onto video, adjusting speed to match video length."""
    video_dur = await get_video_duration(video_path)
    audio_dur = await get_audio_duration(audio_path)

    print(f"Merging: video={video_dur:.1f}s audio={audio_dur:.1f}s")

    if video_dur <= 0 or audio_dur <= 0:
        print("Merge skipped: invalid durations")
        return False

    speed = audio_dur / video_dur
    speed = max(0.75, min(speed, 1.4))
    audio_filter = f"atempo={speed:.4f}" if abs(speed - 1.0) > 0.05 else "anull"

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-filter_complex", f"[1:a]{audio_filter}[audio]",
        "-map", "0:v",
        "-map", "[audio]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            print(f"FFmpeg merge error: {stderr.decode()[-300:]}")
            return False
        exists = Path(output_path).exists()
        print(f"Merge {'succeeded' if exists else 'failed'}: {output_path}")
        return exists
    except Exception as e:
        print(f"Merge exception: {e}")
        return False
