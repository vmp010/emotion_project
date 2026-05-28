# Emotion Project — Web Dashboard 實作計畫

> 為 `emotion_project` 加入手機網頁儀表板（RWD），與現有的 OpenCV 顯示、InfluxDB + Grafana 共存。
> 樹莓派上運行，剩餘約 25GB 空間，新增佔用 **~200 MB**（主要是輕量 Docker image）。

---

## 1. 架構總覽

### 1.1 上線架構（全部在樹莓派 Docker）

```
┌──────────────────────────────────────────────────────────────────┐
│                       Raspberry Pi                               │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Docker Compose                                          │   │
│  │                                                          │   │
│  │  ┌──────────┐    ┌──────────┐    ┌──────────┐          │   │
│  │  │ influxdb │    │ grafana  │    │  ai_app  │          │   │
│  │  │ :8086    │◄───│ :3000    │    │ (main.py)│          │   │
│  │  └──────────┘    └──────────┘    └────┬─────┘          │   │
│  │                                       │ 寫入 InfluxDB   │   │
│  │  ┌──────────┐                         │                 │   │
│  │  │ web_app  │◄──────── 讀取 InfluxDB ─┘                 │   │
│  │  │ :5000    │    (emotion_server.py)                    │   │
│  │  └────┬─────┘                                           │   │
│  └───────┼─────────────────────────────────────────────────┘   │
│          │ 提供前端靜態檔 + SSE 即時推送                         │
└──────────┼─────────────────────────────────────────────────────┘
           │ Tailscale / 區域網路
           │ http://樹莓派IP:5000
           │
     ┌─────┴──────┐      ┌──────────┐
     │  筆電瀏覽器  │      │ 手機瀏覽器 │
     │ (開發/展示)  │      │ (主要使用) │
     └────────────┘      └──────────┘
```

### 1.2 Docker Service 關係

```
services:
  influxdb  ─── 資料庫，儲存情緒時間序列資料
  grafana   ─── 儀表板（保留原有）
  ai_app    ─── main.py，情緒辨識 + 寫入 InfluxDB（不改）
  web_app   ─── [新增] emotion_server.py，讀 InfluxDB + 提供前端
```

---

## 2. Tailscale VPN 整合

### 2.1 為什麼用 Tailscale

| 問題 | Tailscale 解法 |
|------|---------------|
| 樹莓派在實驗室，筆電在家/咖啡廳不能連 | Tailscale 建立加密隧道，感覺像在同一區網 |
| 學校/公司 Wi-Fi 有防火牆不能開 port | Tailscale 不需要開任何 port、不用 port forwarding |
| 用手機 4G 連回樹莓派 | Tailscale 手機版裝了就能連 |
| HTTP 沒加密不安全 | Tailscale 連線全程 WireGuard 加密 |

### 2.2 IP 對照

| 裝置 | Tailscale IP | 區域網路 IP（備用） |
|------|-------------|-------------------|
| 樹莓派 | `100.x.x.2`（假設） | `192.168.x.x` |
| 筆電 | `100.x.x.5`（假設） | `192.168.x.x` |
| 手機 | `100.x.x.10`（假設） | `192.168.x.x` |

**只要裝 Tailscale，不管人在哪裡，瀏覽器打開 `http://100.x.x.2:5000` 就能連到樹莓派。**

### 2.3 三種連線方式比較

| 方式 | 適用場景 | 優點 | 缺點 |
|------|---------|------|------|
| `http://192.168.x.x:5000` | 同一區網內（都在實驗室） | 最簡單，不需額外軟體 | 離開區網就不能用 |
| `http://100.x.x.x:5000` | 任何地方（Tailscale） | 到哪都能連、加密安全 | 需裝 Tailscale |
| `http://raspberrypi.local:5000` | macOS/Linux 本機 | 不用記 IP | 僅限本機、常不穩定 |

**建議開發和上線都用 Tailscale IP**，習慣後就不用煩惱網路問題。

---

## 3. CORS 處理（前後端分離時需要）

### 3.1 什麼是 CORS

