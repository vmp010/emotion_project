import cv2
import mediapipe as mp
from fer import FER
from PIL import ImageFont, ImageDraw, Image
import numpy as np
import time
import threading
import influxdb_client
from influxdb_client import Point
from influxdb_client.client.write_api import SYNCHRONOUS
from picamera2 import Picamera2

# =========================
# 基本設定
# =========================
MODEL_PATH = "face_landmarker.task"
CAMERA_SOURCE = "picamera2"
SHOW_LANDMARKS = False

# 效能 / 準確率平衡
ANALYZE_EVERY = 4              # 每 4 幀送一次背景分析
ROI_SIZE = 160                 # 固定臉部輸入尺寸，提升速度
EMA_ALPHA = 0.45               # 指數平滑，越大越靈敏
MIN_FACE_SIZE = 50
MIN_CONFIDENCE = 0.10

# =========================
# InfluxDB 設定
# Python 在主機跑、InfluxDB 在 Docker 跑時，使用 localhost
# 若之後 Python 也容器化，再改成 http://influxdb:8086
# =========================
INFLUX_URL = "http://influxdb:8086"
INFLUX_TOKEN = "emotion-super-token"
INFLUX_ORG = "emotion-org"
INFLUX_BUCKET = "emotion-bucket"
INFLUX_MEASUREMENT = "emotion_metrics"

WRITE_INTERVAL = 1.0  # 每 1 秒寫一次 InfluxDB

emotion_labels = ['happy', 'sad', 'angry', 'neutral']

TARGET_EMOTIONS_ZH = {
    'happy': '開心',
    'sad': '難過',
    'angry': '憤怒',
    'neutral': '平靜'
}

EMOTION_COLORS = {
    'happy': (0, 255, 0),
    'sad': (255, 140, 0),
    'angry': (0, 0, 255),
    'neutral': (220, 220, 220)
}

BAR_COLORS = {
    'happy': (0, 255, 0),
    'sad': (255, 140, 0),
    'angry': (0, 0, 255),
    'neutral': (180, 180, 180)
}

FER_ALL_LABELS = ['angry', 'disgust', 'fear', 'happy', 'sad', 'surprise', 'neutral']

# =========================
# 字型
# =========================
try:
    FONT = ImageFont.truetype("C:/Windows/Fonts/msjh.ttc", 30)
    FONT_SMALL = ImageFont.truetype("C:/Windows/Fonts/msjh.ttc", 22)
    FONT_TINY = ImageFont.truetype("C:/Windows/Fonts/msjh.ttc", 18)
except Exception:
    FONT = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()
    FONT_TINY = ImageFont.load_default()


def put_chinese_text(frame, text, position, color, font=None):
    if font is None:
        font = FONT
    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    draw.text(position, text, font=font, fill=(color[2], color[1], color[0]))
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


# =========================
# InfluxDB 初始化
# =========================
client = influxdb_client.InfluxDBClient(
    url=INFLUX_URL,
    token=INFLUX_TOKEN,
    org=INFLUX_ORG
)
write_api = client.write_api(write_options=SYNCHRONOUS)


def write_metrics_to_influx(
    fps,
    face_detected,
    face_count,
    quality_msg,
    dominant_emotion,
    scores,
    bbox
):
    face_width = 0
    face_height = 0
    if bbox is not None:
        x_min, y_min, x_max, y_max = bbox
        face_width = max(0, x_max - x_min)
        face_height = max(0, y_max - y_min)

    point = (
        Point(INFLUX_MEASUREMENT)
        .tag("source", CAMERA_SOURCE)
        .tag("camera_index", CAMERA_SOURCE)
        .tag("dominant_emotion", dominant_emotion if dominant_emotion else "unknown")
        .tag("quality", quality_msg if quality_msg else "unknown")
        .field("fps", float(fps))
        .field("face_detected", int(face_detected))
        .field("face_count", int(face_count))
        .field("face_width", int(face_width))
        .field("face_height", int(face_height))
        .field("happy", float(scores.get("happy", 0.0)))
        .field("sad", float(scores.get("sad", 0.0)))
        .field("angry", float(scores.get("angry", 0.0)))
        .field("neutral", float(scores.get("neutral", 0.0)))
    )

    write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)


# =========================
# MediaPipe
# =========================
BaseOptions = mp.tasks.BaseOptions
FaceLandmarker = mp.tasks.vision.FaceLandmarker
FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
VisionRunningMode = mp.tasks.vision.RunningMode

latest_result = None


def result_callback(result, output_image, timestamp_ms):
    global latest_result
    latest_result = result


options = FaceLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=VisionRunningMode.LIVE_STREAM,
    num_faces=1,
    min_face_detection_confidence=0.4,
    min_tracking_confidence=0.4,
    result_callback=result_callback
)

emotion_detector = FER(mtcnn=False)

