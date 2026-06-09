#!/bin/bash
APP_DIR="/Users/alston/Documents/AntiGravity/windows_Whisper/approach-6-whisper-macos"
PYTHON="$APP_DIR/.venv/bin/python"

echo "🔄 重啟語音轉文字工具..."

# 找並結束現有 main.py 程序
PIDS=$(pgrep -f "python.*approach-6.*main.py")
if [ -n "$PIDS" ]; then
    echo "🛑 結束現有程序 (PID: $PIDS)..."
    kill $PIDS
    sleep 1
fi

echo "🎤 啟動語音轉文字工具..."
cd "$APP_DIR"
"$PYTHON" main.py
