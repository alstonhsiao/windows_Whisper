"""
macOS 語音轉文字工具 — 方案六：Whisper / Grok STT（macOS）

使用方式：
  pip install -r requirements.txt
  python main.py

操作：
  - 按住 F9  → 開始錄音（聽到提示音後開始說話）
  - 放開 F9  → 停止錄音 → 自動辨識 → 貼上文字到游標位置
  - 按  F10  → 循環切換轉錄模式（直接轉錄 / 中翻英 / 專業模式 / 一般對話）
  - 點 HUD  → 展開模式選單（右下角浮動視窗）
  - HUD 右鍵 → 結束程式

macOS 權限需求：
  - 系統設定 → 隱私權與安全性 → 麥克風 → 允許 Terminal / IDE
  - 系統設定 → 隱私權與安全性 → 輔助使用 → 允許 Terminal / IDE
  - 系統設定 → 隱私權與安全性 → 輸入監控 → 允許 Terminal / IDE

API Provider：
  - 預設：xAI Grok STT（XAI_API_KEY in env.local）
  - 可在 config.json api.provider 切換：grok / openai / groq

與 approach-3（Windows Whisper）差異：
  - 針對 macOS 優化（提示音、Command+V、fcntl 單例鎖、rumps 選單列）
  - 加入浮動 HUD、多模式切換、API Provider 抽象
  - 無 winsound / Windows Mutex 依賴
"""

from __future__ import annotations

import json
import os
import re
import subprocess
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
# 防重複啟動（fcntl lockfile）
# ---------------------------------------------------------------------------

_lock_file_handle = None


def ensure_single_instance(app_name: str = "WhisperVoiceTypingMac") -> bool:
    """使用 lockfile + fcntl.flock 防止重複啟動"""
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
        return True


# ---------------------------------------------------------------------------
# macOS 選單列圖示（rumps — 可選）
# ---------------------------------------------------------------------------

_status_label = {"text": "⏸ 待機"}


