# AutoCollab: the app, Chromium for the agents, run as an unprivileged user.
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    # browser-use adds --no-sandbox and --disable-dev-shm-usage to Chromium (the container is the sandbox)
    IN_DOCKER=true \
    APP_HOST=0.0.0.0 \
    APP_PORT=8800 \
    BROWSER_PATH= \
    BROWSER_HEADLESS=true \
    ANONYMIZED_TELEMETRY=false

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && playwright install --with-deps chromium \
 # xvfb: a virtual screen, so a run started with "Afficher le navigateur" works instead of failing
 && apt-get install -y --no-install-recommends xvfb xauth tini \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 app \
 && mkdir -p /app/data /app/runs /home/app/.autocollab \
 && chown -R app:app /app /home/app/.autocollab

COPY --chown=app:app . .

USER app
EXPOSE 8800
VOLUME ["/app/data", "/app/runs", "/home/app/.autocollab"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8800/login', timeout=4)"

ENTRYPOINT ["tini", "--"]
CMD ["xvfb-run", "-a", "--server-args=-screen 0 1280x800x24", "python", "run.py"]
