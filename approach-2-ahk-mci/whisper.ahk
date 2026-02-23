; ============================================================================
; Windows 語音轉文字工具 — 方案二：AutoHotkey v2 + Windows MCI（無 SoX）
;
; 使用方式：
;   1. 安裝 AutoHotkey v2：https://www.autohotkey.com/
;   2. 編輯同目錄的 config.ini，填入 API Key
;   3. 雙擊本檔案（whisper.ahk）啟動
;
; 操作：
;   - 按住 F1 → 開始錄音（聽到 beep 後開始說話）
;   - 放開 F1 → 停止錄音 → 自動辨識 → 貼上文字到游標位置
;   - 右鍵系統匣圖示 → 結束程式
; ============================================================================

#Requires AutoHotkey v2.0
#SingleInstance Force
#MaxThreadsPerHotkey 1

; ---------------------------------------------------------------------------
; 全域變數
; ---------------------------------------------------------------------------
global isRecording := false
global tempDir := EnvGet("TEMP")
global wavFile := tempDir "\whisper_voice.wav"
global responseFile := tempDir "\whisper_response.json"

; ---------------------------------------------------------------------------
; 讀取設定
; ---------------------------------------------------------------------------
configFile := A_ScriptDir "\config.ini"
if !FileExist(configFile) {
    MsgBox "找不到 config.ini！`n請將 config.ini 放在與 whisper.ahk 同目錄。", "錯誤", "Icon!"
    ExitApp
}

apiKey := IniRead(configFile, "API", "OpenAI_API_Key", "")
model := IniRead(configFile, "API", "Model", "whisper-1")
language := IniRead(configFile, "API", "Language", "zh")
temperature := IniRead(configFile, "API", "Temperature", "0.0")
promptText := IniRead(configFile, "Prompt", "PromptText", "請使用繁體中文。")
hotkey := IniRead(configFile, "Hotkey", "RecordKey", "F1")

if (apiKey = "" || apiKey = "YOUR_OPENAI_API_KEY_HERE") {
    MsgBox "請先在 config.ini 中設定 OpenAI API Key！", "錯誤", "Icon!"
    ExitApp
}

; 讀取 Regex 規則
regexRules := []
loop {
    rule := IniRead(configFile, "PostProcess", "Regex" A_Index, "")
    if (rule = "")
        break
    parts := StrSplit(rule, "=>")
    if (parts.Length >= 2)
        regexRules.Push({pattern: parts[1], replacement: parts[2]})
}

; ---------------------------------------------------------------------------
; 系統匣
; ---------------------------------------------------------------------------
A_IconTip := "Whisper 語音轉文字 — 待機中"
TraySetIcon("Shell32.dll", 18)  ; 麥克風圖示

trayMenu := A_TrayMenu
trayMenu.Delete()
trayMenu.Add("Whisper 語音轉文字", (*) => "")
trayMenu.Disable("Whisper 語音轉文字")
trayMenu.Add()
trayMenu.Add("開啟設定檔", (*) => Run(configFile))
trayMenu.Add("結束程式", (*) => ExitApp())

; 提示啟動成功
ToolTip("🎤 Whisper 語音轉文字已啟動`n按住 " hotkey " 說話", A_ScreenWidth - 350, A_ScreenHeight - 100)
SetTimer () => ToolTip(), -3000

; ---------------------------------------------------------------------------
; MCI 錄音函式（使用 Windows 內建 winmm.dll）
; ---------------------------------------------------------------------------
MCI_SendString(command) {
    buf := Buffer(512)
    result := DllCall("winmm\mciSendStringW"
        , "Str", command
        , "Ptr", buf.Ptr
        , "UInt", 255
        , "Ptr", 0
        , "Int")
    return StrGet(buf.Ptr)
}

StartRecording() {
    global isRecording, wavFile

    ; 刪除舊錄音檔
    try FileDelete(wavFile)

    ; 開啟 MCI 錄音裝置
    MCI_SendString("close whisper_mic")  ; 確保先關閉
    MCI_SendString("open new Type waveaudio Alias whisper_mic")
    MCI_SendString("set whisper_mic time format milliseconds bitspersample 16 channels 1 samplespersec 16000")
    MCI_SendString("record whisper_mic")

    isRecording := true

    ; 等待錄音就緒後發出 beep
    ; MCI 不寫檔，所以用時間延遲代替檢查檔案大小
    Sleep(300)
    SoundBeep(1000, 200)
}

