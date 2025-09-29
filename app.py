#!/usr/bin/env python3
import os, wave, struct, math, threading, subprocess, signal, time
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from gpiozero import Button, LED

# ===== GPIO pins (BCM) =====
BUTTON_START_PIN = 17      # toggle playback
BUTTON_MODE_PIN  = 22      # cycle modes
STATUS_LED_PIN   = 27      # optional

# ===== Audio config =====
AUDIO_DIR    = Path("/home/zainal/floodWarning/sirens")
UPLOADS_DIR  = AUDIO_DIR / "uploads"
CUSTOM_WAV   = AUDIO_DIR / "custom.wav"
SAMPLE_RATE  = 44100
BITS         = 16
CHANNELS     = 2
AMPLITUDE    = 0.75
APLAY        = ["aplay", "-q"]   # ALSA player

# ===== Modes =====
MODE_NAMES = ["flood", "earthquake", "custom"]
FLOOD_PATTERN = [("sweep", 1.2, 450, 1000), ("sweep", 1.2, 1000, 450)]
EARTHQUAKE_PATTERN = [
    ("sweep", 0.5, 600, 1600), ("silence", 0.15, 0, 0),
    ("sweep", 0.5, 600, 1600), ("silence", 0.15, 0, 0),
    ("sweep", 0.5, 600, 1600), ("silence", 1.2, 0, 0),
]
MODE_TO_FILE = {"flood": "flood.wav", "earthquake": "earthquake.wav", "custom": "custom.wav"}

# ===== State =====
current_mode_idx = 0
play_proc = None
running = False
state_lock = threading.Lock()
announce_lock = threading.Lock()  # ensure one announcement at a time

# ===== Hardware =====
button_start = Button(BUTTON_START_PIN, pull_up=True, bounce_time=0.05)
button_mode  = Button(BUTTON_MODE_PIN,  pull_up=True, bounce_time=0.05)
led = LED(STATUS_LED_PIN) if STATUS_LED_PIN is not None else None

# ===== Flask =====
app = Flask(__name__, static_folder="static", static_url_path="/static")

# ---------- Helpers ----------
def ensure_dirs():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

