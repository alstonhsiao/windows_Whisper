"""
macOS 語音轉文字工具 — 方案五：Gemini 1.5 Flash（macOS）

使用方式：
  pip install -r requirements.txt
  python main.py

操作：
  - 按住 F9 → 開始錄音（聽到提示音後開始說話）
  - 放開 F9 → 停止錄音 → 自動辨識 → 貼上文字到游標位置
  - 按 Ctrl+C 結束程式

macOS 權限需求：
  - 系統設定 → 隱私權與安全性 → 麥克風 → 允許 Terminal / IDE
  - 系統設定 → 隱私權與安全性 → 輔助使用 → 允許 Terminal / IDE
  - 系統設定 → 隱私權與安全性 → 輸入監控 → 允許 Terminal / IDE

與 approach-4 差異：
  - 針對 macOS 優化（提示音、快捷鍵、單例鎖、選用 rumps 系統列）
  - 使用 Command+V 貼上（非 Ctrl+V）
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
# 防重複啟動（跨平台 lockfile）
# ---------------------------------------------------------------------------

_lock_file_handle = None


def ensure_single_instance(app_name: str = "GeminiVoiceTyping") -> bool:
    """
    使用 lockfile 防止重複啟動。
    macOS / Linux：fcntl.flock
    Windows fallback：Named Mutex（但此方案 macOS 專用）
    """
    global _lock_file_handle
    lock_path = Path(tempfile.gettempdir()) / f"{app_name}.lock"

    try:
        import fcntl
        _lock_file_handle = open(lock_path, "w")
        fcntl.flock(_lock_file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_file_handle.write(str(os.getpid()))
        _lock_file_handle.flush()
        return True
    except (IOError, OSError):
        print(f"⚠️  程式已經在執行中（lock: {lock_path}）")
        return False
    except ImportError:
        # Windows — 不應該走到這裡，但保險起見
        return True


# ---------------------------------------------------------------------------
# macOS 選單列圖示（rumps — 可選）
# ---------------------------------------------------------------------------

_status_label = {"text": "⏸ 待機"}


def try_start_menubar():
    """嘗試啟動 macOS 選單列圖示（rumps），失敗則跳過"""
    try:
        import rumps

        class VoiceTypingApp(rumps.App):
            def __init__(self):
                super().__init__("🎤", quit_button="結束程式")
                self.menu = [rumps.MenuItem("Gemini 語音轉文字"), None]

            @rumps.timer(1)
            def update_title(self, _):
                self.title = _status_label["text"]

        app = VoiceTypingApp()
        threading.Thread(target=app.run, daemon=True).start()
        return True
    except ImportError:
        print("ℹ️  rumps 未安裝，跳過選單列圖示（功能不受影響）")
        return False
    except Exception:
        return False


def set_menubar_state(state: str):
    """更新選單列圖示狀態"""
    states = {
        "idle":       "⏸ 待機",
        "recording":  "🔴 錄音中",
        "processing": "🔄 辨識中",
        "error":      "⚠️ 錯誤",
    }
    _status_label["text"] = states.get(state, "⏸ 待機")


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
            if "prompt" in user_cfg:
                config["prompt"] = user_cfg["prompt"].get("text", config["prompt"])
            if "hotkey" in user_cfg:
                config["hotkey"] = user_cfg["hotkey"].get("record_key", config["hotkey"]).lower()
            if "post_process" in user_cfg:
                config["regex_rules"] = user_cfg["post_process"].get("regex_rules", config["regex_rules"])
            break

    # .env.local 覆蓋
    env_file = base / ".env.local"
    if not env_file.exists():
        env_file = base.parent / ".env.local"
    if env_file.exists():
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())

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

        wav_path = os.path.join(tempfile.gettempdir(), "gemini_voice_mac.wav")
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
    """
    api_key = config["api_key"]
    model = config["model"]
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={api_key}"
    )

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
# Beep（macOS 原生提示音）
# ---------------------------------------------------------------------------

def beep():
    try:
        os.system("afplay /System/Library/Sounds/Tink.aiff &")
    except Exception:
        print("\a", end="", flush=True)


# ---------------------------------------------------------------------------
# 貼上（macOS：Command+V）
# ---------------------------------------------------------------------------

def paste_text(text: str):
    from pynput.keyboard import Controller, Key

    pyperclip.copy(text)
    time.sleep(0.05)

    kb = Controller()
    kb.press(Key.cmd)
    kb.press("v")
    kb.release("v")
    kb.release(Key.cmd)


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
        print("❌ 錯誤：請設定 GEMINI_API_KEY")
        print("   方法 1：在 .env.local 中設定 GEMINI_API_KEY=你的Key")
        print("   方法 2：在 config.json 中填入 gemini_api_key")
        sys.exit(1)

    # ── 3. macOS 選單列圖示（可選） ──
    try_start_menubar()

    # ── 4. 初始化錄音 ──
    recorder = AudioRecorder(
        sample_rate=config["sample_rate"],
        channels=config["channels"],
    )
    recording = False
    lock = threading.Lock()

    print("=" * 50)
    print("🎤 Gemini 語音轉文字工具已啟動（macOS）")
    print(f"   模型：{config['model']}")
    print(f"   熱鍵：按住 {config['hotkey'].upper()} 說話，放開後自動辨識")
    print(f"   語言：{config['language']}")
    print("   結束：Ctrl+C")
    print("=" * 50)

    # ── 5. 熱鍵偵測 ──
    from pynput import keyboard

    hotkey_map = {f"f{i}": getattr(keyboard.Key, f"f{i}") for i in range(1, 13)}
    target_key = hotkey_map.get(config["hotkey"].lower(), keyboard.Key.f9)

    def on_press(key):
        nonlocal recording
        if key != target_key:
            return
        with lock:
            if recording:
                return
            recording = True

        set_menubar_state("recording")
        print("🔴 錄音中... （放開按鍵停止）")
        recorder.start()

        for _ in range(60):
            time.sleep(0.05)
            if recorder.buffer_samples > 4000:
                beep()
                break

    def on_release(key):
        nonlocal recording
        if key != target_key:
            return
        with lock:
            if not recording:
                return
            recording = False

        wav_path = recorder.stop()
        if not wav_path:
            set_menubar_state("idle")
            print("⚠️  錄音時間太短，已忽略")
            return

        set_menubar_state("processing")
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
            set_menubar_state("error")
            time.sleep(2)
            set_menubar_state("idle")
            return
        except requests.exceptions.Timeout:
            print("❌ 網路逾時")
            set_menubar_state("error")
            time.sleep(2)
            set_menubar_state("idle")
            return
        except ValueError as e:
            print(f"❌ 回應解析錯誤：{e}")
            set_menubar_state("error")
            time.sleep(2)
            set_menubar_state("idle")
            return
        except Exception as e:
            print(f"❌ 發生錯誤：{e}")
            set_menubar_state("error")
            time.sleep(2)
            set_menubar_state("idle")
            return

        final_text = apply_corrections(raw_text, config["regex_rules"])
        if not final_text:
            print("⚠️  辨識結果為空")
            set_menubar_state("idle")
            return

        paste_text(final_text)
        print(f"✅ 已貼上：{final_text}")
        set_menubar_state("idle")

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


if __name__ == "__main__":
    main()