# =========================
# 共用狀態
# =========================
frame_count = 0
last_box = None
current_emotion_key = None
current_emotion_text = "未偵測"
current_color = (255, 255, 255)
current_scores = {e: 0.0 for e in emotion_labels}
latest_quality_msg = "等待偵測"

analysis_lock = threading.Lock()
is_analyzing = False
pending_roi = None

last_write_time = 0



# =========================
# 工具函式
# =========================
def clamp(val, min_val, max_val):
    return max(min_val, min(val, max_val))


def get_refined_face_bbox(landmarks, frame_shape):
    h, w, _ = frame_shape
    xs = np.array([p.x for p in landmarks])
    ys = np.array([p.y for p in landmarks])

    x_min = xs.min() * w
    x_max = xs.max() * w
    y_min = ys.min() * h
    y_max = ys.max() * h

    face_w = x_max - x_min
    face_h = y_max - y_min

    x_min = x_min + face_w * 0.03
    x_max = x_max - face_w * 0.03
    y_min = y_min - face_h * 0.08
    y_max = y_max + face_h * 0.04

    x_min = clamp(int(x_min), 0, w - 1)
    y_min = clamp(int(y_min), 0, h - 1)
    x_max = clamp(int(x_max), 0, w - 1)
    y_max = clamp(int(y_max), 0, h - 1)

    return x_min, y_min, x_max, y_max


def check_face_quality(face_roi):
    if face_roi is None or face_roi.size == 0:
        return False, "無臉部"

    h, w = face_roi.shape[:2]
    if w < MIN_FACE_SIZE or h < MIN_FACE_SIZE:
        return False, "臉太小"

    gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()

    if brightness < 20:
        return False, "太暗"
    if sharpness < 15:
        return False, "太模糊"

    return True, "OK"


def preprocess_face(face_roi):
    face = cv2.resize(face_roi, (ROI_SIZE, ROI_SIZE), interpolation=cv2.INTER_AREA)

    ycrcb = cv2.cvtColor(face, cv2.COLOR_BGR2YCrCb)
    y, cr, cb = cv2.split(ycrcb)
    y = cv2.equalizeHist(y)
    face = cv2.cvtColor(cv2.merge([y, cr, cb]), cv2.COLOR_YCrCb2BGR)

    return face


def merge_emotions(raw_scores):
    angry = raw_scores.get('angry', 0.0) + raw_scores.get('disgust', 0.0)
    sad = raw_scores.get('sad', 0.0) + raw_scores.get('fear', 0.0)
    happy = raw_scores.get('happy', 0.0) + raw_scores.get('surprise', 0.0) * 0.30
    neutral = raw_scores.get('neutral', 0.0) + raw_scores.get('surprise', 0.0) * 0.15

    merged = {
        'happy': happy,
        'sad': sad,
        'angry': angry,
        'neutral': neutral
    }

    total = sum(merged.values())
    if total > 0:
        merged = {k: v / total for k, v in merged.items()}
    return merged


def ema_update(old_scores, new_scores, alpha=EMA_ALPHA):
    updated = {}
    for e in emotion_labels:
        updated[e] = alpha * new_scores.get(e, 0.0) + (1 - alpha) * old_scores.get(e, 0.0)
    s = sum(updated.values())
    if s > 0:
        updated = {k: v / s for k, v in updated.items()}
    return updated


def draw_emotion_panel(frame, scores, x=10, y=120, w=300, row_h=34):
    panel_h = row_h * len(emotion_labels) + 15

    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + w, y + panel_h), (0, 0, 0), -1)
    frame = cv2.addWeighted(overlay, 0.55, frame, 0.45, 0)

    for i, emotion in enumerate(emotion_labels):
        score = float(scores.get(emotion, 0))
        zh = TARGET_EMOTIONS_ZH[emotion]

        row_y = y + 10 + i * row_h
        label_x = x + 8
        bar_x = x + 85
        bar_y = row_y + 6
        bar_w = 140
        bar_h = 16

        frame = put_chinese_text(frame, zh, (label_x, row_y - 4), (255, 255, 255), FONT_TINY)
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (70, 70, 70), -1)

        fill_w = int(bar_w * score)
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), BAR_COLORS[emotion], -1)
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (180, 180, 180), 1)

        cv2.putText(
            frame,
            f"{score:.0%}",
            (bar_x + bar_w + 10, bar_y + 13),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (255, 255, 255),
            1,
            cv2.LINE_AA
        )
    return frame