StopRecording() {
    global isRecording, wavFile

    isRecording := false

    ; 停止並儲存 WAV（MCI save 會寫入完整 WAV header）
    MCI_SendString("stop whisper_mic")
    MCI_SendString("save whisper_mic " wavFile)
    MCI_SendString("close whisper_mic")

    Sleep(100)  ; 確保檔案寫入完成
}

; ---------------------------------------------------------------------------
; Whisper API 呼叫（使用 Windows 內建 curl.exe）
; ---------------------------------------------------------------------------
CallWhisperAPI() {
    global wavFile, responseFile, apiKey, model, language, temperature, promptText

    ; 刪除舊回應
    try FileDelete(responseFile)

    ; 組裝 curl 指令
    cmd := 'curl.exe -s -f'
        . ' --connect-timeout 10 --max-time 30'
        . ' -H "Authorization: Bearer ' apiKey '"'
        . ' -H "Content-Type: multipart/form-data"'
        . ' -F file="@' wavFile '"'
        . ' -F model="' model '"'
        . ' -F language="' language '"'
        . ' -F temperature="' temperature '"'
        . ' -F response_format="json"'
        . ' -F prompt="' promptText '"'
        . ' "https://api.openai.com/v1/audio/transcriptions"'
        . ' -o "' responseFile '"'

    RunWait(cmd, , "Hide")

    ; 讀取回應
    if !FileExist(responseFile) {
        return ""
    }
    jsonStr := FileRead(responseFile, "UTF-8")

    ; 用 RegEx 提取 text 欄位
    if RegExMatch(jsonStr, '"text"\s*:\s*"((?:[^"\\]|\\.)*)"', &match) {
        text := match[1]
        ; 處理 JSON 轉義字元
        text := StrReplace(text, "\n", "`n")
        text := StrReplace(text, "\r", "`r")
        text := StrReplace(text, "\t", "`t")
        text := StrReplace(text, '\"', '"')
        text := StrReplace(text, "\\", "\")
        return text
    }
    return ""
}

; ---------------------------------------------------------------------------
; 後處理（Regex 修正 + Trim）
; ---------------------------------------------------------------------------
ApplyCorrections(text) {
    global regexRules

    for rule in regexRules {
        text := RegExReplace(text, "i)" rule.pattern, rule.replacement)
    }

    return Trim(text)
}

; ---------------------------------------------------------------------------
; 熱鍵：F1 按下 → 開始錄音
; ---------------------------------------------------------------------------
*F1:: {
    global isRecording
    if isRecording
        return

    A_IconTip := "Whisper 語音轉文字 — 🔴 錄音中"
    TraySetIcon("Shell32.dll", 110)  ; 紅色圖示
    ToolTip("🔴 錄音中...")

    StartRecording()
}

; ---------------------------------------------------------------------------
; 熱鍵：F1 放開 → 停止錄音、辨識、貼上
; ---------------------------------------------------------------------------
*F1 Up:: {
    global isRecording, wavFile
    if !isRecording
        return

    ToolTip("⏹️ 停止錄音...")
    StopRecording()

    ; 檢查檔案大小（< 5KB 視為太短）
    if !FileExist(wavFile) || FileGetSize(wavFile) < 5000 {
        ToolTip("⚠️ 錄音時間太短")
        SetTimer () => ToolTip(), -2000
        A_IconTip := "Whisper 語音轉文字 — 待機中"
        TraySetIcon("Shell32.dll", 18)
        return
    }

    ; 呼叫 API
    ToolTip("🔄 辨識中...")
    A_IconTip := "Whisper 語音轉文字 — 🔄 辨識中"
    TraySetIcon("Shell32.dll", 136)  ; 藍色圖示

    text := CallWhisperAPI()

    if (text = "") {
        ToolTip("❌ 辨識失敗")
        SetTimer () => ToolTip(), -2000
        A_IconTip := "Whisper 語音轉文字 — 待機中"
        TraySetIcon("Shell32.dll", 18)
        return
    }

    ; 後處理
    text := ApplyCorrections(text)

    if (text = "") {
        ToolTip("⚠️ 辨識結果為空")
        SetTimer () => ToolTip(), -2000
        A_IconTip := "Whisper 語音轉文字 — 待機中"
        TraySetIcon("Shell32.dll", 18)
        return
    }

    ; 貼上文字
    A_Clipboard := text
    Sleep(50)
    Send("^v")

    ToolTip("✅ " text)
    SetTimer () => ToolTip(), -3000

    ; 恢復待機狀態
    A_IconTip := "Whisper 語音轉文字 — 待機中"
    TraySetIcon("Shell32.dll", 18)
}
