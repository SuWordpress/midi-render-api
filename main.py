import os
import uuid
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI()

TMP_DIR = Path("/tmp")
SOUNDFONT_PATH = Path("/app/soundfont.sf2")  # we will add this in Dockerfile step

def ensure_ffmpeg():
    # Railway containers usually allow apt-get in Docker build; runtime should have ffmpeg available
    return

@app.get("/")
def root():
    return {"ok": True, "service": "midi-render-api"}

@app.post("/render")
async def render_midi(
    midi: UploadFile = File(...),
    format: str = Form("mp3"),   # mp3 or wav
):
    fmt = format.lower().strip()
    if fmt not in ["mp3", "wav"]:
        raise HTTPException(status_code=400, detail="format must be mp3 or wav")

    # Save uploaded MIDI
    job_id = str(uuid.uuid4())
    workdir = TMP_DIR / f"job_{job_id}"
    workdir.mkdir(parents=True, exist_ok=True)

    midi_path = workdir / "input.mid"
    with open(midi_path, "wb") as f:
        shutil.copyfileobj(midi.file, f)

    # Convert MIDI -> WAV using fluidsynth
    wav_path = workdir / "output.wav"

    if not SOUNDFONT_PATH.exists():
        raise HTTPException(status_code=500, detail="Soundfont not found in container")

    cmd = [
        "fluidsynth",
        "-ni",
        str(SOUNDFONT_PATH),
        str(midi_path),
        "-F",
        str(wav_path),
        "-r",
        "44100",
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"fluidsynth failed: {e.stderr.decode(errors='ignore')}")

    if fmt == "wav":
        return FileResponse(str(wav_path), media_type="audio/wav", filename="output.wav")

    # WAV -> MP3 using ffmpeg
    mp3_path = workdir / "output.mp3"
    cmd2 = ["ffmpeg", "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-q:a", "4", str(mp3_path)]

    try:
        subprocess.run(cmd2, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"ffmpeg failed: {e.stderr.decode(errors='ignore')}")

    return FileResponse(str(mp3_path), media_type="audio/mpeg", filename="output.mp3")
