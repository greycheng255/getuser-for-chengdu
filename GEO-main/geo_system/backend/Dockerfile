FROM python:3.11-slim

WORKDIR /app

RUN sed -i 's|http://deb.debian.org/debian|http://mirrors.tencentyun.com/debian|g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's|http://deb.debian.org/debian-security|http://mirrors.tencentyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .

RUN pip install --no-cache-dir -i http://mirrors.tencentyun.com/pypi/simple/ --trusted-host mirrors.tencentyun.com -r requirements.txt

RUN playwright install chromium

COPY . .

ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=backend/app.py
ENV FLASK_ENV=production
ENV PYTHONPATH=/app

EXPOSE 5000

CMD ["python", "backend/app.py"]