def build_menubar_app(mode_manager):
    """
    建立 rumps 選單列 App（不啟動）。
    回傳 app 物件供 main() 在主執行緒呼叫 .run()。
    macOS 26 要求 NSApplication 必須在主執行緒初始化。
    """
    try:
        import rumps

        class VoiceTypingApp(rumps.App):
            def __init__(self):
                super().__init__("🎤", quit_button=None)
                self._mm = mode_manager
                self._rebuild_menu()

            def _rebuild_menu(self):
                """建立模式選單 + 結束按鈕"""
                items = []
                for mode in self._mm.all:
                    def _make_cb(mid):
                        def cb(_):
                            self._mm.set_by_id(mid)
                            print(f"🔀 模式 → {self._mm.current.display}")
                        return cb
                    items.append(rumps.MenuItem(mode.display, callback=_make_cb(mode.id)))
                items.append(None)  # 分隔線
                items.append(rumps.MenuItem("❌ 結束程式", callback=lambda _: os._exit(0)))
                self.menu = items

            @rumps.timer(0.4)
            def update_status(self, _):
                """每 0.4 秒更新選單列標題為目前狀態"""
                self.title = _status_label["text"]

        app = VoiceTypingApp()
        return app

    except ImportError:
        print("ℹ️  rumps 未安裝，跳過選單列圖示（功能不受影響）")
        return None
    except Exception as e:
        print(f"ℹ️  rumps 初始化失敗（{e}），跳過選單列圖示")
        return None


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
    """從 config.json 載入設定（支援新 schema + 向後相容舊 schema）"""

    # ── 預設值 ──
    _default_mode = {
        "id": "direct",
        "name": "直接轉錄",
        "icon": "📝",
        "language": "zh",
        "translate_to_english": False,
        "prompt": "請使用繁體中文。包含：蕭淳云, 周芷萓, 合作廠商加模, 專案 Tahoe, n8n, Zeabur。",
        "regex_rules": [
            {"pattern": r"N8n|N 8 n", "replacement": "n8n", "flags": "IGNORECASE"}
        ],
    }
    config = {
        # 新 schema 必要欄位預設值
        "api": {
            "provider": "grok",
            "openai": {
                "api_key": "",
                "model": "gpt-4o-transcribe",
                "endpoint": "https://api.openai.com/v1/audio/transcriptions",
            },
            "grok": {
                "api_key": "",
                "model": "grok-stt",
                "endpoint": "https://api.x.ai/v1/stt",
            },
            "groq": {
                "api_key": "",
                "model": "whisper-large-v3-turbo",
                "endpoint": "https://api.groq.com/openai/v1/audio/transcriptions",
            },
            "temperature": 0.0,
        },
        "recording": {"sample_rate": 16000, "channels": 1},
        "hotkey": {"record_key": "F1", "record_modifier": "ctrl", "mode_cycle_key": "F10"},
        "modes": [_default_mode],
        "default_mode_id": "direct",
        "ui": {
            "hud_enabled": True,
            "hud_position": "bottom-right",
            "hud_offset_x": 20,
            "hud_offset_y": 20,
            "hud_opacity": 0.9,
            "hud_font_size": 14,
        },
    }

    base = get_base_dir()
    config_paths = [
        base / "config.json",
        Path.home() / ".whisper-voice-typing" / "config.json",
    ]

    for cp in config_paths:
        if not cp.exists():
            continue
        with open(cp, encoding="utf-8") as f:
            user_cfg = json.load(f)

        # ── 新 schema ──
        if "modes" in user_cfg:
            config["modes"] = user_cfg["modes"]
            config["default_mode_id"] = user_cfg.get("default_mode_id", "direct")
            if "api" in user_cfg:
                api_u = user_cfg["api"]
                config["api"]["provider"] = api_u.get("provider", config["api"]["provider"])
                config["api"]["temperature"] = api_u.get("temperature", config["api"]["temperature"])
                for pname in ("openai", "grok", "groq"):
                    if pname in api_u:
                        config["api"][pname].update(api_u[pname])
            if "recording" in user_cfg:
                config["recording"].update(user_cfg["recording"])
            if "hotkey" in user_cfg:
                config["hotkey"].update(user_cfg["hotkey"])
            if "ui" in user_cfg:
                config["ui"].update(user_cfg["ui"])

        # ── 舊 schema fallback ──
        else:
            old_prompt = _default_mode["prompt"]
            old_regex = _default_mode["regex_rules"]
            old_lang = "zh"
            if "prompt" in user_cfg:
                old_prompt = user_cfg["prompt"].get("text", old_prompt)
            if "post_process" in user_cfg:
                old_regex = user_cfg["post_process"].get("regex_rules", old_regex)
            if "api" in user_cfg:
                old_lang = user_cfg["api"].get("language", old_lang)
                config["api"]["temperature"] = user_cfg["api"].get("temperature", 0.0)
                # 舊 schema 的 openai_api_key 對應到 openai provider
                old_key = user_cfg["api"].get("openai_api_key", "")
                if old_key and old_key != "YOUR_OPENAI_API_KEY_HERE":
                    config["api"]["openai"]["api_key"] = old_key
                old_model = user_cfg["api"].get("model", "")
                if old_model:
                    config["api"]["openai"]["model"] = old_model
                # 舊 schema 預設 provider 為 openai
                config["api"]["provider"] = "openai"
            if "recording" in user_cfg:
                config["recording"].update(user_cfg["recording"])
            if "hotkey" in user_cfg:
                config["hotkey"]["record_key"] = user_cfg["hotkey"].get("record_key", "F1")
                config["hotkey"]["record_modifier"] = user_cfg["hotkey"].get("record_modifier", "ctrl")

            # 合成一個 direct 模式
            config["modes"] = [{
                **_default_mode,
                "language": old_lang,
                "prompt": old_prompt,
                "regex_rules": old_regex,
            }]
            config["default_mode_id"] = "direct"
        break

    # ── env.local / .env.local 覆蓋 API keys ──
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

    # 環境變數優先覆蓋各 provider 的 api_key
    if os.environ.get("OPENAI_API_KEY"):
        config["api"]["openai"]["api_key"] = os.environ["OPENAI_API_KEY"]
    if os.environ.get("XAI_API_KEY"):
        config["api"]["grok"]["api_key"] = os.environ["XAI_API_KEY"]
    if os.environ.get("GROQ_API_KEY"):
        config["api"]["groq"]["api_key"] = os.environ["GROQ_API_KEY"]

    return config


