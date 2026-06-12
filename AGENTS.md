# AGENTS

> Governance Hub for this project. Read this file first in every new session.

## Mission
語音轉文字工具（Grok STT / Whisper / Groq，多平台）。
macOS 主力方案：approach-6（rumps 選單列、四模式切換、multi-provider；macOS 26 相容）。
Windows 封存方案：approach-3（Python + PyInstaller .exe，暫時封存，有空再維護）。
架構：**Grok STT（第一層）→ Cerebras LLM（第二層修正）**，解決繁簡混用、字間空格、術語辨識問題。

## Always-On Rules
- Keep this file concise: governance only; move details to spoke modules.
- Treat secrets and production credentials as strictly local and non-committable.
- Prioritize high-risk constraints and validation steps before implementation.
- If requirement is unclear and risk is non-trivial, mark as `NEED_REVIEW` instead of guessing.

## Default Execution Flow
1. Read `AGENTS.md` (this file).
2. Open only the relevant spoke modules from the quick map.
3. For large directories, read their `INDEX.md` first, then drill down minimally.
4. After work, update `agent-progress.md` and keep governance docs aligned.

## Quick Map
| Spoke | Path | When to Read |
|---|---|---|
| Context | `agent-context.md` | Project purpose, stack, boundaries, key paths. |
| Operations | `agent-operations.md` | High-impact rules, execution order, validation baseline. |
| Progress | `agent-progress.md` | Recent work, TODOs, unresolved items. |
| Refactor Report | `agent-refactor-report.md` | Phase 1+2 governance refactor record and metrics. |

## Repo 結構（精簡後）

```
windows_Whisper/
├── approach-6-whisper-macos/   ← ✅ 唯一現役方案（macOS）
│   ├── main.py                 ← 主程式（1,400 行）
│   ├── config.json             ← 設定（api / modes / hotkey / ui）
│   ├── requirements.txt        ← Python 依賴（待鎖版）
│   ├── install.sh              ← 自動安裝腳本
│   ├── install_manual.md       ← 手動安裝說明
│   ├── 啟動語音輸入.command      ← 雙擊啟動
│   └── 重啟語音輸入.command      ← 殺舊程序後重啟
├── approach-3-python-exe/      ← 🗄️ 封存（Windows，有空再維護）
│   ├── main.py
│   ├── config.json
│   ├── requirements.txt
│   └── build.bat
├── test_api_key.py             ← 手動測試 OpenAI/Grok/Groq 連線
├── test_cerebras.py            ← 手動測試 Cerebras 連線
└── env.local                  ← 機密設定（git-ignored，chmod 600）
```

> approach-1（Python+uv）、approach-2（AHK+MCI）、approach-4（Gemini Windows）、approach-5（Gemini macOS）已於 2026-06-12 刪除。
> - approach-1/2/4/5 刪除原因：approach-2 有 Critical 命令注入風險；approach-4/5 依賴已退役的 gemini-1.5-flash（API 回 404）；approach-1 功能被 approach-3 取代。

## 待處理的已知問題（安全審查產出，2026-06-12）

優先度 P0（立即）：
- [x] `~/.whisper_voice_log.db` 權限收斂為 600；main.py SessionLogger `__init__` 加 `os.chmod(DB_PATH, 0o600)`（2026-06-12）
- [x] 刪除重複的根目錄 `.env.local`（`env.local` 為主）（2026-06-12）

優先度 P1（短期，approach-6）：
- [ ] WAV 暫存改 `tempfile.NamedTemporaryFile` 隨機檔名，用後刪除（main.py:761）
- [ ] PID/lock 檔移出 `/tmp` → `~/Library/Application Support/WhisperVoice/`
- [ ] recorder race condition：辨識進行中以 busy flag 擋住新錄音（main.py:1345）
- [ ] `requirements.txt` 鎖版（全改 `==` + `uv pip compile` 產 lock 檔）
- [ ] install.sh：`read -rs` 靜默讀 key；建檔即 `chmod 600 "$ENV_FILE"`
- [ ] .command 硬編碼絕對路徑 `/Users/alston/…` → 改 `$(cd "$(dirname "$0")" && pwd)`
- [ ] 重啟語音輸入.command：kill 前比對 `ps -p $PID -o command=` 含 `main.py`，防誤殺

優先度 P2（中期）：
- [ ] approach-3 封存：修 build.bat 移除 `--add-data config.json`（金鑰打包風險）；requirements.txt 鎖版
- [ ] approach-6 main.py 拆模組（audio / providers / hud / paste / config / app）
- [ ] `print()` 全改 `logging` 模組（含 level + 檔案 handler）
- [ ] config schema 驗證（缺欄位時給友善錯誤，而非 KeyError）
- [ ] test_api_key.py / test_cerebras.py：API key 印出改為只印固定前綴 + 長度，不印任何秘密字元
- [ ] install_manual.md 補 `opencc-python-reimplemented` 套件；同步 GROQ key 的 prompt_key

