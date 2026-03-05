# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend
```bash
cd backend
pip install -r requirements.txt && pip install manim
GEMINI_API_KEY=... uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev       # Vite dev server on http://localhost:5174
npm run build     # tsc + vite build → frontend/dist/
```

### Docker
```bash
docker compose up --build   # Full stack on port 80
```

There are no automated tests in this repository.

## Architecture

The app accepts a CS topic, sends it through an LLM to generate Manim Python code, renders the animation, and streams progress back to the browser via SSE.

### Generation Pipeline

**Mode 1 (default, `USE_LAYOUT_ENGINE=true`):** `backend/services/manim_runner.py:render_with_healing_v2`
1. LLM generates a JSON scene graph (`backend/scene_graph/json_prompt.py`)
2. Layout engine computes positions/collision-detection (`backend/scene_graph/layout.py`)
3. Code generator emits Manim Python from layout plan (`backend/scene_graph/codegen.py`)
4. Manim renders; on failure, falls back to Mode 2 after 2 attempts

**Mode 2 (fallback):** `backend/services/manim_runner.py:render_with_healing`
1. LLM generates raw Manim code from system prompt (`backend/prompts.py`)
2. Manim renders; on failure, LLM repairs the code and retries (up to `MAX_SELF_HEAL_ATTEMPTS=3`)

All Manim output lands in `/tmp/manim_outputs/`. After serving, temp files are cleaned up except the final `.mp4`.

### Real-Time Streaming

`POST /api/generate` → returns `job_id` immediately, runs pipeline in background.
`GET /api/stream/{job_id}` → SSE stream of step events:
```json
{"step": "rendering", "attempt": 1}
{"step": "complete", "video_url": "/api/video/...", "code": "..."}
```

The frontend SSE hook (`frontend/src/hooks/useSSE.ts`) **bypasses the Vite proxy** and connects directly to `http://localhost:8000` in dev mode — this is intentional to avoid buffering of SSE frames by Vite's proxy.

### LLM Provider Selection

`backend/services/llm.py` supports Anthropic, Google Gemini, and Groq. The provider and model are determined by `X-Provider` and `X-Model` request headers (sent by the frontend). API keys can be passed via `X-API-Key` header or set server-side as env vars.

Frontend stores per-model API keys in `localStorage`. Model list with providers is hardcoded in `frontend/src/pages/Generator.tsx`.

### Manim Code Contract

All generated scenes **must** follow these rules (enforced by system prompt and `extract_code()`):
- Class name: `class GeneratedScene(VoiceoverScene):`
- First line of `construct`: `self.set_speech_service(GTTSService())`
- Background: `self.camera.background_color = "#1a1a2e"`
- All text must be ASCII-only (TTS limitation)
- Numbers in `Text()` must be wrapped in `str()`
- Wrap animations in `with self.voiceover("..."):` blocks

Screen zones (y-axis, [-4, +4] range):
- Title: y 3.0–4.0
- Stage (main content): y -2.2 to +2.8
- Caption: y -2.4 to -3.8

### Fatal Render Errors

`manim_runner.py` checks stderr for patterns that indicate the environment is broken (missing modules, missing `sox`, plugin errors). On fatal errors, retrying is skipped immediately to avoid wasting API credits.

### Deployment

Production: single Docker container built from `Dockerfile` (multi-stage: Node for frontend build, `manimcommunity/manim:v0.18.1` for runtime). FastAPI serves the built frontend from `backend/static/`. Render.com config in `render.yaml`.
