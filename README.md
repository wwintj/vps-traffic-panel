# VPS 監控流量面板

一個輕量、直觀、適合長期掛在 VPS 上的流量監控面板。支援即時上下行速度、今日流量、本期流量、最近 24 小時、最近 30 天、最近 12 個月統計，並內建面板文字、登入資訊、流量重置日與流量清零功能。

後端使用 FastAPI，資料存入 SQLite，前端使用 ECharts。採集資料直接讀取 Linux 系統的 `/proc/net/dev`，資源占用很低，適合 1C1G 這類小機器。

## 一鍵安裝

推薦使用 `git clone` 部署，後續升級會更方便。

```bash
cd /opt
git clone https://github.com/wwintj/vps-traffic-panel.git vps-traffic-panel-src
cd /opt/vps-traffic-panel-src
chmod +x scripts/*.sh
sudo ./scripts/install.sh
```

安裝腳本會自動完成：

- 檢測並處理舊版本安裝
- 自動檢測網卡
- 自動檢測可用 SSL 證書
- 建立 Python 虛擬環境
- 安裝依賴
- 生成 `.env` 配置
- 建立並啟動 systemd 服務

安裝完成後，終端會顯示面板訪問地址、服務狀態命令和日誌命令。

## 一鍵升級

已經部署過的 VPS，直接執行：

```bash
cd /opt/vps-traffic-panel-src
git fetch origin
git reset --hard origin/main
chmod +x scripts/*.sh
sudo ./scripts/update.sh
```

升級腳本會保留你的 `.env`、資料庫和面板設定，只更新程式檔案並重啟服務。

## 一鍵卸載

```bash
cd /opt/vps-traffic-panel
sudo ./scripts/uninstall.sh
```

卸載腳本會停止並移除 systemd 服務。若需要完全刪除檔案，可以再手動刪除安裝目錄。

## 常用管理命令

```bash
systemctl status vps-traffic-panel
systemctl restart vps-traffic-panel
journalctl -u vps-traffic-panel -f
```

## 面板功能

- 即時下載 / 上傳速度
- 今日流量與本期流量
- 自訂每月流量重置日期
- 一鍵重置流量統計
- 總下載、總上傳與統計起點
- 最近 24 小時趨勢
- 最近 30 天趨勢
- 最近 12 個月趨勢
- CPU、記憶體、磁碟使用率進度條
- VPS 系統版本、Kernel、IP、運行時間
- 修改登入用戶名與密碼
- 修改面板標題與副標題
- 自動檢測網卡離線狀態
- Basic Auth 登入保護

## 預設配置

安裝後的主要配置位於：

```bash
/opt/vps-traffic-panel/.env
```

常見配置項：

```ini
HOST=0.0.0.0
PORT=8088
AUTH_USERNAME=admin
AUTH_PASSWORD=your_password
PANEL_TITLE="VPS 監控流量面板"
PANEL_SUBTITLE="Tim哥在三更半夜改好的"
INTERFACE=
MONTH_RESET_DAY=1
SSL_ENABLED=0
```

通常不需要手動修改。登入資訊、面板文字、流量重置日都可以直接在面板裡修改。

## SSL 說明

安裝腳本會嘗試自動搜尋 VPS 上已有的證書，例如：

- `/root/cert.crt`
- `/root/private.key`
- acme.sh 證書目錄
- x-ui / 3x-ui 使用過的證書路徑
- Nginx 配置中引用的證書路徑

如果檢測到可用證書，面板會盡量直接使用 HTTPS 啟動。若你的 VPS 前面已經有 Nginx 反向代理，也可以繼續用 Nginx 接管 HTTPS。

## Nginx 反向代理示例

如果你想用域名訪問，可以讓 Nginx 轉發到面板端口：

```nginx
server {
    listen 80;
    server_name monitor.example.com;

    location / {
        proxy_pass http://127.0.0.1:8088;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

重新載入 Nginx：

```bash
nginx -t
systemctl reload nginx
```

## 常見問題

### 面板打不開

先看服務是否正在運行：

```bash
systemctl status vps-traffic-panel
```

再看日誌：

```bash
journalctl -u vps-traffic-panel -f
```

### 顯示 502 Bad Gateway

通常是 Nginx 還在，但後端面板服務沒有正常啟動。執行：

```bash
systemctl restart vps-traffic-panel
systemctl status vps-traffic-panel
```

### 流量一直是 0

面板會自動偵測預設網卡。如果你的 VPS 網卡比較特殊，可以手動查看：

```bash
ip route
ip a
```

然後在 `.env` 中指定：

```ini
INTERFACE=eth0
```

重啟服務：

```bash
systemctl restart vps-traffic-panel
```

### 忘記密碼

優先在面板裡修改。若已經無法登入，可以直接修改：

```bash
nano /opt/vps-traffic-panel/.env
```

改完後重啟：

```bash
systemctl restart vps-traffic-panel
```

## 技術棧

- FastAPI
- Uvicorn
- SQLite
- ECharts
- systemd
- Bash installer
