# Exotic OS — System Telemetry Log (Sample)

## Hardware Profile
- GPU: NVIDIA RTX 2060 6 GB VRAM
- CPU: AMD Ryzen 5 3600
- RAM: 16 GB DDR4 3200 MHz
- OS: Windows 11 Home 22H2

## Event Log — 2026-05-01

### GPU Temperature Spike
14:32:11 — GPU temp reached 87°C during extended render job.
Driver version: 536.40. Frame buffer utilisation: 98%.
Throttling engaged at 85°C. Clock reduced from 1680 MHz to 1200 MHz.

### RAM Pressure
14:45:03 — System committed 14.2 GB of 16 GB. Swap activity detected.
Processes: Ollama (4.1 GB), Chrome (2.8 GB), Python (1.1 GB), OS (2.4 GB).
Recommendation: close Chrome tabs before starting RAG indexing.

## Known Issues
- RTX 2060 driver 536.23 caused BSOD on VRAM allocation > 5.8 GB.
  Fixed in 536.40. Ensure driver is current before large model loads.
- Faster-Whisper float16 on 6 GB VRAM causes OOM when Ollama mistral Q8
  is resident. Use int8_float16 or swap to Q4 quantisation.
