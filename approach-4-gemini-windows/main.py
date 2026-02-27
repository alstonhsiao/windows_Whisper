"""
Windows 語音轉文字工具 — 方案四：Gemini 1.5 Flash（Windows）

使用方式（開發）：
  pip install -r requirements.txt
  python main.py

使用方式（打包後）：
  雙擊 GeminiVoiceTyping.exe
  config.json 需放在 exe 同目錄

操作：
  - 按住 F9 → 開始錄音（聽到 beep 後開始說話）
  - 放開 F9 → 停止錄音 → 自動辨識 → 貼上文字到游標位置
  - 右鍵右下角系統匣圖示 → 結束程式

防重複啟動：
  程式啟動時自動檢查是否已有實例執行，若已有則彈出提示並退出。

與 approach-3 差異：
  - 改用 Google Gemini 1.5 Flash API（多模態音訊辨識）取代 OpenAI Whisper
  - API Key 改為 GEMINI_API_KEY
"""

import base64
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pyperclip
import requests
import sounddevice as sd
import soundfile as sf


# ---------------------------------------------------------------------------
# 防重複啟動（Single Instance — Windows Named Mutex）
# ---------------------------------------------------------------------------

_mutex_handle = None


def ensure_single_instance(app_name: str = "GeminiVoiceTyping") -> bool:
    """
    建立 Windows 具名 Mutex，確保只有一個執行中的實例。
    回傳 True = 第一個實例（繼續啟動）
    回傳 False = 已有實例（彈出提示後結束）
    非 Windows 平台永遠回傳 True（供開發用）。
    """
    global _mutex_handle
    if sys.platform != "win32":
        return True

    import ctypes
    mutex_name = f"Global\\{app_name}_SingleInstance"
    handle = ctypes.windll.kernel32.CreateMutexW(None, True, mutex_name)
    last_error = ctypes.windll.kernel32.GetLastError()

    if last_error == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(
            0,
            "程式已經在執行中！\n\n請查看右下角系統匣（工作列右側）的圖示。",
            "Gemini 語音轉文字",
            0x40,
        )
        return False

    _mutex_handle = handle
    return True


# ---------------------------------------------------------------------------
# 系統匣圖示（System Tray — pystray + PIL）
# ---------------------------------------------------------------------------

TRAY_IDLE       = "idle"
TRAY_RECORDING  = "recording"
TRAY_PROCESSING = "processing"
TRAY_ERROR      = "error"

_TRAY_COLORS = {
    TRAY_IDLE:       "#5c6370",
    TRAY_RECORDING:  "#e06c75",
    TRAY_PROCESSING: "#4285f4",   # Google 藍
    TRAY_ERROR:      "#e5c07b",
}
_TRAY_TOOLTIPS = {
    TRAY_IDLE:       "Gemini 語音轉文字 — 待機中",
    TRAY_RECORDING:  "Gemini 語音轉文字 — 🔴 錄音中",
    TRAY_PROCESSING: "Gemini 語音轉文字 — 🔄 辨識中",
    TRAY_ERROR:      "Gemini 語音轉文字 — ⚠️ 發生錯誤",
}


def _make_icon_image(color: str, size: int = 64):
    """用 PIL 動態建立純色圓形麥克風圖示"""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, size - 2, size - 2], fill=color)
    cx, cy = size // 2, size // 2
    draw.ellipse([cx - 6, cy - 10, cx + 6, cy + 8], fill="white")
    draw.rectangle([cx - 4, cy + 6, cx + 4, cy + 14], fill="white")
    draw.arc([cx - 10, cy + 4, cx + 10, cy + 18], 0, 180, fill="white", width=2)
    return img


