#!/usr/bin/env python3
"""
fix_and_run.py (עם logs + timeout)
מתקן ומריץ את lan-chat-overlay, בלי להיתקע לנצח על הורדת Electron.

מה חדש בגרסה הזו:
- כל ניסיון הורדה מוגבל בזמן (ברירת מחדל: 90 שניות). אם זה תקוע - עוברים
  אוטומטית לניסיון הבא במקום לחכות לנצח.
- כל הפלט (stdout+stderr) מודפס בזמן אמת עם חותמת זמן, וגם נשמר לקובץ
  fix_and_run.log לצפייה/שליחה אם צריך.
- מדפיס בבירור באיזה שלב/מראה זה נמצא, כדי שלא תשב שוב חצי שעה בלי לדעת מה קורה.

הרצה:
    python fix_and_run.py
    python fix_and_run.py --timeout 120      # לשנות את זמן ה-timeout (בשניות)
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

MIRRORS = [
    ("ללא מראה (ישיר, ברירת מחדל)", None),
    ("npmmirror (מראה סינית, לרוב מהירה ולא חסומה)",
     "https://npmmirror.com/mirrors/electron/"),
    ("Electron GitHub releases (ישיר)",
     "https://github.com/electron/electron/releases/download/"),
    ("jsdelivr proxy למראה electron", "https://cdn.jsdelivr.net/gh/electron/electron-mirror/"),
]

LOG_FILE = None


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def run_with_timeout(cmd, env, cwd, timeout_sec):
    """
    מריץ פקודה, סוטרם פלט חי עם חותמות זמן, וקוטע אותה אם עוברת timeout_sec.
    מחזיר (success: bool, timed_out: bool)
    """
    log(f"מריץ: {cmd}   (timeout: {timeout_sec}s)")
    proc = subprocess.Popen(
        cmd,
        shell=True,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    timed_out = {"flag": False}

    def killer():
        time.sleep(timeout_sec)
        if proc.poll() is None:
            timed_out["flag"] = True
            log(f"⏱️  עברו {timeout_sec} שניות בלי שהפקודה הסתיימה - מבטל ומנסה חלופה אחרת...")
            proc.kill()

    timer_thread = threading.Thread(target=killer, daemon=True)
    timer_thread.start()

    try:
        for raw_line in proc.stdout:
            line = raw_line.rstrip()
            if line:
                log(f"    | {line}")
    except Exception as e:
        log(f"שגיאה בקריאת פלט: {e}")

    proc.wait()
    success = (proc.returncode == 0) and not timed_out["flag"]
    return success, timed_out["flag"]


def get_electron_cache_dir():
    system = platform.system()
    home = Path.home()
    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "electron" / "Cache"
        return home / "AppData" / "Local" / "electron" / "Cache"
    elif system == "Darwin":
        return home / "Library" / "Caches" / "electron"
    else:
        return home / ".cache" / "electron"


def clean_cache():
    cache_dir = get_electron_cache_dir()
    if cache_dir.exists():
        log(f"מנקה קאש קיים (יכול להיות פגום/חלקי): {cache_dir}")
        try:
            shutil.rmtree(cache_dir)
            log("קאש נוקה בהצלחה.")
        except Exception as e:
            log(f"לא הצלחתי לנקות קאש (ממשיכים בכל זאת): {e}")
    else:
        log("אין קאש קיים - אין מה לנקות.")


def check_node_npm():
    for tool in ("node", "npm"):
        found = shutil.which(tool)
        if not found:
            log(f"❌ '{tool}' לא נמצא ב-PATH. התקינו Node.js מ-https://nodejs.org ונסו שוב.")
            sys.exit(1)
        else:
            run_with_timeout(f"{tool} --version", os.environ.copy(), None, 15)
    log("Node.js ו-npm נמצאים ב-PATH, ממשיכים.")


def find_project_dir():
    cwd = Path.cwd()
    if (cwd / "package.json").exists():
        return cwd
    candidate = cwd / "lan-chat-overlay"
    if (candidate / "package.json").exists():
        return candidate
    log("❌ לא נמצא package.json. הריצו את הסקריפט מתוך תיקיית הפרויקט (lan-chat-overlay).")
    sys.exit(1)


def try_install(project_dir, label, mirror_url, timeout_sec):
    log("")
    log("=" * 60)
    log(f"ניסיון: {label}")
    log("=" * 60)

    env = os.environ.copy()
    env["npm_config_loglevel"] = "verbose"
    if mirror_url:
        env["ELECTRON_MIRROR"] = mirror_url
        env["npm_config_electron_mirror"] = mirror_url
        log(f"משתמש במראה: {mirror_url}")
    else:
        env.pop("ELECTRON_MIRROR", None)
        env.pop("npm_config_electron_mirror", None)
        log("לא משתמש במראה (ברירת מחדל של Electron).")

    success, timed_out = run_with_timeout("npm install", env, str(project_dir), timeout_sec)

    if timed_out:
        log(f"❌ ניסיון '{label}' נכשל - חרג מזמן ({timeout_sec}s). כנראה חסום/איטי מדי.")
    elif success:
        log(f"✅ ניסיון '{label}' הצליח!")
    else:
        log(f"❌ ניסיון '{label}' נכשל (קוד יציאה שונה מ-0).")

    return success


def main():
    global LOG_FILE

    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=90,
                         help="שניות המתנה מקסימלית לכל ניסיון הורדה (ברירת מחדל: 90)")
    args = parser.parse_args()

    project_dir_hint = Path.cwd()
    LOG_FILE = str(project_dir_hint / "fix_and_run.log")
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        LOG_FILE = None

    log("=== fix_and_run.py: תיקון והרצת lan-chat-overlay ===")
    if LOG_FILE:
        log(f"כל הפלט נשמר גם לקובץ: {LOG_FILE}")

    check_node_npm()
    project_dir = find_project_dir()
    log(f"תיקיית פרויקט: {project_dir}")

    clean_cache()

    success = False
    for label, mirror in MIRRORS:
        if try_install(project_dir, label, mirror, args.timeout):
            success = True
            break

    if not success:
        log("")
        log("❌ כל הניסיונות נכשלו תוך timeout. הרשת כנראה חוסמת גם GitHub וגם את המראות.")
        log("אפשרויות נוספות:")
        log("  1. בדקו אנטי-וירוס/פיירוול חברה שחוסם חיבורי npm/node.")
        log("  2. נסו לרגע רשת אחרת (למשל נקודת חיבור מהטלפון) רק כדי")
        log("     להוריד את קובץ ה-Electron, ואז חזרו לרשת הרגילה.")
        log("  3. הורידו ידנית מ: https://github.com/electron/electron/releases")
        log(f"  4. הפלט המלא נשמר ב-{LOG_FILE} - אפשר לשלוח אותו לבדיקה.")
        sys.exit(1)

    log("")
    log("✅ ההתקנה הצליחה! מפעיל את האפליקציה (npm start)...")
    log("")
    run_with_timeout("npm start", os.environ.copy(), str(project_dir), 30)
    log("(npm start רץ ברקע/נפתח - אם לא נפתח חלון, בדקו את הלוג למעלה)")


if __name__ == "__main__":
    main()