# ---------------------------------------------------------------------------
# Mode 系統（多模式切換）
# ---------------------------------------------------------------------------

class Mode:
    def __init__(self, raw: dict):
        self.id = raw["id"]
        self.name = raw["name"]
        self.icon = raw.get("icon", "📝")
        self.language = raw.get("language", "zh")
        self.translate_to_english = raw.get("translate_to_english", False)
        self.prompt = raw.get("prompt", "")
        self.regex_rules = raw.get("regex_rules", [])

    @property
    def display(self) -> str:
        return f"{self.icon} {self.name}"


class ModeManager:
    """管理可切換的轉錄模式。執行緒安全。"""

    def __init__(self, modes: list[dict], default_id: str):
        self._modes = [Mode(m) for m in modes]
        if not self._modes:
            raise ValueError("config.modes 不可為空")
        self._index = 0
        for i, m in enumerate(self._modes):
            if m.id == default_id:
                self._index = i
                break
        self._lock = threading.Lock()
        self._listeners: list = []

    @property
    def current(self) -> Mode:
        with self._lock:
            return self._modes[self._index]

    @property
    def all(self) -> list[Mode]:
        return list(self._modes)

    def set_by_id(self, mode_id: str):
        with self._lock:
            for i, m in enumerate(self._modes):
                if m.id == mode_id:
                    self._index = i
                    break
        self._notify()

    def cycle(self):
        with self._lock:
            self._index = (self._index + 1) % len(self._modes)
        self._notify()

    def on_change(self, callback):
        self._listeners.append(callback)

    def _notify(self):
        current = self.current
        for cb in self._listeners:
            try:
                cb(current)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# API Provider 抽象
# ---------------------------------------------------------------------------

class TranscribeProvider:
    """Provider 介面。子類實作 transcribe(wav_path, mode) -> str"""
    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def transcribe(self, wav_path: str, mode: Mode) -> str:
        raise NotImplementedError


class OpenAIProvider(TranscribeProvider):
    name = "openai"

    def transcribe(self, wav_path, mode):
        url = self.cfg["endpoint"]
        headers = {"Authorization": f"Bearer {self.cfg['api_key']}"}
        with open(wav_path, "rb") as f:
            files = {"file": ("voice.wav", f, "audio/wav")}
            data = {
                "model": self.cfg["model"],
                "language": mode.language,
                "temperature": str(self.cfg.get("temperature", 0.0)),
                "response_format": "text",
                "prompt": mode.prompt,
            }
            if mode.translate_to_english:
                url = url.replace("/transcriptions", "/translations")
                data.pop("language", None)
            r = requests.post(url, headers=headers, files=files, data=data, timeout=30)
        r.raise_for_status()
        return r.text.strip()


class GroqProvider(TranscribeProvider):
    """Groq API 與 OpenAI 格式相容"""
    name = "groq"

    def transcribe(self, wav_path, mode):
        return OpenAIProvider.transcribe(self, wav_path, mode)


