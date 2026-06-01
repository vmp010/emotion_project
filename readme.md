# Emotion Project 情緒辨識專案

本專案使用 Raspberry Pi 相機進行情緒辨識，並將辨識結果寫入 InfluxDB，再透過 Grafana 顯示即時圖表。

目前的執行方式是：

- `main.py` 直接在 Raspberry Pi 本機的 Python 虛擬環境中執行
- InfluxDB 和 Grafana 使用 Docker Compose 啟動
- `main.py` 不在 Docker container 裡執行

## 環境需求

- Raspberry Pi OS Bookworm
- Python 3.11.2
- Raspberry Pi Camera Module 3 / IMX708
- Docker 和 Docker Compose
- 專案資料夾內需要有 `face_landmarker.task`

## 安裝系統套件

相機相關套件建議使用 Raspberry Pi OS 的 `apt` 安裝，不要全部丟進 pip 裡安裝。

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip python3-picamera2 python3-libcamera python3-opencv libatlas-base-dev
```

## 建立與啟動虛擬環境

第一次建立虛擬環境：

```bash
cd ~/emotion_project
python3 -m venv --system-site-packages .venv
```

啟動虛擬環境：

```bash
source .venv/bin/activate
```

安裝 Python 套件：

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

之後每次重新開終端機，只需要進入專案資料夾並啟動虛擬環境：

```bash
cd ~/emotion_project
source .venv/bin/activate
```

## 啟動 InfluxDB 和 Grafana

`main.py` 不需要 Docker build。現在 Docker 只負責啟動 InfluxDB 和 Grafana。

```bash
cd ~/emotion_project
docker compose up -d influxdb grafana
```

查看服務狀態：

```bash
docker compose ps
```

確認 InfluxDB 是否正常：

```bash
curl http://localhost:8086/health
```

如果看到 `status` 是 `pass`，代表 InfluxDB 已經啟動成功。

## 執行主程式

執行前先確認虛擬環境已啟動：

```bash
cd ~/emotion_project
source .venv/bin/activate
```

可以先檢查 Python 語法：

```bash
python -m py_compile main.py
```

啟動情緒辨識程式：

```bash
python main.py
```

## InfluxDB 連線設定

因為 `main.py` 是在 Raspberry Pi 本機執行，所以程式連到 InfluxDB 時使用：

```text
http://localhost:8086
```

目前預設設定：

```text
INFLUX_URL=http://localhost:8086
INFLUX_TOKEN=emotion-super-token
INFLUX_ORG=emotion-org
INFLUX_BUCKET=emotion-bucket
```

如果要手動指定，可以在執行 `main.py` 前設定環境變數：

```bash
export INFLUX_URL=http://localhost:8086
export INFLUX_TOKEN=emotion-super-token
export INFLUX_ORG=emotion-org
export INFLUX_BUCKET=emotion-bucket
```

## Grafana 查看結果

Grafana 網頁：

```text
http://樹莓派IP:3000
```

如果在樹莓派本機瀏覽器開啟：

```text
http://localhost:3000
```

預設帳號密碼：

```text
帳號：admin
密碼：admin123456
```

Grafana 新增 InfluxDB data source 時，URL 要填：

```text
http://influxdb:8086
```

注意：

- `main.py` 連 InfluxDB：使用 `http://localhost:8086`
- Grafana container 連 InfluxDB container：使用 `http://influxdb:8086`

## 模型檔案

專案資料夾內需要有：

```text
face_landmarker.task
```

如果沒有，可以從 MediaPipe 官方模型下載：

```text
https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
```

## Python 套件說明

`requirements.txt` 內目前使用：

- `numpy<2`：數值運算，處理影像矩陣資料
- `mediapipe==0.10.18`：臉部 landmark 偵測
- `fer==22.2.0`：臉部情緒辨識
- `Pillow`：繪製文字與影像處理
- `tensorflow`：FER 情緒辨識模型需要使用
- `influxdb-client`：將情緒辨識結果寫入 InfluxDB

另外透過 `apt` 安裝並在虛擬環境中使用：

- `python3-picamera2`：Raspberry Pi Camera 控制
- `python3-libcamera`：Raspberry Pi 相機底層支援
- `python3-opencv`：OpenCV 影像處理

## Docker 服務說明

`docker-compose.yml` 內主要服務：

- `influxdb`：儲存情緒分數、FPS、人臉偵測狀態等時間序列資料
- `grafana`：讀取 InfluxDB 資料並顯示圖表
- `ai_app`：舊的 Docker 執行方式，目前不使用

目前只需要啟動：

```bash
docker compose up -d influxdb grafana
```

不需要啟動 `ai_app`，也不需要執行：

```bash
docker compose build ai_app
```

## 相機測試

如果懷疑相機沒有被系統抓到，先使用 Raspberry Pi 官方工具測試：

```bash
rpicam-hello --list-cameras
rpicam-hello -t 5000
```

如果 `rpicam-hello` 都顯示 `No cameras available`，代表問題在相機、排線、CAM/DISP 接頭或系統相機設定，不是 `main.py`。
