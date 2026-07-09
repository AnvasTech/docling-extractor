FROM python:3.12-slim

# System deps:
#  - tesseract + Indic language packs (ta/hi/ml/te/kn/gu/bn) and OSD script
#    detection data — used by the sampler, the Tesseract extractor, and
#    Docling's OCR stage
#  - poppler (PDF utils), libGL/glib (OpenCV, used by EasyOCR)
#  - libgomp (torch/onnx runtimes)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-osd \
    tesseract-ocr-tam \
    tesseract-ocr-hin \
    tesseract-ocr-mal \
    tesseract-ocr-tel \
    tesseract-ocr-kan \
    tesseract-ocr-guj \
    tesseract-ocr-ben \
    tesseract-ocr-mar \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only PyTorch FIRST (Docling + EasyOCR dependency) — avoids multi-GB CUDA libraries.
RUN pip install --no-cache-dir \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt requirements-rag.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# OpenDataLoader-PDF is optional (mode=rag only). Best-effort — if it can't
# install, the RAG path falls back to Docling at runtime.
RUN pip install --no-cache-dir -r requirements-rag.txt || \
    echo "opendataloader-pdf optional: skipped"

# Bake Docling layout/table models into the image (no runtime download).
RUN docling-tools models download

# Bake EasyOCR detection + per-language recognition models (te/kn/bn/hi each
# ship their own recognition model; en rides along in every reader). Tamil is
# deliberately absent: the upstream tamil.pth asset was replaced with a
# 143-class model that no easyocr release can load — Tamil routes to
# Tesseract + the VLM lane instead (see core/languages.py).
RUN python -c "import easyocr; [easyocr.Reader([l, 'en'], gpu=False, verbose=False) for l in ('te', 'kn', 'bn', 'hi')]"

COPY . .

EXPOSE 8000

# Single uvicorn process: the queue + job store are in-process. Tune concurrency
# with DOCLING_WORKERS, not uvicorn workers.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
