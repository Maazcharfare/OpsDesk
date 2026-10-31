FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN groupadd --system opsdesk && useradd --system --gid opsdesk --home-dir /app opsdesk
COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip && pip install -r requirements.txt
COPY main.py ./main.py
COPY scripts ./scripts
COPY static ./static
COPY templates ./templates
RUN mkdir -p /data && chown -R opsdesk:opsdesk /app /data
USER opsdesk
ENV OPSDESK_DB_PATH=/data/opsdesk.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import os,base64,urllib.request; u=os.environ['OPSDESK_USERNAME']; p=os.environ['OPSDESK_PASSWORD']; r=urllib.request.Request('http://127.0.0.1:8000/health',headers={'Authorization':'Basic '+base64.b64encode((u+':'+p).encode()).decode()}); urllib.request.urlopen(r,timeout=3)" || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