def emotion_worker():
    global is_analyzing, pending_roi, current_scores, current_emotion_key
    global current_emotion_text, current_color, latest_quality_msg

    while True:
        with analysis_lock:
            if pending_roi is None:
                is_analyzing = False
                return
            face_roi = pending_roi.copy()
            pending_roi = None

        try:
            face_input = preprocess_face(face_roi)
            emotions = emotion_detector.detect_emotions(face_input)

            if emotions:
                raw_scores = emotions[0].get("emotions", {})
                raw_scores = {e: raw_scores.get(e, 0.0) for e in FER_ALL_LABELS}
                merged_scores = merge_emotions(raw_scores)

                current_scores = ema_update(current_scores, merged_scores, EMA_ALPHA)

                best_emotion = max(current_scores, key=current_scores.get)
                best_score = current_scores[best_emotion]

                if best_score >= MIN_CONFIDENCE:
                    current_emotion_key = best_emotion
                    current_emotion_text = f"{TARGET_EMOTIONS_ZH[best_emotion]} {best_score:.0%}"
                    current_color = EMOTION_COLORS[best_emotion]
                else:
                    current_emotion_key = None
                    current_emotion_text = "情緒不明確"
                    current_color = (255, 255, 255)

                latest_quality_msg = "OK"
            else:
                latest_quality_msg = "無情緒"
        except Exception:
            latest_quality_msg = "分析失敗"

        with analysis_lock:
            if pending_roi is None:
                is_analyzing = False
                return


# =========================
# 主程式
# =========================
picam2 = Picamera2()
config = picam2.create_preview_configuration(
    main={"size": (640, 480), "format": "BGR888"}
)
picam2.configure(config)
picam2.start()
time.sleep(1)

prev_time = time.time()

with FaceLandmarker.create_from_options(options) as landmarker:
    while True:
        frame = picam2.capture_array()

        frame_count += 1
        display_frame = frame.copy()
        face_count = 0

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        landmarker.detect_async(mp_image, int(time.time() * 1000))

        if latest_result and latest_result.face_landmarks:
            face_count = len(latest_result.face_landmarks)

            landmarks = latest_result.face_landmarks[0]
            x_min, y_min, x_max, y_max = get_refined_face_bbox(landmarks, frame.shape)
            last_box = (x_min, y_min, x_max, y_max)

            face_roi = frame[y_min:y_max, x_min:x_max]
            ok, quality_msg = check_face_quality(face_roi)

            if ok and frame_count % ANALYZE_EVERY == 0:
                with analysis_lock:
                    pending_roi = face_roi.copy()
                    if not is_analyzing:
                        is_analyzing = True
                        threading.Thread(target=emotion_worker, daemon=True).start()
            else:
                latest_quality_msg = quality_msg

        if last_box is not None:
            x_min, y_min, x_max, y_max = last_box
            cv2.rectangle(display_frame, (x_min, y_min), (x_max, y_max), current_color, 2)

            if current_emotion_key:
                score_to_show = current_scores.get(current_emotion_key, 0.0)
                cv2.putText(
                    display_frame,
                    f"{current_emotion_key}: {score_to_show:.2f}",
                    (x_min, max(25, y_min - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    current_color,
                    2,
                    cv2.LINE_AA
                )

        if SHOW_LANDMARKS and latest_result and latest_result.face_landmarks:
            h, w, _ = display_frame.shape
            for p in latest_result.face_landmarks[0]:
                x = int(p.x * w)
                y = int(p.y * h)
                cv2.circle(display_frame, (x, y), 1, (0, 255, 0), -1)

        display_frame = cv2.flip(display_frame, 1)

        current_time = time.time()
        fps = 1.0 / max(current_time - prev_time, 1e-6)
        prev_time = current_time

        overlay = display_frame.copy()
        cv2.rectangle(overlay, (0, 0), (430, 110), (0, 0, 0), -1)
        display_frame = cv2.addWeighted(overlay, 0.55, display_frame, 0.45, 0)

        display_frame = put_chinese_text(display_frame, current_emotion_text, (10, 10), current_color, FONT)
        display_frame = put_chinese_text(display_frame, f"FPS: {fps:.1f}", (10, 45), (255, 255, 0), FONT_SMALL)
        display_frame = put_chinese_text(display_frame, f"品質: {latest_quality_msg}", (10, 75), (200, 200, 200), FONT_TINY)

        display_frame = draw_emotion_panel(display_frame, current_scores, x=10, y=120, w=300, row_h=34)

        cv2.rectangle(display_frame, (0, display_frame.shape[0] - 32), (430, display_frame.shape[0]), (0, 0, 0), -1)
        cv2.putText(
            display_frame,
            "Q: Quit   L: Landmarks On/Off",
            (10, display_frame.shape[0] - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA
        )

        # =========================
        # 每秒寫一次 InfluxDB
        # =========================
        now = time.time()
        if now - last_write_time >= WRITE_INTERVAL:
            try:
                write_metrics_to_influx(
                    fps=fps,
                    face_detected=(1 if last_box is not None else 0),
                    face_count=face_count,
                    quality_msg=latest_quality_msg,
                    dominant_emotion=current_emotion_key,
                    scores=current_scores.copy(),
                    bbox=last_box
                )
                last_write_time = now
            except Exception as e:
                print("InfluxDB 寫入失敗:", e)

        # cv2.imshow("Fast Emotion Detection", display_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('l'):
            SHOW_LANDMARKS = not SHOW_LANDMARKS

picam2.stop()
cv2.destroyAllWindows()
client.close()