import json
import os
import time
from flask import Flask, Response, send_from_directory
from influxdb_client import InfluxDBClient

app = Flask(__name__, static_folder=None)

INFLUX_URL = os.getenv("INFLUX_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "emotion-super-token")
INFLUX_ORG = os.getenv("INFLUX_ORG", "emotion-org")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "emotion-bucket")
INFLUX_MEASUREMENT = "emotion_metrics"

client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
query_api = client.query_api()


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response


def query_latest():
    flux = f'''
    from(bucket: "{INFLUX_BUCKET}")
        |> range(start: -5m)
        |> filter(fn: (r) => r._measurement == "{INFLUX_MEASUREMENT}")
        |> filter(fn: (r) =>
            r._field == "happy" or
            r._field == "sad" or
            r._field == "angry" or
            r._field == "neutral" or
            r._field == "fps" or
            r._field == "face_detected" or
            r._field == "face_count"
        )
        |> map(fn: (r) => ({{ r with _value: float(v: r._value) }}))
        |> group(columns: ["source", "camera_index", "dominant_emotion", "quality"])
        |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        |> group()
        |> sort(columns: ["_time"], desc: true)
        |> limit(n: 1)
    '''
    try:
        tables = query_api.query(flux)
        for table in tables:
            for record in table.records:
                values = record.values
                emotions = {}
                for e in ["happy", "sad", "angry", "neutral"]:
                    val = values.get(e, 0.0)
                    emotions[e] = round(float(val), 4)
                dominant = values.get("dominant_emotion", "unknown")
                if dominant is None:
                    dominant = "unknown"
                return {
                    "emotion": dominant,
                    "scores": emotions,
                    "fps": round(float(values.get("fps", 0.0)), 1),
                    "face_detected": bool(values.get("face_detected", 0)),
                    "face_count": int(values.get("face_count", 0)),
                    "quality": str(values.get("quality", "unknown")),
                    "timestamp": str(values.get("_time", ""))
                }
    except Exception as e:
        print("Query error:", e)
    return None


def format_sse(data):
    return f"data: {json.dumps(data)}\n\n"


@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("frontend", path)


@app.route("/api/emotion")
def get_emotion():
    data = query_latest()
    if data is None:
        return json.dumps({"error": "no data"}), 503, {"Content-Type": "application/json"}
    return json.dumps(data), 200, {"Content-Type": "application/json"}


@app.route("/api/stream")
def stream():
    def generate():
        while True:
            data = query_latest()
            if data:
                yield format_sse(data)
            else:
                yield format_sse({"emotion": "unknown", "scores": {}, "fps": 0, "face_detected": False, "face_count": 0, "quality": "no data"})
            time.sleep(0.25)
    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
