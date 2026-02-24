FROM python:3.11-slim

# System dependencies:
# - fluidsynth: renders MIDI -> WAV
# - ffmpeg: converts WAV -> MP3
# - fluid-soundfont-gm: General MIDI soundfont package (no wget, no 404)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fluidsynth \
    ffmpeg \
    fluid-soundfont-gm \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Railway uses PORT
ENV PORT=8080
EXPOSE 8080

CMD ["bash", "-lc", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
