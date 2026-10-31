FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# Tesseract for OCR of scanned PDFs (English + Hindi language packs).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

RUN useradd --create-home --uid 10001 app && mkdir -p /data/storage && chown -R app /data
USER app
ENV STORAGE_DIR=/data/storage
EXPOSE 8000

# Migrates, optionally seeds (SEED_ON_START), then serves the website and API on $PORT (default 8000). See start.py.
CMD ["python", "start.py"]
