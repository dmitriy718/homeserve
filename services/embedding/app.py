import os
import json
from contextlib import asynccontextmanager
from typing import List, Union
from urllib.error import URLError
from urllib.request import Request, urlopen
import json

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "all-minilm")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
MAX_INPUTS = int(os.getenv("MAX_EMBEDDING_INPUTS", "64"))
MAX_CHARS = int(os.getenv("MAX_EMBEDDING_CHARS", "50000"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="AI Node Embeddings", version="1.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


class EmbeddingRequest(BaseModel):
    input: Union[str, List[str]]
    model: str = MODEL_NAME


@app.get("/health")
def health():
    try:
        with urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=5) as response:
            models = json.load(response).get("models", [])
    except (OSError, URLError):
        raise HTTPException(status_code=503, detail="laptop Ollama is unavailable")
    if not any(item.get("name", "").split(":")[0] == MODEL_NAME.split(":")[0] for item in models):
        raise HTTPException(status_code=503, detail=f"{MODEL_NAME} is not available on laptop Ollama")
    return {"status": "ok", "model": MODEL_NAME, "backend": OLLAMA_BASE_URL}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "aidev"}]}


@app.post("/v1/embeddings")
def embeddings(request: EmbeddingRequest):
    if request.model != MODEL_NAME:
        raise HTTPException(status_code=400, detail=f"Only {MODEL_NAME} is loaded")
    texts = [request.input] if isinstance(request.input, str) else request.input
    if not texts or any(not isinstance(text, str) or not text for text in texts):
        raise HTTPException(status_code=400, detail="input must contain non-empty text")
    if len(texts) > MAX_INPUTS:
        raise HTTPException(status_code=413, detail=f"at most {MAX_INPUTS} inputs are allowed")
    if sum(len(text) for text in texts) > MAX_CHARS:
        raise HTTPException(status_code=413, detail=f"input exceeds {MAX_CHARS} total characters")
    payload = json.dumps({"model": MODEL_NAME, "input": texts}).encode()
    request = Request(f"{OLLAMA_BASE_URL}/api/embed", data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=180) as response:
            vectors = json.load(response)["embeddings"]
    except URLError as error:
        raise HTTPException(status_code=502, detail=f"laptop Ollama embedding request failed: {error.reason}")
    data = [{"object": "embedding", "index": i, "embedding": vector} for i, vector in enumerate(vectors)]
    token_estimate = sum(max(1, len(text.split())) for text in texts)
    return {
        "object": "list",
        "data": data,
        "model": MODEL_NAME,
        "usage": {"prompt_tokens": token_estimate, "total_tokens": token_estimate},
    }
