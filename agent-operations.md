# Agent Operations

## Non-Negotiable Rules
- API keys 必須放在專案根目錄的 `env.local`（或 `.env.local`）；**絕對不可 commit**。
  - 各 provider 的 key 名稱：`OPENAI_API_KEY`、`GEMINI_API_KEY`、`GROK_API_KEY`
- 任何需要呼叫 provider 的測試前，先用 `test_api_key.py` 驗證 API 連線（免費，不消耗 token）。
- Keys 不可出現在程式碼、log 輸出、或 git history 中。
- `approach-6-whisper-macos/` 內的 `.bak` 檔是本地備份，不可 commit 也不可修改。

## Execution Order
- Step 1: Read `AGENTS.md` and the quick map first.
- Step 2: Open only the module/index files relevant to the requested task.
- Step 3: Implement minimal safe changes, then validate with the project's native checks.

## Validation Baseline
- Confirm no secrets are exposed in code, logs, or commits.
- Confirm business-critical flows still pass smoke checks.
- Document assumptions in the final update when requirements are ambiguous.
