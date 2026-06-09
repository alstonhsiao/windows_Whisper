#!/bin/bash
# ============================================================
# Whisper Voice Typing — macOS 自動安裝腳本
# 適用：approach-6-whisper-macos
# 用法：bash install.sh
# ============================================================
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✅ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
err()  { echo -e "${RED}❌ $1${NC}"; }
info() { echo -e "${BLUE}   $1${NC}"; }

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( dirname "$SCRIPT_DIR" )"
ENV_FILE="$PROJECT_ROOT/env.local"

echo ""
echo -e "${BOLD}🎤 Whisper Voice Typing — macOS 安裝程式${NC}"
echo "=================================================="
echo ""

# ── 1. 確認 Python 3.9+ ──────────────────────────────────
echo -e "${BOLD}[1/5] 檢查 Python 版本${NC}"
if ! command -v python3 &>/dev/null; then
    err "找不到 python3"
    info "請先安裝：https://www.python.org/downloads/"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]); then
    err "Python $PY_VER 太舊，需要 3.9 以上"
    info "請至 https://www.python.org/downloads/ 更新"
    exit 1
fi
ok "Python $PY_VER"

# ── 2. 建立虛擬環境 ──────────────────────────────────────
echo ""
echo -e "${BOLD}[2/5] 建立虛擬環境${NC}"
if [ -d "$SCRIPT_DIR/.venv" ]; then
    ok "虛擬環境已存在（跳過）"
else
    python3 -m venv "$SCRIPT_DIR/.venv"
    ok "虛擬環境建立完成（$SCRIPT_DIR/.venv）"
fi

# ── 3. 安裝套件 ──────────────────────────────────────────
echo ""
echo -e "${BOLD}[3/5] 安裝 Python 套件${NC}"
info "升級 pip..."
"$SCRIPT_DIR/.venv/bin/pip" install -q --upgrade pip

info "安裝 requirements.txt（約 30 秒）..."
"$SCRIPT_DIR/.venv/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"
ok "套件安裝完成"

# ── 4. 設定 API Key ──────────────────────────────────────
echo ""
echo -e "${BOLD}[4/5] 設定 API Key${NC}"

[ -f "$ENV_FILE" ] || touch "$ENV_FILE"

has_key() {
    local KEY_NAME="$1"
    local VAL
    VAL=$(grep "^${KEY_NAME}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d ' ')
    [ -n "$VAL" ] && [[ "$VAL" != YOUR* ]]
}

prompt_key() {
    local KEY_NAME="$1"
    local DESC="$2"
    local EXAMPLE="$3"
    echo ""
    info "$DESC"
    info "範例格式：$EXAMPLE"
    read -r -p "   請貼上你的 Key（Enter 跳過）: " INPUT_KEY
    if [ -n "$INPUT_KEY" ]; then
        # 移除舊的同名 key 再寫入
        if grep -q "^${KEY_NAME}=" "$ENV_FILE" 2>/dev/null; then
            sed -i '' "/^${KEY_NAME}=/d" "$ENV_FILE"
        fi
        echo "${KEY_NAME}=${INPUT_KEY}" >> "$ENV_FILE"
        ok "$KEY_NAME 已儲存"
        return 0
    fi
    return 1
}

HAS_ANY_KEY=false

# xAI Grok（主要）
if has_key "XAI_API_KEY"; then
    ok "XAI_API_KEY 已設定（主要 provider：Grok STT）"
    HAS_ANY_KEY=true
else
    warn "XAI_API_KEY 未設定"
    info "取得：https://console.x.ai/ → API Keys"
    if prompt_key "XAI_API_KEY" "xAI Grok STT API Key（推薦，速度最快）" "xai-xxxxxxxxxxxxx"; then
        HAS_ANY_KEY=true
    fi
fi

# OpenAI（備用）
if has_key "OPENAI_API_KEY"; then
    ok "OPENAI_API_KEY 已設定（備用 provider：OpenAI Whisper）"
    HAS_ANY_KEY=true
else
    warn "OPENAI_API_KEY 未設定"
    info "取得：https://platform.openai.com/api-keys"
    if prompt_key "OPENAI_API_KEY" "OpenAI API Key（備用）" "sk-xxxxxxxxxxxxx"; then
        HAS_ANY_KEY=true
    fi
fi

if [ "$HAS_ANY_KEY" = false ]; then
    err "未設定任何 API Key，無法使用語音辨識"
    info "安裝已完成，請之後手動編輯：$ENV_FILE"
    info "加入：XAI_API_KEY=你的Key"
fi

# ── 5. 建立啟動捷徑 ──────────────────────────────────────
echo ""
echo -e "${BOLD}[5/5] 建立啟動捷徑${NC}"

LAUNCH_PATH="$SCRIPT_DIR/啟動語音輸入.command"
cat > "$LAUNCH_PATH" << CMDEOF
#!/bin/bash
cd "${SCRIPT_DIR}"
echo "🎤 啟動語音轉文字工具..."
"${SCRIPT_DIR}/.venv/bin/python" main.py
CMDEOF
chmod +x "$LAUNCH_PATH"
ok "啟動捷徑已建立：啟動語音輸入.command"
info "在 Finder 中雙擊即可啟動"

# ── 完成摘要 ─────────────────────────────────────────────
echo ""
echo "=================================================="
echo -e "${GREEN}${BOLD}🎉 安裝完成！${NC}"
echo ""
echo -e "${BOLD}啟動方式：${NC}"
echo "  雙擊 Finder 中的「啟動語音輸入.command」"
echo "  或執行：cd $SCRIPT_DIR && .venv/bin/python main.py"
echo ""
echo -e "${BOLD}操作說明：${NC}"
echo "  Ctrl + F1    → 開始錄音（聽到 beep 再說話）"
echo "  Ctrl + F1    → 再按一次，停止並辨識貼上"
echo "  F10          → 切換辨識模式（四種）"
echo "  點 HUD        → 展開模式選單"
echo "  HUD 右鍵      → 結束程式"
echo ""
echo -e "${YELLOW}⚠️  首次執行：macOS 會要求三項授權${NC}"
echo "   麥克風 / 輔助使用 / 輸入監控 → 全部點「允許」"
echo "   授權後請重新啟動程式。"
echo ""
