#!/bin/bash
APP_DIR="/Users/alston/Documents/AntiGravity/windows_Whisper/approach-6-whisper-macos"
PYTHON="$APP_DIR/.venv/bin/python"
PID_FILE="/tmp/WhisperVoice.pid"

echo "🔄 重啟語音轉文字工具..."

# 從 PID 檔找到並結束現有程序
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "🛑 結束現有程序 (PID: $OLD_PID)..."
        kill "$OLD_PID"
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

echo "🎤 啟動語音轉文字工具..."
cd "$APP_DIR"
"$PYTHON" main.py
