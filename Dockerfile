FROM python:3.12-slim

# Install system deps — NO docker CLI (avoid version mismatch with NAS daemon)
RUN apt-get update && apt-get install -y \
    git curl \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libatspi2.0-0 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

COPY app.py .
COPY VERSION .
COPY templates/ templates/
RUN mkdir -p /data

EXPOSE 7895
CMD ["python", "app.py"]