class TrayIcon:
    """系統匣圖示管理"""

    def __init__(self, hotkey: str = "F9"):
        self._state = TRAY_IDLE
        self._hotkey = hotkey.upper()
        self._icon = None
        self._lock = threading.Lock()

    def _build_menu(self):
        import pystray
        return pystray.Menu(
            pystray.MenuItem("Gemini 語音轉文字", None, enabled=False),
            pystray.MenuItem(f"熱鍵：按住 {self._hotkey} 說話", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("結束程式", lambda icon, item: os._exit(0)),
        )

    def start(self):
        """在 daemon 執行緒中啟動系統匣"""
        import pystray
        img = _make_icon_image(_TRAY_COLORS[TRAY_IDLE])
        self._icon = pystray.Icon(
            name="GeminiVoiceTyping",
            icon=img,
            title=_TRAY_TOOLTIPS[TRAY_IDLE],
            menu=self._build_menu(),
        )
        threading.Thread(target=self._icon.run, daemon=True).start()

    def set_state(self, state: str):
        """更新圖示顏色與 tooltip"""
        with self._lock:
            if self._state == state or self._icon is None:
                return
            self._state = state
        self._icon.icon = _make_icon_image(_TRAY_COLORS.get(state, _TRAY_COLORS[TRAY_IDLE]))
        self._icon.title = _TRAY_TOOLTIPS.get(state, "Gemini 語音轉文字")


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def load_config() -> dict:
    """從 config.json 載入設定"""
    config = {
        "api_key": "",
        "model": "gemini-1.5-flash",
        "language": "zh-TW",
        "sample_rate": 16000,
        "channels": 1,
        "hotkey": "f9",
        "prompt": "請將以下音訊逐字轉錄為繁體中文。僅輸出轉錄文字，不要加任何說明、標題或格式。"
                  "專有名詞參考：蕭淳云, 周芷萓, 合作廠商加模, 專案 Tahoe, n8n, Zeabur。",
        "regex_rules": [
            {"pattern": r"N8n|N 8 n", "replacement": "n8n", "flags": "IGNORECASE"}
        ],
    }

    base = get_base_dir()
    config_paths = [
        base / "config.json",
        Path.home() / ".gemini-voice-typing" / "config.json",
    ]

    for cp in config_paths:
        if cp.exists():
            with open(cp, encoding="utf-8") as f:
                user_cfg = json.load(f)
            if "api" in user_cfg:
                config["api_key"] = user_cfg["api"].get("gemini_api_key", config["api_key"])
                config["model"] = user_cfg["api"].get("model", config["model"])
                config["language"] = user_cfg["api"].get("language", config["language"])
            if "recording" in user_cfg:
                config["sample_rate"] = user_cfg["recording"].get("sample_rate", config["sample_rate"])
                config["channels"] = user_cfg["recording"].get("channels", config["channels"])
            if "prompt" in user_cfg:
                config["prompt"] = user_cfg["prompt"].get("text", config["prompt"])
            if "hotkey" in user_cfg:
                config["hotkey"] = user_cfg["hotkey"].get("record_key", config["hotkey"]).lower()
            if "post_process" in user_cfg:
                config["regex_rules"] = user_cfg["post_process"].get("regex_rules", config["regex_rules"])
            break

    # env.local / .env.local 覆蓋
    env_candidates = [
        base / "env.local",
        base / ".env.local",
        base.parent / "env.local",
        base.parent / ".env.local",
    ]
    for env_file in env_candidates:
        if env_file.exists():
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        os.environ.setdefault(key.strip(), value.strip())
            break

    config["api_key"] = os.environ.get("GEMINI_API_KEY", config["api_key"])

    return config


# ---------------------------------------------------------------------------
# 錄音模組
# ---------------------------------------------------------------------------

class AudioRecorder:
    """使用 sounddevice 在記憶體中錄音"""

    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.is_recording = False
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None

    def start(self):
        self._frames = []
        self.is_recording = True
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def _callback(self, indata, frames, time_info, status):
        if self.is_recording:
            self._frames.append(indata.copy())

    def stop(self) -> str | None:
        self.is_recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._frames:
            return None

        audio_data = np.concatenate(self._frames, axis=0)
        duration = len(audio_data) / self.sample_rate
        if duration < 0.5:
            return None

        wav_path = os.path.join(tempfile.gettempdir(), "gemini_voice.wav")
        sf.write(wav_path, audio_data, self.sample_rate, subtype="PCM_16")
        return wav_path

    @property
    def buffer_samples(self) -> int:
        return sum(len(f) for f in self._frames)


# ---------------------------------------------------------------------------
# Gemini 1.5 Flash API — 多模態音訊辨識
# ---------------------------------------------------------------------------

def transcribe(wav_path: str, config: dict) -> str:
    """
    使用 Gemini 1.5 Flash 的 generateContent API 進行語音轉文字。
    將 WAV 檔案以 base64 編碼傳送，搭配 prompt 指示模型逐字轉錄。
    """
    api_key = config["api_key"]
    model = config["model"]
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={api_key}"
    )

    # 讀取音訊並 base64 編碼
    with open(wav_path, "rb") as f:
        audio_bytes = f.read()
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": config["prompt"]},
                    {
                        "inline_data": {
                            "mime_type": "audio/wav",
                            "data": audio_b64,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 4096,
        },
    }

    headers = {"Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()

    result = response.json()

    # 解析回應
    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise ValueError(f"Gemini 回應格式異常：{json.dumps(result, ensure_ascii=False)[:200]}")

    return text.strip()


# ---------------------------------------------------------------------------
# 後處理
# ---------------------------------------------------------------------------

def apply_corrections(text: str, regex_rules: list[dict]) -> str:
    for rule in regex_rules:
        flags = 0
        flag_str = rule.get("flags", "")
        if "IGNORECASE" in flag_str.upper():
            flags |= re.IGNORECASE
        text = re.sub(rule["pattern"], rule["replacement"], text, flags=flags)
    return text.strip()


# ---------------------------------------------------------------------------
# Beep
# ---------------------------------------------------------------------------

def beep():
    try:
        if sys.platform == "win32":
            import winsound
            winsound.Beep(1000, 200)
        elif sys.platform == "darwin":
            os.system("afplay /System/Library/Sounds/Tink.aiff &")
        else:
            print("\a", end="", flush=True)
    except Exception:
        print("\a", end="", flush=True)


# ---------------------------------------------------------------------------
# 貼上
# ---------------------------------------------------------------------------

def paste_text(text: str):
    from pynput.keyboard import Controller, Key

    pyperclip.copy(text)
    time.sleep(0.05)

    kb = Controller()
    if sys.platform == "darwin":
        kb.press(Key.cmd)
        kb.press("v")
        kb.release("v")
        kb.release(Key.cmd)
    else:
        kb.press(Key.ctrl)
        kb.press("v")
        kb.release("v")
        kb.release(Key.ctrl)


# ---------------------------------------------------------------------------
# 主程式
# ---------------------------------------------------------------------------

def main():
    # ── 1. 防重複啟動 ──
    if not ensure_single_instance():
        sys.exit(0)

    # ── 2. 載入設定 ──
    config = load_config()

    if not config["api_key"] or config["api_key"] == "YOUR_GEMINI_API_KEY_HERE":
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    0,
                    "請先設定 Gemini API Key！\n\n"
                    "開啟 config.json，將\n"
                    "YOUR_GEMINI_API_KEY_HERE\n"
                    "替換為你的 API Key，重新啟動程式。",
                    "Gemini 語音轉文字",
                    0x30,
                )
            except Exception:
                pass
        print("❌ 錯誤：請設定 GEMINI_API_KEY")
        sys.exit(1)

    # ── 3. 啟動系統匣圖示 ──
    tray = TrayIcon(hotkey=config["hotkey"])
    tray.start()

    # ── 4. 初始化錄音 ──
    recorder = AudioRecorder(
        sample_rate=config["sample_rate"],
        channels=config["channels"],
    )
    recording = False
    lock = threading.Lock()

    print("=" * 50)
    print("🎤 Gemini 語音轉文字工具已啟動（Windows）")
    print(f"   模型：{config['model']}")
    print(f"   熱鍵：按住 {config['hotkey'].upper()} 說話，放開後自動辨識")
    print(f"   語言：{config['language']}")
    print("   結束：右鍵右下角系統匣圖示 → 結束程式")
    print("=" * 50)

    # ── 5. 熱鍵偵測 ──
    from pynput import keyboard

    hotkey_map = {f"f{i}": getattr(keyboard.Key, f"f{i}") for i in range(1, 13)}
    target_key = hotkey_map.get(config["hotkey"].lower(), keyboard.Key.f9)

    def _do_start_recording():
        tray.set_state(TRAY_RECORDING)
        print("🔴 錄音中... （放開按鍵停止）")
        recorder.start()

        for _ in range(60):
            time.sleep(0.05)
            if recorder.buffer_samples > 4000:
                beep()
                break

    def _do_process_recording():
        wav_path = recorder.stop()
        if not wav_path:
            tray.set_state(TRAY_IDLE)
            print("⚠️  錄音時間太短，已忽略")
            return

        tray.set_state(TRAY_PROCESSING)
        print("🔄 辨識中...")

        try:
            raw_text = transcribe(wav_path, config)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            msg = {
                400: "請求格式錯誤",
                401: "API Key 無效",
                403: "API Key 權限不足",
                429: "請求過於頻繁（超出配額）",
            }.get(status, f"API 錯誤 HTTP {status}")
            print(f"❌ {msg}")
            tray.set_state(TRAY_ERROR)
            time.sleep(2)
            tray.set_state(TRAY_IDLE)
            return
        except requests.exceptions.Timeout:
            print("❌ 網路逾時")
            tray.set_state(TRAY_ERROR)
            time.sleep(2)
            tray.set_state(TRAY_IDLE)
            return
        except ValueError as e:
            print(f"❌ 回應解析錯誤：{e}")
            tray.set_state(TRAY_ERROR)
            time.sleep(2)
            tray.set_state(TRAY_IDLE)
            return
        except Exception as e:
            print(f"❌ 發生錯誤：{e}")
            tray.set_state(TRAY_ERROR)
            time.sleep(2)
            tray.set_state(TRAY_IDLE)
            return

        final_text = apply_corrections(raw_text, config["regex_rules"])
        if not final_text:
            print("⚠️  辨識結果為空")
            tray.set_state(TRAY_IDLE)
            return

        paste_text(final_text)
        print(f"✅ 已貼上：{final_text}")
        tray.set_state(TRAY_IDLE)

    def on_press(key):
        nonlocal recording
        if key != target_key:
            return
        with lock:
            if recording:
                return
            recording = True
        threading.Thread(target=_do_start_recording, daemon=True).start()

    def on_release(key):
        nonlocal recording
        if key != target_key:
            return
        with lock:
            if not recording:
                return
            recording = False
        threading.Thread(target=_do_process_recording, daemon=True).start()

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


if __name__ == "__main__":
    main()
