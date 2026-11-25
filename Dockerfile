FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FXJEFE_FEATURE_POLICY=ACCEPT_ALL_FEATURES \
    FXJEFE_ALLOW_ALL_FEATURES=1 \
    FXJEFE_MIN_CONFIDENCE=0.77 \
    FXJEFE_FEATURE_BACKEND=numpy \
    FXJEFE_HEALTH_BIND=0.0.0.0 \
    FXJEFE_PROJECT_DIR=/app \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements-docker.txt /app/requirements-docker.txt
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -r /app/requirements-docker.txt

COPY . /app

EXPOSE 8080 8081 5555

HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
    CMD python -c "import json,urllib.request; body=json.load(urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=4)); loaded=[item for item in body.get('models') or [] if item.get('loaded')]; raise SystemExit(0 if loaded else 1)"

CMD ["python", "docker_entry.py"]
