@echo off
REM install_startup.bat
REM מתקין הפעלה אוטומטית של lan-chat-overlay עם כל התחברות ל-Windows,
REM לגמרי ברקע, בלי חלון קונסולה שקופץ.
REM
REM הרצה: פשוט לחצו כפול על הקובץ הזה פעם אחת (אין צורך להריץ שוב).

setlocal

set "PROJECT_DIR=%~dp0"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS_PATH=%STARTUP_DIR%\lan-chat-overlay-autostart.vbs"

REM מוצאים pythonw.exe (הגרסה של פייתון בלי קונסולה)
where pythonw >nul 2>nul
if errorlevel 1 (
    echo לא נמצא pythonw.exe. ודאו ש-Python מותקן ונמצא ב-PATH.
    pause
    exit /b 1
)
for /f "delims=" %%P in ('where pythonw') do set "PYTHONW=%%P" & goto :found
:found

REM יוצרים קובץ VBS קטן ב-Startup - זה מבטיח שגם ההפעלה של pythonw
REM עצמה לא תגרום בכלל להבהוב חלון, בניגוד להפעלת .bat ישירות מ-Startup.
> "%VBS_PATH%" (
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WshShell.Run """%PYTHONW%"" ""%PROJECT_DIR%run_hidden.py""", 0, False
)

if exist "%VBS_PATH%" (
    echo הותקן בהצלחה. lan-chat-overlay יופעל אוטומטית וברקע בכל כניסה ל-Windows.
    echo ^(הקובץ נוצר ב: "%VBS_PATH%"^)
) else (
    echo משהו השתבש - לא נוצר קובץ ההפעלה האוטומטית.
)

pause
endlocal
