#!/bin/bash
APP_DIR="/Users/alston/Documents/AntiGravity/windows_Whisper/approach-6-whisper-macos"
PYTHON="$APP_DIR/.venv/bin/python"
PID_FILE="/tmp/WhisperVoice.pid"

# 清除可能殘留的舊 PID 檔（進程已不存在）
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ! kill -0 "$OLD_PID" 2>/dev/null; then
        rm -f "$PID_FILE"
    fi
fi

echo "🎤 啟動語音轉文字工具..."
cd "$APP_DIR"
"$PYTHON" main.py
