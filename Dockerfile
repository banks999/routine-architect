FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HOME=/app/.hf

# Deps first (cache-friendly). requirements.txt pins the CPU-only torch wheel, so no
# multi-GB CUDA stack is pulled.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model INTO the image (needs Hub access, so BEFORE the offline env).
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# Runtime is fully offline: without these, sentence-transformers still pings the HF Hub
# at startup (hangs to timeout in an air-gapped env) despite the baked-in model.
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

COPY app ./app
COPY scripts ./scripts
COPY eval ./eval
COPY data/processed ./data/processed
COPY data/sample ./data/sample

# Hugging Face Spaces runs containers as uid 1000 (app_port is set to 8000 in README.md frontmatter).
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "scripts/start.sh"]
