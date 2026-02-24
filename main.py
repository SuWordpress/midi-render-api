import uuid
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from mido import MidiFile, MidiTrack, Message

app = FastAPI()

TMP_DIR = Path("/tmp")
SOUNDFONT_PATH = Path("/app/soundfont.sf2")


@app.get("/")
def root():
    return {"ok": True, "service": "midi-render-api"}


def apply_instrument_program(input_midi_path: Path, program: int) -> Path:
    """
    Applies the selected instrument program to ALL channels used in the MIDI
    (excluding channel 9 which is usually drums in General MIDI).
    program must be 0–127.
    """
    if program < 0 or program > 127:
        raise HTTPException(status_code=400, detail="program must be between 0 and 127")

    mid = MidiFile(str(input_midi_path))

    # Collect channels actually used in the MIDI
    used_channels = set()
    for track in mid.tracks:
        for msg in track:
            if hasattr(msg, "channel"):
                used_channels.add(msg.channel)

    # Remove drum channel (GM standard: channel 9 is drums)
    used_channels.discard(9)

    # If no channels were detected, default to channel 0
    if not used_channels:
        used_channels = {0}

    # Insert a track at the beginning with program changes for each used channel
    program_track = MidiTrack()
    for ch in sorted(used_channels):
        program_track.append(Message("program_change", program=program, channel=ch, time=0))

    mid.tracks.insert(0, program_track)

    # Save new MIDI (unique name to avoid collisions)
    output_midi_path = input_midi_path.parent / f"instrument_{program}.mid"
    mid.save(str(output_midi_path))
    return output_midi_path


@app.post("/render")
async def render_midi(
    midi: UploadFile = File(...),
    format: str = Form("mp3"),
    program: int = Form(0),
):
    fmt = (format or "").lower().strip()
    if fmt not in ["mp3", "wav"]:
        raise HTTPException(status_code=400, detail="format must be mp3 or wav")

    if not SOUNDFONT_PATH.exists():
        raise HTTPException(status_code=500, detail="Soundfont not found in container")

    # Logs (Railway)
    print("RENDER REQUEST -> program:", program, "format:", fmt, "filename:", midi.filename)

    # Create temp working directory
    job_id = str(uuid.uuid4())
    workdir = TMP_DIR / f"job_{job_id}"
    workdir.mkdir(parents=True, exist_ok=True)

    # Save uploaded midi file
    input_midi_path = workdir / "input.mid"
    with open(input_midi_path, "wb") as f:
        shutil.copyfileobj(midi.file, f)

    # Apply selected instrument
    instrument_midi_path = apply_instrument_program(input_midi_path, program)

    # MIDI -> WAV using fluidsynth
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
        err = e.stderr.decode(errors="ignore")
        print("FLUIDSYNTH ERROR:", err)
        raise HTTPException(status_code=500, detail=f"fluidsynth failed: {err}")

    if fmt == "wav":
        response = FileResponse(
            str(wav_path),
            media_type="audio/wav",
            filename=f"output_{job_id}_{program}.wav",
        )
        response.headers["Cache-Control"] = "no-store"
        print("RETURNING WAV:", wav_path)
        return response

    # WAV -> MP3 using ffmpeg
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
        err = e.stderr.decode(errors="ignore")
        print("FFMPEG ERROR:", err)
        raise HTTPException(status_code=500, detail=f"ffmpeg failed: {err}")

    response = FileResponse(
        str(mp3_path),
        media_type="audio/mpeg",
        filename=f"output_{job_id}_{program}.mp3",
    )
    response.headers["Cache-Control"] = "no-store"
    print("RETURNING MP3:", mp3_path)
    return response
