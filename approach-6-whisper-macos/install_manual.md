# 安裝說明 — Whisper Voice Typing（macOS）

> **approach-6-whisper-macos**
> 使用 xAI Grok STT / OpenAI Whisper，搭配浮動 HUD 與四種辨識模式

---

## 目錄

1. [系統需求](#1-系統需求)
2. [取得 API Key](#2-取得-api-key)
3. [安裝步驟](#3-安裝步驟)
4. [設定 API Key](#4-設定-api-key)
5. [首次啟動與權限設定](#5-首次啟動與權限設定)
6. [日常使用](#6-日常使用)
7. [模式切換說明](#7-模式切換說明)
8. [自訂設定](#8-自訂設定)
9. [常見問題](#9-常見問題)
10. [解除安裝](#10-解除安裝)

---

## 1. 系統需求

| 項目 | 需求 |
|---|---|
| 作業系統 | macOS 12 Monterey 以上（macOS 26 Tahoe：HUD 停用，功能正常） |
| Python | 3.9 以上（推薦 3.11+） |
| 網路 | 需要連線（API 呼叫） |
| 麥克風 | 內建或外接皆可 |
| 磁碟空間 | 約 200MB（虛擬環境 + 套件） |

**確認 Python 版本：**
```bash
python3 --version
# 應顯示 Python 3.9.x 以上
```

若沒有 Python 3，前往 [python.org/downloads](https://www.python.org/downloads/) 下載安裝。

---

## 2. 取得 API Key

至少需要以下其中一個：

### 選項 A：xAI Grok STT（推薦）
- 速度最快（平均 ~1.0 秒）
- 前往：[console.x.ai](https://console.x.ai/)
- 登入 → 左側 **API Keys** → **Create API Key**
- 複製格式為 `xai-xxxxxxxxxx` 的 Key

### 選項 B：OpenAI Whisper（備用）
- 前往：[platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- 登入 → **Create new secret key**
- 複製格式為 `sk-xxxxxxxxxx` 的 Key（只顯示一次）

### 選項 C：Groq（免費額度最多）
- 前往：[console.groq.com](https://console.groq.com/)
- 登入 → **API Keys** → **Create API Key**
- 複製格式為 `gsk_xxxxxxxxxx` 的 Key

---

## 3. 安裝步驟

### 方法 A：自動安裝（推薦）

```bash
# 1. 進入方案六目錄
cd /path/to/windows_Whisper/approach-6-whisper-macos

# 2. 執行安裝腳本
bash install.sh
```

腳本會自動完成：建立虛擬環境 → 安裝套件 → 設定 API Key → 建立啟動捷徑。

---

### 方法 B：手動安裝

**步驟 1：進入目錄**
```bash
cd /path/to/windows_Whisper/approach-6-whisper-macos
```

**步驟 2：建立虛擬環境**
```bash
python3 -m venv .venv
```

虛擬環境是一個獨立的 Python 環境，確保套件不與其他專案衝突。

**步驟 3：安裝套件**
```bash
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

安裝的套件（約 30 秒）：

| 套件 | 用途 |
|---|---|
| `sounddevice` | 麥克風錄音 |
| `soundfile` | 儲存 WAV 檔 |
| `numpy` | 音訊資料處理 |
| `requests` | 呼叫 STT API |
| `pynput` | 全局熱鍵偵測 |
| `pyperclip` | 寫入剪貼簿 |
| `rumps` | macOS 選單列圖示（可選） |

**步驟 4：設定 API Key**（見下一節）

**步驟 5：啟動程式**
```bash
.venv/bin/python main.py
```

---

## 4. 設定 API Key

API Key 存放在專案**根目錄**（`windows_Whisper/`）的 `env.local` 檔案中。

> ⚠️ `env.local` 不會上傳 GitHub（已加入 .gitignore），安全存放。

### 編輯 env.local

```bash
# 用文字編輯器開啟
open -e /path/to/windows_Whisper/env.local
```

加入你的 Key（擇一或多個）：
```
XAI_API_KEY=xai-你的Key貼在這裡
OPENAI_API_KEY=sk-你的Key貼在這裡
GROQ_API_KEY=gsk_你的Key貼在這裡
```

### 切換使用的 Provider

編輯 `config.json`，修改 `api.provider`：
```json
"api": {
  "provider": "grok"    ← 改成 grok / openai / groq
}
```

| provider 值 | 對應 Key | 速度 |
|---|---|---|
| `grok` | `XAI_API_KEY` | ~1.0s ⚡ |
| `openai` | `OPENAI_API_KEY` | ~1.4s |
| `groq` | `GROQ_API_KEY` | ~0.5s ⚡⚡ |

---

## 5. 首次啟動與權限設定

### 啟動程式

```bash
cd /path/to/windows_Whisper/approach-6-whisper-macos
.venv/bin/python main.py
```

或雙擊 Finder 中的 **「啟動語音輸入.command」**（需先執行 `install.sh` 建立）。

### macOS 權限授權（首次必做）

程式啟動後，macOS 會依序跳出授權視窗：

#### 授權 1：麥克風
```
"Terminal" 想要存取麥克風
[ 不允許 ]  [ 允許 ]
```
→ 點 **「允許」**

位置：系統設定 → 隱私權與安全性 → **麥克風**

#### 授權 2：輔助使用（Accessibility）
```
"Terminal" 想要控制這部電腦
[ 拒絕 ]  [ 好的 ]
```
→ 點 **「好的」**，在設定中打勾 Terminal

位置：系統設定 → 隱私權與安全性 → **輔助使用**

#### 授權 3：輸入監控（Input Monitoring）
```
"Terminal" 想要監控鍵盤輸入
[ 拒絕 ]  [ 好的 ]
```
→ 點 **「好的」**，在設定中打勾 Terminal

位置：系統設定 → 隱私權與安全性 → **輸入監控**

> **⚠️ 重要：授權完成後，請關掉程式重新執行一次才會生效。**

### 確認啟動成功

Terminal 應顯示：
```
==================================================
🎤 Whisper 語音轉文字工具已啟動（macOS）
   錄音熱鍵：CTRL+F1（按一下開始，再按一下停止）
   切換模式：F10 或點 HUD
   Provider：grok
   目前模式：📝 直接轉錄
   結束：HUD 右鍵 或 Ctrl+C
==================================================
```

同時螢幕**右下角**出現浮動 HUD：
```
┌─────────────────────┐
│  📝 直接轉錄   ⏸   │
└─────────────────────┘
```

---

## 6. 日常使用

### 操作流程

```
1. 啟動程式（雙擊「啟動語音輸入.command」）
2. 切換到你想輸入文字的 App（如 Notion、Slack、文件編輯器）
3. 把游標點到你要輸入的地方
4. 按下 Ctrl + F1 → 聽到 beep 聲後開始說話
5. 說完後再按 Ctrl + F1 → 等 1 秒 → 文字自動貼上
```

### 熱鍵快速參考

| 按鍵 | 動作 |
|---|---|
| **Ctrl + F1** | 第一次按：開始錄音 |
| **Ctrl + F1** | 第二次按：停止錄音並辨識貼上 |
| **F10** | 循環切換辨識模式 |
| **點 HUD 文字** | 展開模式選單直接選擇 |
| **HUD 右鍵** | 結束程式 |

### HUD 狀態說明

| HUD 顯示 | 含義 |
|---|---|
| `📝 直接轉錄  ⏸` | 待機中，可以按熱鍵開始 |
| `📝 直接轉錄  🔴` | 錄音中，說話中... |
| `📝 直接轉錄  🔄` | 辨識中，等待 API 回應 |
| `📝 直接轉錄  ⚠️` | 發生錯誤，2 秒後自動恢復 |

---

## 7. 模式切換說明

按 **F10** 或**點 HUD** 可切換以下四種模式：

### 📝 直接轉錄（預設）
- 說繁體中文 → 輸出繁體中文
- 包含個人常用術語（n8n、Zeabur 等）
- 適合：日常工作、訊息回覆、文件撰寫

### 🌐 中翻英
- 說中文 → 輸出英文
- 適合：寫英文 email、回覆外國同事

### 💼 專業模式
- 技術術語保留英文（API、Docker、PostgreSQL 等）
- 適合：寫技術文件、程式碼註解

### 💬 一般對話
- 口語化輸出，適合對話場景
- 適合：聊天訊息、非正式文字

### 自訂模式

在 `config.json` 的 `modes` 陣列中新增：
```json
{
  "id": "my_mode",
  "name": "我的模式",
  "icon": "🎯",
  "language": "zh",
  "translate_to_english": false,
  "prompt": "請使用繁體中文。[你的自訂 prompt]",
  "regex_rules": []
}
```

---

## 8. 自訂設定

所有設定都在 `approach-6-whisper-macos/config.json`：

### 修改熱鍵

```json
"hotkey": {
  "record_key": "F1",
  "record_modifier": "ctrl",
  "mode_cycle_key": "F10"
}
```

| 欄位 | 說明 | 可選值 |
|---|---|---|
| `record_key` | 錄音觸發鍵 | `F1`～`F12` |
| `record_modifier` | 搭配的修飾鍵 | `ctrl` / `shift` / `alt` / `""` |
| `mode_cycle_key` | 模式切換鍵 | `F1`～`F12` |

### 加入個人術語（直接轉錄模式）

在 `modes[0].prompt` 加入你的名字、公司名、專有名詞：
```json
"prompt": "請使用繁體中文。包含：你的名字, 公司名稱, 專案代號。"
```

### 加入自動修正規則

在 `modes[0].regex_rules` 加入：
```json
{ "pattern": "Whisper一", "replacement": "Whisper-1", "flags": "IGNORECASE" }
```

### 調整 HUD 位置

```json
"ui": {
  "hud_position": "bottom-right",  // top-left / top-right / bottom-left / bottom-right
  "hud_offset_x": 20,
  "hud_offset_y": 20,
  "hud_opacity": 0.9,
  "hud_font_size": 14
}
```

---

## 9. 常見問題

### 按了熱鍵沒有反應
1. 確認 Terminal 的**輸入監控**權限已開啟並打勾
2. 授權後重新啟動程式

### 有錄音但沒有貼上文字
1. 確認 Terminal 的**輔助使用**權限已開啟並打勾
2. 確認目標 App 有游標焦點（先點一下輸入框）
3. 授權後重新啟動程式

### 辨識結果是空白
- 可能錄音太短（< 0.5 秒），請說久一點再放開
- 確認麥克風有收音（系統偏好設定 → 聲音 → 輸入）

### 出現 `❌ API Key 無效`
- 確認 `env.local` 中的 Key 格式正確，沒有多餘空格
- xAI Key 格式：`xai-` 開頭
- OpenAI Key 格式：`sk-` 開頭

### 出現 `❌ 網路逾時`
- 確認網路連線正常
- API 伺服器偶爾會短暫延遲，等 2 秒後自動重試即可

### Grok 辨識結果是簡體字
- Grok STT 目前對繁體中文的支援有限，可切換成 OpenAI provider
- 編輯 `config.json`：`"provider": "openai"`

### 程式啟動後沒有 HUD
- 確認 `config.json` 中 `"hud_enabled": true`
- 確認 Python 版本 ≥ 3.9（tkinter 內建）

### 程式啟動後立刻閃退（macOS 26 Tahoe）

**症狀**：程式啟動後立刻崩潰，崩潰報告顯示 `[NSApplication macOSVersion]: unrecognized selector`

**原因**：Tcl/Tk 9.0（tkinter 的底層）在 macOS 26 呼叫了已移除的 macOS API。

**解法**：確認 `config.json` 中 `"hud_enabled": false`（此版本 HUD 已停用）

---

## 10. 解除安裝

```bash
# 刪除虛擬環境（最大的部分）
rm -rf /path/to/windows_Whisper/approach-6-whisper-macos/.venv

# 刪除暫存錄音檔（系統 tmp，通常重開機會自動清除）
rm -f /tmp/whisper_voice_mac.wav

# 刪除啟動捷徑（如果建立了）
rm -f /path/to/windows_Whisper/approach-6-whisper-macos/啟動語音輸入.command

# 移除 macOS 授權（可選）
# 系統設定 → 隱私權與安全性 → 輔助使用 / 輸入監控
# 找到 Terminal 並取消勾選
```

API Key 存在 `env.local`，如需刪除：
```bash
rm /path/to/windows_Whisper/env.local
```

---

## 附錄：費用參考

| Provider | 費用 | 每次說話（10秒）約花費 |
|---|---|---|
| xAI Grok STT | $0.10 USD / 小時 | ~$0.0003 |
| OpenAI Whisper | $0.006 USD / 分鐘 | ~$0.001 |
| Groq Whisper | $0.04 USD / 小時 | ~$0.0001 |

一般日常使用每月花費約 **NT$1~5 元**，幾乎可以忽略不計。
