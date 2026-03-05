FROM python:3.11-slim

# System deps for Manim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libcairo2-dev \
    libpango1.0-dev \
    pkg-config \
    python3-dev \
    build-essential \
    texlive-latex-base \
    texlive-fonts-recommended \
    texlive-latex-extra \
    dvisvgm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir manim

COPY . .

RUN mkdir -p /tmp/manim_outputs

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
