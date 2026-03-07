FROM python:3.11-slim

# Instalăm toate dependențele de sistem (Build Tools + OCR + Libs)
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    tesseract-ocr \
    tesseract-ocr-ron \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Instalăm dependențele separat pentru a folosi cache-ul Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiem restul codului
COPY . .

# Expunem portul (informativ)
EXPOSE 5000
