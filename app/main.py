import os
import asyncio
import secrets
import platform
import psutil
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from calendar import monthrange
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from app.config import AUTH_USERNAME, AUTH_PASSWORD, BASE_DIR, MONTH_RESET_DAY, PANEL_TITLE, PANEL_SUBTITLE, TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PUSH_HOUR, BANDWAGON_VEID, BANDWAGON_API_KEY
from app.database import init_db, get_db, get_meta_value, set_meta_value
from app.collector import collector_instance

security = HTTPBasic()

def verify_auth(credentials: HTTPBasicCredentials = Depends(security)):
    is_user_ok = secrets.compare_digest(credentials.username.encode("utf8"), AUTH_USERNAME.encode("utf8"))
    is_pass_ok = secrets.compare_digest(credentials.password.encode("utf8"), AUTH_PASSWORD.encode("utf8"))
    
    if not (is_user_ok and is_pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    collector_task = asyncio.create_task(collector_instance.start())
    telegram_task = asyncio.create_task(telegram_daily_notifier())
    yield
    collector_instance.running = False
    collector_task.cancel()
    telegram_task.cancel()
    for task in (collector_task, telegram_task):
        try:
            await task
        except asyncio.CancelledError:
            pass

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app/templates"))
ENV_PATH = os.path.join(BASE_DIR, ".env")
SYSTEM_INFO_CACHE = {"public_ip": None, "ip_info": None, "updated_at": 0}
SYSTEM_INFO_CACHE_TTL = 600

def get_os_pretty_name():
    try:
        with open('/etc/os-release', 'r') as f:
            for line in f:
                if line.startswith('PRETTY_NAME='):
                    return line.split('=', 1)[1].strip().strip('"')
    except Exception:
        pass
    return f"{platform.system()} {platform.release()}"

def clamp_day(year, month, day):
    return min(day, monthrange(year, month)[1])

def previous_month(year, month):
    if month == 1:
        return year - 1, 12
    return year, month - 1

def recent_months(count):
    now = datetime.now()
    months = []
    year, month = now.year, now.month
    for _ in range(count):
        months.append((year, month))
        year, month = previous_month(year, month)
    return months[::-1]

def get_current_cycle_start(now):
    reset_day = clamp_day(now.year, now.month, MONTH_RESET_DAY)
    if now.day >= reset_day:
        return datetime(now.year, now.month, reset_day)

    prev_year, prev_month = previous_month(now.year, now.month)
    prev_reset_day = clamp_day(prev_year, prev_month, MONTH_RESET_DAY)
    return datetime(prev_year, prev_month, prev_reset_day)

def format_meta_time(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value

def format_env_value(value):
    value = str(value)
    if any(ch.isspace() for ch in value) or "#" in value or '"' in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value

def parse_env_value(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value

def update_env_values(updates):
    existing = {}
    order = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                raw = line.rstrip("\n")
                if "=" in raw and not raw.lstrip().startswith("#"):
                    key, value = raw.split("=", 1)
                    existing[key] = parse_env_value(value)
                    order.append(key)

    for key, value in updates.items():
        existing[key] = str(value)
        if key not in order:
            order.append(key)

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        for key in order:
            f.write(f"{key}={format_env_value(existing[key])}\n")

def is_safe_auth_value(value):
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@_.!%-")
    return bool(value) and all(ch in allowed for ch in value)

def classify_ip_info(info):
    if not info or info.get("status") != "success":
        return "未知"
    if info.get("hosting"):
        return "機房 / VPS"
    if info.get("proxy"):
        return "代理 / VPN"
    if info.get("mobile"):
        return "行動網路"
    return "家寬 / 商寬"

def get_cached_public_ip_info():
    now = time.time()
    if SYSTEM_INFO_CACHE["public_ip"] and now - SYSTEM_INFO_CACHE["updated_at"] < SYSTEM_INFO_CACHE_TTL:
        return SYSTEM_INFO_CACHE["public_ip"], SYSTEM_INFO_CACHE["ip_info"]

    try:
        public_ip = urllib.request.urlopen('https://api.ipify.org', timeout=3).read().decode('utf-8')
    except Exception:
        public_ip = "Unknown"

    ip_info = {}
    if public_ip != "Unknown":
        try:
            fields = "status,message,country,regionName,city,isp,org,as,query,hosting,proxy,mobile"
            url = f"http://ip-api.com/json/{public_ip}?fields={fields}&lang=zh-CN"
            with urllib.request.urlopen(url, timeout=3) as response:
                ip_info = json.loads(response.read().decode("utf-8"))
        except Exception:
            ip_info = {}

    SYSTEM_INFO_CACHE["public_ip"] = public_ip
    SYSTEM_INFO_CACHE["ip_info"] = ip_info
    SYSTEM_INFO_CACHE["updated_at"] = now
    return public_ip, ip_info

def format_bytes(value):
    value = int(value or 0)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(value)
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.2f} {units[unit_index]}"

def get_traffic_summary():
    now = datetime.now()
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''SELECT SUM(rx_bytes), SUM(tx_bytes) FROM hourly_traffic
                      WHERE year=? AND month=? AND day=?''', (now.year, now.month, now.day))
    row = cursor.fetchone()
    today_rx, today_tx = (row[0] or 0), (row[1] or 0)

    cycle_start = get_current_cycle_start(now)

    cursor.execute('''SELECT SUM(rx_bytes), SUM(tx_bytes) FROM hourly_traffic
                      WHERE datetime(
                          printf('%04d-%02d-%02d %02d:00:00', year, month, day, hour)
                      ) >= datetime(?)''', (cycle_start.strftime('%Y-%m-%d %H:%M:%S'),))
    row = cursor.fetchone()
    month_rx, month_tx = (row[0] or 0), (row[1] or 0)

    cursor.execute('SELECT SUM(rx_bytes), SUM(tx_bytes) FROM hourly_traffic')
    row = cursor.fetchone()
    total_rx, total_tx = (row[0] or 0), (row[1] or 0)
    conn.close()

    for (y, m, d, h), traffic in collector_instance.pending_buckets.items():
        if y == now.year and m == now.month and d == now.day:
            today_rx += traffic["rx"]
            today_tx += traffic["tx"]
        if datetime(y, m, d, h) >= cycle_start:
            month_rx += traffic["rx"]
            month_tx += traffic["tx"]
        total_rx += traffic["rx"]
        total_tx += traffic["tx"]

    return {
        "today_rx": today_rx, "today_tx": today_tx,
        "month_rx": month_rx, "month_tx": month_tx,
        "total_rx": total_rx, "total_tx": total_tx,
        "month_reset_day": MONTH_RESET_DAY,
        "cycle_start": cycle_start.isoformat(),
        "total_since": format_meta_time(get_meta_value("install_time", ""))
    }

def fetch_bandwagon_info():
    if not BANDWAGON_VEID or not BANDWAGON_API_KEY:
        return None
    params = urllib.parse.urlencode({"veid": BANDWAGON_VEID, "api_key": BANDWAGON_API_KEY})
    url = f"https://api.64clouds.com/v1/getServiceInfo?{params}"
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"error": str(exc)}
    if data.get("error"):
        return {"error": data.get("message") or data.get("error")}
    used = int(data.get("data_counter") or 0) * int(data.get("monthly_data_multiplier") or 1)
    limit = int(data.get("plan_monthly_data") or 0) * int(data.get("monthly_data_multiplier") or 1)
    return {
        "used": used,
        "limit": limit,
        "reset": data.get("data_next_reset") or "",
        "hostname": data.get("hostname") or "",
        "node": data.get("node_location") or data.get("node_alias") or "",
    }

def build_telegram_message():
    summary = get_traffic_summary()
    ip, ip_info = get_cached_public_ip_info()
    lines = [
        f"{PANEL_TITLE}",
        f"IP: {ip}",
        f"位置: {' / '.join(filter(None, [ip_info.get('country'), ip_info.get('regionName'), ip_info.get('city')])) or 'Unknown'}",
        f"類型: {classify_ip_info(ip_info)}",
        "",
        f"今日下載: {format_bytes(summary['today_rx'])}",
        f"今日上傳: {format_bytes(summary['today_tx'])}",
        f"本期下載: {format_bytes(summary['month_rx'])}",
        f"本期上傳: {format_bytes(summary['month_tx'])}",
        f"重置日: 每月 {summary['month_reset_day']} 日",
    ]

    bw = fetch_bandwagon_info()
    if bw:
        lines.append("")
        lines.append("Bandwagon 官方流量:")
        if bw.get("error"):
            lines.append(f"查詢失敗: {bw['error']}")
        else:
            lines.append(f"已用: {format_bytes(bw['used'])}")
            lines.append(f"配額: {format_bytes(bw['limit'])}")
            if bw.get("reset"):
                lines.append(f"下次重置: {bw['reset']}")
            if bw.get("node"):
                lines.append(f"節點: {bw['node']}")
    return "\n".join(lines)

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError("Telegram token or chat id is empty")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))

def china_now():
    return datetime.utcnow() + timedelta(hours=8)

async def telegram_daily_notifier():
    while True:
        try:
            await asyncio.sleep(60)
            if TELEGRAM_ENABLED != "1" or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
                continue
            now = china_now()
            if now.hour != TELEGRAM_PUSH_HOUR:
                continue
            today_key = now.strftime("%Y-%m-%d")
            if get_meta_value("telegram_last_daily") == today_key:
                continue
            await asyncio.to_thread(send_telegram_message, build_telegram_message())
            set_meta_value("telegram_last_daily", today_key)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(300)

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, username: str = Depends(verify_auth)):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "interface": collector_instance.interface,
        "panel_title": PANEL_TITLE,
        "panel_subtitle": PANEL_SUBTITLE,
    })

@app.get("/logout")
async def logout():
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Logged out",
        headers={"WWW-Authenticate": "Basic realm=\"Logged out\""},
    )

@app.get("/api/settings")
async def api_get_settings(username: str = Depends(verify_auth)):
    return {
        "auth_username": AUTH_USERNAME,
        "panel_title": PANEL_TITLE,
        "panel_subtitle": PANEL_SUBTITLE,
    }

@app.post("/api/settings")
async def api_update_settings(payload: dict, username: str = Depends(verify_auth)):
    global AUTH_USERNAME, AUTH_PASSWORD, PANEL_TITLE, PANEL_SUBTITLE

    new_username = str(payload.get("auth_username", "")).strip()
    new_password = str(payload.get("auth_password", "")).strip()
    new_title = str(payload.get("panel_title", "")).strip()
    new_subtitle = str(payload.get("panel_subtitle", "")).strip()

    if not is_safe_auth_value(new_username):
        raise HTTPException(status_code=400, detail="Invalid username")
    if new_password and not is_safe_auth_value(new_password):
        raise HTTPException(status_code=400, detail="Invalid password")
    if not new_title or not new_subtitle:
        raise HTTPException(status_code=400, detail="Panel title and subtitle cannot be empty")

    updates = {
        "AUTH_USERNAME": new_username,
        "PANEL_TITLE": new_title,
        "PANEL_SUBTITLE": new_subtitle,
    }
    if new_password:
        updates["AUTH_PASSWORD"] = new_password

    update_env_values(updates)
    AUTH_USERNAME = new_username
    if new_password:
        AUTH_PASSWORD = new_password
    PANEL_TITLE = new_title
    PANEL_SUBTITLE = new_subtitle

    return {"ok": True}

@app.get("/api/telegram-settings")
async def api_get_telegram_settings(username: str = Depends(verify_auth)):
    return {
        "telegram_enabled": TELEGRAM_ENABLED == "1",
        "telegram_chat_id": TELEGRAM_CHAT_ID,
        "telegram_bot_token": TELEGRAM_BOT_TOKEN,
        "telegram_push_hour": TELEGRAM_PUSH_HOUR,
        "bandwagon_veid": BANDWAGON_VEID,
        "bandwagon_api_key": BANDWAGON_API_KEY,
    }

@app.post("/api/telegram-settings")
async def api_update_telegram_settings(payload: dict, username: str = Depends(verify_auth)):
    global TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PUSH_HOUR, BANDWAGON_VEID, BANDWAGON_API_KEY

    TELEGRAM_ENABLED = "1" if payload.get("telegram_enabled") else "0"
    TELEGRAM_BOT_TOKEN = str(payload.get("telegram_bot_token", "")).strip()
    TELEGRAM_CHAT_ID = str(payload.get("telegram_chat_id", "")).strip()
    try:
        TELEGRAM_PUSH_HOUR = int(payload.get("telegram_push_hour", 20))
    except (TypeError, ValueError):
        TELEGRAM_PUSH_HOUR = 20
    TELEGRAM_PUSH_HOUR = max(0, min(23, TELEGRAM_PUSH_HOUR))
    BANDWAGON_VEID = str(payload.get("bandwagon_veid", "")).strip()
    BANDWAGON_API_KEY = str(payload.get("bandwagon_api_key", "")).strip()

    update_env_values({
        "TELEGRAM_ENABLED": TELEGRAM_ENABLED,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
        "TELEGRAM_PUSH_HOUR": TELEGRAM_PUSH_HOUR,
        "BANDWAGON_VEID": BANDWAGON_VEID,
        "BANDWAGON_API_KEY": BANDWAGON_API_KEY,
    })
    return {"ok": True}

@app.post("/api/telegram-test")
async def api_telegram_test(username: str = Depends(verify_auth)):
    try:
        await asyncio.to_thread(send_telegram_message, build_telegram_message())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}

@app.post("/api/traffic/reset")
async def api_reset_traffic(username: str = Depends(verify_auth)):
    collector_instance.flush_to_db()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM hourly_traffic')
    conn.commit()
    conn.close()
    reset_time = datetime.now().isoformat()
    set_meta_value("install_time", reset_time)
    return {"ok": True, "total_since": format_meta_time(reset_time)}

@app.post("/api/reset-day")
async def api_update_reset_day(payload: dict, username: str = Depends(verify_auth)):
    global MONTH_RESET_DAY

    try:
        new_day = int(payload.get("month_reset_day", 1))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid reset day")

    if new_day < 1 or new_day > 31:
        raise HTTPException(status_code=400, detail="Reset day must be between 1 and 31")

    update_env_values({"MONTH_RESET_DAY": new_day})
    MONTH_RESET_DAY = new_day
    return {"ok": True, "month_reset_day": MONTH_RESET_DAY}

@app.get("/api/realtime")
async def api_realtime(username: str = Depends(verify_auth)):
    return {
        "rx_speed": collector_instance.current_rx_speed,
        "tx_speed": collector_instance.current_tx_speed
    }

@app.get("/api/ping")
async def api_ping(username: str = Depends(verify_auth)):
    return {"ok": True, "server_time": datetime.now().isoformat()}

@app.get("/api/system")
async def api_system(request: Request, username: str = Depends(verify_auth)):
    ip, ip_info = get_cached_public_ip_info()

    forwarded_for = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded_for.split(",", 1)[0].strip() if forwarded_for else ""
    if not client_ip and request.client:
        client_ip = request.client.host
    client_ip = client_ip or "Unknown"
    
    uptime = "Unknown"
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
            uptime = str(timedelta(seconds=int(uptime_seconds)))
    except Exception:
        pass
        
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    return {
        "public_ip": ip,
        "client_ip": client_ip,
        "ip_location": " / ".join(filter(None, [
            ip_info.get("country"),
            ip_info.get("regionName"),
            ip_info.get("city"),
        ])) or "Unknown",
        "ip_isp": ip_info.get("isp") or "Unknown",
        "ip_org": ip_info.get("org") or "Unknown",
        "ip_as": ip_info.get("as") or "Unknown",
        "ip_type": classify_ip_info(ip_info),
        "hostname": platform.node(),
        "uptime": uptime,
        "cpu_count": psutil.cpu_count(logical=True),
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_total": mem.total,
        "memory_used": mem.used,
        "memory_percent": mem.percent,
        "disk_total": disk.total,
        "disk_used": disk.used,
        "disk_percent": disk.percent,
        "os_version": get_os_pretty_name(),
        "kernel_release": platform.release(),
        "kernel_version": platform.version(),
        "interface": collector_instance.interface,
        "interface_status": collector_instance.interface_status
    }

@app.get("/api/summary")
async def api_summary(username: str = Depends(verify_auth)):
    return get_traffic_summary()

@app.get("/api/hourly")
async def api_hourly(username: str = Depends(verify_auth)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT year, month, day, hour, rx_bytes, tx_bytes 
        FROM hourly_traffic 
        ORDER BY year DESC, month DESC, day DESC, hour DESC LIMIT 24
    ''')
    data = [dict(row) for row in cursor.fetchall()][::-1]
    conn.close()
    return data

@app.get("/api/daily")
async def api_daily(username: str = Depends(verify_auth)):
    today = datetime.now().date()
    days = [today - timedelta(days=offset) for offset in range(29, -1, -1)]
    data_by_day = {
        (day.year, day.month, day.day): {
            "year": day.year,
            "month": day.month,
            "day": day.day,
            "rx_bytes": 0,
            "tx_bytes": 0,
        }
        for day in days
    }

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT year, month, day, SUM(rx_bytes) as rx_bytes, SUM(tx_bytes) as tx_bytes 
        FROM hourly_traffic
        WHERE date(printf('%04d-%02d-%02d', year, month, day)) >= date(?)
        GROUP BY year, month, day 
        ORDER BY year, month, day
    ''', (days[0].isoformat(),))
    for row in cursor.fetchall():
        key = (row["year"], row["month"], row["day"])
        if key in data_by_day:
            data_by_day[key]["rx_bytes"] = row["rx_bytes"] or 0
            data_by_day[key]["tx_bytes"] = row["tx_bytes"] or 0
    conn.close()

    for (y, m, d, _h), traffic in collector_instance.pending_buckets.items():
        key = (y, m, d)
        if key in data_by_day:
            data_by_day[key]["rx_bytes"] += traffic["rx"]
            data_by_day[key]["tx_bytes"] += traffic["tx"]

    return [data_by_day[(day.year, day.month, day.day)] for day in days]

@app.get("/api/monthly")
async def api_monthly(username: str = Depends(verify_auth)):
    months = recent_months(12)
    data_by_month = {
        (year, month): {
            "year": year,
            "month": month,
            "rx_bytes": 0,
            "tx_bytes": 0,
        }
        for year, month in months
    }
    start_year, start_month = months[0]

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT year, month, SUM(rx_bytes) as rx_bytes, SUM(tx_bytes) as tx_bytes 
        FROM hourly_traffic
        WHERE (year > ? OR (year = ? AND month >= ?))
        GROUP BY year, month 
        ORDER BY year, month
    ''', (start_year, start_year, start_month))
    for row in cursor.fetchall():
        key = (row["year"], row["month"])
        if key in data_by_month:
            data_by_month[key]["rx_bytes"] = row["rx_bytes"] or 0
            data_by_month[key]["tx_bytes"] = row["tx_bytes"] or 0
    conn.close()

    for (y, m, _d, _h), traffic in collector_instance.pending_buckets.items():
        key = (y, m)
        if key in data_by_month:
            data_by_month[key]["rx_bytes"] += traffic["rx"]
            data_by_month[key]["tx_bytes"] += traffic["tx"]

    return [data_by_month[key] for key in months]
