# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "sounddevice>=0.5.0",
#     "soundfile>=0.12.0",
#     "numpy>=1.24.0",
#     "requests>=2.31.0",
#     "pynput>=1.7.6",
#     "pyperclip>=1.8.2",
# ]
# ///

"""
Windows 語音轉文字工具 — 方案一：Python + uv 單檔腳本

使用方式：
  1. 安裝 uv：powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  2. 設定 env.local（或 .env.local）中的 OPENAI_API_KEY
  3. 執行：uv run main.py

操作：
  - 按住 F9 → 開始錄音（聽到 beep 後開始說話）
  - 放開 F9 → 停止錄音 → 自動辨識 → 貼上文字到游標位置
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

def load_env_local():
    """從 env.local / .env.local 讀取環境變數"""
    env_paths = [
        Path(__file__).parent.parent / "env.local",   # repo 根目錄
        Path(__file__).parent.parent / ".env.local",  # 相容舊檔名
        Path(__file__).parent / "env.local",          # 同目錄
        Path(__file__).parent / ".env.local",         # 相容舊檔名
    ]
    for env_path in env_paths:
        if env_path.exists():
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        os.environ.setdefault(key.strip(), value.strip())
            break


def load_config():
    """載入設定（優先環境變數，其次 config.json，最後預設值）"""
    config = {
        "api_key": "",
        "model": "whisper-1",
        "language": "zh",
        "temperature": 0.0,
        "response_format": "json",
        "sample_rate": 16000,
        "channels": 1,
        "hotkey": "f9",
        "prompt": "請使用繁體中文。包含：蕭淳云, 周芷萓, 合作廠商加模, 專案 Tahoe, n8n, Zeabur。",
        "regex_rules": [
            {"pattern": r"N8n|N 8 n", "replacement": "n8n", "flags": "IGNORECASE"}
        ],
    }

    # 嘗試讀取 config.json
    config_paths = [
        Path(__file__).parent / "config.json",
        Path(__file__).parent.parent / "config.json",
    ]
    for cp in config_paths:
        if cp.exists():
            with open(cp, encoding="utf-8") as f:
                user_cfg = json.load(f)
            # 合併 user config
            if "api" in user_cfg:
                config["api_key"] = user_cfg["api"].get("openai_api_key", config["api_key"])
                config["model"] = user_cfg["api"].get("model", config["model"])
                config["language"] = user_cfg["api"].get("language", config["language"])
                config["temperature"] = user_cfg["api"].get("temperature", config["temperature"])
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

    # 環境變數覆蓋
    config["api_key"] = os.environ.get("OPENAI_API_KEY", config["api_key"])

    return config


# ---------------------------------------------------------------------------
# 錄音模組
# ---------------------------------------------------------------------------

class AudioRecorder:
    """使用 sounddevice 在記憶體中錄音，避免 WAV header 損壞問題"""

    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.is_recording = False
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None

    def start(self):
        """啟動錄音（非阻塞，背景 callback 收集音訊）"""
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
        """PortAudio callback — 在背景線程中收集音訊數據"""
        if self.is_recording:
            self._frames.append(indata.copy())

    def stop(self) -> str | None:
        """停止錄音，將音訊寫入 WAV 檔案，回傳檔案路徑"""
        self.is_recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._frames:
            return None

        audio_data = np.concatenate(self._frames, axis=0)

        # 檢查錄音長度（< 0.5 秒視為太短）
        duration = len(audio_data) / self.sample_rate
        if duration < 0.5:
            return None

        # 寫入 WAV 暫存檔
        wav_path = os.path.join(tempfile.gettempdir(), "whisper_voice.wav")
        sf.write(wav_path, audio_data, self.sample_rate, subtype="PCM_16")
        return wav_path

    @property
    def buffer_samples(self) -> int:
        """目前已收集的 sample 數量"""
        return sum(len(f) for f in self._frames)


# ---------------------------------------------------------------------------
# Whisper API 模組
# ---------------------------------------------------------------------------

def transcribe(wav_path: str, config: dict) -> str:
    """呼叫 OpenAI Whisper API 進行語音辨識"""
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
        response = requests.post(
            url, headers=headers, files=files, data=data,
            timeout=30,
        )

    response.raise_for_status()
    return response.json()["text"]


# ---------------------------------------------------------------------------
# 後處理模組
# ---------------------------------------------------------------------------

def apply_corrections(text: str, regex_rules: list[dict]) -> str:
    """套用 Regex 修正規則並 Trim 空白"""
    for rule in regex_rules:
        flags = 0
        flag_str = rule.get("flags", "")
        if "IGNORECASE" in flag_str.upper():
            flags |= re.IGNORECASE
        text = re.sub(rule["pattern"], rule["replacement"], text, flags=flags)
    return text.strip()


# ---------------------------------------------------------------------------
# Beep 通知（跨平台）
# ---------------------------------------------------------------------------

def beep():
    """播放提示音，通知使用者可以開始說話"""
    try:
        if sys.platform == "win32":
            import winsound
            winsound.Beep(1000, 200)
        elif sys.platform == "darwin":
            os.system("afplay /System/Library/Sounds/Tink.aiff &")
        else:
            # Linux fallback
            print("\a", end="", flush=True)
    except Exception:
        print("\a", end="", flush=True)


# ---------------------------------------------------------------------------
# 貼上文字
# ---------------------------------------------------------------------------

def paste_text(text: str):
    """將文字寫入剪貼簿並模擬 Ctrl+V 貼上"""
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
    load_env_local()
    config = load_config()

    # 檢查 API Key
    if not config["api_key"] or config["api_key"] == "your_openai_api_key_here":
        print("❌ 錯誤：請在 env.local（或 .env.local）中設定 OPENAI_API_KEY")
        print("   檔案位置：專案根目錄的 env.local")
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

    # --- 熱鍵偵測 ---
    from pynput import keyboard

    # 將 config hotkey 字串轉為 pynput Key
    hotkey_map = {
        "f1": keyboard.Key.f1, "f2": keyboard.Key.f2,
        "f3": keyboard.Key.f3, "f4": keyboard.Key.f4,
        "f5": keyboard.Key.f5, "f6": keyboard.Key.f6,
        "f7": keyboard.Key.f7, "f8": keyboard.Key.f8,
        "f9": keyboard.Key.f9, "f10": keyboard.Key.f10,
        "f11": keyboard.Key.f11, "f12": keyboard.Key.f12,
    }
    target_key = hotkey_map.get(config["hotkey"].lower(), keyboard.Key.f9)

    def _do_start_recording():
        print("🔴 錄音中... （放開按鍵停止）")
        recorder.start()

        # 等待 buffer 累積（約 0.25 秒 = 4000 samples @16kHz）
        for _ in range(60):
            time.sleep(0.05)
            if recorder.buffer_samples > 4000:
                beep()
                break

    def _do_process_recording():
        # 停止錄音
        wav_path = recorder.stop()
        if not wav_path:
            print("⚠️  錄音時間太短，已忽略")
            return

        # 呼叫 API
        print("🔄 辨識中...")
        try:
            raw_text = transcribe(wav_path, config)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            if status == 401:
                print("❌ API Key 無效，請檢查 env.local / .env.local")
            elif status == 429:
                print("❌ API 請求過於頻繁，請稍後再試")
            else:
                print(f"❌ API 錯誤 (HTTP {status})")
            return
        except requests.exceptions.Timeout:
            print("❌ 網路逾時，請檢查網路連線")
            return
        except Exception as e:
            print(f"❌ 發生錯誤：{e}")
            return

        # 後處理
        final_text = apply_corrections(raw_text, config["regex_rules"])

        if not final_text:
            print("⚠️  辨識結果為空")
            return

        # 貼上
        paste_text(final_text)
        print(f"✅ 已貼上：{final_text}")

    def on_press(key):
        nonlocal recording
        if key != target_key:
            return
        with lock:
            if recording:
                return  # 防止重複觸發
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

    # 退出熱鍵偵測
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
