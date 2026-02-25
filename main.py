import uuid
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from mido import MidiFile, MidiTrack, Message

app = FastAPI()

TMP_DIR = Path("/tmp")
import os
SOUNDFONT_PATH = Path(os.getenv("SOUNDFONT_PATH", "/usr/share/sounds/sf2/FluidR3_GM.sf2"))
# ✅ GM (General MIDI) program map (0–127)
GM_PROGRAM_NAMES = {
    0: "Acoustic Grand Piano",
    1: "Bright Acoustic Piano",
    2: "Electric Grand Piano",
    3: "Honky-tonk Piano",
    4: "Electric Piano 1",
    5: "Electric Piano 2",
    6: "Harpsichord",
    7: "Clavinet",
    8: "Celesta",
    9: "Glockenspiel",
    10: "Music Box",
    11: "Vibraphone",
    12: "Marimba",
    13: "Xylophone",
    14: "Tubular Bells",
    15: "Dulcimer",
    16: "Drawbar Organ",
    17: "Percussive Organ",
    18: "Rock Organ",
    19: "Church Organ",
    20: "Reed Organ",
    21: "Accordion",
    22: "Harmonica",
    23: "Tango Accordion",
    24: "Acoustic Guitar (nylon)",
    25: "Acoustic Guitar (steel)",
    26: "Electric Guitar (jazz)",
    27: "Electric Guitar (clean)",
    28: "Electric Guitar (muted)",
    29: "Overdriven Guitar",
    30: "Distortion Guitar",
    31: "Guitar Harmonics",
    32: "Acoustic Bass",
    33: "Electric Bass (finger)",
    34: "Electric Bass (pick)",
    35: "Fretless Bass",
    36: "Slap Bass 1",
    37: "Slap Bass 2",
    38: "Synth Bass 1",
    39: "Synth Bass 2",
    40: "Violin",
    41: "Viola",
    42: "Cello",
    43: "Contrabass",
    44: "Tremolo Strings",
    45: "Pizzicato Strings",
    46: "Orchestral Harp",
    47: "Timpani",
    48: "String Ensemble 1",
    49: "String Ensemble 2",
    50: "Synth Strings 1",
    51: "Synth Strings 2",
    52: "Choir Aahs",
    53: "Voice Oohs",
    54: "Synth Voice",
    55: "Orchestra Hit",
    56: "Trumpet",
    57: "Trombone",
    58: "Tuba",
    59: "Muted Trumpet",
    60: "French Horn",
    61: "Brass Section",
    62: "Synth Brass 1",
    63: "Synth Brass 2",
    64: "Soprano Sax",
    65: "Alto Sax",
    66: "Tenor Sax",
    67: "Baritone Sax",
    68: "Oboe",
    69: "English Horn",
    70: "Bassoon",
    71: "Clarinet",
    72: "Piccolo",
    73: "Flute",
    74: "Recorder",
    75: "Pan Flute",
    76: "Blown Bottle",
    77: "Shakuhachi",
    78: "Whistle",
    79: "Ocarina",
    80: "Lead 1 (square)",
    81: "Lead 2 (sawtooth)",
    82: "Lead 3 (calliope)",
    83: "Lead 4 (chiff)",
    84: "Lead 5 (charang)",
    85: "Lead 6 (voice)",
    86: "Lead 7 (fifths)",
    87: "Lead 8 (bass + lead)",
    88: "Pad 1 (new age)",
    89: "Pad 2 (warm)",
    90: "Pad 3 (polysynth)",
    91: "Pad 4 (choir)",
    92: "Pad 5 (bowed)",
    93: "Pad 6 (metallic)",
    94: "Pad 7 (halo)",
    95: "Pad 8 (sweep)",
    96: "FX 1 (rain)",
    97: "FX 2 (soundtrack)",
    98: "FX 3 (crystal)",
    99: "FX 4 (atmosphere)",
    100: "FX 5 (brightness)",
    101: "FX 6 (goblins)",
    102: "FX 7 (echoes)",
    103: "FX 8 (sci-fi)",
    104: "Sitar",
    105: "Banjo",
    106: "Shamisen",
    107: "Koto",
    108: "Kalimba",
    109: "Bag pipe",
    110: "Fiddle",
    111: "Shanai",
    112: "Tinkle Bell",
    113: "Agogo",
    114: "Steel Drums",
    115: "Woodblock",
    116: "Taiko Drum",
    117: "Melodic Tom",
    118: "Synth Drum",
    119: "Reverse Cymbal",
    120: "Guitar Fret Noise",
    121: "Breath Noise",
    122: "Seashore",
    123: "Bird Tweet",
    124: "Telephone Ring",
    125: "Helicopter",
    126: "Applause",
    127: "Gunshot",
}


@app.get("/")
def root():
    return {"ok": True, "service": "midi-render-api"}


def apply_instrument_program(input_midi_path: Path, program: int) -> Path:
    """
    Adds a Program Change message so FluidSynth uses the selected instrument.
    program must be 0–127.
    """
    if program < 0 or program > 127:
        raise HTTPException(status_code=400, detail="program must be between 0 and 127")

    mid = MidiFile(str(input_midi_path))

    # Put program change in its own track at the top
    program_track = MidiTrack()
    program_track.append(Message("program_change", program=program, channel=0, time=0))
    mid.tracks.insert(0, program_track)

    output_midi_path = input_midi_path.parent / "instrument.mid"
    mid.save(str(output_midi_path))
    return output_midi_path


def ffprobe_duration_seconds(audio_path: Path) -> int:
    """
    Returns rounded duration in seconds using ffprobe.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    try:
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        dur = float(result.stdout.decode().strip() or "0")
        return int(round(dur))
    except Exception:
        return 0


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
        raise HTTPException(status_code=500, detail=f"Soundfont not found in container ({SOUNDFONT_PATH})")

    # Create temp working directory
    job_id = str(uuid.uuid4())
    workdir = TMP_DIR / f"job_{job_id}"
    workdir.mkdir(parents=True, exist_ok=True)

    # Save uploaded midi file
    input_midi_path = workdir / "input.mid"
    with open(input_midi_path, "wb") as f:
        shutil.copyfileobj(midi.file, f)

    # Apply instrument program
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
        raise HTTPException(status_code=500, detail=f"fluidsynth failed: {err}")

    # If user wants WAV
    if fmt == "wav":
        duration = ffprobe_duration_seconds(wav_path)
        instrument_name = GM_PROGRAM_NAMES.get(program, f"Program {program}")

        resp = FileResponse(str(wav_path), media_type="audio/wav", filename="output.wav")
        resp.headers["X-Duration-Seconds"] = str(duration)
        resp.headers["X-Program"] = str(program)
        resp.headers["X-Instrument-Name"] = instrument_name
        return resp

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
        raise HTTPException(status_code=500, detail=f"ffmpeg failed: {err}")

    # ✅ Duration + instrument name returned in headers
    duration = ffprobe_duration_seconds(mp3_path)
    instrument_name = GM_PROGRAM_NAMES.get(program, f"Program {program}")

    resp = FileResponse(str(mp3_path), media_type="audio/mpeg", filename="output.mp3")
    resp.headers["X-Duration-Seconds"] = str(duration)
    resp.headers["X-Program"] = str(program)
    resp.headers["X-Instrument-Name"] = instrument_name
    return resp

