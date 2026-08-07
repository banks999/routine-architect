FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HOME=/app/.hf HF_HUB_OFFLINE=0

# Deps first (cache-friendly). requirements.txt pins the CPU-only torch wheel, so no
# multi-GB CUDA stack is pulled.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model INTO the image so first request is instant and the app
# works fully offline (no HuggingFace download at runtime).
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY app ./app
COPY scripts ./scripts
COPY eval ./eval
COPY data/processed ./data/processed
COPY data/sample ./data/sample

EXPOSE 8000
# load Mongo from the committed parquet/sample, then serve
CMD ["sh", "-c", "python scripts/01_load_mongo.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
