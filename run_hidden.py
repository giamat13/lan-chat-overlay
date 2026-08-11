#!/usr/bin/env python3
"""
run_hidden.py
מפעיל את lan-chat-overlay ברקע, בלי שום חלון קונסולה שקופץ.

חשוב: יש להריץ קובץ זה עם pythonw.exe (לא python.exe) כדי שגם
לתהליך הפייתון עצמו לא תהיה קונסולה. install_startup.bat עושה את
זה אוטומטית.

מה זה עושה:
- מוצא את תיקיית הפרויקט (התיקייה שבה נמצא הקובץ הזה).
- מפעיל "npm start" בלי שום חלון (CREATE_NO_WINDOW), ומנתק את
  התהליך מהטרמינל כדי שהוא ימשיך לרוץ גם אחרי שהסקריפט מסתיים.
- לא מדפיס כלום למסך (אין קונסולה בכלל) - אם רוצים לבדוק שגיאות,
  הפלט נשמר לקובץ run_hidden.log באותה תיקייה.
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
LOG_FILE = PROJECT_DIR / "run_hidden.log"

# חשוב: CREATE_NO_WINDOW ו-DETACHED_PROCESS אסור לשלב יחד (Windows דוחה
# את הקומבינציה) - זו הייתה אחת הסיבות שהגרסה הקודמת נכשלה בלי הודעה.
CREATE_NO_WINDOW = 0x08000000


def log_debug(msg):
    if "--debug" in sys.argv:
        print(msg)


def main():
    debug = "--debug" in sys.argv

    try:
        log_fh = open(LOG_FILE, "a", encoding="utf-8")
    except Exception as e:
        log_debug(f"לא הצלחתי לפתוח קובץ לוג: {e}")
        log_fh = subprocess.DEVNULL

    creationflags = 0
    startupinfo = None
    if os.name == "nt" and not debug:
        creationflags = CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE

    # npm ב-Windows הוא בעצם npm.cmd (קובץ batch), ולא ניתן להריץ קובץ כזה
    # ישירות עם CreateProcess כמו קובץ exe רגיל - צריך להעביר אותו דרך
    # cmd.exe. זו הייתה הבאגה השנייה בגרסה הקודמת (הייתה נכשלת בשקט עם
    # "is not a valid Win32 application" אילו הייתה הגעת עד לשם).
    cmd = ["cmd", "/c", "npm", "start"]

    log_debug(f"תיקיית פרויקט: {PROJECT_DIR}")
    log_debug(f"מריץ: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_DIR),
            stdout=log_fh,
            stderr=log_fh,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
            close_fds=True,
        )
        log_debug(f"הותחל בהצלחה, PID={proc.pid}. הפלט נשמר ל-{LOG_FILE}")
        if debug:
            proc.wait()
    except Exception as e:
        # במצב --debug זה יודפס למסך; במצב רגיל (pythonw, בלי קונסולה)
        # זה נכתב לקובץ הלוג כדי שאפשר יהיה לבדוק מה קרה.
        err_msg = f"נכשל בהפעלה: {e}"
        log_debug(err_msg)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(err_msg + "\n")
        except Exception:
            pass


if __name__ == "__main__":
    main()