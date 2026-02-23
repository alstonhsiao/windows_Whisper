"""
Windows 語音轉文字工具 — 方案三：Python 可打包 .exe 版本

使用方式（開發）：
  pip install -r requirements.txt
  python main.py

使用方式（打包後）：
  雙擊 WhisperVoiceTyping.exe
  config.json 需放在 exe 同目錄

操作：
  - 按住 F1 → 開始錄音（聽到 beep 後開始說話）
  - 放開 F1 → 停止錄音 → 自動辨識 → 貼上文字到游標位置
  - Ctrl+Shift+Q → 結束程式
"""

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
# 設定
# ---------------------------------------------------------------------------

def get_base_dir() -> Path:
    """取得程式所在目錄（支援 PyInstaller 打包後的路徑）"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包後的 exe 目錄
        return Path(sys.executable).parent
    return Path(__file__).parent


def load_config() -> dict:
    """從 config.json 載入設定"""
    config = {
        "api_key": "",
        "model": "whisper-1",
        "language": "zh",
        "temperature": 0.0,
        "response_format": "json",
        "sample_rate": 16000,
        "channels": 1,
        "hotkey": "f1",
        "prompt": "請使用繁體中文。包含：蕭淳云, 周芷萓, 合作廠商加模, 專案 Tahoe, n8n, Zeabur。",
        "regex_rules": [
            {"pattern": r"N8n|N 8 n", "replacement": "n8n", "flags": "IGNORECASE"}
        ],
    }

    # 搜尋 config.json
    base = get_base_dir()
    config_paths = [
        base / "config.json",
        Path.home() / ".whisper-voice-typing" / "config.json",
    ]

    for cp in config_paths:
        if cp.exists():
            with open(cp, encoding="utf-8") as f:
                user_cfg = json.load(f)
            if "api" in user_cfg:
                config["api_key"] = user_cfg["api"].get("openai_api_key", config["api_key"])
                config["model"] = user_cfg["api"].get("model", config["model"])
                config["language"] = user_cfg["api"].get("language", config["language"])
                config["temperature"] = user_cfg["api"].get("temperature", config["temperature"])
            if "prompt" in user_cfg:
                config["prompt"] = user_cfg["prompt"].get("text", config["prompt"])
            if "hotkey" in user_cfg:
                config["hotkey"] = user_cfg["hotkey"].get("record_key", config["hotkey"]).lower()
            if "post_process" in user_cfg:
                config["regex_rules"] = user_cfg["post_process"].get("regex_rules", config["regex_rules"])
            break

    # .env.local 覆蓋（開發用）
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

    # 環境變數最優先
    config["api_key"] = os.environ.get("OPENAI_API_KEY", config["api_key"])

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

        wav_path = os.path.join(tempfile.gettempdir(), "whisper_voice.wav")
        sf.write(wav_path, audio_data, self.sample_rate, subtype="PCM_16")
        return wav_path

    @property
    def buffer_samples(self) -> int:
        return sum(len(f) for f in self._frames)


# ---------------------------------------------------------------------------
# Whisper API
# ---------------------------------------------------------------------------

def transcribe(wav_path: str, config: dict) -> str:
    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {config['api_key']}"}

    with open(wav_path, "rb") as f:
        files = {"file": ("voice.wav", f, "audio/wav")}
        data = {
            "model": config["model"],
            "language": config["language"],
            "temperature": str(config["temperature"]),
            "response_format": config["response_format"],
            "prompt": config["prompt"],
        }
        response = requests.post(url, headers=headers, files=files, data=data, timeout=30)

    response.raise_for_status()
    return response.json()["text"]


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
    config = load_config()

    if not config["api_key"] or config["api_key"] == "YOUR_OPENAI_API_KEY_HERE":
        # 如果是打包後的 exe，用 MessageBox 提示
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    0,
                    "請先設定 OpenAI API Key！\n\n"
                    "1. 開啟 config.json\n"
                    "2. 將 YOUR_OPENAI_API_KEY_HERE 替換為你的 API Key\n"
                    "3. 重新啟動程式",
                    "Whisper 語音轉文字",
                    0x30,  # MB_ICONWARNING
                )
            except Exception:
                pass
        print("❌ 錯誤：請設定 OPENAI_API_KEY")
        sys.exit(1)

    recorder = AudioRecorder(
        sample_rate=config["sample_rate"],
        channels=config["channels"],
    )

    recording = False
    lock = threading.Lock()

    print("=" * 50)
    print("🎤 Whisper 語音轉文字工具已啟動")
    print(f"   熱鍵：按住 {config['hotkey'].upper()} 說話，放開後自動辨識")
    print(f"   語言：{config['language']}")
    print(f"   結束：Ctrl+Shift+Q")
    print("=" * 50)

    from pynput import keyboard

    hotkey_map = {
        "f1": keyboard.Key.f1, "f2": keyboard.Key.f2,
        "f3": keyboard.Key.f3, "f4": keyboard.Key.f4,
        "f5": keyboard.Key.f5, "f6": keyboard.Key.f6,
        "f7": keyboard.Key.f7, "f8": keyboard.Key.f8,
        "f9": keyboard.Key.f9, "f10": keyboard.Key.f10,
        "f11": keyboard.Key.f11, "f12": keyboard.Key.f12,
    }
    target_key = hotkey_map.get(config["hotkey"].lower(), keyboard.Key.f1)

    def on_press(key):
        nonlocal recording
        if key != target_key:
            return
        with lock:
            if recording:
                return
            recording = True

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
            print("⚠️  錄音時間太短，已忽略")
            return

        print("🔄 辨識中...")
        try:
            raw_text = transcribe(wav_path, config)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            if status == 401:
                print("❌ API Key 無效")
            elif status == 429:
                print("❌ API 請求過於頻繁")
            else:
                print(f"❌ API 錯誤 (HTTP {status})")
            return
        except requests.exceptions.Timeout:
            print("❌ 網路逾時")
            return
        except Exception as e:
            print(f"❌ 發生錯誤：{e}")
            return

        final_text = apply_corrections(raw_text, config["regex_rules"])
        if not final_text:
            print("⚠️  辨識結果為空")
            return

        paste_text(final_text)
        print(f"✅ 已貼上：{final_text}")

    # 退出熱鍵
    exit_combo = {keyboard.Key.ctrl_l, keyboard.Key.shift, keyboard.KeyCode.from_char("q")}
    pressed_keys = set()

    def on_press_with_exit(key):
        pressed_keys.add(key)
        if exit_combo.issubset(pressed_keys):
            print("\n👋 程式結束")
            os._exit(0)
        on_press(key)

    def on_release_with_exit(key):
        pressed_keys.discard(key)
        on_release(key)

    with keyboard.Listener(on_press=on_press_with_exit, on_release=on_release_with_exit) as listener:
        listener.join()


if __name__ == "__main__":
    main()
