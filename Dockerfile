FROM python:3.12-slim

# System deps: Tesseract + Indic language packs, poppler (PDF), libGL (OpenCV).
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-tam \
    tesseract-ocr-tel \
    tesseract-ocr-kan \
    tesseract-ocr-mal \
    tesseract-ocr-hin \
    tesseract-ocr-mar \
    tesseract-ocr-ben \
    tesseract-ocr-guj \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only PyTorch FIRST — the default torch wheel bundles multi-GB CUDA/nvidia
# libraries that are useless on a CPU box and fill the disk. Installing the CPU
# build up front satisfies Docling's torch dependency without them.
RUN pip install --no-cache-dir \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the Docling layout/table models into the image so the container needs no
# model download at runtime.
RUN docling-tools models download

COPY . .

EXPOSE 8000

# Keep --workers 1: the job queue + job store live in-process, so a single
# uvicorn process is required. Raise concurrency with DOCLING_WORKERS
# (asyncio workers inside this process), not uvicorn workers.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
