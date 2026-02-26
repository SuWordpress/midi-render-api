import os
import tempfile
import subprocess
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from mido import MidiFile

app = FastAPI()

# Stable path provided by `fluid-soundfont-gm` package on Debian/Ubuntu
SOUNDFONT_PATH = "/usr/share/sounds/sf2/FluidR3_GM.sf2"

# General MIDI Program names (0-127)
GM_PROGRAMS = [
    "Acoustic Grand Piano","Bright Acoustic Piano","Electric Grand Piano","Honky-tonk Piano",
    "Electric Piano 1","Electric Piano 2","Harpsichord","Clavinet",
    "Celesta","Glockenspiel","Music Box","Vibraphone",
    "Marimba","Xylophone","Tubular Bells","Dulcimer",
    "Drawbar Organ","Percussive Organ","Rock Organ","Church Organ",
    "Reed Organ","Accordion","Harmonica","Tango Accordion",
    "Acoustic Guitar (nylon)","Acoustic Guitar (steel)","Electric Guitar (jazz)","Electric Guitar (clean)",
    "Electric Guitar (muted)","Overdriven Guitar","Distortion Guitar","Guitar harmonics",
    "Acoustic Bass","Electric Bass (finger)","Electric Bass (pick)","Fretless Bass",
    "Slap Bass 1","Slap Bass 2","Synth Bass 1","Synth Bass 2",
    "Violin","Viola","Cello","Contrabass",
    "Tremolo Strings","Pizzicato Strings","Orchestral Harp","Timpani",
    "String Ensemble 1","String Ensemble 2","SynthStrings 1","SynthStrings 2",
    "Choir Aahs","Voice Oohs","Synth Voice","Orchestra Hit",
    "Trumpet","Trombone","Tuba","Muted Trumpet",
    "French Horn","Brass Section","SynthBrass 1","SynthBrass 2",
    "Soprano Sax","Alto Sax","Tenor Sax","Baritone Sax",
    "Oboe","English Horn","Bassoon","Clarinet",
    "Piccolo","Flute","Recorder","Pan Flute",
    "Blown Bottle","Shakuhachi","Whistle","Ocarina",
    "Lead 1 (square)","Lead 2 (sawtooth)","Lead 3 (calliope)","Lead 4 (chiff)",
    "Lead 5 (charang)","Lead 6 (voice)","Lead 7 (fifths)","Lead 8 (bass + lead)",
    "Pad 1 (new age)","Pad 2 (warm)","Pad 3 (polysynth)","Pad 4 (choir)",
    "Pad 5 (bowed)","Pad 6 (metallic)","Pad 7 (halo)","Pad 8 (sweep)",
    "FX 1 (rain)","FX 2 (soundtrack)","FX 3 (crystal)","FX 4 (atmosphere)",
    "FX 5 (brightness)","FX 6 (goblins)","FX 7 (echoes)","FX 8 (sci-fi)",
    "Sitar","Banjo","Shamisen","Koto",
    "Kalimba","Bag pipe","Fiddle","Shanai",
    "Tinkle Bell","Agogo","Steel Drums","Woodblock",
    "Taiko Drum","Melodic Tom","Synth Drum","Reverse Cymbal",
    "Guitar Fret Noise","Breath Noise","Seashore","Bird Tweet",
    "Telephone Ring","Helicopter","Applause","Gunshot"
]


def _safe_int(value: str, default: int, min_v: int, max_v: int) -> int:
    try:
        i = int(value)
    except Exception:
        return default
    return max(min_v, min(max_v, i))


def _render_with_fluidsynth(midi_path: str, wav_path: str, program: int) -> None:
    """
    Render MIDI to WAV using fluidsynth + FluidR3_GM.sf2.
    Program is applied globally via -p (program select) where possible.
    """
    if not os.path.exists(SOUNDFONT_PATH):
        raise RuntimeError(f"SoundFont missing at {SOUNDFONT_PATH}")

    cmd = [
        "fluidsynth",
        "-ni",
        SOUNDFONT_PATH,
        midi_path,
        "-F",
        wav_path,
        "-r",
        "44100",
        "-p",
        str(program),
    ]

    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"fluidsynth failed: {p.stderr.strip() or p.stdout.strip()}")


def _wav_to_mp3(wav_path: str, mp3_path: str) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        wav_path,
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "2",
        mp3_path,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg mp3 failed: {p.stderr.strip() or p.stdout.strip()}")


def _midi_duration_seconds(midi_path: str) -> int:
    """
    Uses mido's built-in length calculation (handles tempo changes).
    Returns rounded seconds.
    """
    mf = MidiFile(midi_path)
    seconds = float(getattr(mf, "length", 0.0) or 0.0)
    if seconds <= 0:
        return 0
    return int(round(seconds))


@app.get("/")
def health():
    return {"ok": True}


@app.post("/render")
async def render(
    midi: UploadFile = File(...),
    format: str = Form("mp3"),
    program: str = Form("0"),
):
    fmt = (format or "mp3").strip().lower()
    if fmt not in ("mp3", "wav"):
        raise HTTPException(status_code=400, detail="format must be mp3 or wav")

    prog = _safe_int(program, default=0, min_v=0, max_v=127)
    instrument_name = GM_PROGRAMS[prog] if 0 <= prog < len(GM_PROGRAMS) else f"Program {prog}"

    # Create temp workspace
    with tempfile.TemporaryDirectory() as td:
        midi_path = os.path.join(td, "input.mid")
        wav_path = os.path.join(td, "output.wav")
        out_path = os.path.join(td, f"output.{fmt}")

        # Save MIDI upload
        content = await midi.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty midi file")

        with open(midi_path, "wb") as f:
            f.write(content)

        # Calculate duration from MIDI
        duration_seconds = _midi_duration_seconds(midi_path)

        # Render to WAV
        try:
            _render_with_fluidsynth(midi_path=midi_path, wav_path=wav_path, program=prog)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        # Convert if mp3
        if fmt == "mp3":
            try:
                _wav_to_mp3(wav_path=wav_path, mp3_path=out_path)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
            media_type = "audio/mpeg"
            filename = "rendered.mp3"
        else:
            # wav
            os.replace(wav_path, out_path)
            media_type = "audio/wav"
            filename = "rendered.wav"

        # FileResponse supports custom headers
        headers = {
            "X-Instrument-Name": instrument_name,
            "X-Duration-Seconds": str(duration_seconds),
            "X-Program": str(prog),
        }

        return FileResponse(
            path=out_path,
            media_type=media_type,
            filename=filename,
            headers=headers,
        )
