# Slim base + wheels only. geopandas/pyproj/pvlib publish manylinux wheels,
# so no compiler is needed -- installing build-essential would add ~400 MB
# for nothing.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# Requirements first so a code change does not re-download 240 MB of wheels.
COPY app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# Persistent disk mount point. SQLite on an ephemeral container filesystem
# loses every lead on redeploy.
ENV RAAH_DB_PATH=/data/raah.db
RUN mkdir -p /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; \
      sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

# Single worker: SQLite with WAL tolerates concurrent reads but not multiple
# writer processes. Scale by moving to PostgreSQL, not by adding workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