def make_pattern_wav(path: Path, pattern):
    frames = bytearray()
    max_amp = int((2**(BITS-1) - 1) * AMPLITUDE)
    for kind, seconds, f0, f1 in pattern:
        n = int(seconds * SAMPLE_RATE)
        if kind == "silence":
            z = (0).to_bytes(2, "little", signed=True)
            for _ in range(n):
                frames.extend(z + z)
            continue
        for i in range(n):
            t = i / SAMPLE_RATE
            freq = f0 if kind == "tone" else (f0 + (f1 - f0) * (i / max(1, n-1)))
            val = int(max_amp * math.sin(2 * math.pi * freq * t))
            s = int.to_bytes(val, 2, "little", signed=True)
            frames.extend(s + s)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(BITS // 8)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(frames)

def ensure_default_wavs():
    ensure_dirs()
    f = AUDIO_DIR / "flood.wav"
    e = AUDIO_DIR / "earthquake.wav"
    if not f.exists(): make_pattern_wav(f, FLOOD_PATTERN)
    if not e.exists(): make_pattern_wav(e, EARTHQUAKE_PATTERN)
    if not CUSTOM_WAV.exists():  # placeholder tone so "custom" works
        make_pattern_wav(CUSTOM_WAV, [("tone", 1.0, 800, 800), ("silence", 0.3, 0, 0)])

def current_mode():
    return MODE_NAMES[current_mode_idx]

def wav_for_mode(mode: str) -> Path:
    return AUDIO_DIR / MODE_TO_FILE[mode]

def start_siren():
    global play_proc, running
    with state_lock:
        if running: return
        ensure_default_wavs()
        wav = wav_for_mode(current_mode())
        play_proc = subprocess.Popen(APLAY + ["--loop=9999", str(wav)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     preexec_fn=os.setsid)
        running = True
        if led: led.on()
        print(f"[INFO] START siren ({current_mode()})")

def stop_siren():
    global play_proc, running
    with state_lock:
        if not running: return
        try:
            os.killpg(os.getpgid(play_proc.pid), signal.SIGTERM)
        except Exception:
            pass
        play_proc = None
        running = False
        if led: led.off()
        print("[INFO] STOP siren")

def toggle_siren():
    start_siren() if not running else stop_siren()

def next_mode():
    global current_mode_idx
    current_mode_idx = (current_mode_idx + 1) % len(MODE_NAMES)
    print(f"[INFO] Mode -> {current_mode()}")
    if running:
        stop_siren()
        time.sleep(0.15)
        start_siren()

def convert_to_wav(src: Path, dst: Path, stereo=True, rate=SAMPLE_RATE) -> bool:
    args = ["ffmpeg", "-y", "-i", str(src)]
    if stereo: args += ["-ac", "2"]
    if rate:   args += ["-ar", str(rate)]
    args += ["-sample_fmt", "s16", str(dst)]
    try:
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def play_once_wav(wav_path: Path):
    """Play a WAV file once (blocking) without looping."""
    try:
        subprocess.run(APLAY + [str(wav_path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

# ---------- Button callbacks ----------
button_start.when_pressed = lambda: toggle_siren()
button_mode.when_pressed  = lambda: next_mode()

# ---------- Routes ----------
@app.route("/")
def root():
    # Serve the static frontend file
    return send_from_directory(app.static_folder, "index.html")

# ----- API: Start/Stop/Mode/Status -----
@app.post("/api/start")
def api_start(): start_siren(); return jsonify(status())

@app.post("/api/stop")
def api_stop():  stop_siren();  return jsonify(status())

@app.post("/api/next_mode")
def api_next_mode(): next_mode(); return jsonify(status())

@app.get("/api/status")
def api_status(): return jsonify(status())

def status():
    return {"mode": current_mode(), "running": running, "modes": MODE_NAMES, "custom_exists": CUSTOM_WAV.exists()}

# ----- Upload custom (saved) -----
@app.post("/api/upload")
def upload_audio():
    ensure_dirs()
    f = request.files.get("file")
    if not f: return jsonify({"ok": False, "error": "no file"}), 400
    tmp = UPLOADS_DIR / f"upload_{int(time.time())}"
    name = (f.filename or "audio.webm")
    ext = "." + (name.split(".")[-1] if "." in name else "webm")
    src = tmp.with_suffix(ext)
    f.save(str(src))
    ok = convert_to_wav(src, CUSTOM_WAV)
    try: src.unlink(missing_ok=True)
    except Exception: pass
    if not ok: return jsonify({"ok": False, "error": "ffmpeg failed"}), 500
    if running and current_mode() == "custom":
        stop_siren(); time.sleep(0.15); start_siren()
    return jsonify({"ok": True})

# ----- Live announcement (not saved) -----
@app.post("/api/announce")
def announce():
    ensure_dirs()
    f = request.files.get("file")
    if not f: return jsonify({"ok": False, "error": "no file"}), 400
    with announce_lock:
        was_running = running
        if was_running: stop_siren()
        # Save temp & convert
        tmp = UPLOADS_DIR / f"announce_{int(time.time())}"
        name = (f.filename or "announce.webm")
        ext = "." + (name.split(".")[-1] if "." in name else "webm")
        src = tmp.with_suffix(ext)
        wav = tmp.with_suffix(".wav")
        try:
            f.save(str(src))
            if not convert_to_wav(src, wav):
                return jsonify({"ok": False, "error": "ffmpeg failed"}), 500
            ok = play_once_wav(wav)
        finally:
            try: src.unlink(missing_ok=True)
            except Exception: pass
            try: wav.unlink(missing_ok=True)
            except Exception: pass
        if was_running: start_siren()
        return jsonify({"ok": bool(ok)})

# ----- Main -----
if __name__ == "__main__":
    ensure_default_wavs()
    print("== Disaster Siren (split) with 2 Buttons + Flask + Live PA ==")
    print(f"GPIO Start={BUTTON_START_PIN}, Mode={BUTTON_MODE_PIN}, LED={STATUS_LED_PIN}")
    app.run(host="0.0.0.0", port=5000, threaded=True, ssl_context=("cert.pem","key.pem"))