當前端檔案不是由 Flask 提供（例如筆電自己開 dev server）時，瀏覽器會因為**不同 origin** 擋掉 API 請求：

```
❌ 前端 origin: http://localhost:5500
❌ API origin:  http://100.x.x.2:5000
→ 瀏覽器封鎖跨域請求
```

解法：Flask 後端加上 `Access-Control-Allow-Origin` header。

### 3.2 兩種做法

#### 做法 A：手動加 header（不需安裝）

```python
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response
```

#### 做法 B：flask-cors（標準做法）

```bash
pip install flask-cors
```

```python
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # 允許所有來源
```

### 3.3 建議

`emotion_server.py` 直接採用**做法 A**（手動加 header），這樣可以少裝一個套件，而且只有開發模式需要 CORS，上線時前端由 Flask 自己提供，不會有跨域問題。

---

## 4. 方案選擇：emotion_server.py 怎麼跑

因為 `main.py` 已經在 Docker 裡了，新的 web server 有兩種做法：

### 方案 A：emotion_server.py 也進 Docker（✅ 推薦上線用）

```
ai_app (main.py)  ──寫入──▶  influxdb  ──查詢──▶  web_app (Flask)  ──SSE──▶  瀏覽器
```

| 項目 | 內容 |
|------|------|
| `main.py` | **不必修改**。原本就在寫 InfluxDB，直接拿來用 |
| 資料傳遞 | `emotion_server.py` 每 0.25 秒 query InfluxDB 最新的 1 筆資料 |
| 通訊方式 | Docker 內部網路，用 service name (`influxdb:8086`) 連線 |
| 新 Docker image | 極輕量：python:3.10-slim + flask + influxdb-client (~200MB) |
| 啟動 | `docker-compose up` 一次全部起來 |

**為什麼推薦：**
1. 不用改 `main.py` 任何一行
2. 不用 shared volume（InfluxDB 就是 bridge）
3. Docker image 很輕（不用裝 tensorflow/opencv/mediapipe）
4. 全部一個指令啟動

### 方案 B：emotion_server.py 在本機跑（開發用）

```
ai_app (main.py in Docker)  ──寫入──▶  influxdb (in Docker)
                                           │
emotion_server.py (本機，not Docker)  ◄────┘ (query InfluxDB)
    │
    └── SSE → 瀏覽器
```

| 項目 | 內容 |
|------|------|
| 啟動方式 | `docker-compose up`（influxdb+grafana+ai_app）+ 另開 terminal 跑 `python emotion_server.py` |
| 注意 | 本機程式要連 Docker 內的 InfluxDB，需用 `localhost:8086` 而非 service name |
| 優勢 | 開發時可直接改直接重啟，不用 rebuild Docker image |

---

## 5. 前後端網路通訊方式

### 5.1 正常上線模式（一切在樹莓派上）

```
樹莓派 (Docker)
  └── web_app (Flask container)
        ├── GET  /              → 回傳 index.html（靜態檔）
        ├── GET  /api/emotion   → 回傳 JSON { emotion, scores, fps, ... }
        ├── GET  /api/stream    → SSE 即時推送
        └── GET  /frontend/*.js → 回傳 app.js 等靜態檔

筆電 / 手機
  └── 瀏覽器打開 http://100.x.x.2:5000
        ├── 載入 index.html ← 來自樹莓派 Flask
        ├── 載入 app.js     ← 來自樹莓派 Flask
        ├── Tailwind/Chart.js ← CDN（非樹莓派提供）
        └── EventSource → /api/stream → 連回樹莓派 Flask（同 origin，不需 CORS）
```

### 5.2 開發模式（前端在筆電編輯、預覽）

```
樹莓派（跑 Docker）
  ├── influxdb :8086
  ├── grafana  :3000
  ├── ai_app   (main.py)
  └── web_app  :5000（只提供 API，不提供前端）

筆電
  └── VS Code Live Server（:5500）
        ├── index.html ← 自己改
        ├── app.js     ← 自己改
        └── SSE 連到 http://100.x.x.2:5000/api/stream（不同 origin，需 CORS）
```

### 5.3 app.js 開發/上線模式切換

