FROM pytorch/pytorch:2.9.1-cuda13.0-cudnn9-runtime

ARG COMFYUI_TAG=v0.31.0

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/* \
 && git clone --branch "${COMFYUI_TAG}" --depth 1 https://github.com/Comfy-Org/ComfyUI.git /opt/ComfyUI \
 && pip install --no-cache-dir -r /opt/ComfyUI/requirements.txt \
 && groupadd --gid 1000 comfy \
 && useradd --uid 1000 --gid 1000 --create-home comfy \
 && chown -R 1000:1000 /opt/ComfyUI

WORKDIR /opt/ComfyUI
USER 1000:1000
EXPOSE 8188
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", "--preview-method", "none"]

