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

import ctypes
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyperclip
import requests
import sounddevice as sd
import soundfile as sf

try:
    from opencc import OpenCC
except ImportError:
    OpenCC = None


# ---------------------------------------------------------------------------
# 防重複啟動（fcntl lockfile）
# ---------------------------------------------------------------------------

_lock_file_handle = None


_PID_FILE = Path("/tmp/WhisperVoice.pid")
_OPENCC_CONVERTER = OpenCC("s2twp") if OpenCC else None


def write_pid_file() -> None:
    _PID_FILE.write_text(str(os.getpid()))


def remove_pid_file() -> None:
    _PID_FILE.unlink(missing_ok=True)


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
                items.append(rumps.MenuItem("❌ 結束程式", callback=lambda _: (remove_pid_file(), os._exit(0))))
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
        "hotkey": {
            "record_key": "F1",
            "record_modifier": "ctrl",
            "mode_cycle_key": "F10",
            "mode_cycle_modifier": "ctrl",
        },
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
                if "llm_correction" in api_u:
                    config["api"]["llm_correction"] = api_u["llm_correction"]
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
                config["hotkey"]["mode_cycle_key"] = user_cfg["hotkey"].get("mode_cycle_key", "F10")
                config["hotkey"]["mode_cycle_modifier"] = user_cfg["hotkey"].get("mode_cycle_modifier", "ctrl")

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
        self.grok_keyterms = raw.get("grok_keyterms", [])
        self.llm_prompt = raw.get("llm_prompt", "")

        # 向後相容：若無 grok_keyterms，從 prompt 提取
        if not self.grok_keyterms and self.prompt:
            self.grok_keyterms = [
                kw.strip() for kw in self.prompt.split(",") if kw.strip()
            ]

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
        # keyterm：改為直接使用 mode.grok_keyterms，最多 10 個（Grok STT API 限制）
        keyterms = mode.grok_keyterms[:10]
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
# LLM 修正 Provider 抽象
# ---------------------------------------------------------------------------

class LLMCorrectionProvider:
    """LLM 後處理介面。子類實作 correct(text, mode) -> str"""
    name = "base_llm"

    def correct(self, text: str, mode: Mode) -> str:
        raise NotImplementedError


class CerebrasProvider(LLMCorrectionProvider):
    """Cerebras 快速 LLM 修正（Llama / Qwen）"""
    name = "cerebras"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def correct(self, text: str, mode: Mode) -> str:
        self.last_finish_reason: str | None = None
        if not mode.llm_prompt or not text:
            return text
        try:
            url = self.cfg.get("endpoint", "https://api.cerebras.ai/v1/chat/completions")
            headers = {
                "Authorization": f"Bearer {self.cfg['api_key']}",
                "Content-Type": "application/json"
            }
            data = {
                "model": self.cfg.get("model", "llama3.3-70b"),
                "messages": [
                    {"role": "system", "content": mode.llm_prompt},
                    {"role": "user",   "content": text},
                ],
                "max_tokens": self.cfg.get("max_tokens", 512),
                "temperature": 0.0,
            }
            r = requests.post(url, headers=headers, json=data, timeout=15)
            r.raise_for_status()
            res = r.json()
            choice = res["choices"][0]
            self.last_finish_reason = choice.get("finish_reason")
            if self.last_finish_reason == "length":
                print(f"⚠️  Cerebras 輸出被截斷（finish_reason=length，max_tokens={self.cfg.get('max_tokens', 512)}）")
            return choice["message"]["content"].strip()
        except Exception as e:
            print(f"⚠️  Cerebras 修正失敗（{e}），使用原始文字")
            return text  # fallback：返回未修正的文字


