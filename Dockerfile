FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# tini = a tiny init that reaps zombies and forwards SIGTERM for clean shutdown.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as an unprivileged user.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser /app
USER appuser

# Health check uses the bot's heartbeat file (see bot/healthcheck.py).
HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
    CMD python -m bot.healthcheck || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "bot.main"]
