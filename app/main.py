import os
import asyncio
import secrets
import platform
import psutil
import urllib.request
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from app.config import AUTH_USERNAME, AUTH_PASSWORD, BASE_DIR
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
        "os_version": f"{platform.system()} {platform.release()}",
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
    
    cursor.execute('''SELECT SUM(rx_bytes), SUM(tx_bytes) FROM hourly_traffic 
                      WHERE year=? AND month=?''', (now.year, now.month))
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
        if y == now.year and m == now.month:
            month_rx += traffic["rx"]
            month_tx += traffic["tx"]
        total_rx += traffic["rx"]
        total_tx += traffic["tx"]
        
    return {
        "today_rx": today_rx, "today_tx": today_tx,
        "month_rx": month_rx, "month_tx": month_tx,
        "total_rx": total_rx, "total_tx": total_tx
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
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT year, month, day, SUM(rx_bytes) as rx_bytes, SUM(tx_bytes) as tx_bytes 
        FROM hourly_traffic 
        GROUP BY year, month, day 
        ORDER BY year DESC, month DESC, day DESC LIMIT 30
    ''')
    data = [dict(row) for row in cursor.fetchall()][::-1]
    conn.close()
    return data

@app.get("/api/monthly")
async def api_monthly(username: str = Depends(verify_auth)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT year, month, SUM(rx_bytes) as rx_bytes, SUM(tx_bytes) as tx_bytes 
        FROM hourly_traffic 
        GROUP BY year, month 
        ORDER BY year DESC, month DESC LIMIT 12
    ''')
    data = [dict(row) for row in cursor.fetchall()][::-1]
    conn.close()
    return data
