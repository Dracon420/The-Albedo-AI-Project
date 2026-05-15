from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

CHAOTIC_3D_PATH = Path(os.getenv("CHAOTIC_3D_PATH", ""))
EXOTIC_OS_PATH = Path(os.getenv("EXOTIC_OS_PATH", ""))
CHROMA_DB_PATH = Path(os.getenv("CHROMA_DB_PATH", "./chroma_db"))

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))

# Indexer memory controls — tuned for 16 GB RAM.
# Chunks are added to ChromaDB in batches; IDs are checked in pages.
# Lower INDEXER_BATCH_SIZE if you see OOM during indexing (minimum: 10).
INDEXER_BATCH_SIZE = int(os.getenv("INDEXER_BATCH_SIZE", "50"))
INDEXER_ID_PAGE_SIZE = int(os.getenv("INDEXER_ID_PAGE_SIZE", "1000"))
# Max bytes read per file — files over this limit are chunked via streaming.
INDEXER_MAX_FILE_BYTES = int(os.getenv("INDEXER_MAX_FILE_BYTES", str(10 * 1024 * 1024)))  # 10 MB

# File extensions indexed per collection
CHAOTIC_3D_EXTENSIONS = {".gcode", ".cfg", ".ini", ".json", ".txt", ".md", ".xml"}
EXOTIC_OS_EXTENSIONS = {".py", ".sh", ".txt", ".md", ".log", ".json", ".yaml", ".yml", ".toml"}

COLLECTION_CHAOTIC_3D = "chaotic_3d"
COLLECTION_EXOTIC_OS = "exotic_os"

# --- Audio / Voice ---
# Path to the Piper TTS executable (download from github.com/rhasspy/piper/releases)
PIPER_BINARY = os.getenv("PIPER_BINARY", str(_PROJECT_ROOT / "piper" / "piper.exe"))

# Project root (two levels up: albedo/config.py → albedo/ → root)
_PROJECT_ROOT = Path(__file__).parent.parent

# Local voice model cache -- downloaded by setup_utility.py / Invoke-Update
VOICES_DIR = Path(os.getenv("VOICES_DIR", str(_PROJECT_ROOT / "voices")))

# Per-persona voice paths (overrideable via .env)
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

# Local wake word model cache (bundled in repo under wakewords/)
WAKEWORD_MODELS_DIR = Path(os.getenv(
    "WAKEWORD_MODELS_DIR", str(_PROJECT_ROOT / "wakewords")
))

# OpenWakeWord model — set to path of a custom .onnx, or use a built-in label.
# Train a custom model: github.com/dscripka/openWakeWord#training-new-models
WAKEWORD_MODEL = os.getenv("WAKEWORD_MODEL", "hey_jarvis")

# Faster-Whisper: keep "small" + int8_float16 to stay within 6 GB VRAM alongside Ollama.
# Bump to "medium" only after upgrading to 32 GB RAM and verifying VRAM headroom.
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8_float16")

AUDIO_SAMPLE_RATE = 16000          # Hz — required by both OpenWakeWord and Whisper
AUDIO_CHUNK_MS = 80                # ms per OpenWakeWord inference frame (1280 samples)
WAKEWORD_THRESHOLD = float(os.getenv("WAKEWORD_THRESHOLD", "0.5"))

# VAD — silence detection after wake word
VAD_SILENCE_THRESHOLD = float(os.getenv("VAD_SILENCE_THRESHOLD", "0.01"))  # RMS energy
VAD_SILENCE_DURATION = float(os.getenv("VAD_SILENCE_DURATION", "1.5"))     # seconds
VAD_MAX_RECORD_SECONDS = int(os.getenv("VAD_MAX_RECORD_SECONDS", "30"))

# Short spoken acknowledgment played immediately on wake word detection
WAKE_ACK_PHRASE = os.getenv("WAKE_ACK_PHRASE", "Yes?")

# --- Keywords that trigger the Verify protocol ---
HARDWARE_KEYWORDS = {
    "error", "crash", "driver", "temperature", "thermal", "overheat",
    "gpu", "cpu", "ram", "memory", "vram", "bsod", "freeze", "lag",
    "bottleneck", "fps", "stuttering", "artifact", "driver", "kernel",
    "hardware", "diagnose", "diagnosis", "not working", "failed", "failure",
}
