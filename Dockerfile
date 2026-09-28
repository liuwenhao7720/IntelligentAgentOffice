# V-FLO 智能办公系统 · 单机镜像（海光 x86_64）
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 系统依赖（可换国内源）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# SQLAlchemy 固定 1.4（兼容当前代码与环境）
RUN pip install -r requirements.txt psycopg2-binary gunicorn

COPY app ./app
COPY web ./web
COPY tests ./tests

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