## Known Gotchas（踩過的坑）

### macOS 自動貼上失效：Accessibility ≠ Input Monitoring
- **症狀**：辨識成功、文字在剪貼簿，但不會自動貼到游標位置；osascript 印出 `error 1002`
- **根因**：macOS 有兩個獨立權限——Input Monitoring（偵測按鍵）和 Accessibility（模擬按鍵送 Cmd+V）。兩者都要開。
- **解法**：系統設定 → 隱私權與安全性 → **輔助使用** → Terminal ✓ → 重啟程式
- **程式碼**：`paste_text()` 用方案A（osascript activate + keystroke）為主，方案B（pynput）為 fallback

### macOS 26 啟動崩潰：rumps 必須在主執行緒
- **症狀**：`NSWindow should only be instantiated on the main thread!`
- **解法**：`build_menubar_app()` 回傳 app 物件，`main()` 在主執行緒呼叫 `rumps_app.run()`；pynput 改 `listener.start()` 非阻塞

### macOS 26 HUD 崩潰：Tk 全系列不相容
- **症狀**：`[NSApplication macOSVersion]: unrecognized selector` → SIGABRT
- **解法**：`config.json` 設 `"hud_enabled": false`；`_probe_tkinter()` 以子程序安全偵測

### Grok STT 沒有 prompt 欄位：繁簡問題根因
- **症狀**：辨識結果偶爾出現簡體中文，即使 config prompt 寫了「請使用繁體中文」
- **根因**：Grok STT API 只接受 `language` 和 `keyterm`，**沒有 `prompt` 欄位**。
  keyterm 是詞彙 hint，對字型無約束力。
- **已做（v2）**：加入 **Cerebras LLM 第二層**，全包繁簡轉換、字間空格、標點、人名術語修正。
  config.json 各 mode 新增 `grok_keyterms`（STT 層詞彙，≤10）與 `llm_prompt`（LLM 層完整指令）。
- **API Key**：`CEREBRAS_API_KEY` 加入 `env.local`，免費方案每天 1M tokens。

### macOS 26 TSM 執行緒斷言：pynput 從背景執行緒崩潰
- **症狀**：辨識完成後程式 SIGTRAP 崩潰；crash log 顯示 `_dispatch_assert_queue_fail` → `TSMGetInputSourceProperty` → Thread-23 (`_do_process_recording`)
- **根因**：macOS 26 在 HIToolbox 新增 GCD 執行緒斷言——`TSMGetInputSourceProperty`（Text Services Manager）只能在主執行緒呼叫。`pynput.keyboard.Controller.press()` 內部用 ctypes 呼叫此 API 來對應字元鍵碼；若從 `_do_process_recording` 背景執行緒觸發，直接 SIGTRAP 崩潰。
- **觸發條件**：Terminal 沒有 Accessibility 授權 → osascript 方案 A 失敗（error 1002）→ fallback 到 pynput → 崩潰
- **解法**：新增 `_run_on_main_thread(fn)` helper，以 `libdispatch.dispatch_async_f` 把 pynput 按鍵動作排程到 GCD 主執行緒，背景執行緒等待 Event 後繼續。`dispatch_get_main_queue` 在 macOS 26 已是 macro，改直接取 `_dispatch_main_q` symbol 位址。
- **程式碼**：`main.py` → `_gcd_init()` / `_run_on_main_thread()` / `paste_text()` 的 pynput 路徑
- **根本預防**：在系統設定授予 Terminal Accessibility 權限，讓 osascript 路徑正常運作，無須走到 pynput fallback

### Cerebras LLM fallback 原則
- **症狀**：Cerebras API 失敗時程式不應崩潰
- **解法**：`CerebrasProvider.correct()` 的 except 直接 return 原始 STT 文字（降級但不中斷）
- **程式碼**：`main.py` → `CerebrasProvider.correct()`

### regex 不做主要修正
- **決策**：regex 層（`apply_corrections`）僅保留作 fallback 兜底，不用於移除字間空格。
- **原因**：regex 無法區分字元空格與句子邊界空格，會造成「耶用」此類誤合。全部交由 LLM 處理。

### SQLite session log 權限
- **風險**：`~/.whisper_voice_log.db` 記錄所有口述文字，預設建檔權限 644（同機他人可讀）
- **待修**：P0 待辦，main.py SessionLogger 建檔後補 `os.chmod(DB_PATH, 0o600)`

## Escalation & Review
- `NEED_REVIEW`: conflicting specs, missing credentials, or potentially destructive changes.
- Keep historical details out of this hub; store them in spoke modules or legacy archive.
