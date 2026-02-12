FROM python:3.11-slim

# Install system deps: fluidsynth + ffmpeg + wget
RUN apt-get update && apt-get install -y --no-install-recommends \
    fluidsynth \
    ffmpeg \
    wget \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY main.py .

# Download a free SoundFont into the container
# (We’ll use a small-ish general MIDI soundfont)
RUN wget -O /app/soundfont.sf2 https://github.com/FluidSynth/fluidsynth/raw/master/sf2/VintageDreamsWaves-v2.sf2

# Railway expects PORT
ENV PORT=8080
EXPOSE 8080

CMD ["bash", "-lc", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
