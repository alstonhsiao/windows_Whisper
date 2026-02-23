# Windows 語音轉文字工具 (Whisper Voice Typing)

> **按住熱鍵 → 錄音 → OpenAI Whisper API 辨識 → 自動貼上文字到游標位置**

將 macOS 上的語音轉文字功能移植到 Windows 10/11，取代傳統鍵盤輸入。

---

## 目錄

- [專案背景](#專案背景)
- [實作策略](#實作策略)
- [目錄結構](#目錄結構)
- [快速開始](#快速開始)
  - [方案一：Python + uv（推薦首選）](#方案一python--uv推薦首選)
  - [方案二：AutoHotkey v2 + MCI](#方案二autohotkey-v2--mci)
  - [方案三：Python 打包 .exe](#方案三python-打包-exe)
- [使用者操作指南](#使用者操作指南)
- [測試 API Key](#測試-api-key)
- [設定說明](#設定說明)
- [三方案比較](#三方案比較)
- [附錄：技術細節](#附錄技術細節)

---

## 專案背景

### 原始需求（macOS 版）

在 macOS 上透過 Keyboard Maestro 實現的語音轉文字功能：

1. **按住 F1** → 開始錄音（SoX `rec` 指令）
2. 錄音就緒後發出 **beep 提示音**
3. **放開 F1** → 停止錄音
4. 自動送往 **OpenAI Whisper API** 辨識
5. **Regex 修正**專有名詞 → **Trim 空白** → 模擬貼上到游標位置

### 使用情境

- 日常工作快速輸入繁體中文
- 會議記錄、訊息回覆、文件撰寫
- 需正確辨識人名、公司名、技術名詞

### 為什麼要移植到 Windows

macOS 版依賴 Keyboard Maestro（macOS 專屬付費軟體），Windows 上需要獨立的解決方案。

---

## 實作策略

採用三階段策略，由快到穩逐步推進：

| 階段 | 方案 | 目的 | 狀態 |
|------|------|------|------|
| **Phase 1** | 方案一：Python + `uv` 單檔腳本 | 最快驗證整個流程 | 🟢 就緒 |
| **Phase 2** | 方案三：Python + PyInstaller 打包 `.exe` | 給同事零門檻使用 | 🟢 就緒 |
| **Phase 3** | 方案二：AutoHotkey v2 + Windows MCI | 最輕量 fallback | 🟢 就緒 |

### 關鍵技術決策

| 決策 | 選擇 | 原因 |
|------|------|------|
| 錄音 | `sounddevice`（Python）/ MCI（AHK） | 記憶體內操作，避免 SoX 的 WAV header 損壞問題 |
| 熱鍵 | `pynput` | 不需管理員權限（`keyboard` 套件需要） |
| API 呼叫 | `requests` / `curl.exe` | 只呼叫一個 endpoint，比 `openai` SDK 少 15 個子依賴 |
| 提示音 | `winsound.Beep` / `SoundBeep` | Windows 內建，零依賴 |
| 環境管理 | `uv` + PEP 723 | 單檔即完整程式，一行啟動 |

---

## 目錄結構

```
windows_Whisper/
├── .env.local                      ← API Key（不會推送到 GitHub）
├── .gitignore
├── README.md                       ← 本文件
│
├── approach-1-python-uv/           ← 方案一：Python + uv 單檔腳本
│   └── main.py                     ← 單檔（含 PEP 723 依賴宣告）
│
├── approach-2-ahk-mci/             ← 方案二：AutoHotkey v2 + MCI
│   ├── whisper.ahk                 ← AHK v2 主程式
│   └── config.ini                  ← 設定檔
│
└── approach-3-python-exe/          ← 方案三：Python 打包 .exe
    ├── main.py                     ← 主程式
    ├── config.json                 ← 設定檔
    ├── requirements.txt            ← pip 依賴
    └── build.bat                   ← PyInstaller 打包腳本
```

---

## 快速開始

### 前置需求

1. **OpenAI API Key** — 前往 [platform.openai.com/api-keys](https://platform.openai.com/api-keys) 取得
2. **麥克風** — 內建或外接皆可
3. **網路連線** — Whisper API 需要連網
4. **Windows 10 1803+**（方案二三需要內建的 `curl.exe`）

### 設定 API Key

編輯專案根目錄的 `.env.local`：
```
OPENAI_API_KEY=sk-your-actual-key-here
```

---

### 方案一：Python + uv（推薦首選）

> 最快上手、最穩定、單檔即完整程式

**安裝 uv（一次性）：**
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**啟動：**
```bash
cd approach-1-python-uv
uv run main.py
```

`uv` 會自動建虛擬環境、安裝依賴、執行腳本（首次 ~5 秒，後續 <1 秒）。

**操作：**
- 按住 **F1** → 聽到 beep 後開始說話
- 放開 **F1** → 自動辨識並貼上文字
- **Ctrl+Shift+Q** → 結束程式

---

### 方案二：AutoHotkey v2 + MCI

> 最輕量、不需 Python、適合作為 fallback

**安裝 AutoHotkey v2：**
前往 [autohotkey.com](https://www.autohotkey.com/) 下載安裝（~5MB）

**設定：**
編輯 `approach-2-ahk-mci/config.ini`，填入 API Key

**啟動：**
雙擊 `approach-2-ahk-mci/whisper.ahk`

**操作同上**（F1 按住/放開）。右鍵系統匣圖示可結束程式。

---

### 方案三：Python 打包 .exe

> 給同事「雙擊即用」，不需安裝任何東西

**開發者（打包）：**
```bash
cd approach-3-python-exe
pip install -r requirements.txt

# 測試
python main.py

# 打包
build.bat
```

**終端使用者（同事）：**
1. 取得 `WhisperVoiceTyping.exe` + `config.json`
2. 編輯 `config.json` 填入 API Key
3. 雙擊 exe 啟動

---

## 使用者操作指南

> 這一節說明**日常使用流程**，不需要懂程式也能操作。

### 第一次使用前（僅需設定一次）

**步驟 1：取得 OpenAI API Key**
1. 前往 [platform.openai.com/api-keys](https://platform.openai.com/api-keys) 登入
2. 點選「Create new secret key」
3. 複製完整的 Key（格式：`sk-...`，只顯示一次）

**步驟 2：填入 API Key**

開啟專案根目錄的 `.env.local`，將 `your_openai_api_key_here` 換成你的 Key：
```
OPENAI_API_KEY=sk-你的Key貼在這裡
```

**步驟 3：測試 API Key 是否正常**

```bash
# Windows（安裝 uv 後）
uv run test_api_key.py

# 或直接用 Python
python test_api_key.py
```

看到 `🎉 測試通過！` 就代表設定完成。

---

### 日常使用流程

```
開啟程式（uv run approach-1-python-uv/main.py）
         ↓
系統匣顯示圖示 → 程式在背景待機
         ↓
    想要輸入文字時
         ↓
  按住 F1 不要放開  ← ── ── ── ──┐
         ↓                      │
   聽到「嗶」一聲                 │
         ↓                      │
     開始說話  ✦                 │
         ↓                      │
     說完放開 F1                  │
         ↓                      │
  等待約 1-3 秒（API 辨識中）      │
         ↓                      │
  文字自動貼到游標位置              │
         ↓                      │
   繼續做其他事 ── ── ── ── ── ──┘
```

### 操作快速參考

| 動作 | 說明 |
|------|------|
| **按住 F1** | 開始錄音 |
| **聽到 beep** | 可以開始說話了 |
| **放開 F1** | 停止錄音，自動辨識並貼上 |
| **Ctrl+Shift+Q** | 結束程式 |

### 熱鍵說明

- **按住** F1 才會開始錄音（不是點一下）
- 聽到 **beep 聲才開始說話**（beep 前說的話可能被略過）
- 盡量說完整句子再放開，不要在句子中間放開
- 錄音時間太短（< 0.5 秒）會自動忽略，不會呼叫 API

### 費用參考

- Whisper API：**$0.006 美元 / 分鐘**（≈ NT$0.2 / 分鐘）
- 每次說 10-20 秒 ≈ $0.001 美元（不到台幣 0.04 元）
- 一般日常使用每月不超過 $1 美元

### 常見問題

**Q：放開 F1 後等很久沒有貼上？**
- 檢查網路連線，API 通常 1-3 秒內回應
- 如果超過 30 秒會自動逾時並顯示錯誤

**Q：貼上的是空白或什麼都沒有？**
- 可能錄音時間太短，請至少說 1 秒以上
- 可能麥克風沒有收到聲音，確認麥克風已啟用

**Q：貼上的文字有錯字（專有名詞）？**
- 在設定檔的 `prompt` 中加入該專有名詞，例如：`包含：你的名字, 公司名稱`
- 或在 `regex_rules` 中加入自動修正規則

**Q：F1 跟其他程式衝突？**
- 在設定檔中將熱鍵改為 F8、F9 等較少使用的按鍵

---

## 測試 API Key

使用專案根目錄的 `test_api_key.py` 驗證 API Key 是否有效（**完全免費**，呼叫的是列出模型的端點，不消耗任何 token）：

```bash
# 安裝 uv 後（推薦）
uv run test_api_key.py

# 或使用已安裝 requests 的 Python
python test_api_key.py
```

**成功輸出範例：**
```
✅ 已讀取 .env.local
✅ API Key 格式正確（前綴：sk-...）
✅ API Key 有效！帳號可存取 113 個模型
✅ Whisper 模型可用 — 語音辨識功能就緒
🎉 測試通過！
```

| 錯誤訊息 | 解決方式 |
|---------|----------|
| `找不到 OPENAI_API_KEY` | 確認 `.env.local` 存在且格式正確 |
| `HTTP 401 Unauthorized` | Key 無效或已撤銷，請重新產生 |
| `HTTP 429` | 請求過於頻繁，稍後再試 |
| `無法連線` | 檢查網路連線 |

---

## 設定說明

### API Key 優先順序

1. 環境變數 `OPENAI_API_KEY`（最優先）
2. `.env.local` 檔案
3. `config.json` / `config.ini` 中的設定

### Whisper API 參數

| 參數 | 值 | 說明 |
|------|-----|------|
| `model` | `whisper-1` | OpenAI Whisper 模型 |
| `language` | `zh` | ISO-639-1 語言碼，強制中文辨識 |
| `temperature` | `0.0` | 0 = 最精確（不引入隨機性） |
| `prompt` | 見下方 | 詞彙引導，最多 224 tokens |

### Prompt（詞彙引導）

預設：
```
請使用繁體中文。包含：蕭淳云, 周芷萓, 合作廠商加模, 專案 Tahoe, n8n, Zeabur。
```

- `請使用繁體中文` — 強制輸出繁體
- `包含：...` — 專有名詞參考，提升辨識準確度
- 可在設定檔中自訂

### Regex 後處理規則

| 搜尋模式 | 替換為 | 說明 |
|---------|--------|------|
| `N8n\|N 8 n` | `n8n` | Whisper 常誤辨識的名詞修正 |

規則可在設定檔中擴充。

### 錄音規格

| 參數 | 值 | 說明 |
|------|-----|------|
| 取樣率 | 16000 Hz | Whisper 最佳規格 |
| 聲道 | 1（Mono） | 語音辨識不需立體聲 |
| 位元深度 | 16-bit PCM | 標準品質 |
| 格式 | WAV | 無損，~32KB/秒 |

### 熱鍵

預設 **F1**，可在設定檔中改為 F2-F12。

> **注意：** F1 在很多應用程式是「說明」鍵，如有衝突可改用 F8 等。

---

## 三方案比較

| | 方案一：Python+uv | 方案二：AHK+MCI | 方案三：Python .exe |
|---|---|---|---|
| **安裝門檻** | 需裝 uv | 需裝 AHK v2 | 雙擊 exe 即用 |
| **檔案大小** | ~1KB（單檔 .py） | ~10KB（.ahk + .ini） | ~30-50MB（.exe） |
| **錄音穩定度** | ⭐⭐⭐⭐⭐ sounddevice 記憶體操作 | ⭐⭐⭐⭐ MCI save 完整寫入 | ⭐⭐⭐⭐⭐ 同方案一 |
| **管理員權限** | 不需要（pynput） | 視目標視窗而定 | 不需要（pynput） |
| **常駐 RAM** | ~30MB | ~3-5MB | ~30MB |
| **可維護性** | Python（開發者多） | AHK（較小眾） | Python |
| **開發時間** | 2-3 小時 | 3-5 小時 | 3-4 小時 |
| **適合場景** | 自己用、快速驗證 | 輕量 fallback | 分發給同事 |

---

## 附錄：技術細節

### A. 錄音機制比較

**為什麼不用 SoX：**
- Windows 上 SoX 停止錄音需 `taskkill`（強制終止），可能導致 WAV header 損壞
- macOS 上 SoX `rec` 收到 SIGINT 會正確收尾，但 Windows 沒有等效機制

**sounddevice（方案一三）：**
- PortAudio callback 在背景線程收集音訊到記憶體 buffer
- `stop()` 時才用 `soundfile.write()` 寫入完整 WAV
- 從根本上避免 WAV 損壞問題

**MCI（方案二）：**
- Windows 內建 `winmm.dll` 的 Media Control Interface
- `save` 指令會寫入完整 WAV header
- 不需外部程式

### B. 熱鍵偵測

**pynput vs keyboard（Python 套件）：**
- `keyboard` 需要管理員權限 → 每次執行要右鍵「以管理員身份執行」
- `pynput` 不需管理員 → 直接雙擊執行
- 兩者功能相近，選 `pynput`

**AHK v2 熱鍵系統：**
- KeyDown / KeyUp 偵測是 AHK 的核心功能
- `#MaxThreadsPerHotkey 1` 防止重複觸發
- 最原生可靠的熱鍵方案

### C. Beep 提示音機制

錄音啟動有延遲（0.1-0.5 秒），需等待就緒後才通知使用者：

```
錄音開始 → 等待 buffer > 4000 samples（~0.25 秒）
→ 播放 beep（1000Hz, 200ms）
→ 使用者聽到 beep 後開始說話
```

避免使用者在錄音尚未就緒時開口，導致前幾個字被截斷。

### D. Whisper API 呼叫

```
POST https://api.openai.com/v1/audio/transcriptions
Content-Type: multipart/form-data

file: @voice.wav
model: whisper-1
language: zh
temperature: 0.0
prompt: 請使用繁體中文。...
```

費用：$0.006 USD / 分鐘（極低成本）

### E. 貼上文字流程

1. 將辨識結果寫入系統剪貼簿
2. 模擬 `Ctrl+V` 貼上到當前焦點視窗的游標位置
3. 等效於 macOS Keyboard Maestro 的 `InsertText ByPasting`

### F. 錯誤處理

| 狀況 | 處理方式 |
|------|---------|
| API Key 未設定 | 啟動時提示設定 |
| 錄音 < 0.5 秒 | 忽略並提示「錄音時間過短」 |
| API 401 | 提示「API Key 無效」 |
| API 429 | 提示「請求過於頻繁」 |
| 網路逾時 (>30s) | 提示「網路逾時」 |
| WAV > 25MB | Whisper API 限制，約 13 分鐘錄音上限 |

### G. 手動測試 API（驗證 Key 可用）

```batch
curl.exe -s -f ^
  -H "Authorization: Bearer sk-your-key-here" ^
  -H "Content-Type: multipart/form-data" ^
  -F file="@test.wav" ^
  -F model="whisper-1" ^
  -F language="zh" ^
  -F temperature="0.0" ^
  -F prompt="請使用繁體中文。" ^
  "https://api.openai.com/v1/audio/transcriptions"
```

### H. 未來可擴充功能

- **多語言切換** — 快捷鍵切換 zh/en/ja
- **歷史記錄** — SQLite 儲存過去的辨識結果
- **自訂修正詞庫** — GUI 編輯 Regex 規則
- **語音指令** — 「換行」→ `\n`，「句號」→ `。`
- **離線模式** — 使用本地 whisper.cpp（需下載 ~3GB 模型）

---

## 系統需求

- Windows 10 1803+（內建 curl.exe）
- 麥克風（需在 設定 → 隱私 → 麥克風 中允許存取）
- 網路連線
- OpenAI 帳號 + API Key

---

## 授權

本專案供學習與個人使用。OpenAI Whisper API 使用需遵守 [OpenAI 服務條款](https://openai.com/terms)。
