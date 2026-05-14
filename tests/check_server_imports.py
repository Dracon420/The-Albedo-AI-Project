import sys
sys.path.insert(0, ".")

from albedo.config import OLLAMA_MODEL, WHISPER_MODEL_SIZE, WHISPER_DEVICE
from albedo.audio.tts import synthesize_to_bytes
from albedo.verify import is_hardware_query
import fastapi
import uvicorn

print(f"config OK  -> model={OLLAMA_MODEL} whisper={WHISPER_MODEL_SIZE} device={WHISPER_DEVICE}")
print(f"tts OK     -> synthesize_to_bytes defined: {callable(synthesize_to_bytes)}")
print(f"verify OK  -> is_hardware_query('GPU crash') = {is_hardware_query('GPU crash')}")
print(f"fastapi OK -> {fastapi.__version__}")
print(f"uvicorn OK -> {uvicorn.__version__}")
print("ALL IMPORTS OK")
