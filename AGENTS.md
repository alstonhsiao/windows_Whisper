# AGENTS

> Governance Hub for this project. Read this file first in every new session.

## Mission
語音轉文字工具（Grok STT / Whisper / Gemini，多平台）。
macOS 主力方案：approach-6（rumps 選單列、四模式切換、multi-provider；macOS 26 相容）。

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

## Escalation & Review
- `NEED_REVIEW`: conflicting specs, missing credentials, or potentially destructive changes.
- Keep historical details out of this hub; store them in spoke modules or legacy archive.
