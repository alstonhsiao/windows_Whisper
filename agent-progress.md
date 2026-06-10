# Agent Progress & Open Issues

## Recent Progress

### 2026-06-10 — approach-6-whisper-macos：Cerebras LLM 雙層語音修正整合

**完成 Phases 0–5（plan20260610.md）**

#### 變更
- `approach-6-whisper-macos/config.json`：
  - 在 `api` 區塊下新增 `llm_correction` 設定，採用 `gpt-oss-120b` 作為 Cerebras 的預設大語言模型。
  - 為 `direct`、`zh2en`、`pro`、`casual` 模式新增 `grok_keyterms` 與 `llm_prompt`。
- `approach-6-whisper-macos/main.py`：
  - 新增 `LLMCorrectionProvider` 與其 `CerebrasProvider` 實作。
  - `CerebrasProvider` 採用 `requests` 庫直接調用 Cerebras API，避免安裝 `cerebras-cloud-sdk` 帶來的環境依賴衝突。
  - 實作 API 呼叫的 Fallback 邏輯（Cerebras 失敗時安全返回 STT 原始文字，不崩潰）。
  - 更新 `Mode` 類別以載入 `grok_keyterms` 與 `llm_prompt`，並實作向後相容。
  - 更新 `GrokProvider` 改為直接使用 `mode.grok_keyterms`。
  - 更新 `load_config`，支援讀取與複製 `llm_correction` 設定。
  - 重構 `_do_process_recording` 加入 LLM 修正與計時 Log（`⏱ STT: X.XXs | LLM: X.XXs | total: X.XXs`）。

#### 驗證
- 驗證 Cerebras API Key（`env.local` 讀取正常）。
- `test_cerebras.py` 測試通過（成功取得回覆「OK」）。
- 端對端單元測試：字間空格修正、繁簡轉換、標點補充、人名與術語修正符合預期。
- 429 Rate Limit/其他異常 Fallback 驗證：當遇到限制時安全返回 STT 原始文字，程式正常執行不崩潰。

---

### 2026-06-09 — approach-6-whisper-macos：macOS 26 相容性修正

**修復 macOS 26 (Tahoe) 啟動崩潰：停用 HUD + 重構 rumps 主執行緒**

#### 根因
- macOS 26 移除 `[NSApplication macOSVersion]` 與 `_setup:` selector
- Tk 8.5/9.0 在 `TkpGetColor → GetRGBA` 時呼叫已移除 API → SIGABRT
- rumps `NSApplication.run()` 必須在主執行緒，背景執行緒會丟 `NSWindow should only be instantiated on the main thread!`

#### 變更
- `config.json`：`ui.hud_enabled = false`
- `main.py`：
  - 移除 `try_start_menubar()`（背景執行緒架構）
  - 新增 `build_menubar_app(mode_manager)`：建立 rumps app 但不啟動，回傳給 main()
  - rumps 選單列加入四種模式切換與 `❌ 結束程式`
  - `main()` 結尾：pynput 改用 `listener.start()` 非阻塞，主執行緒呼叫 `rumps_app.run()`
  - `_probe_tkinter()` 加入 `Frame(bg=...)` + `Label(bg=...)` 測試以偵測 macOS 26 GetRGBA 崩潰
- `install_manual.md`：加入 macOS 26 Tahoe 系統需求註記與 FAQ
- `README.md`：更新 HUD 功能說明
- `todo.md`：標記 rumps 主執行緒重構完成

#### 驗證
- `.venv/bin/python main.py` 啟動 30 秒以上不崩潰，rumps 主執行緒事件迴圈正常

---

### 2026-06-09 — approach-6-whisper-macos：浮動 HUD + 模式切換 + Grok API

**完成 Phases 0–9（plan20260609.md）**

#### 變更檔案
- `approach-6-whisper-macos/main.py`：重構（+約 350 行）
  - `load_config()` 重寫：支援新 schema + 向後相容舊 schema
  - 新增 `Mode` / `ModeManager` 類別（模式系統）
  - 新增 `TranscribeProvider` / `OpenAIProvider` / `GroqProvider` / `GrokProvider` + `build_provider()`（Provider 抽象）
  - 移除舊 `transcribe()` 函式
  - 新增 `HUD` 類別（tkinter 浮動視窗、點擊展開模式選單）
  - `main()` 重寫：注入 ModeManager、Provider、HUD；加入 F10 模式循環熱鍵
- `approach-6-whisper-macos/config.json`：重寫為新 schema（多模式、multi-provider）
- `approach-6-whisper-macos/main.py.bak` / `config.json.bak`：備份（不入 git）

#### 不變動的函式（依計畫保留）
`ensure_single_instance`, `try_start_menubar`, `set_menubar_state`,
`AudioRecorder`, `apply_corrections`, `paste_text`, `beep`

#### Grok STT API 驗證結論
- Endpoint: `POST https://api.x.ai/v1/stt`
- 欄位：`file`（最後）、`language`、`keyterm`（可重複，對應 prompt 關鍵字）
- 無 `model` 欄位；response: JSON `{"text":"...", "language":"...", "duration":N}`
- `prompt` 欄位不支援 → 改用 `keyterm` 傳遞關鍵詞

#### Phase 8 速度比較（5 秒語音 × 3 次）
| Provider | 平均回應時間 |
|---------|------------|
| Grok STT | **0.97s** |
| OpenAI gpt-4o-transcribe | 1.43s |
> Grok 比 OpenAI 快 ~32%，延遲更穩定（0.94–0.99s vs 0.87–2.05s）

---

## Open Issues / TODO
- [ ] Grok STT 傳統中文 keyterm 支援需更多實測（目前使用 TTS 生成音訊測試）
- [ ] 使用者實際錄音測試 HUD 三個狀態切換（需人工操作）
- [ ] 如需繁體中文輸出，可考慮 post-process 轉換（Grok 目前回簡體）

## Maintenance Note
- Update this file at end of each substantial task to avoid AGENTS.md growth.
