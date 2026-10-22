# ClaudeReset service — small, no build toolchain in the final image.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Non-root, with the data directory owned by it. Tokens live only in the volume.
RUN useradd --system --uid 10001 --home-dir /app claudereset \
 && mkdir -p /data \
 && chown -R claudereset:claudereset /data /app
USER claudereset

VOLUME ["/data"]
EXPOSE 8790

HEALTHCHECK --interval=60s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8790/health', timeout=4).status in (200,503) else 1)"

CMD ["python", "-m", "app.main"]
