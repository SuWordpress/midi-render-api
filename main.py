import uuid
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Set

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from mido import MidiFile, MidiTrack, Message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("midi-render-api")

app = FastAPI()

TMP_DIR = Path("/tmp")
SOUNDFONT_PATH = Path("/app/soundfont.sf2")


@app.get("/")
def root():
    return {"ok": True, "service": "midi-render-api"}


def _safe_rmtree(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def _detect_channels(mid: MidiFile) -> Set[int]:
    channels: Set[int] = set()
    for track in mid.tracks:
        for msg in track:
            if getattr(msg, "channel", None) is not None:
                channels.add(int(msg.channel))
    return channels


def apply_instrument_program_all_channels(input_midi_path: Path, program: int) -> Path:
    """
    Force the selected program (instrument) across ALL channels used by the MIDI.
    Many MIDIs put notes on channel != 0, so changing only channel 0 does nothing.

    - program must be 0–127
    - We avoid channel 9 by default (standard GM drums channel)
    """
    if program < 0 or program > 127:
        raise HTTPException(status_code=400, detail="program must be between 0 and 127")

    mid = MidiFile(str(input_midi_path))

    channels = _detect_channels(mid)
    if not channels:
        # If MIDI has no channel messages, assume channel 0
        channels = {0}

    logger.info(f"Detected MIDI channels: {sorted(channels)} | requested program={program}")

    # Remove existing program_change messages (so they don't override ours later)
    for t in mid.tracks:
        to_keep = []
        for msg in t:
            if msg.type == "program_change":
                continue
            to_keep.append(msg)
        t[:] = to_keep

    # Create a new first track with program_change on all relevant channels at time=0
    program_track = MidiTrack()

    for ch in sorted(channels):
        # Skip GM drum channel (channel 10 in MIDI spec, index 9)
        if ch == 9:
            continue
        program_track.append(Message("program_change", program=program, channel=ch, time=0))

    # Insert at the beginning so it's applied before note events
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
    if fmt not in ["mp3", "wav"]:
        raise HTTPException(status_code=400, detail="format must be mp3 or wav")

    if not SOUNDFONT_PATH.exists():
        raise HTTPException(status_code=500, detail="Soundfont not found in container (/app/soundfont.sf2)")

    # Create temp working directory
    job_id = str(uuid.uuid4())
    workdir = TMP_DIR / f"job_{job_id}"
    workdir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Job {job_id} started | fmt={fmt} | program={program} | filename={midi.filename}")

    # Save uploaded midi file
    input_midi_path = workdir / "input.mid"
    try:
        with open(input_midi_path, "wb") as f:
            shutil.copyfileobj(midi.file, f)
    except Exception as e:
        _safe_rmtree(workdir)
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded MIDI: {e}")

    # Apply selected instrument across channels
    instrument_midi_path = apply_instrument_program_all_channels(input_midi_path, program)

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
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.stderr:
            logger.info(f"fluidsynth stderr (job {job_id}): {p.stderr.decode(errors='ignore')[:1000]}")
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode(errors="ignore")
        _safe_rmtree(workdir)
        raise HTTPException(status_code=500, detail=f"fluidsynth failed: {err}")

    if fmt == "wav":
        return FileResponse(
            str(wav_path),
            media_type="audio/wav",
            filename="output.wav",
            background=BackgroundTask(_safe_rmtree, workdir),
        )

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
        p2 = subprocess.run(cmd2, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p2.stderr:
            logger.info(f"ffmpeg stderr (job {job_id}): {p2.stderr.decode(errors='ignore')[:1000]}")
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode(errors="ignore")
        _safe_rmtree(workdir)
        raise HTTPException(status_code=500, detail=f"ffmpeg failed: {err}")

    logger.info(f"Job {job_id} complete | returning mp3")
    return FileResponse(
        str(mp3_path),
        media_type="audio/mpeg",
        filename="output.mp3",
        background=BackgroundTask(_safe_rmtree, workdir),
    )
