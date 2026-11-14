FROM ghcr.io/astral-sh/uv:0.13.8 AS uv
FROM python:3.13.18-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PORT=8000
COPY pyproject.toml uv.lock ./
COPY services/backend/app ./services/backend/app
RUN uv sync --locked --no-dev --no-editable && useradd --uid 10001 --create-home demo
ENV PATH="/app/.venv/bin:$PATH"
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz', timeout=2)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
