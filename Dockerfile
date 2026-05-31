FROM debian:bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg \
    python3 python3-pip python3-venv \
    libgl1 libglib2.0-0 libdrm2 \
    && rm -rf /var/lib/apt/lists/*

# 加 Raspberry Pi 套件來源
RUN curl -fsSL https://archive.raspberrypi.com/debian/raspberrypi.gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/raspberrypi-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/raspberrypi-archive-keyring.gpg] http://archive.raspberrypi.com/debian/ bookworm main" \
    > /etc/apt/sources.list.d/raspi.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-picamera2 \
    python3-libcamera \
    rpicam-apps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN grep -v '^picamera2$' requirements.txt > /tmp/requirements-docker.txt && \
    python3 -m pip install --break-system-packages --no-cache-dir -r /tmp/requirements-docker.txt

COPY . .

CMD ["python3", "main.py"]