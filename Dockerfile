# EASE — Emergent-Stitching Architecture for Evolution
# Docker 测试镜像
FROM python:3.12-slim

LABEL org.opencontainers.image.title="EASE"
LABEL org.opencontainers.image.description="Emergent-Stitching Architecture for Evolution — Docker test"
LABEL org.opencontainers.image.version="0.2.0"

# 安装项目
WORKDIR /esae
COPY . /esae/
RUN pip install --no-cache-dir -e /esae/ && \
    pip install --no-cache-dir 'pytest>=7.0'

# 默认入口
CMD ["ease", "help"]
