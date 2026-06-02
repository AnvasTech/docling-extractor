FROM python:3.12-slim

# System deps:
#  - tesseract (Docling's OCR backend for the complex-layout path)
#  - poppler (PDF utils), libGL/glib (OpenCV, used by RapidOCR)
#  - libgomp (ONNX Runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only PyTorch FIRST (Docling dependency) — avoids multi-GB CUDA libraries.
RUN pip install --no-cache-dir \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt requirements-rag.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# OpenDataLoader-PDF is optional (mode=rag only). Best-effort — if it can't
# install, the RAG path falls back to Docling at runtime.
RUN pip install --no-cache-dir -r requirements-rag.txt || \
    echo "opendataloader-pdf optional: skipped"

# Bake Docling layout/table models into the image (no runtime download).
# RapidOCR ships its PP-OCR ONNX models inside the wheel — nothing to download.
RUN docling-tools models download

COPY . .

EXPOSE 8000

# Single uvicorn process: the queue + job store are in-process. Tune concurrency
# with DOCLING_WORKERS, not uvicorn workers.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