```javascript
// 自動判斷：如果前端是自己開的 dev server，就用 Tailscale IP
const API_BASE = location.hostname === "localhost" || location.hostname === "127.0.0.1"
    ? "http://100.x.x.2:5000"   // 開發模式（筆電 dev server）
    : "";                        // 上線模式（同 origin）

const evtSource = new EventSource(API_BASE + "/api/stream");
```

這樣同一份 `app.js` 不用手動改網址。

---

## 6. 新增/修改檔案一覽

| 檔案 | 動作 | 說明 |
|------|------|------|
| `emotion_server.py` | **新增** | Flask server，Query InfluxDB + SSE 推送，約 80 行 |
| `Dockerfile.web` | **新增** | 輕量 Docker image (~200MB) |
| `frontend/index.html` | **新增** | 儀表板 HTML，Tailwind CDN |
| `frontend/app.js` | **新增** | 前端 JS：SSE + Chart.js |
| `docker-compose.yml` | **修改** | 加一個 `web_app` service |
| `main.py` | **不需修改** | ✅ 直接用現有的 InfluxDB 資料 |

### 目錄結構（新增部分）

```
emotion_project/
├── main.py                  ← 不改
├── emotion_server.py        ← 新增（Flask）
├── Dockerfile.web           ← 新增（輕量 Dockerfile）
├── docker-compose.yml       ← 修改（加 web_app service）
├── frontend/                ← 新增資料夾
│   ├── index.html
│   └── app.js
└── (其餘檔案不變)
```

---

## 7. emotion_server.py 規格

### 7.1 技術選擇

| 項目 | 選擇 | 理由 |
|------|------|------|
| 框架 | **Flask** | 輕量、相依少、成熟穩定 |
| 資料來源 | **InfluxDB 查詢** | 不需改 main.py，不需 shared volume |
| 即時推送 | **SSE (Server-Sent Events)** | 單向推送即可，比 WebSocket 簡單 |
| 輪詢頻率 | 每 **0.25 秒**查一次 InfluxDB | 夠即時，不增加 InfluxDB 負擔 |
| CORS | **手動加 header** | 減少套件相依，開發模式才需要 |

### 7.2 API 設計

| 端點 | 方法 | 說明 |
|------|------|------|
| `/` | GET | 回傳 `frontend/index.html` |
| `/api/emotion` | GET | 回傳最新情緒資料 (JSON) |
| `/api/stream` | GET | SSE 即時串流，每秒推送 4 次 |

### 7.3 預期程式碼架構（約 80 行）

```python
import json, time
from flask import Flask, Response, send_from_directory
from influxdb_client import InfluxDBClient

app = Flask(__name__, static_folder=None)

INFLUX_URL = "http://influxdb:8086"
INFLUX_TOKEN = "emotion-super-token"
INFLUX_ORG = "emotion-org"
INFLUX_BUCKET = "emotion-bucket"

client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
query_api = client.query_api()

# 開發模式 CORS（可安全移除）
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

def query_latest():
    # Flux 查詢：取最近一筆資料
    ...

@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")

@app.route("/api/emotion")
def get_emotion():
    # 查 InfluxDB 回傳 JSON
    ...

@app.route("/api/stream")
def stream():
    def generate():
        while True:
            # 查 InfluxDB 並以 SSE 格式推送
            yield f"data: {json.dumps(data)}\n\n"
            time.sleep(0.25)
    return Response(generate(), mimetype="text/event-stream")
```

### 7.4 通訊埠

| 服務 | 埠號 | 備註 |
|------|------|------|
| web_app | **5000** | 前端連這個 port |
| InfluxDB | 8086 | container 內部，不對外 |
| Grafana | 3000 | 保留原有 |
| ai_app | 無 | 無對外 port，純寫入 |

---

## 8. Docker 設定

### 8.1 Dockerfile.web（輕量）

```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY emotion_server.py .
COPY frontend/ frontend/
RUN pip install flask influxdb-client
CMD ["python", "emotion_server.py"]
```

對比原本的 `Dockerfile`（裝 tensorflow/opencv/mediapipe 等）：
- 原本 Dockerfile image size: **~1.5 GB**
- Dockerfile.web image size: **~200 MB**

