import os
import asyncio
import secrets
import platform
import psutil
import urllib.request
from datetime import datetime, timedelta
from calendar import monthrange
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from app.config import AUTH_USERNAME, AUTH_PASSWORD, BASE_DIR, MONTH_RESET_DAY
from app.database import init_db, get_db
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
    task = asyncio.create_task(collector_instance.start())
    yield
    collector_instance.running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app/templates"))

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

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, username: str = Depends(verify_auth)):
    return templates.TemplateResponse("index.html", {"request": request, "interface": collector_instance.interface})

@app.get("/api/realtime")
async def api_realtime(username: str = Depends(verify_auth)):
    return {
        "rx_speed": collector_instance.current_rx_speed,
        "tx_speed": collector_instance.current_tx_speed
    }

@app.get("/api/system")
async def api_system(username: str = Depends(verify_auth)):
    try:
        ip = urllib.request.urlopen('https://api.ipify.org', timeout=3).read().decode('utf-8')
    except Exception:
        ip = "Unknown"
    
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
        "cycle_start": cycle_start.isoformat()
    }

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
