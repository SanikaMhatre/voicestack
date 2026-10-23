FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 PORT=8000 VOICESTACK_DB=/data/voicestack.db

# Run as an unprivileged user; the database lives in the /data volume.
RUN useradd --create-home --uid 10001 app && mkdir /data && chown app /data
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY voicestack ./voicestack
COPY web ./web

USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/ready', timeout=2).status==200 else 1)"

CMD ["python", "-m", "voicestack.server"]
