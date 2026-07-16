FROM python:3.11-slim

WORKDIR /app

# requirements.txt still lists Phase 1 scraping deps (playwright, PyMuPDF,
# pytesseract...) that this deployed app never imports at runtime — they're
# just unused weight here. Left as one file for now since it's the exact
# set already verified working together; split into a leaner
# requirements-deploy.txt later if image size/build time becomes a concern.
COPY requirements.txt .

# Install CPU-only torch first: the default PyPI wheel bundles ~8GB of
# CUDA/cuDNN/NCCL libraries for GPU support this deployment never uses (no
# GPU on a standard AWS instance) — that alone was responsible for most of
# this image's size. Once installed, the requirements.txt install below
# finds torch already satisfied and won't pull in the CUDA build.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "ui/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
