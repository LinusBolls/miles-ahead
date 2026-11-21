FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app.py stations.json ./
ENV DATA_DIR=/data STATIONS=/app/stations.json
CMD ["uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8792", "--no-access-log", "--timeout-graceful-shutdown", "3"]
