# 《织梦》后端：FastAPI + uvicorn（生产），监听 8000
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    ZM_DATA_DIR=/data
WORKDIR /app

# 健康检查用 Python 自带 urllib，不再 apt 安装 curl（构建不依赖 Debian 镜像源，镜像更小）
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p /data/assets /data/chroma /data/avatars && useradd -r -u 10001 zm && chown -R zm /data /app
USER zm

EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
