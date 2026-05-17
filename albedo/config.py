from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL",    "llama3.2:3b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))

# Project root (two levels up: albedo/config.py → albedo/ → root)
_PROJECT_ROOT = Path(__file__).parent.parent

# --- Audio / Voice ---
PIPER_BINARY = os.getenv("PIPER_BINARY", str(_PROJECT_ROOT / "piper" / "piper.exe"))

VOICES_DIR = Path(os.getenv("VOICES_DIR", str(_PROJECT_ROOT / "voices")))

PIPER_VOICE_CORTANA = os.getenv(
    "PIPER_VOICE_CORTANA",
    str(VOICES_DIR / "en_US-kristin-medium.onnx"),
)
PIPER_VOICE_JARVIS = os.getenv(
    "PIPER_VOICE_JARVIS",
    str(VOICES_DIR / "en_US-ryan-medium.onnx"),
)

# Legacy single-model path (used as fallback when per-persona paths aren't set)
PIPER_VOICE_MODEL = os.getenv("PIPER_VOICE_MODEL", PIPER_VOICE_CORTANA)

# --- Vosk STT ---
VOSK_MODEL_PATH = os.getenv(
    "VOSK_MODEL_PATH",
    str(_PROJECT_ROOT / "vosk_models" / "vosk-model-small-en-us-0.15"),
)

# Wake word(s) — comma-separated list matched against Vosk transcription.
WAKE_WORDS = os.getenv("WAKE_WORDS", "cortana,jarvis")

AUDIO_SAMPLE_RATE = 16000   # Hz — required by Vosk
AUDIO_CHUNK_MS    = 80      # ms per audio inference frame (1280 samples)

VAD_SILENCE_THRESHOLD  = float(os.getenv("VAD_SILENCE_THRESHOLD",  "0.01"))
VAD_SILENCE_DURATION   = float(os.getenv("VAD_SILENCE_DURATION",   "1.2"))
VAD_MAX_RECORD_SECONDS = int(os.getenv("VAD_MAX_RECORD_SECONDS",   "30"))

WAKE_ACK_PHRASE = os.getenv("WAKE_ACK_PHRASE", "Yes?")

VISION_TEMPERATURE = float(os.getenv("VISION_TEMPERATURE", "0.2"))

# --- Keywords that trigger the Verify protocol ---
HARDWARE_KEYWORDS = {
    "error", "crash", "driver", "temperature", "thermal", "overheat",
    "gpu", "cpu", "ram", "memory", "vram", "bsod", "freeze", "lag",
    "bottleneck", "fps", "stuttering", "artifact", "kernel",
    "hardware", "diagnose", "diagnosis", "not working", "failed", "failure",
}
