# TODO — windows_Whisper 專案

## 中優先

- [ ] **approach-6 原生 HUD（PyObjC NSPanel）**
  - 背景：tkinter 全系列（Tk 8.5 / Tk 9.0）在 macOS 26 Tahoe 不相容
  - macOS 26 移除了 `[NSApplication macOSVersion]` selector，Tk 呼叫它導致 SIGABRT
  - 解法：用 PyObjC (`pyobjc-framework-Cocoa` 已裝，pynput 依賴) 實作 NSPanel
  - 設計重點：
    - `class NativeHUD` 替換 `class HUD`
    - NSPanel (floating, non-activating) 定位在右下角
    - NSTextField 顯示模式名稱 + 狀態 emoji
    - 點擊觸發 NSMenu 模式選單
    - 右鍵 → 結束程式
    - 所有 UI 更新透過 `dispatch_async(dispatch_get_main_queue(), ...)` 從背景執行緒發送
  - 參考 API：
    - `NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(...)`
    - `NSFloatingWindowLevel`
    - `NSWindowStyleMaskBorderless`
    - `AppKit.NSApp` 必須在主執行緒
  - 前置條件：先完成 rumps 選單列修正（NSApplication 已在主執行緒）

---

## 低優先 / 探索

- [ ] **OpenCC 後處理（繁簡轉換保底）**
  - 背景：Grok STT 沒有 `prompt` 欄位，`language: zh-TW` 有效但不保證 100% 輸出繁體
  - 解法：`pip install opencc-python-reimplemented`，辨識結果送入 `opencc.OpenCC('s2twp').convert(text)`
  - 位置：`main.py` 辨識後、regex 後處理前（約 L883）
  - 評估條件：若 `zh-TW` 語言碼測試後仍偶發簡體，則加入此項
  - 參考：`s2twp` = 簡→繁（台灣詞彙標準），idempotent

- [ ] **Groq Whisper 語速測試（繁中）**
  - 已知 Groq 約 0.5s，但繁中辨識品質待評估

- [ ] **approach-7：完整 PyObjC app（無 Terminal 視窗）**
  - 打包成 .app bundle，使用者體驗更好

---

## 已完成

- [x] approach-6 基礎架構（hotkey + Whisper API + paste）
- [x] approach-6 Grok STT 整合（`/v1/stt` endpoint）
- [x] approach-6 四模式切換（direct / zh2en / pro / casual）
- [x] approach-6 Toggle 模式熱鍵（Ctrl+F1）
- [x] approach-6 install.sh + install_manual.md
- [x] macOS 26 崩潰根因分析（Tk 全系列不相容）
- [x] approach-6 rumps 主執行緒重構（macOS 26 相容）
- [x] approach-6 HUD 停用 + `_probe_tkinter` 強化偵測