### 8.2 docker-compose.yml 修改

在現有檔案加上 `web_app` service：

```yaml
web_app:
  build:
    context: .
    dockerfile: Dockerfile.web
  container_name: emotion_web
  ports:
    - "5000:5000"
  depends_on:
    - influxdb
  restart: always
```

### 8.3 啟動

```bash
# 全部一起啟動（influxdb + grafana + ai_app + web_app）
docker-compose up -d

# 只重啟 web_app（修改程式碼後）
docker-compose restart web_app

# 看 log
docker-compose logs -f web_app
```

---

## 9. 前端規格

### 9.1 技術棧

| 項目 | 選擇 | 說明 |
|------|------|------|
| CSS 框架 | **Tailwind CSS v3 CDN** | Play CDN，不需安裝 |
| JS 框架 | 無框架 (vanilla JS) | 無需 node_modules |
| 圖表 | **Chart.js CDN** | 輕量圖表 (~60KB) |
| RWD 策略 | **Tailwind 響應式 class** | 手機直排、筆電橫排 |
| 主題 | **暗色主題** | 適合現場低光源，也省電 |

### 9.2 頁面畫面配置 (mobile-first)

```
┌──────────────────────────────────┐
│  😊 開心                          │ ← 大表情 emoji + 情緒名稱
│  92%                              │ ← 信心度
├──────────────────────────────────┤
│  FPS: 28.5  │  臉部: 偵測中 ✅    │ ← 狀態列
├──────────────────────────────────┤
│  開心  ████████████ 92%           │
│  難過  ██           12%           │ ← 長條圖
│  憤怒  █             5%           │
│  平靜  ██           15%           │
├──────────────────────────────────┤
│  情緒歷史趨勢（最近 60 秒）         │
│  ┌──────────────────────────┐    │
│  │  📈 折線圖 (Canvas)       │    │ ← Chart.js
│  │  開心 ─ 綠色 線            │    │
│  │  難過 ─ 橘色 線            │    │
│  │  憤怒 ─ 紅色 線            │    │
│  │  平靜 ─ 灰色 線            │    │
│  └──────────────────────────┘    │
├──────────────────────────────────┤
│  連線狀態: 正常 🟢               │
└──────────────────────────────────┘
```

### 9.3 RWD 斷點

| 螢幕寬度 | 排版 | 目標裝置 |
|----------|------|---------|
| < 640px | 單欄，長條圖滿寬 | 手機直式 |
| 640px ~ 1024px | 長條圖 50% + 圖表 50% | 手機橫式 / 小平板 |
| > 1024px | 長條圖 40% + 圖表 60% | 筆電 / 大螢幕 |

### 9.4 前端邏輯 (`app.js`)

1. 連線到 `/api/stream` SSE 端點
2. 收到資料後更新 DOM：
   - 情緒 emoji + 名稱 + 百分比
   - 四條長條圖的寬度與顏色
   - FPS 和臉部狀態
3. 維護一個長度 60（60 秒）的歷史陣列
4. 每收到一筆資料，更新 Chart.js 折線圖
5. 連線中斷時自動重連（exponential backoff）

### 9.5 情緒對應表

| 情緒 | Emoji | Tailwind 顏色 |
|------|-------|---------------|
| happy | 😊 | `text-green-400` |
| sad | 😢 | `text-orange-400` |
| angry | 😠 | `text-red-500` |
| neutral | 😐 | `text-gray-400` |
| 未偵測 | 🤷 | `text-gray-500` |

---

## 10. 啟動方式

### 10.1 樹莓派上線（全部 Docker）

```bash
# 第一次需要 build
docker-compose build

# 啟動全部服務
docker-compose up -d

# 確認都在跑
docker-compose ps

# 看 web_app 的 log
docker-compose logs -f web_app
```

然後：
- **手機**：Tailscale 連線下，瀏覽器打開 `http://100.x.x.2:5000`
- **筆電**：瀏覽器打開 `http://100.x.x.2:5000`
- **Grafana**：瀏覽器打開 `http://100.x.x.2:3000`

