from pathlib import Path
from dotenv import load_dotenv
import os

# Resolve project root before load_dotenv so we always load the right .env
# regardless of what the process CWD is (shortcut, terminal, installer, etc.)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)

OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL",    "albedo-cortana-8b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))

# --- External API keys (all free tiers) ---
# Tavily web search — 1,000 queries/month free: https://app.tavily.com
TAVILY_API_KEY  = os.getenv("TAVILY_API_KEY",  "")
# Wolfram Alpha Short Answers — 2,000 queries/month free: https://developer.wolframalpha.com
WOLFRAM_API_KEY = os.getenv("WOLFRAM_API_KEY", "")

# --- Azure Cognitive Services (Tier 0 TTS + STT) ---
# Free tier: 500K Neural TTS chars/month, 5 hrs STT/month
# Create a Speech resource at https://portal.azure.com (free account, no credit card)
AZURE_SPEECH_KEY    = os.getenv("AZURE_SPEECH_KEY",    "")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "")
# Voice overrides (defaults are CortanaNeural / GuyNeural)
AZURE_TTS_VOICE_CORTANA = os.getenv("AZURE_TTS_VOICE_CORTANA", "en-US-CortanaNeural")
AZURE_TTS_VOICE_JARVIS  = os.getenv("AZURE_TTS_VOICE_JARVIS",  "en-US-GuyNeural")
AZURE_TTS_STYLE         = os.getenv("AZURE_TTS_STYLE",         "")
AZURE_STT_LANGUAGE      = os.getenv("AZURE_STT_LANGUAGE",      "en-US")

# --- Azure OpenAI (optional Tier 0 LLM — user's own deployment) ---
# Works with any Azure OpenAI deployment (GPT-3.5, GPT-4, Phi-3.5, etc.)
# Create: https://portal.azure.com → Azure OpenAI → Create deployment
AZURE_OPENAI_KEY        = os.getenv("AZURE_OPENAI_KEY",        "")
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT",   "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-35-turbo")
AZURE_OPENAI_API_VERSION= os.getenv("AZURE_OPENAI_API_VERSION","2024-02-01")

# --- XTTS-v2 local voice clone (Tier 1 TTS) ---
# Free, local, no API. Clone any voice from a 6-second WAV reference clip.
# pip install TTS  (Coqui TTS — downloads 1.8 GB model on first use)
XTTS_VOICE_SAMPLE = os.getenv("XTTS_VOICE_SAMPLE", "")   # path to .wav ref clip
XTTS_DEVICE       = os.getenv("XTTS_DEVICE",       "")   # "cuda" or "cpu"

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

# --- Idle / Dream cycle ---
IDLE_THRESHOLD_MINUTES = int(os.getenv("IDLE_THRESHOLD_MINUTES", "20"))
IDLE_POLL_INTERVAL_S   = int(os.getenv("IDLE_POLL_INTERVAL_S",   "30"))
IDLE_COOLDOWN_MINUTES  = int(os.getenv("IDLE_COOLDOWN_MINUTES",  "120"))

VAD_SILENCE_THRESHOLD  = float(os.getenv("VAD_SILENCE_THRESHOLD",  "0.01"))
VAD_SILENCE_DURATION   = float(os.getenv("VAD_SILENCE_DURATION",   "1.2"))
VAD_MAX_RECORD_SECONDS = int(os.getenv("VAD_MAX_RECORD_SECONDS",   "30"))

WAKE_ACK_PHRASE = os.getenv("WAKE_ACK_PHRASE", "Yes?")

VISION_TEMPERATURE = float(os.getenv("VISION_TEMPERATURE", "0.2"))

# --- Keywords that trigger the Verify protocol ---
# Fault/symptom indicators ONLY — generic component names (gpu, cpu, ram, vram)
# deliberately excluded. Those appear in conceptual questions ("how does VRAM
# work?") that should go straight to Gemini, not the fault-diagnosis path.
HARDWARE_KEYWORDS = {
    "error", "crash", "driver",
    "overheat", "overheating", "thermal throttle", "throttling",
    "bsod", "blue screen", "freeze", "frozen", "lag", "lagging",
    "stuttering", "stutter", "artifact", "artifacting",
    "kernel panic", "not working", "stopped working",
    "failed", "failure", "corrupted", "corrupt",
    "diagnose", "diagnosis", "troubleshoot",
}