_SIMPLIFIED_CHAR_PATTERN = re.compile(
    "["  # 常見簡體字，足以做告警判斷
    "万与丑专业东丝丢两严丧个丰临为丽举么义乌乐乔习乡书买乱争于亏云亚产亩亲亵亿仅从"
    "仓仪们价众优会伞伟传伤伦伪体余侠侣侥侦侧侨侩侪侬俩俭债倾偬儿兑党兰关兴养兽冈"
    "册写军农冯冲决况冻净凉减凑几凤凭凯击凿刍划刘则刚创删别刬刭刹剂剐剑剥剧劝办务"
    "动励劲劳势勋匀区医华协单卖卢卤卧卫却厂厅历厉压厌厦厨县参双发变叙叶号叹叽吁后"
    "吓吕吗吨听启吴呐呒呓呕呗员呙呛呜咏咙咛咝咸响哑哒哓哔哕哗哙哜唛唠唡唢唤啧啬啭啮"
    "喷喽喾嗫嘘嘤噜嚣团园围国图圆圣场坏块坚坛坝坞坟坠垄垅垒垦垩垫垭垯垱垲埙埚埯堑堕"
    "墙壮声壳壶壹处备复够头夹夺奁奂奋奖奥妇妈妩姗姜姹娄娱娲娴婳婴婵媪嫒嫔嬷孙学宁宝"
    "实宠审宪宫宽宾寝对寻导寿将尔尘尝尧尴尸层屉届属屡岁岂岖岗岛岭岳岽岿峃峡峤峥峦崂"
    "崃崄崭嵘巅巩币帅师帐帘帜带帮帱帻帼幂广庄庆库应庙庞废廪开异弃张弥弯弹强归录彦彻"
    "径征待很后御忆忧怀态怂怃怄怅怆怜总怼恋恒恳恶恸恹恺恻恼悦悫悬悭悯惊惧惨惩惫惬惭"
    "惯愠愤愦愿慑慭懑懒戏戗战戬户扑执扩扫扬扰抚抛护报担拟拢拣拥拦拧拨择挂挚挛挝挞挟"
    "挠挡挢挣挤挥挦捞损捡换捣据掳掴掷掸掺揽揿搀搁搂搅携摄摅摆摇摈摊撄撑撒撵撷撸擞攒"
    "敌数斋斓斗斩断无旧时旷晋晒晓晔晕暂暖术朴机杀杂权条来杨杰极构枞枢枣枪枫柜柠查栀"
    "标栈栋栌栏树栖样栾桠桡桢档桥桨桩梦梼检棁棂椁椟椠椤椭楼榄榅榇榈榉槛槟横樯樱橥欢"
    "欧欲歼殁殇残殒殓殚殡殴毁毂毕毙毡毵氇气氢氩汇汉汤汹沟没沣沤沥沦沧沪泞泪泶洁洒洼"
    "浃浅浆浇浈浉测浍济浏浑浓浔涂涌涛涝涞涟涠涡涣涤润涧涨涩淀渊渌渍渎渐渑渔渖温湾湿"
    "溃溅滚滞滟滠满滢滤滥滨滩漤潆潇潋潍潜潴澜濑濒灏灭灯灵灾灿炀炉炜炝点炼炽烁烂烃烛"
    "烟烨热焕焖焘煅煳熏爱爷牍牦牵牺犊状犷犸犹狈狝狞独狭狮狯狰狱狲猃猎猪猫猬献獭玑现"
    "珐珑琎琏琐琼瑶璇璎瓒瓯电画畅畴疗疟疠疡疬疭痈痉痒痖痨痪痫瘅瘆瘗瘘瘪瘫瘾癞癣皑皱"
    "监盖盗盘眍眦着睁睐睑瞒矶矾矿砀码砖砗砚砜砺砻础硕硖硗硙确碍碛碜礼祃祎祯祷祸禀禄"
    "离秃秆种积称秽秾税稳穑穷窃窍窎窜窝窥窦窭竞笔笃笋笕笺筚筛筜筝筹签简箓箦箧箨箩箪"
    "箫篑篓篮篯簖籁籴类籼粜粝粤粪粮糁糇糍系紧絷纠纡红纣纤约级纨纪纫纬纭纯纰纱纲纳纵"
    "纶纷纸纹纺纽纾线绀绁绂练组绅细织终绉绊绋绌绍绎经绑绒结绔绕绖绗绘给绚绛络绝绞统"
    "绠绡绢绣绥继绨绩绪绫续绮绯绰绱绲绳维绵绶绷绸绹绺绻综绽绿缀缁缂缃缄缅缆缇缈缉缊"
    "缋缌缍缎缏缐缑缓缔缕编缘缙缚缛缜缝缟缠缡缢缣缤缥缦缧缩缪缫缬缭缮缯缰缱缲缳缴缵"
    "罂网罗罚罢羁羟翘耢耧耸聂聋职联聩聪肃肠肤肮肴肾肿胀胁胆胜胧胨胪胫胶脉脍脏脑脓脚"
    "脱脸腊腌腘腭腻腼腽腾膑臜舆舣舰舱舻艰艳艺节芈芗芜芦苁苇苈苋苌苍苎苏茎茧茑茔茕茧"
    "荆荐荙荚荛荜荞荟荠荡荣荤荥荦荧荨药莅莱莲莳获莸莹莺莼萝萤营萦萧萨葱蒇蒉蒋蒌蓝蓟"
    "蓠蓣蓥蓦蔷蔹蔺蕲蕴薮藓虏虑虚虫虽虾蚀蚁蚂蚕蚝蚬蛊蛎蛏蛮蛰蜕蝇蝈蝉蝼蝾衅补表衬衮"
    "袄袅袜袭袯装裆裢裤褛褴见观规觅视觇览觉觊觋觌觍觎觏觐觑觞触觯訚誉誊讠计订认讥讦"
    "讧讨让讪讫训议讯记讲讳讴讵讶讷许讹论讼讽设访诀证诂诃评诅识诈诉诊诋词诎诏译诒试"
    "诗诘诙诚诛话诞诟诠诡询诣诤该详诧诨诩诫诬语误诰诱诲说诵请诸诺读诽课诿谀谁调谄谅"
    "谆谈谊谋谌谍谎谏谐谑谒谓谔谕谖谗谘谙谚谛谜谝谞谟谢谣谤谥谦谧谨谩谪谫谬谭谱谲谳"
    "谴谶贝贞负贡财责贤败账货质贩贪贫贬购贯贰贱贴贵贷贸费贺贻贼贽赀赁赂赃资赅赆赇赈"
    "赉赊赋赌赍赎赏赐赑赒赓赔赕赖赘赙赚赛赜赝赞赟赠赡赢赣赵赶趋趱趋跄跃跞践跶跷跸跹"
    "踊踌踪踬踯蹑蹒蹰蹿躏躜躯车轧轨轩转轮软轰轱轲轳轴轵轶轻载轾轿辀辁辂较辅辆辇辈辉"
    "辊辋辍辎辏辐辑输辔辕辖辗辘辙辚辞边辽达迁过迈运还这进远违连迟迩迳迹适选逊递逦逻"
    "遗邓邝邬邮邻郁郄郏郐郑郓郦郧酝酱酽酾释里鉴钅钆钇针钉钊钋钌钍钎钏钐钒钓钔钕钗钙"
    "钛钜钝钞钟钠钢钣钥钦钧钨钩钪钫钬钭钮钯钰钱钲钳钴钵钶钷钸钹钻钼钽钾钿铀铁铃铄铅"
    "铆铈铉铊铋铌铍铎铐铑铒铓铕铖铗铙铛铜铝铞铟铠铡铢铣铤铥铧铨铩铪铫铬铭铮铯铰铱铲"
    "铳铴铵银铷铸铺链铿销锁锂锅锆锇锈锉锊锋锌锎锏锐锑锒锓锔锕锖锗错锚锛锜锝锞锟锡锢"
    "锣锤锥锦锨锩锪锫锬锭键锯锰锱锲锳锴锵锶锷锸锹锺锻锼锽镀镁镂镃镄镅镆镇镉镊镋镌镍"
    "镎镏镐镑镒镓镔镕镖镗镘镚镛镜镝镞镟镠镡镢镣镤镥镦镧镨镩镪镫镬镭镮镯镰镱镲镳门闩"
    "闪闭问闯闰闱闲间闵闶闷闸闹闺闻闼闽闾闿阀阁阂阃阅阆阈阉阊阋阌阍阎阏阐阑阒阓阔阕"
    "阖阗阘阙队阳阴阵阶际陆陇陈陉陕陧陨险随隐隶难雏雠雳雾霁霡靓静面鞑鞒鞯韦韧韩韪韫"
    "韬页顶顷顸项顺须顼顽顾顿颀颁颂颃预颅领颇颈颉颊颋颌颍颎颏颐频颓颔颖颗题颜额颞颟"
    "颠颡颢颣颤风飏飐飑飒飓飔飕飖飗飘飙飞饣饮饯饰饱饲饴饵饶饷饺饼饽饿馀馁馂馃馄馆馇"
    "馈馉馊馋馌馍馏馐馑馒馓馔马驭驮驯驰驱驳驴驶驷驸驹驻驼驽驾驿骀骁骂骄骅骆骇骈骉骊"
    "骋验骏骑骗骚骛骜骝骞骟骠骡骤骥骧髅髋鬓魇鱼鲁鲂鲅鲆鲇鲈鲍鲎鲐鲑鲒鲔鲕鲚鲛鲜鲞鲟"
    "鲠鲡鲢鲣鲤鲥鲦鲧鲨鲩鲪鲫鲭鲮鲰鲱鲲鲳鲴鲵鲶鲷鲸鲺鲻鲼鲽鳃鳄鳅鳆鳇鳊鳋鳌鳍鳎鳏鳐"
    "鳓鳔鳕鳖鳗鳘鳙鳜鳝鳞鳟鳢鸟鸡鸣鸥鸦鸭鸯鸲鸳鸵鸶鸷鸸鸹鸺鸽鸾鸿鹀鹂鹃鹅鹆鹇鹈鹉鹊"
    "鹋鹌鹏鹑鹕鹖鹗鹘鹚鹛鹜鹞鹣鹤鹦鹧鹨鹩鹪鹫鹬鹭鹰鹳鹾麦麸黄黉黡黩黪鼋鼍鼹齐齑齿龄"
    "]"
)


