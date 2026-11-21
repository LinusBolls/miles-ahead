FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY geo ./geo
COPY model ./model
ENV GEO_DIR=/app/geo MODEL_DIR=/app/model DATA_DIR=/data
CMD ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8791", "--no-access-log", "--timeout-graceful-shutdown", "3"]
