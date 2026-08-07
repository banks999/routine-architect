FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HOME=/app/.hf

# CPU torch + deps. Prebuilt FAISS/BM25/embeddings are committed under data/processed,
# so the image needs no model-build step at runtime.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY eval ./eval
COPY data/processed ./data/processed
COPY data/sample ./data/sample

EXPOSE 8000
# load Mongo from the committed parquet/sample, then serve
CMD ["sh", "-c", "python scripts/01_load_mongo.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