### 10.2 全部在本機開發測試（Windows，不用 Docker）

如果 Windows 上也有攝影機，可以在本機開發測試：

```bash
# 先確定 InfluxDB 有跑（可用 Docker Desktop 跑 influxdb 單一 container）
# 修改 emotion_server.py 中的 INFLUX_URL 為 localhost

# Terminal 1
python main.py

# Terminal 2
python emotion_server.py

# 瀏覽器打開 http://localhost:5000
```

---

## 11. 開發環境設定（給開發者看的）

### 11.1 開發方式選擇

這個專案支援三種開發方式，開發者可以依習慣選擇：

| 方式 | 適合誰 | 優點 | 缺點 |
|------|--------|------|------|
| **A. SSH Remote（推薦）** | 所有人 | 直接在樹莓派上改檔案，不用 scp、不用複製 | 需 Tailscale / 區網連線 |
| **B. scp + Live Server** | 習慣本機開發的人 | 前端在筆電跑，live reload 順暢 | 每次改完要 scp 回樹莓派 |
| **C. 全部在本機** | Windows 有攝影機的人 | 不用 Tailscale，全部 localhost | 不模擬樹莓派環境 |

本節以 **方式 A（SSH Remote）** 為主，方式 B 和 C 放最後。

---

### 11A. 方式 A：SSH Remote（強烈推薦）

#### 原理

```
VS Code 開在本機，但透過 SSH 連到樹莓派，
你編輯的所有檔案「實際存在樹莓派上」，

              SSH 隧道
  筆電 VS Code ◄══════════► 樹莓派 ~/emotion_project/
                                 ├── frontend/index.html
                                 ├── frontend/app.js
                                 ├── emotion_server.py
                                 └── docker-compose.yml

你在 VS Code 看到的目錄是樹莓派的，改的也是樹莓派的。
```

#### 一次性的初始設定

```
Step 1: 樹莓派裝 Tailscale（已有可跳過）
─────────────────────────────────────────
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up        # 用 Google/Microsoft 帳號登入
tailscale ip             # 記下這個 IP（假設 100.x.x.2）

Step 2: 筆電裝 Tailscale + VS Code Remote SSH
─────────────────────────────────────────
- Tailscale: https://tailscale.com/download
- VS Code 擴充: 搜尋 "Remote - SSH" 安裝

Step 3: 確認連線
─────────────────────────────────────────
ping 100.x.x.2     # 有回應表示通了
ssh pi@100.x.x.2   # 確認可以 SSH 進去
```

#### 日常開發流程

```bash
# ===== 每天早上 =====

# 1. 樹莓派啟動 Docker 後端
ssh pi@100.x.x.2
cd ~/emotion_project
docker-compose up -d
exit

# 2. VS Code 連上樹莓派
#    Ctrl+Shift+P → "Remote-SSH: Connect to Host..."
#    輸入 pi@100.x.x.2
#    打開目錄 ~/emotion_project
```

```
      VS Code 畫面長這樣

┌────────────────────────────────────────────────────────────┐
│  檔案(F)  編輯(E)  選取(S)  檢視(V)  前往(G)  執行(R)     │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ 連線主機: 100.x.x.2                                    │ │
│ │                                                         │ │
│ │ 瀏覽器                                                  │ │
│ │  ▼ emotion_project                                     │ │
│ │    ▼ frontend/           ← 你在這裡寫前端              │ │
│ │        index.html                                       │ │
│ │        app.js                                           │ │
│ │    emotion_server.py     ← 你在這裡寫後端              │ │
│ │    docker-compose.yml                                   │ │
│ │    main.py                                              │ │
│ │    ...                                                  │ │
│ └────────────────────────────────────────────────────────┘ │
│ SSH:100.x.x.2  Python 3.10.11                              │
└────────────────────────────────────────────────────────────┘
```

#### 怎麼看前端修改結果

三種方式，選一種就好：

**方式 A1：直接開瀏覽器（最簡單）**

