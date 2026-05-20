FROM python:3.10-bookworm AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 避免交互提示
ARG DEBIAN_FRONTEND=noninteractive

# 使用阿里云 Debian 镜像源，提升下载稳定性
RUN rm -rf /etc/apt/sources.list.d/* || true && \
    printf "deb http://mirrors.aliyun.com/debian/ bookworm main contrib non-free\n" \
    "deb-src http://mirrors.aliyun.com/debian/ bookworm main contrib non-free\n" \
    "deb http://mirrors.aliyun.com/debian-security bookworm-security main contrib non-free\n" \
    "deb-src http://mirrors.aliyun.com/debian-security bookworm-security main contrib non-free\n" \
    "deb http://mirrors.aliyun.com/debian/ bookworm-updates main contrib non-free\n" \
    "deb-src http://mirrors.aliyun.com/debian/ bookworm-updates main contrib non-free\n" \
    > /etc/apt/sources.list

# 安装编译依赖和系统库
RUN apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    gcc \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    wget \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ========== 运行阶段 ==========
FROM python:3.10-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

ARG DEBIAN_FRONTEND=noninteractive

# 使用阿里云 Debian 镜像源，提升下载稳定性（运行阶段）
RUN rm -rf /etc/apt/sources.list.d/* || true && \
    printf "deb http://mirrors.aliyun.com/debian/ bookworm main contrib non-free\n" \
    "deb-src http://mirrors.aliyun.com/debian/ bookworm main contrib non-free\n" \
    "deb http://mirrors.aliyun.com/debian-security bookworm-security main contrib non-free\n" \
    "deb-src http://mirrors.aliyun.com/debian-security bookworm-security main contrib non-free\n" \
    "deb http://mirrors.aliyun.com/debian/ bookworm-updates main contrib non-free\n" \
    "deb-src http://mirrors.aliyun.com/debian/ bookworm-updates main contrib non-free\n" \
    > /etc/apt/sources.list

# 仅复制运行时需要的系统库
RUN apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制 Python 依赖
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制应用代码
COPY backend ./backend
COPY frontend ./frontend

# 创建数据目录
RUN mkdir -p data storage/uploads storage/exports logs

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

