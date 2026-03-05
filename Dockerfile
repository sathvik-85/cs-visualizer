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

# Install sox (required by manim-voiceover for audio processing)
RUN apt-get update && apt-get install -y --no-install-recommends sox && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# Install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./

# Copy built frontend into backend/static (served by FastAPI)
COPY --from=frontend-build /app/frontend/dist ./static

# Output directory for Manim renders
RUN mkdir -p /tmp/manim_outputs

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
