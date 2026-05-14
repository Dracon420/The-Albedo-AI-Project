FROM python:3.11-slim

# System deps for sounddevice, scipy, and Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    libportaudio2 \
    libsndfile1 \
    ffmpeg \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium for Open Interpreter web scraping
RUN playwright install --with-deps chromium

# Pre-cache OpenWakeWord base models at build time
RUN python -c "import openwakeword; openwakeword.utils.download_models()"

COPY . .

# chroma_db and user knowledge directories are bind-mounted at runtime
VOLUME ["/app/chroma_db"]

CMD ["python", "main.py"]