```
1. 本機瀏覽器打開 http://100.x.x.2:5000
2. VS Code 裡改 frontend/ 下的檔案
3. 存檔後回到瀏覽器按 F5 重整
   → 立即看到修改效果
   → Flask 提供靜態檔，改完存檔就有效，不用重啟
```

**方式 A2：VS Code Port Forwarding（本機 localhost 看）**

```
1. VS Code 按 Ctrl+Shift+P → 搜尋 "Forward a Port"
2. 輸入 5000
3. VS Code 會顯示：
   ┌────────────────────┐
   │ 連接埠 (Ports)      │
   │ localhost:5000 → 5000 │  ← 自動建立
   └────────────────────┘
4. 本機瀏覽器打開 http://localhost:5000
   → VS Code 自動把 localhost:5000 轉到樹莓派 :5000
```

優點：瀏覽器連 `localhost`，Tailscale 斷線也能看（前提是 SSH 連線還在）

**方式 A3：Live Server + Port Forwarding（自動重整）**

```
1. VS Code Remote 連樹莓派
2. 左邊擴充搜尋 "Live Server" 安裝（裝在 Remote 端）
3. 對 frontend/index.html 按右鍵 → Open with Live Server
4. VS Code 跳出提示 "你的應用程式在 port 5500 上" → 按「開啟瀏覽器」
5. 或者手動加 port forwarding: 5500
6. 本機瀏覽器打開 http://localhost:5500
   → 改 frontend/ 存檔 → 瀏覽器自動重整
   → 不用按 F5
```

#### 前後端各自怎麼寫

**前端開發者寫法：**
```
1. VS Code Remote 連樹莓派
2. 編輯 frontend/index.html 或 frontend/app.js
3. 方式 A1：瀏覽器開 http://100.x.x.2:5000 重整看結果
   方式 A3：Live Server 開了自動重整
```

**後端開發者寫法：**
```
1. VS Code Remote 連樹莓派
2. 編輯 emotion_server.py
3. 存檔後執行：
   ssh pi@100.x.x.2 "cd ~/emotion_project && docker-compose restart web_app"
4. 瀏覽器重整確認結果

# 或直接在 VS Code 的終端機（按 Ctrl+`）執行：
docker-compose restart web_app
```

#### 前後端同一個人寫（最常見）

```
1. VS Code Remote 連樹莓派
2. 瀏覽器開 http://100.x.x.2:5000（看目前樣子）
3. 改前端 → 瀏覽器重整（秒看到）
4. 改後端 → docker-compose restart web_app（幾秒後看到）
5. 全部在同一個 VS Code 視窗完成
```

#### SSH Remote 開發流程圖

```
┌──────────────────────────────────────────────────────────────────────┐
│  筆電                                                                │
│                                                                      │
│  ┌─────────────────────────────────────────────────────┐             │
│  │  VS Code (Remote SSH)                              │             │
│  │  ┌─────────────────────────────────────────────────┐│             │
│  │  │  終端機（已 SSH 到樹莓派）                       ││             │
│  │  │  pi@raspberrypi:~/emotion_project$              ││             │
│  │  │  $ docker-compose restart web_app               ││             │
│  │  └─────────────────────────────────────────────────┘│             │
│  │  ┌─────────────┐  ┌─────────────┐                  │             │
│  │  │ 前端檔案    │  │ 後端檔案    │                  │             │
│  │  │ index.html  │  │ emotion_    │                  │             │
│  │  │ app.js      │  │ server.py   │                  │             │
│  │  └──────┬──────┘  └──────┬──────┘                  │             │
│  └─────────┼────────────────┼─────────────────────────┘             │
│            │ SSH            │ SSH                                    │
└────────────┼────────────────┼────────────────────────────────────────┘
             │                │
             ▼                ▼
    ┌──────────────────────────────────────────┐
    │  樹莓派 (pi@100.x.x.2)                    │
    │                                           │
    │  ~/emotion_project/                       │
    │    ├── frontend/index.html  ← 你在改的    │
    │    ├── frontend/app.js      ← 你在改的    │
    │    ├── emotion_server.py    ← 你在改的    │
    │    └── Docker: web_app :5000             │
    │                                           │
    │  改前端：存檔 → 瀏覽器重整就有效           │
    │  改後端：docker-compose restart web_app   │
    └──────────────────────────────────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  本機瀏覽器        │
                    │  http://100.x.x.2 │
                    │  :5000            │
                    └──────────────────┘
