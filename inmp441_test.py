from __future__ import annotations
import argparse
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

# 定義支援的 ALSA 錄音格式、位元組長度、struct 解析格式及最大振幅值
SAMPLE_FORMATS = {
    "S16_LE": (2, "<h", 32768.0),
    "S24_LE": (3, None, 8388608.0),
    "S32_LE": (4, "<i", 2147483648.0),
}

# =========================
#檢查系統是否安裝 ALSA 工具組的 `arecord`，若無則提示安裝並結束程式。
# =========================

def require_arecord() -> None:
    if not shutil.which("arecord"):
        print("ERROR: cannot find `arecord`.")
        print("Install ALSA utilities with: sudo apt install alsa-utils")
        raise SystemExit(1)
    
# =========================
#安全執行子程序指令，若失敗則自動印出 stdout/stderr 並帶有錯誤碼結束。
# =========================

def run_checked(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, text=True, capture_output=True, check=True)
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        raise SystemExit(exc.returncode)

# =========================
#列出目前系統上所有可用的 ALSA 音訊輸入硬體裝置與 PCM 通道。
# =========================

def list_devices() -> None:
    require_arecord()
    print("=== arecord -l ===")
    run = run_checked(["arecord", "-l"])
    print(run.stdout.rstrip() or "(no capture hardware listed)")
    print()
    print("=== arecord -L ===")
    run = run_checked(["arecord", "-L"])
    print(run.stdout.rstrip() or "(no ALSA PCMs listed)")

# =========================
#將二進位原始音訊資料（Little-Endian）解碼為整數數值。
#支援 1 到 4 類型的位元組寬度，其中 3 bytes (S24_LE) 會特別補零填滿至 4 bytes 再解碼。
# =========================

def decode_sample(data: bytes, sample_width: int) -> int:
    if sample_width == 1:
        return data[0] - 128
    if sample_width == 2:
        return struct.unpack("<h", data)[0]
    if sample_width == 3:
        # S24_LE 處理：讀取最高位元判定正負號，補足第 4 個 byte 轉成 32 位元有號整數
        sign = 0xFF if data[2] & 0x80 else 0x00
        return struct.unpack("<i", data + bytes([sign]))[0]
    if sample_width == 4:
        return struct.unpack("<i", data)[0]
    raise ValueError(f"unsupported sample width: {sample_width}")

# =========================
#讀取並分析錄好的 WAV 檔案，計算其時間、音量峰值(Peak)與均方根(RMS)音量。
# =========================

def analyze_wav(path: Path) -> dict[str, float | int]:
   
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        frame_rate = wav.getframerate()
        frames = wav.getnframes()
        raw = wav.readframes(frames)

    if sample_width not in (1, 2, 3, 4):
        raise ValueError(f"unsupported WAV sample width: {sample_width} bytes")

    bytes_per_frame = sample_width * channels
    if bytes_per_frame == 0:
        raise ValueError("invalid WAV format")

    max_possible = float(2 ** (sample_width * 8 - 1))
    peak = 0
    total_sq = 0.0
    sample_count = 0

    # 逐幀走訪所有音訊樣本進行統計
    for offset in range(0, len(raw), sample_width):
        sample = decode_sample(raw[offset : offset + sample_width], sample_width)
        abs_sample = abs(sample)
        peak = max(peak, abs_sample)
        total_sq += sample * sample
        sample_count += 1

    # 計算分貝數值（dBFS）
    rms = math.sqrt(total_sq / sample_count) if sample_count else 0.0
    peak_ratio = min(peak / max_possible, 1.0)
    rms_ratio = min(rms / max_possible, 1.0)

    return {
        "channels": channels,
        "sample_width": sample_width,
        "frame_rate": frame_rate,
        "frames": frames,
        "duration": frames / frame_rate if frame_rate else 0,
        "samples": sample_count,
        "peak_percent": peak_ratio * 100.0,
        "rms_percent": rms_ratio * 100.0,
        "peak_dbfs": 20 * math.log10(peak_ratio) if peak_ratio > 0 else float("-inf"),
        "rms_dbfs": 20 * math.log10(rms_ratio) if rms_ratio > 0 else float("-inf"),
    }

# =========================
# 印出音訊分析報告，並根據音量大小給出硬體狀態的診斷建議。
# =========================

