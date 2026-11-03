# ZEVORA — self-hosted AI coding workspace
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ZEVORA_PORT=7432

WORKDIR /app

# System deps: build tools for llama-cpp-python wheels fallback, git for MCP tools
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Non-root runtime; workspace + model cache live in volumes
RUN useradd -m zevora && chown -R zevora:zevora /app
USER zevora

EXPOSE 7432

VOLUME ["/app/data", "/home/zevora/.cache"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -sf http://127.0.0.1:7432/api/health || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7432"]
