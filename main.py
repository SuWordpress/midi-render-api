import os
import subprocess
import tempfile
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

app = FastAPI()

# Debian package soundfont path (installed by: fluid-soundfont-gm)
DEFAULT_SF2 = "/usr/share/sounds/sf2/FluidR3_GM.sf2"

# GM program names (0-127)
GM_INSTRUMENTS = [
    "Acoustic Grand Piano","Bright Acoustic Piano","Electric Grand Piano","Honky-tonk Piano",
    "Electric Piano 1","Electric Piano 2","Harpsichord","Clavinet",
    "Celesta","Glockenspiel","Music Box","Vibraphone","Marimba","Xylophone","Tubular Bells","Dulcimer",
    "Drawbar Organ","Percussive Organ","Rock Organ","Church Organ","Reed Organ","Accordion","Harmonica","Tango Accordion",
    "Acoustic Guitar (nylon)","Acoustic Guitar (steel)","Electric Guitar (jazz)","Electric Guitar (clean)",
    "Electric Guitar (muted)","Overdriven Guitar","Distortion Guitar","Guitar Harmonics",
    "Acoustic Bass","Electric Bass (finger)","Electric Bass (pick)","Fretless Bass",
    "Slap Bass 1","Slap Bass 2","Synth Bass 1","Synth Bass 2",
    "Violin","Viola","Cello","Contrabass","Tremolo Strings","Pizzicato Strings","Orchestral Harp","Timpani",
    "String Ensemble 1","String Ensemble 2","Synth Strings 1","Synth Strings 2","Choir Aahs","Voice Oohs","Synth Choir","Orchestra Hit",
    "Trumpet","Trombone","Tuba","Muted Trumpet","French Horn","Brass Section","Synth Brass 1","Synth Brass 2",
    "Soprano Sax","Alto Sax","Tenor Sax","Baritone Sax","Oboe","English Horn","Bassoon","Clarinet",
    "Piccolo","Flute","Recorder","Pan Flute","Blown Bottle","Shakuhachi","Whistle","Ocarina",
    "Lead 1 (square)","Lead 2 (sawtooth)","Lead 3 (calliope)","Lead 4 (chiff)","Lead 5 (charang)","Lead 6 (voice)","Lead 7 (fifths)","Lead 8 (bass + lead)",
    "Pad 1 (new age)","Pad 2 (warm)","Pad 3 (polysynth)","Pad 4 (choir)","Pad 5 (bowed)","Pad 6 (metallic)","Pad 7 (halo)","Pad 8 (sweep)",
    "FX 1 (rain)","FX 2 (soundtrack)","FX 3 (crystal)","FX 4 (atmosphere)","FX 5 (brightness)","FX 6 (goblins)","FX 7 (echoes)","FX 8 (sci-fi)",
    "Sitar","Banjo","Shamisen","Koto","Kalimba","Bag Pipe","Fiddle","Shanai",
    "Tinkle Bell","Agogo","Steel Drums","Woodblock","Taiko Drum","Melodic Tom","Synth Drum","Reverse Cymbal",
    "Guitar Fret Noise","Breath Noise","Seashore","Bird Tweet","Telephone Ring","Helicopter","Applause","Gunshot",
]

def safe_int(v: Optional[str], default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default

def ffprobe_duration_seconds(path: str) -> float:
    # Uses ffprobe (comes with ffmpeg)
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return float(out) if out else 0.0

@app.post("/render")
async def render(
    midi: UploadFile = File(...),
    format: str = Form("mp3"),
    program: str = Form("0"),
):
    fmt = (format or "mp3").lower().strip()
    if fmt not in ("mp3", "wav"):
        raise HTTPException(status_code=400, detail="format must be mp3 or wav")

    prog = safe_int(program, 0)
    if prog < 0: prog = 0
    if prog > 127: prog = 127

    instrument_name = GM_INSTRUMENTS[prog] if prog < len(GM_INSTRUMENTS) else f"Program {prog}"

    sf2 = os.getenv("SOUNDFONT_PATH", DEFAULT_SF2)
    if not os.path.exists(sf2):
        raise HTTPException(status_code=500, detail=f"Soundfont not found: {sf2}")

    with tempfile.TemporaryDirectory() as td:
        midi_path = os.path.join(td, "in.mid")
        out_path = os.path.join(td, f"out.{fmt}")

        # Save MIDI upload
        with open(midi_path, "wb") as f:
            f.write(await midi.read())

        # Render using fluidsynth
        # -ni: no interactive, -F output file, -T output type, -g gain
        cmd = [
            "fluidsynth", "-ni",
            sf2,
            midi_path,
            "-F", out_path,
            "-T", "wav" if fmt == "wav" else "raw",
        ]

        # If mp3 requested, render WAV first then convert to MP3 using ffmpeg
        if fmt == "mp3":
            wav_path = os.path.join(td, "out.wav")
            cmd = ["fluidsynth", "-ni", sf2, midi_path, "-F", wav_path, "-T", "wav"]
            subprocess.check_call(cmd)

            ff_cmd = ["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-q:a", "4", out_path]
            subprocess.check_call(ff_cmd)
        else:
            subprocess.check_call(cmd)

        # Duration from output audio
        duration = ffprobe_duration_seconds(out_path)
        duration_seconds = int(round(duration))
        duration_mmss = f"{duration_seconds//60}:{duration_seconds%60:02d}"

        headers = {
            "X-Instrument-Name": instrument_name,
            "X-Program": str(prog),
            "X-Duration-Seconds": str(duration_seconds),
            "X-Duration-MMSS": duration_mmss,
        }

        media_type = "audio/mpeg" if fmt == "mp3" else "audio/wav"
        filename = f"rendered.{fmt}"
        return FileResponse(out_path, media_type=media_type, filename=filename, headers=headers)
