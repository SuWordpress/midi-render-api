FROM python:3.11-slim

# System deps: fluidsynth, ffmpeg (includes ffprobe), wget
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

# ✅ Download a known good SoundFont (FluidR3_GM)
RUN wget -O /app/soundfont.sf2 \
    https://member.keymusician.com/Member/FluidR3_GM/FluidR3_GM.sf2

ENV PORT=8080
EXPOSE 8080

CMD ["bash", "-lc", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
