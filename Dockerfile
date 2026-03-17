# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python backend + Manim ───────────────────────────────────────────
# Use official Manim image — already has LaTeX, ffmpeg, Cairo, fonts, everything
FROM manimcommunity/manim:v0.18.1

USER root

# Install sox + libsox-fmt-mp3 (manim-voiceover) + Node.js (Kokoro TTS)
RUN apt-get update && apt-get install -y --no-install-recommends sox libsox-fmt-mp3 curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# Install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./

# Pre-install Kokoro TTS npm dependencies
RUN if [ -f package.json ]; then npm install; fi

# Copy built frontend into backend/static (served by FastAPI)
COPY --from=frontend-build /app/frontend/dist ./static

# Output directory for Manim renders
RUN mkdir -p /tmp/manim_outputs

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
