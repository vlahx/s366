# STAGE 1: Compilare (aici instalăm tot ce trebuie pentru compilare pachete Python)
FROM nvidia/cuda:12.2.0-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# Instalăm tot în /usr/local ca să le putem muta ulterior
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 && \
    pip3 install --no-cache-dir -r requirements.txt

# STAGE 2: Runtime (imaginea curată)
FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

# Instalăm doar strictul necesar pentru rulare (tesseract, etc.)
RUN apt-get update && apt-get install -y \
    python3 \
    tesseract-ocr \
    tesseract-ocr-ron \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copiem tot ce am compilat din etapa 1
COPY --from=builder /usr/local /usr/local

WORKDIR /app
COPY . .

EXPOSE 5000
CMD ["python3", "run.py"]