def print_result(stats: dict[str, float | int], out_path: Path) -> None:
    print()
    print("=== Capture analysis ===")
    print(f"WAV file     : {out_path}")
    print(f"Channels     : {stats['channels']}")
    print(f"Sample rate  : {stats['frame_rate']} Hz")
    print(f"Sample width : {stats['sample_width']} bytes")
    print(f"Duration     : {stats['duration']:.2f} s")
    print(f"Peak level   : {stats['peak_percent']:.3f}% ({stats['peak_dbfs']:.1f} dBFS)")
    print(f"RMS level    : {stats['rms_percent']:.3f}% ({stats['rms_dbfs']:.1f} dBFS)")
    print()

    peak = float(stats["peak_percent"])
    rms = float(stats["rms_percent"])
    
    # 根據測量數值給出硬體除錯建議
    if peak < 0.01 and rms < 0.005:
        print("Result: almost silence. Check wiring, dtoverlay, ALSA device, and L/R pin.")
    elif peak > 98:
        print("Result: signal is clipping. Lower gain or move the sound source farther away.")
    else:
        print("Result: audio signal detected. Try speaking/clapping near the INMP441 and compare levels.")

# =========================
#呼叫 `arecord` 指令錄製指定時間的 WAV 檔案。
# =========================

def capture_wav(args: argparse.Namespace) -> Path:
    require_arecord()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "arecord",
        "-q",
        "-D", args.device,
        "-f", args.format,
        "-r", str(args.rate),
        "-c", str(args.channels),
        "-d", str(args.seconds),
        "-t", "wav",
        str(out_path),
    ]
    print("Recording...")
    print(" ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        print()
        print("Recording failed.")
        print("Try listing devices first: python3 inmp441_test.py --list")
        print("Common devices are: default, plughw:0,0, plughw:1,0")
        raise SystemExit(exc.returncode)

    return out_path

# =========================
#啟動即時音量條模式。透過 Pipe 讀取 `arecord` 的串流資料並動態刷新終端機畫面。
# =========================

def meter(args: argparse.Namespace) -> None:
    require_arecord()
    sample_width, _, max_possible = SAMPLE_FORMATS[args.format]
    cmd = [
        "arecord",
        "-q",
        "-D", args.device,
        "-f", args.format,
        "-r", str(args.rate),
        "-c", str(args.channels),
        "-t", "raw", # 使用 raw 串流格式以便即時讀取二進位資料
    ]
    if args.seconds:
        cmd.extend(["-d", str(args.seconds)])

    print("Live meter. Press Ctrl+C to stop.")
    print(" ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    assert proc.stdout is not None

    chunk_size = sample_width * args.channels * 2048 # 每次讀取的緩衝區大小
    try:
        while True:
            chunk = proc.stdout.read(chunk_size)
            if not chunk:
                break
            # 解碼當前 chunk 的所有樣本
            values = [
                abs(decode_sample(chunk[i : i + sample_width], sample_width))
                for i in range(0, len(chunk) - sample_width + 1, sample_width)
            ]
            rms = math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0
            peak = max(values) if values else 0
            rms_percent = min(rms / max_possible * 100.0, 100.0)
            peak_percent = min(peak / max_possible * 100.0, 100.0)
            
            # 動態畫出 # 字型的音量條
            bars = "#" * min(int(rms_percent * 1.5), 60)
            print(f"\rRMS {rms_percent:7.3f}%  PEAK {peak_percent:7.3f}%  {bars:<60}", end="")
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
        print()

# =========================
#解析終端機輸入的指令參數。
# =========================

def parse_args() -> argparse.Namespace:  
    parser = argparse.ArgumentParser(
        description="Test an INMP441 I2S microphone through ALSA/arecord.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--list", action="store_true", help="list ALSA capture devices and exit")
    parser.add_argument("--meter", action="store_true", help="show a live level meter instead of saving WAV")
    parser.add_argument("-D", "--device", default="default", help="ALSA capture device")
    parser.add_argument("-d", "--seconds", type=int, default=5, help="recording duration in seconds")
    parser.add_argument("-r", "--rate", type=int, default=48000, help="sample rate")
    parser.add_argument("-c", "--channels", type=int, default=1, help="channel count")
    parser.add_argument("-f", "--format", choices=sorted(SAMPLE_FORMATS), default="S32_LE", help="sample format")
    parser.add_argument("-o", "--out", default="inmp441_test.wav", help="output WAV path")
    return parser.parse_args()

# =========================
#主主控流程，根據引數決定執行：列出裝置、即時音量計、或錄音並分析。
# =========================

def main() -> None:
    args = parse_args()
    if args.list:
        list_devices()
        return
    if args.meter:
        meter(args)
        return

    out_path = capture_wav(args)
    stats = analyze_wav(out_path)
    print_result(stats, out_path)


if __name__ == "__main__":
    main()