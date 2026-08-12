FROM python:3.12-slim-bookworm

ARG SENTENCE_TRANSFORMERS_VERSION=5.7.0
ARG FASTAPI_VERSION=0.141.1
ARG UVICORN_VERSION=0.52.1
ARG TORCH_VERSION=2.13.0+cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==${TORCH_VERSION}" \
 && pip install --no-cache-dir \
    "sentence-transformers==${SENTENCE_TRANSFORMERS_VERSION}" \
    "fastapi==${FASTAPI_VERSION}" \
    "uvicorn[standard]==${UVICORN_VERSION}" \
 && groupadd --gid 1000 embeddings \
 && useradd --uid 1000 --gid 1000 --create-home embeddings

WORKDIR /app
COPY --chmod=0644 app.py /app/app.py
COPY --chmod=0644 test_app.py /app/test_app.py
USER 1000:1000
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