class GrokProvider(TranscribeProvider):
    """xAI Grok STT — https://api.x.ai/v1/stt
    欄位：file（最後）、language、keyterm（可重複，對應 prompt 關鍵詞）
    無 model 欄位；回應：JSON {"text":"...", "language":"...", "duration":N}
    """
    name = "grok"

    def transcribe(self, wav_path, mode):
        url = self.cfg["endpoint"]
        headers = {"Authorization": f"Bearer {self.cfg['api_key']}"}
        lang = "en" if mode.translate_to_english else mode.language
        # keyterm：從 prompt 中擷取逗號分隔的關鍵字（最多 100 個，每個最多 50 字元）
        keyterms = [kw.strip() for kw in mode.prompt.split(",") if kw.strip()][:10]
        # multipart 手動組裝，確保 file 在最後
        fields = [("language", lang)]
        for kt in keyterms:
            if len(kt) <= 50:
                fields.append(("keyterm", kt))
        with open(wav_path, "rb") as f:
            files = {"file": ("voice.wav", f, "audio/wav")}
            r = requests.post(
                url, headers=headers,
                data=fields,
                files=files,
                timeout=30,
            )
        r.raise_for_status()
        try:
            return r.json().get("text", "").strip()
        except ValueError:
            return r.text.strip()


def build_provider(api_cfg: dict) -> TranscribeProvider:
    name = api_cfg.get("provider", "grok").lower()
    sub = dict(api_cfg.get(name, {}))
    sub["temperature"] = api_cfg.get("temperature", 0.0)
    if not sub.get("api_key"):
        raise RuntimeError(f"❌ {name} provider 缺少 api_key（請設定對應環境變數）")
    return {
        "openai": OpenAIProvider,
        "grok": GrokProvider,
        "groq": GroqProvider,
    }[name](sub)


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

        wav_path = os.path.join(tempfile.gettempdir(), "whisper_voice_mac.wav")
        sf.write(wav_path, audio_data, self.sample_rate, subtype="PCM_16")
        return wav_path

    @property
    def buffer_samples(self) -> int:
        return sum(len(f) for f in self._frames)


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
# 貼上（macOS：osascript → 對前景視窗發送 Cmd+V，比 pynput 更可靠）
# ---------------------------------------------------------------------------

def paste_text(text: str):
    import subprocess

    # 1. 寫入剪貼簿
    pyperclip.copy(text)

    # 2. 短暫等待，讓焦點有時間回到目標視窗
    time.sleep(0.15)

    # 3. 用 osascript 對當前前景 App 發送 Cmd+V
    result = subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to keystroke "v" using command down'],
        capture_output=True,
    )

    # 如果 osascript 失敗（罕見），fallback 到 pynput
    if result.returncode != 0:
        from pynput.keyboard import Controller, Key
        kb = Controller()
        kb.press(Key.cmd)
        kb.press("v")
        kb.release("v")
        kb.release(Key.cmd)


# ---------------------------------------------------------------------------
# tkinter 可用性預檢（避免舊版 Tk 在 macOS 新版崩潰）
# ---------------------------------------------------------------------------