def needs_traditional_normalization(text: str, mode: Mode) -> bool:
    if not text:
        return False
    if mode.translate_to_english:
        return False
    return bool(_SIMPLIFIED_CHAR_PATTERN.search(text))


def normalize_traditional_text(text: str, mode: Mode) -> str:
    if not text or mode.translate_to_english:
        return text
    if not needs_traditional_normalization(text, mode):
        return text
    if not _OPENCC_CONVERTER:
        print("⚠️  偵測到簡體字，但 OpenCC 未安裝，無法自動轉繁體")
        return text
    normalized = _OPENCC_CONVERTER.convert(text).strip()
    if normalized != text:
        print(f"🪵 normalized zh-TW: {normalized}")
    return normalized


def build_llm_correction_provider(api_cfg: dict) -> LLMCorrectionProvider | None:
    llm_cfg = api_cfg.get("llm_correction", {})
    provider_name = llm_cfg.get("provider", "none").lower()
    if provider_name == "none" or not llm_cfg:
        return None
    sub = dict(llm_cfg.get(provider_name, {}))
    
    # 支援從環境變數 CEREBRAS_API_KEY 覆蓋 api_key
    env_key = os.environ.get("CEREBRAS_API_KEY")
    if env_key:
        sub["api_key"] = env_key

    if not sub.get("api_key"):
        raise RuntimeError(f"❌ llm_correction.{provider_name} 缺少 api_key")
    
    providers = {
        "cerebras": CerebrasProvider,
    }
    if provider_name not in providers:
        print(f"⚠️ 找不到 llm_correction provider: {provider_name}，已停用修正。")
        return None
        
    return providers[provider_name](sub)