```

---

### 11B. 方式 B：scp + Live Server（前端在筆電本機跑）

適合不想用 SSH Remote、習慣在本機改檔案的人。

#### 流程

```
第一次：把前端 scp 到筆電
────────────────────────────
scp -r pi@100.x.x.2:~/emotion_project/frontend/ ./my_emotion_frontend/

每天開發循環：
────────────────────────────
1. 筆電 VS Code 開 ./my_emotion_frontend/
2. 筆電開 Live Server（或 python -m http.server 5500）
3. 瀏覽器開 http://localhost:5500
4. 改前端 → 重整瀏覽器（秒看到）
5. 改好了 scp 回樹莓派：
   scp index.html app.js pi@100.x.x.2:~/emotion_project/frontend/
6. ssh pi@100.x.x.2 "docker-compose restart web_app"
```

#### app.js 開發/上線自動切換

```javascript
// 自動判斷當前環境
const isDev = location.hostname === "localhost" || location.hostname === "127.0.0.1";
const API_BASE = isDev ? "http://100.x.x.2:5000" : "";

// 開發時（localhost:5500）→ 連 Tailscale 回樹莓派
// 上線時（100.x.x.2:5000）→ 連同 origin（Flask 自己）
const evtSource = new EventSource(API_BASE + "/api/stream");
```

---

### 11C. 方式 C：全部在本機（Windows 開發測試用）

如果 Windows 上也有攝影機 + Docker Desktop，可以不碰樹莓派純粹在本機測試邏輯：

```bash
# 1. 用 Docker Desktop 只跑 influxdb
docker run -d --name influxdb \
  -p 8086:8086 \
  -e DOCKER_INFLUXDB_INIT_MODE=setup \
  -e DOCKER_INFLUXDB_INIT_USERNAME=admin \
  -e DOCKER_INFLUXDB_INIT_PASSWORD=admin123456 \
  -e DOCKER_INFLUXDB_INIT_ORG=emotion-org \
  -e DOCKER_INFLUXDB_INIT_BUCKET=emotion-bucket \
  -e DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=emotion-super-token \
  influxdb:2

# 2. 修改 emotion_server.py 中的 INFLUX_URL 為 localhost

# 3. 開兩個終端機
#  Terminal 1:
python main.py

#  Terminal 2:
python emotion_server.py

# 4. 瀏覽器開 http://localhost:5000
```

---

### 11D. 三種方式比較表

| 比較項目 | A. SSH Remote ✅ | B. scp + Live Server | C. 本機測試 |
|---------|-----------------|---------------------|------------|
| 前端存檔位置 | 樹莓派 | 筆電 + 要 scp 回去 | 本機 |
| 改前端看效果 | 存檔 → 重整瀏覽器 | Live Server 自動重整 | 存檔 → 重整 |
| 改後端 | `docker-compose restart` | 同上 | 重啟 python |
| 需要 Tailscale | ✅ 需要 | ✅ 需要 | ❌ 不需要 |
| 離線開發 | ❌ 要連樹莓派 | ✅ 前端可離線開發 | ✅ 完全離線 |
| 手機測試 | 直接開瀏覽器 | 需筆電開著 | 無法模擬 |

---

### 11E. 常見開發情境查詢表

| 你想做什麼 | 怎麼做 |
|-----------|--------|
| 改前端顏色、文字 | 改 `frontend/index.html` → 重整瀏覽器 |
| 改前端邏輯（圖表、SSE） | 改 `frontend/app.js` → 重整瀏覽器 |
| 改後端 API 邏輯 | 改 `emotion_server.py` → `docker-compose restart web_app` |
| 想用手機看效果 | 手機 Tailscale 連線 → 瀏覽器開 `http://100.x.x.2:5000` |
| 樹莓派不在身邊 | 只要 Tailscale 有連線，SSH Remote 一樣能改 |
| Docker 全部重來 | `docker-compose down && docker-compose up -d` |
| Flask 回應怪怪的 | `docker-compose logs -f web_app` 看錯誤 |
| 前端改了但瀏覽器沒變 | 按 Ctrl+F5 強制重整（避開瀏覽器快取） |

