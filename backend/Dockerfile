# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app/backend

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \
    for attempt in 1 2 3; do \
        pip install --retries 5 --timeout 120 -e ".[dev]" && exit 0; \
        echo "pip install failed (attempt ${attempt}/3); retrying..." >&2; \
        sleep $((attempt * 3)); \
    done; \
    exit 1

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=12 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=3)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
