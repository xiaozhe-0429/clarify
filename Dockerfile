# ── 多阶段构建 ─────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app
RUN pip install --no-cache-dir pdm

COPY pyproject.toml ./
RUN pdm export --prod -o requirements.txt

# ── Runtime ────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/v1/health')" || exit 1

CMD ["python", "-m", "uvicorn", "clarify.api:app", "--host", "0.0.0.0", "--port", "8000"]
