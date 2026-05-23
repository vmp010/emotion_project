# 1. 放棄 slim，改用自帶編譯工具的完整版 Python 3.10
FROM python:3.10

# 2. 安裝 Linux 執行 OpenCV 必備的圖形基礎庫
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# 3. 升級 pip 並安裝套件
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]