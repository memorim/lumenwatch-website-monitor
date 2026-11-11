FROM docker:28-cli AS docker-cli
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LUMENWATCH_DATABASE_PATH=/data/lumenwatch.db \
    LUMENWATCH_CAPTURE_DIR=/data/captures

WORKDIR /app

COPY pyproject.toml README.md ./
COPY requirements-lock.txt ./
COPY app ./app
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

RUN python -m pip install --no-cache-dir -c requirements-lock.txt .

EXPOSE 8020

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]

