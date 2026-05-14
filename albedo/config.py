from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

CHAOTIC_3D_PATH = Path(os.getenv("CHAOTIC_3D_PATH", ""))
EXOTIC_OS_PATH = Path(os.getenv("EXOTIC_OS_PATH", ""))
CHROMA_DB_PATH = Path(os.getenv("CHROMA_DB_PATH", "./chroma_db"))

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))

# File extensions indexed per collection
CHAOTIC_3D_EXTENSIONS = {".gcode", ".cfg", ".ini", ".json", ".txt", ".md", ".xml"}
EXOTIC_OS_EXTENSIONS = {".py", ".sh", ".txt", ".md", ".log", ".json", ".yaml", ".yml", ".toml"}

COLLECTION_CHAOTIC_3D = "chaotic_3d"
COLLECTION_EXOTIC_OS = "exotic_os"

# Keywords that trigger the Verify protocol
HARDWARE_KEYWORDS = {
    "error", "crash", "driver", "temperature", "thermal", "overheat",
    "gpu", "cpu", "ram", "memory", "vram", "bsod", "freeze", "lag",
    "bottleneck", "fps", "stuttering", "artifact", "driver", "kernel",
    "hardware", "diagnose", "diagnosis", "not working", "failed", "failure",
}
