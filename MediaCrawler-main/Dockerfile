# ====================================
# MediaCrawler 获客系统 - 后端镜像
# 多阶段构建: builder + runtime
# ====================================
FROM python:3.11-slim AS builder

# 系统依赖(Playwright/Chromium 需要)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖文件,利用 Docker 缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ====================================
# 运行时镜像
# ====================================
FROM python:3.11-slim AS runtime

# 运行时系统依赖: Playwright Chromium 依赖 + 中文字体 + Xvfb(虚拟显示)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Playwright Chromium 运行时依赖
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libxkbfile1 \
    libasound2 \
    libatspi2.0-0 \
    libgtk-3-0 \
    # 中文字体
    fonts-noto-cjk \
    # Xvfb 虚拟显示
    xvfb \
    # 基础工具
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 复制 pip 用户安装的包
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /app

# 复制项目代码
COPY . .

# 安装 Playwright Chromium 浏览器
RUN playwright install chromium --with-deps || true

# 暴露 API 端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令: 使用 Xvfb 虚拟显示支持 Playwright
CMD ["sh", "-c", "Xvfb :99 -screen 0 1280x720x24 &> /tmp/xvfb.log & DISPLAY=:99 uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 1"]
