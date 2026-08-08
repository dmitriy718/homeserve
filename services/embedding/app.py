import os
from typing import List, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
MODEL_CACHE = os.getenv("MODEL_CACHE", "/models")
model = SentenceTransformer(MODEL_NAME, device="cpu", cache_folder=MODEL_CACHE)

app = FastAPI(title="AI Node Embeddings", version="1.0.0")


class EmbeddingRequest(BaseModel):
    input: Union[str, List[str]]
    model: str = MODEL_NAME


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "dimensions": model.get_sentence_embedding_dimension()}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "local"}]}


@app.post("/v1/embeddings")
def embeddings(request: EmbeddingRequest):
    if request.model != MODEL_NAME:
        raise HTTPException(status_code=400, detail=f"Only {MODEL_NAME} is loaded")
    texts = [request.input] if isinstance(request.input, str) else request.input
    if not texts or any(not isinstance(text, str) or not text for text in texts):
        raise HTTPException(status_code=400, detail="input must contain non-empty text")
    vectors = model.encode(texts, normalize_embeddings=True).tolist()
    data = [{"object": "embedding", "index": i, "embedding": vector} for i, vector in enumerate(vectors)]
    token_estimate = sum(max(1, len(text.split())) for text in texts)
    return {
        "object": "list",
        "data": data,
        "model": MODEL_NAME,
        "usage": {"prompt_tokens": token_estimate, "total_tokens": token_estimate},
    }

