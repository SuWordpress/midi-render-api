import uuid
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from mido import MidiFile, MidiTrack, Message

app = FastAPI()

TMP_DIR = Path("/tmp")

# Debian installs the GM soundfont here
SOUNDFONT_PATH = Path("/usr/share/sounds/sf2/FluidR3_GM.sf2")


@app.get("/")
def root():
    return {"ok": True, "service": "midi-render-api"}


def apply_instrument_program(input_midi_path: Path, program: int) -> Path:
    if program < 0 or program > 127:
        raise HTTPException(status_code=400, detail="program must be between 0 and 127")

    mid = MidiFile(str(input_midi_path))

    # Apply program change to all channels except drums (9)
    program_track = MidiTrack()
    for ch in range(16):
        if ch == 9:
            continue
        program_track.append(Message("program_change", program=program, channel=ch, time=0))

    mid.tracks.insert(0, program_track)

    output_midi_path = input_midi_path.parent / "instrument.mid"
    mid.save(str(output_midi_path))
    return output_midi_path


@app.post("/render")
async def render_midi(
    midi: UploadFile = File(...),
    format: str = Form("mp3"),
    program: int = Form(0),
):
    fmt = (format or "").lower().strip()
    if fmt not in ("mp3", "wav"):
        raise HTTPException(status_code=400, detail="format must be mp3 or wav")

    if not SOUNDFONT_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Soundfont not found at {SOUNDFONT_PATH}"
        )

    job_id = str(uuid.uuid4())
    workdir = TMP_DIR / f"job_{job_id}"
    workdir.mkdir(parents=True, exist_ok=True)

    input_midi_path = workdir / "input.mid"
    with open(input_midi_path, "wb") as f:
        shutil.copyfileobj(midi.file, f)

    instrument_midi_path = apply_instrument_program(input_midi_path, program)

    # MIDI -> WAV
    wav_path = workdir / "output.wav"
    cmd = [
        "fluidsynth",
        "-ni",
        str(SOUNDFONT_PATH),
        str(instrument_midi_path),
        "-F",
        str(wav_path),
        "-r",
        "44100",
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=e.stderr.decode(errors="ignore"))

    if fmt == "wav":
        return FileResponse(str(wav_path), media_type="audio/wav", filename="output.wav")

    # WAV -> MP3
    mp3_path = workdir / "output.mp3"
    cmd2 = [
        "ffmpeg",
        "-y",
        "-i",
        str(wav_path),
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "4",
        str(mp3_path),
    ]

    try:
        subprocess.run(cmd2, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=e.stderr.decode(errors="ignore"))

    return FileResponse(str(mp3_path), media_type="audio/mpeg", filename="output.mp3")