def _probe_tkinter() -> bool:
    """
    在子程序中測試 tkinter 是否能正常建立帶背景色的 Widget。
    macOS 26 上 Tk 9.0 在 TkpGetColor → GetRGBA 時呼叫已移除的
    [NSApplication macOSVersion]，導致 SIGABRT。
    此探測能在子程序中安全偵測這個崩潰，不影響主程序。
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "import tkinter as tk;"
             "r=tk.Tk();"
             "f=tk.Frame(r,bg='#1c1c1e',padx=4,pady=4);"
             "tk.Label(f,text='HUD',fg='white',bg='#1c1c1e').pack();"
             "f.pack();"
             "r.update_idletasks();"
             "r.destroy();"
             "print('ok')"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0 and b"ok" in result.stdout
    except Exception:
        return False


# ---------------------------------------------------------------------------
# HUD（浮動視窗）
# ---------------------------------------------------------------------------

class HUD:
    """tkinter 浮動 HUD，顯示模式 + 錄音狀態，點擊展開選單切換模式。"""

    STATE_TEXT = {
        "idle":       ("⏸", "#888888"),
        "recording":  ("🔴", "#ff3b30"),
        "processing": ("🔄", "#ff9500"),
        "error":      ("⚠️", "#ff3b30"),
    }

    def __init__(self, mode_manager: "ModeManager", ui_cfg: dict, on_quit):
        self.mm = mode_manager
        self.ui = ui_cfg
        self.on_quit = on_quit
        self._state = "idle"
        self._root = None
        self._main_label = None
        self._state_label = None
        self._menu_window = None
        self._ready = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(timeout=3)
        self.mm.on_change(lambda mode: self._schedule(self._render))

    def _run(self):
        import tkinter as tk
        self._tk = tk
        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", self.ui.get("hud_opacity", 0.9))
        self._root.configure(bg="#1c1c1e")

        frame = tk.Frame(self._root, bg="#1c1c1e", padx=12, pady=6)
        frame.pack()

        font_size = self.ui.get("hud_font_size", 14)
        self._main_label = tk.Label(
            frame, text="", fg="white", bg="#1c1c1e",
            font=("Helvetica", font_size, "bold"), cursor="hand2",
        )
        self._main_label.pack(side="left", padx=(0, 8))
        self._main_label.bind("<Button-1>", lambda e: self._toggle_menu())

        self._state_label = tk.Label(
            frame, text="⏸", fg="#888888", bg="#1c1c1e",
            font=("Helvetica", font_size + 2),
        )
        self._state_label.pack(side="left")

        self._root.bind("<Button-3>", lambda e: self.on_quit())

        self._place_window()
        self._render()
        self._ready.set()
        self._root.mainloop()

    def _place_window(self):
        self._root.update_idletasks()
        w = self._root.winfo_reqwidth()
        h = self._root.winfo_reqheight()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        pos = self.ui.get("hud_position", "bottom-right")
        ox = self.ui.get("hud_offset_x", 20)
        oy = self.ui.get("hud_offset_y", 20)
        if pos == "bottom-right":
            x, y = sw - w - ox, sh - h - oy - 30
        elif pos == "top-right":
            x, y = sw - w - ox, oy + 30
        elif pos == "top-left":
            x, y = ox, oy + 30
        else:
            x, y = ox, sh - h - oy - 30
        self._root.geometry(f"+{x}+{y}")

    def _render(self):
        if not self._main_label:
            return
        mode = self.mm.current
        self._main_label.config(text=mode.display)
        icon, color = self.STATE_TEXT.get(self._state, self.STATE_TEXT["idle"])
        self._state_label.config(text=icon, fg=color)
        self._place_window()

    def set_state(self, state: str):
        self._state = state
        self._schedule(self._render)

    def _schedule(self, fn):
        if self._root:
            self._root.after(0, fn)

    def _toggle_menu(self):
        if self._menu_window and self._menu_window.winfo_exists():
            self._close_menu()
        else:
            self._open_menu()

    def _open_menu(self):
        tk = self._tk
        self._menu_window = tk.Toplevel(self._root)
        self._menu_window.overrideredirect(True)
        self._menu_window.attributes("-topmost", True)
        self._menu_window.configure(bg="#2c2c2e")

        font_size = self.ui.get("hud_font_size", 14)
        current_id = self.mm.current.id
        for mode in self.mm.all:
            mark = " ✓" if mode.id == current_id else "  "
            label = tk.Label(
                self._menu_window,
                text=f"{mode.display}{mark}",
                fg="white", bg="#2c2c2e",
                font=("Helvetica", font_size),
                padx=14, pady=6, anchor="w", cursor="hand2",
            )
            label.pack(fill="x")
            label.bind("<Enter>", lambda e, w=label: w.config(bg="#3a3a3c"))
            label.bind("<Leave>", lambda e, w=label: w.config(bg="#2c2c2e"))
            label.bind("<Button-1>", lambda e, mid=mode.id: self._select_mode(mid))

        sep = tk.Frame(self._menu_window, height=1, bg="#48484a")
        sep.pack(fill="x", padx=8, pady=2)
        quit_label = tk.Label(
            self._menu_window, text="❌ 結束程式",
            fg="#ff453a", bg="#2c2c2e",
            font=("Helvetica", font_size),
            padx=14, pady=6, anchor="w", cursor="hand2",
        )
        quit_label.pack(fill="x")
        quit_label.bind("<Button-1>", lambda e: self.on_quit())

        self._root.update_idletasks()
        self._menu_window.update_idletasks()
        rx = self._root.winfo_rootx()
        ry = self._root.winfo_rooty()
        mh = self._menu_window.winfo_reqheight()
        self._menu_window.geometry(f"+{rx}+{ry - mh - 4}")

        self._menu_window.bind("<FocusOut>", lambda e: self._close_menu())
        self._menu_window.focus_set()

    def _close_menu(self):
        if self._menu_window:
            try:
                self._menu_window.destroy()
            except Exception:
                pass
            self._menu_window = None

    def _select_mode(self, mode_id: str):
        self.mm.set_by_id(mode_id)
        self._close_menu()

    def shutdown(self):
        if self._root:
            self._schedule(self._root.destroy)


# ---------------------------------------------------------------------------
# 主程式
# ---------------------------------------------------------------------------

def main():
    # ── 1. 防重複啟動 ──
    if not ensure_single_instance():
        sys.exit(0)

    # ── 2. 載入設定 ──
    config = load_config()
    mode_manager = ModeManager(config["modes"], config["default_mode_id"])

    try:
        provider = build_provider(config["api"])
    except (RuntimeError, KeyError) as e:
        print(f"❌ Provider 初始化失敗：{e}")
        sys.exit(1)

    # ── 3. 建立 rumps app（不啟動，稍後在主執行緒執行）──
    rumps_app = build_menubar_app(mode_manager)

    # ── 4. HUD ──
    hud = None
    if config["ui"]["hud_enabled"]:
        if _probe_tkinter():
            hud = HUD(mode_manager, config["ui"], on_quit=lambda: os._exit(0))
            hud.start()
        else:
            print("⚠️  HUD 已停用：tkinter 無法初始化（Tk 版本與 macOS 不相容）")
            print("   修復方式：brew install python-tk@3.14")

    def set_state(s: str):
        set_menubar_state(s)
        if hud:
            hud.set_state(s)

    # ── 5. 初始化錄音 ──
    recorder = AudioRecorder(
        sample_rate=config["recording"]["sample_rate"],
        channels=config["recording"]["channels"],
    )
    recording_flag = False
    lock = threading.Lock()

    # ── 6. 熱鍵偵測 ──
    from pynput import keyboard

    hotkey_map = {
        f"f{i}": getattr(keyboard.Key, f"f{i}")
        for i in range(1, 21) if hasattr(keyboard.Key, f"f{i}")
    }
    record_key      = hotkey_map.get(config["hotkey"]["record_key"].lower(), keyboard.Key.f1)
    cycle_key       = hotkey_map.get(config["hotkey"]["mode_cycle_key"].lower(), keyboard.Key.f10)
    record_modifier = config["hotkey"].get("record_modifier", "").lower()  # "ctrl" / "shift" / ""

    # 修飾鍵顯示名（用於 Terminal 提示）
    _mod_display  = f"{record_modifier.upper()}+" if record_modifier else ""
    _key_display  = config["hotkey"]["record_key"].upper()
    hotkey_display = f"{_mod_display}{_key_display}"

    print("=" * 50)
    print("🎤 Whisper 語音轉文字工具已啟動（macOS）")
    print(f"   錄音熱鍵：{hotkey_display}（按一下開始，再按一下停止）")
    print(f"   切換模式：{config['hotkey']['mode_cycle_key'].upper()} 或點 HUD")
    print(f"   Provider：{provider.name}")
    print(f"   目前模式：{mode_manager.current.display}")
    print("   結束：選單列 ❌ 結束程式 或 Ctrl+C")
    print("=" * 50)

    # 修飾鍵即時狀態追蹤
    _MODIFIER_KEYS = {
        "ctrl":  (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl),
        "shift": (keyboard.Key.shift_l, keyboard.Key.shift_r, keyboard.Key.shift),
        "alt":   (keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt),
    }
    _pressed_mods: set[str] = set()

    def _modifier_ok() -> bool:
        """record_modifier 目前是否被按住（無設定則直接通過）"""
        return not record_modifier or record_modifier in _pressed_mods

    def _do_start_recording():
        """背景執行緒：啟動錄音 + 等待 beep，不阻塞監聽器"""
        set_state("recording")
        print(f"🔴 錄音中... [模式：{mode_manager.current.display}]（再按 {hotkey_display} 停止）")
        recorder.start()
        for _ in range(60):
            time.sleep(0.05)
            if recorder.buffer_samples > 4000:
                beep()
                break

    def _do_process_recording():
        """背景執行緒：停止錄音 → 辨識 → 貼上，不阻塞監聽器"""
        wav_path = recorder.stop()
        if not wav_path:
            set_state("idle")
            print("⚠️  錄音時間太短，已忽略")
            return

        set_state("processing")
        mode = mode_manager.current
        print(f"🔄 辨識中... [{mode.display}]")

        try:
            raw_text = provider.transcribe(wav_path, mode)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            msg = {401: "API Key 無效", 403: "API Key 權限不足", 429: "請求過於頻繁"}.get(
                status, f"API 錯誤 HTTP {status}"
            )
            print(f"❌ {msg}")
            set_state("error")
            time.sleep(2)
            set_state("idle")
            return
        except requests.exceptions.Timeout:
            print("❌ 網路逾時")
            set_state("error")
            time.sleep(2)
            set_state("idle")
            return
        except Exception as e:
            print(f"❌ 發生錯誤：{e}")
            set_state("error")
            time.sleep(2)
            set_state("idle")
            return

        final_text = apply_corrections(raw_text, mode.regex_rules)
        if not final_text:
            print("⚠️  辨識結果為空")
            set_state("idle")
            return

        paste_text(final_text)
        print(f"✅ 已貼上：{final_text}")
        set_state("idle")

    def on_press(key):
        nonlocal recording_flag

        # ── 追蹤修飾鍵按下 ──
        for mod_name, mod_keys in _MODIFIER_KEYS.items():
            if key in mod_keys:
                _pressed_mods.add(mod_name)
                return

        # ── F10：循環切換模式 ──
        if key == cycle_key:
            mode_manager.cycle()
            print(f"🔀 模式 → {mode_manager.current.display}")
            return

        # ── 錄音切換鍵（需搭配 record_modifier）──
        if key != record_key or not _modifier_ok():
            return

        with lock:
            if not recording_flag:
                # 第一次按：開始錄音
                recording_flag = True
                threading.Thread(target=_do_start_recording, daemon=True).start()
            else:
                # 第二次按：停止並辨識
                recording_flag = False
                threading.Thread(target=_do_process_recording, daemon=True).start()

    def on_release(key):
        # 追蹤修飾鍵放開（Toggle 模式不需要在 on_release 控制錄音）
        for mod_name, mod_keys in _MODIFIER_KEYS.items():
            if key in mod_keys:
                _pressed_mods.discard(mod_name)
                return

    # pynput 以背景執行緒啟動（非阻塞）
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    # 主執行緒執行 NSApplication 事件迴圈
    # macOS 26 要求 NSApplication（rumps）必須在主執行緒
    if rumps_app:
        try:
            rumps_app.run()   # 阻塞主執行緒直到使用者退出
        except KeyboardInterrupt:
            pass
    else:
        # rumps 不可用：直接等待 pynput listener（舊行為）
        try:
            listener.join()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