---

## 12. 空間與效能評估

### 12.1 磁碟空間

| 項目 | 大小 | 說明 |
|------|------|------|
| Docker image (web_app) | ~200 MB | python:3.10-slim + flask + influxdb-client |
| 前端靜態檔案 | < 50 KB | HTML + JS |
| Tailwind + Chart.js | 0 MB | 使用 CDN |
| **總計新增** | **~200 MB** | ✅ 25GB 完全足夠 |

### 12.2 樹莓派效能影響

| 項目 | 影響 |
|------|------|
| emotion_server.py query InfluxDB | 極小，每 0.25 秒查 1 次 |
| Flask server idle | ~0% CPU |
| SSE 推送 | < 1% CPU（每 0.25 秒寫一次 response） |
| 前端 Chart.js 動畫 | 手機/筆電 GPU 處理，不影響樹莓派 |
| **預估總 CPU 增加** | **< 2%** |

---

## 13. 常見問題

### Q: 一定要用 Tailscale 嗎？

A: 不是必要。如果在同一區網內，直接用 `http://192.168.x.x:5000` 就可以。
Tailscale 是解決「不在同一區網時也能連」的問題。

### Q: 前端檔案放在哪裡？筆電還是樹莓派？

A:
- **上線時**：檔案放在樹莓派 `frontend/` 資料夾，由 Flask 提供
- **開發時**：可以複製到筆電用 dev server 開，改完再 `scp` 回樹莓派

### Q: 可以不用 Docker 跑 emotion_server.py 嗎？

A: 可以。在本機跑 `python emotion_server.py`，但要確保它可以連到 Docker 內的 InfluxDB：
- InfluxDB 的 `docker-compose.yml` 已有 `ports: "8086:8086"`
- 所以本機用 `localhost:8086` 即可連到

### Q: 前端 framework 能換成 React/Vue 嗎？

A: 可以，但要考慮：
- `node_modules` 佔 ~100-300MB
- 需要 build 步驟
- `Dockerfile.web` 要裝 node.js

建議先用純 HTML + JS 開發，之後有需要再升級。

### Q: 開發時前端改了但瀏覽器沒看到變化？

A: 確認：
1. Live Server 有開（瀏覽器是 `localhost:5500` 不是 `file://`）
2. `app.js` 中的 `API_BASE` 指向正確的樹莓派 Tailscale IP
3. 樹莓派後端有在跑（`docker-compose ps`）

---

## 14. 實作步驟

### Phase 0：環境準備

- [ ] 樹莓派裝 Tailscale：`curl -fsSL https://tailscale.com/install.sh | sh`
- [ ] 筆電裝 Tailscale：下載安裝
- [ ] 兩邊登入同一個帳號，確認 `ping 100.x.x.2` 通
- [ ] 樹莓派防火牆開 port 5000：`sudo ufw allow 5000`

### Phase 1：後端（樹莓派）

- [ ] 1. 新增 `emotion_server.py`：query InfluxDB + SSE + CORS
- [ ] 2. 新增 `Dockerfile.web`：輕量 image
- [ ] 3. 修改 `docker-compose.yml`：加 `web_app` service
- [ ] 4. Build + 啟動：`docker-compose up -d`
- [ ] 5. 驗證：筆電打開 `http://100.x.x.2:5000/api/emotion` 回傳 JSON

### Phase 2：前端

- [ ] 6. 新增 `frontend/index.html`：Tailwind CDN + 頁面結構
- [ ] 7. 新增 `frontend/app.js`：SSE + Chart.js + 環境自動切換
- [ ] 8. 手機測試：Tailscale 下打開 `http://100.x.x.2:5000`

### Phase 3：開發流程建立

- [ ] 9. 筆電 `scp` 前端到本機，建立 dev server 開發環境
- [ ] 10. 壓力測試：長時間運作確認無記憶體洩漏
