# KCC Farmer Helpline Assistant: API, farmer chat (/chat), expert desk (/expert),
# operator console (/). Data and built models are mounted from ./data (see
# docker-compose.yml); they are not baked into the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/cache/huggingface

WORKDIR /app

# CPU-only torch first, so requirements.txt does not pull the multi-GB CUDA build.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src
COPY config ./config

RUN useradd --create-home kcc && mkdir -p /cache/huggingface /app/data && chown -R kcc /cache /app/data
USER kcc

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status == 200 else 1)"

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
