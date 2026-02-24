FROM python:3.11-slim

# Install system deps: fluidsynth + ffmpeg + wget + certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    fluidsynth \
    ffmpeg \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY main.py .

# Download a General MIDI soundfont (reliable raw link)
RUN wget -O /app/soundfont.sf2 https://raw.githubusercontent.com/FluidSynth/fluidsynth/master/sf2/FluidR3_GM.sf2

# Railway expects PORT
ENV PORT=8080
EXPOSE 8080

CMD ["bash", "-lc", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