# ---------------------------------------------------------------------------
# Session Logger（SQLite）
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SessionLogger:
    """每次辨識完成後記錄一筆到 SQLite，方便後續 bug 追蹤與改善分析。"""

    DB_PATH = Path.home() / ".whisper_voice_log.db"

    _CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS sessions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp    TEXT    NOT NULL,
        mode_id      TEXT,
        mode_name    TEXT,
        provider     TEXT,
        audio_sec    REAL,
        raw_stt      TEXT,
        regex_out    TEXT,
        llm_out      TEXT,
        final_text   TEXT,
        stt_ms       INTEGER,
        llm_ms       INTEGER,
        paste_method TEXT,
        paste_ok     INTEGER,
        error_type   TEXT,
        error_detail TEXT
    )
    """

    def __init__(self):
        self._conn = sqlite3.connect(str(self.DB_PATH), check_same_thread=False)
        os.chmod(self.DB_PATH, 0o600)
        self._lock = threading.Lock()
        self._conn.execute(self._CREATE_SQL)
        self._conn.commit()
        self._migrate()
        print(f"📊 Session log: {self.DB_PATH}")

    def _migrate(self):
        new_cols = [
            ("llm_finish_reason", "TEXT"),
        ]
        for col, col_type in new_cols:
            try:
                self._conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {col_type}")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # 欄位已存在

    def log(self, **kwargs):
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        sql = (
            f"INSERT INTO sessions ({', '.join(cols)}) "
            f"VALUES ({', '.join(['?'] * len(cols))})"
        )
        try:
            with self._lock:
                self._conn.execute(sql, vals)
                self._conn.commit()
        except Exception as e:
            print(f"⚠️  session log 寫入失敗（{e}）")


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

    def stop(self) -> tuple[str | None, float]:
        self.is_recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._frames:
            return None, 0.0

        audio_data = np.concatenate(self._frames, axis=0)
        duration = len(audio_data) / self.sample_rate
        if duration < 0.5:
            return None, duration

        wav_path = os.path.join(tempfile.gettempdir(), "whisper_voice_mac.wav")
        sf.write(wav_path, audio_data, self.sample_rate, subtype="PCM_16")
        return wav_path, duration

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
# GCD 主執行緒 dispatch（修正 macOS 26+ TSM 執行緒斷言）
# macOS 26 在 HIToolbox 新增 dispatch_assert_queue 斷言：
# TSMGetInputSourceProperty / islGetInputSourceListWithAdditions 只能在主執行緒呼叫。
# pynput.keyboard.Controller 內部用 ctypes 呼叫上述 API，
# 若從背景執行緒觸發會直接 SIGTRAP 崩潰，需用 GCD 排程到主執行緒執行。
# ---------------------------------------------------------------------------

_gcd_lib = None             # ctypes.CDLL | False | None
_gcd_main_queue = 0         # dispatch_queue_t (c_void_p integer)
_gcd_async_f = None
_gcd_work_fn_type = None
_gcd_main_q_anchor = None   # 防止 GC（ctypes symbol 錨定）


def _gcd_init() -> bool:
    global _gcd_lib, _gcd_main_queue, _gcd_async_f, _gcd_work_fn_type, _gcd_main_q_anchor
    if _gcd_lib is not None:
        return bool(_gcd_main_queue)
    try:
        lib = ctypes.CDLL('/usr/lib/system/libdispatch.dylib')
        # dispatch_get_main_queue() 在 macOS 26 是 macro → &_dispatch_main_q
        # 直接取 global symbol 位址
        try:
            get_mq = lib.dispatch_get_main_queue
            get_mq.restype = ctypes.c_void_p
            get_mq.argtypes = []
            main_queue = get_mq()
        except AttributeError:
            anchor = ctypes.c_uint64.in_dll(lib, '_dispatch_main_q')
            _gcd_main_q_anchor = anchor
            main_queue = ctypes.addressof(anchor)
        af = lib.dispatch_async_f
        af.restype = None
        af.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        _gcd_lib = lib
        _gcd_main_queue = main_queue
        _gcd_async_f = af
        _gcd_work_fn_type = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
        return True
    except Exception:
        _gcd_lib = False
        return False


def _run_on_main_thread(fn, timeout: float = 5.0) -> bool:
    """從背景執行緒將 fn 排程到 GCD 主執行緒執行，等待完成後返回。"""
    if not _gcd_init():
        return False
    done = threading.Event()

    def wrapper(_ctx):
        try:
            fn()
        finally:
            done.set()

    cb = _gcd_work_fn_type(wrapper)
    _gcd_async_f(_gcd_main_queue, None, cb)
    done.wait(timeout=timeout)
    return done.is_set()


# ---------------------------------------------------------------------------
# 貼上（macOS：osascript → 對前景視窗發送 Cmd+V，比 pynput 更可靠）
# ---------------------------------------------------------------------------

def get_frontmost_app() -> str:
    """回傳目前前景 App 的 process 名稱，用於精確貼上目標。"""
    try:
        r = subprocess.run(
            ["osascript", "-e",
             "tell application \"System Events\" to get name of first process whose frontmost is true"],
            capture_output=True, text=True, timeout=2,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def paste_text(text: str, target_app: str = "") -> tuple[str, bool]:
    # 1. 寫入剪貼簿
    pyperclip.copy(text)
    time.sleep(0.1)

    # 方案 A（主）：osascript activate 目標 App → keystroke Cmd+V
    # 需要 macOS 輔助使用（Accessibility）權限；error 1002 = 未授權
    if target_app:
        print(f"🪵 paste target app: {target_app}")
        target_app_escaped = target_app.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'tell application "{target_app_escaped}" to activate\n'
            f'delay 0.12\n'
            f'tell application "System Events"\n'
            f'    keystroke "v" using command down\n'
            f'end tell'
        )
        result = subprocess.run(["osascript", "-e", script], capture_output=True)
        if result.returncode == 0:
            print("🪵 paste method: osascript")
            return "osascript", True
        stderr = result.stderr.decode().strip()
        print(f"⚠️  osascript 自動貼上失敗（{stderr}）")
        print("   請確認：系統設定 → 隱私權與安全性 → 輔助使用")
        print("   啟動用的 App 需授權：Terminal / iTerm / PyCharm / VS Code")

    # 方案 B（fallback）：pynput 直送 Cmd+V
    # macOS 26+ 的 TSMGetInputSourceProperty 只能在主執行緒呼叫，
    # 需透過 GCD dispatch_async_f 排程，否則會從 _do_process_recording
    # 背景執行緒觸發 dispatch_assert_queue 斷言，導致 SIGTRAP 崩潰。
    def _pynput_cmd_v():
        from pynput.keyboard import Controller, Key
        kb = Controller()
        kb.press(Key.cmd)
        kb.press("v")
        kb.release("v")
        kb.release(Key.cmd)

    if _run_on_main_thread(_pynput_cmd_v):
        print("🪵 paste method: pynput (main thread)")
        return "pynput", True

    print("⚠️  pynput 貼上失敗，文字已存入剪貼簿，請手動 Cmd+V")
    return "clipboard_only", False


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
    write_pid_file()

    # ── 2. 載入設定 ──
    config = load_config()
    mode_manager = ModeManager(config["modes"], config["default_mode_id"])

    try:
        provider = build_provider(config["api"])
        llm_correction = build_llm_correction_provider(config["api"])
    except (RuntimeError, KeyError) as e:
        print(f"❌ Provider 初始化失敗：{e}")
        sys.exit(1)

    session_logger = SessionLogger()

    # ── 3. 建立 rumps app（不啟動，稍後在主執行緒執行）──
    rumps_app = build_menubar_app(mode_manager)

    # ── 4. HUD ──
    hud = None
    if config["ui"]["hud_enabled"]:
        if _probe_tkinter():
            hud = HUD(mode_manager, config["ui"], on_quit=lambda: (remove_pid_file(), os._exit(0)))
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
    cycle_modifier  = config["hotkey"].get("mode_cycle_modifier", "ctrl").lower()

    # 修飾鍵顯示名（用於 Terminal 提示）
    _mod_display  = f"{record_modifier.upper()}+" if record_modifier else ""
    _key_display  = config["hotkey"]["record_key"].upper()
    hotkey_display = f"{_mod_display}{_key_display}"
    _cycle_mod_display = f"{cycle_modifier.upper()}+" if cycle_modifier else ""
    cycle_hotkey_display = f"{_cycle_mod_display}{config['hotkey']['mode_cycle_key'].upper()}"

    print("=" * 50)
    print("🎤 Whisper 語音轉文字工具已啟動（macOS）")
    print(f"   錄音熱鍵：{hotkey_display}（按一下開始，再按一下停止）")
    print(f"   切換模式：{cycle_hotkey_display} 或點 HUD")
    print(f"   Provider：{provider.name}")
    if llm_correction:
        llm_model = config["api"].get("llm_correction", {}).get(llm_correction.name, {}).get("model", "unknown")
        print(f"   LLM 修正：{llm_correction.name}（{llm_model}）")
    else:
        print("   LLM 修正：停用")
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

    def _cycle_modifier_ok() -> bool:
        """mode_cycle_modifier 目前是否被按住（無設定則直接通過）"""
        return not cycle_modifier or cycle_modifier in _pressed_mods

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

    def _do_process_recording(target_app: str = ""):
        """背景執行緒：停止錄音 → 辨識 → 貼上，不阻塞監聽器"""
        wav_path, audio_sec = recorder.stop()
        if not wav_path:
            set_state("idle")
            print("⚠️  錄音時間太短，已忽略")
            return

        set_state("processing")
        mode = mode_manager.current
        print(f"🔄 辨識中... [{mode.display}]")

        t0 = time.time()
        try:
            raw_text = provider.transcribe(wav_path, mode)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            msg = {401: "API Key 無效", 403: "API Key 權限不足", 429: "請求過於頻繁"}.get(
                status, f"API 錯誤 HTTP {status}"
            )
            print(f"❌ {msg}")
            set_state("error")
            session_logger.log(
                timestamp=_now(), mode_id=mode.id, mode_name=mode.name,
                provider=provider.name, audio_sec=round(audio_sec, 2),
                error_type="http_error", error_detail=f"HTTP {status}: {msg}",
            )
            time.sleep(2)
            set_state("idle")
            return
        except requests.exceptions.Timeout:
            print("❌ 網路逾時")
            set_state("error")
            session_logger.log(
                timestamp=_now(), mode_id=mode.id, mode_name=mode.name,
                provider=provider.name, audio_sec=round(audio_sec, 2),
                error_type="timeout", error_detail="requests.Timeout",
            )
            time.sleep(2)
            set_state("idle")
            return
        except Exception as e:
            print(f"❌ 發生錯誤：{e}")
            set_state("error")
            session_logger.log(
                timestamp=_now(), mode_id=mode.id, mode_name=mode.name,
                provider=provider.name, audio_sec=round(audio_sec, 2),
                error_type="unknown", error_detail=str(e),
            )
            time.sleep(2)
            set_state("idle")
            return

        t_stt = time.time()
        stt_ms = int((t_stt - t0) * 1000)
        print(f"🪵 raw STT: {raw_text}")

        corrected_text = apply_corrections(raw_text, mode.regex_rules)
        if not corrected_text:
            print("⚠️  辨識結果為空")
            set_state("idle")
            return
        print(f"🪵 regex corrected: {corrected_text}")

        t_llm = time.time()
        llm_finish_reason = None
        if llm_correction and mode.llm_prompt:
            llm_corrected_text = llm_correction.correct(corrected_text, mode)
            llm_finish_reason = getattr(llm_correction, "last_finish_reason", None)
            print(f"🪵 LLM corrected: {llm_corrected_text}")
        else:
            llm_corrected_text = corrected_text
            print("🪵 LLM corrected: <skipped>")
        llm_ms = int((time.time() - t_llm) * 1000)

        final_text = normalize_traditional_text(llm_corrected_text, mode)

        print(f"⏱  STT: {stt_ms}ms  |  LLM: {llm_ms}ms  |  total: {int((time.time() - t0) * 1000)}ms")

        paste_method, paste_ok = paste_text(final_text, target_app)
        print(f"✅ 已貼上：{final_text}")
        set_state("idle")

        session_logger.log(
            timestamp=_now(),
            mode_id=mode.id,
            mode_name=mode.name,
            provider=provider.name,
            audio_sec=round(audio_sec, 2),
            raw_stt=raw_text,
            regex_out=corrected_text,
            llm_out=llm_corrected_text if (llm_correction and mode.llm_prompt) else None,
            final_text=final_text,
            stt_ms=stt_ms,
            llm_ms=llm_ms if (llm_correction and mode.llm_prompt) else None,
            paste_method=paste_method,
            paste_ok=int(paste_ok),
            llm_finish_reason=llm_finish_reason,
        )

    def on_press(key):
        nonlocal recording_flag

        # ── 追蹤修飾鍵按下 ──
        for mod_name, mod_keys in _MODIFIER_KEYS.items():
            if key in mod_keys:
                _pressed_mods.add(mod_name)
                return

        # ── F10：循環切換模式 ──
        if key == cycle_key and _cycle_modifier_ok():
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
                # 第二次按：停止並辨識（立刻捕捉前景 App 供方案 A 使用）
                recording_flag = False
                target_app = get_frontmost_app()
                threading.Thread(target=_do_process_recording, args=(target_app,), daemon=True).start()

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
        finally:
            remove_pid_file()
    else:
        # rumps 不可用：直接等待 pynput listener（舊行為）
        try:
            listener.join()
        except KeyboardInterrupt:
            pass
        finally:
            remove_pid_file()


if __name__ == "__main__":
    main()
