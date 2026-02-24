FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    fluidsynth \
    ffmpeg \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Download a General MIDI soundfont (common default)
# If this URL ever changes, swap it for another GM .sf2 file.
RUN wget -O /app/soundfont.sf2 https://github.com/FluidSynth/fluidsynth/raw/master/sf2/FluidR3_GM.sf2

ENV PORT=8080
EXPOSE 8080

CMD ["bash", "-lc", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
