@echo off
echo ============================================
echo  Gemini Voice Typing — 打包成 .exe
echo ============================================
echo.

:: 安裝依賴
pip install -r requirements.txt

:: 打包
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "GeminiVoiceTyping" ^
    --add-data "config.json;." ^
    main.py

echo.
echo ============================================
echo  打包完成！
echo  輸出位置：dist\GeminiVoiceTyping.exe
echo.
echo  給同事使用：
echo    1. 將 dist\GeminiVoiceTyping.exe 複製到目標資料夾
echo    2. 將 config.json 複製到同一資料夾
echo    3. 編輯 config.json 填入 Gemini API Key
echo    4. 雙擊 GeminiVoiceTyping.exe 啟動
echo ============================================
pause
