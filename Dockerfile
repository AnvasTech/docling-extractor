FROM python:3.12-slim

# System deps:
#  - tesseract (Docling's OCR backend for the complex-layout path)
#  - poppler (PDF utils), libGL/glib (OpenCV, used by PaddleOCR), libgomp (Paddle)
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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake models into the image so the container needs no runtime download:
#  - Docling layout/table models
#  - PaddleOCR det/rec/cls models (PP-OCRv4)
RUN docling-tools models download
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='en', show_log=False)"

COPY . .

EXPOSE 8000

# Single uvicorn process: the queue + job store are in-process. Tune concurrency
# with DOCLING_WORKERS, not uvicorn workers.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
