FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app
RUN mkdir -p /model-cache && chown app:app /model-cache

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations

USER app

EXPOSE 8000

STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "30"]
