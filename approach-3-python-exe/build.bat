@echo off
echo ============================================
echo  Whisper Voice Typing — 打包成 .exe
echo ============================================
echo.

:: 安裝 PyInstaller（如果還沒裝）
pip install pyinstaller

:: 打包
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "WhisperVoiceTyping" ^
    --add-data "config.json;." ^
    main.py

echo.
echo ============================================
echo  打包完成！
echo  輸出位置：dist\WhisperVoiceTyping.exe
echo.
echo  使用方式：
echo    1. 將 dist\WhisperVoiceTyping.exe 複製到目標資料夾
echo    2. 將 config.json 複製到同一資料夾
echo    3. 編輯 config.json 填入 API Key
echo    4. 雙擊 WhisperVoiceTyping.exe 啟動
echo ============================================
pause
