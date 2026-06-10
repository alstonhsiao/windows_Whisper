# AGENTS

> Governance Hub for this project. Read this file first in every new session.

## Mission
語音轉文字工具（Grok STT / Whisper / Gemini，多平台）。
macOS 主力方案：approach-6（rumps 選單列、四模式切換、multi-provider；macOS 26 相容）。
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

## Escalation & Review
- `NEED_REVIEW`: conflicting specs, missing credentials, or potentially destructive changes.
- Keep historical details out of this hub; store them in spoke modules or legacy archive.
