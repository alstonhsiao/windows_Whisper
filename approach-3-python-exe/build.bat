@echo off
echo ============================================
echo  Whisper Voice Typing — 打包成 .exe
echo ============================================
echo.

:: 安裝依賴
 pip install -r requirements.txt

:: 打包
::
:: 參數說明：
::   --onefile     單一 exe 檔案
::   --windowed    不顯示命令列視窗
::   --add-data    將 config.json 一併打包
::   --upx-dir     如果安裝了 UPX 可提供路徑以壓縮 exe（可選）
::
:: 注意：pystray 和 Pillow 已在 requirements.txt 中，必須先安裝

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
echo  如何亞警尌同事：
echo    1. 將 dist\WhisperVoiceTyping.exe 複製到目標資料夾
echo    2. 將 config.json 複製到同一資料夾
echo    3. 編輯 config.json 填入 API Key
echo    4. 雙擊 WhisperVoiceTyping.exe 啟動
echo ============================================
pause
