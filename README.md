# VPS Traffic Panel

一个极度轻量、安全、无侵入的 VPS 流量监控与展示面板。由 FastAPI 和 ECharts 驱动，数据采集直接读取系统内核态文件 `/proc/net/dev`。完美避开频繁 I/O 与高 CPU 占用，极度适合小内存 VPS（如 1C1G、2C12G）长期驻留。

## 功能列表

- **超轻量采集**：无锁读取系统网络状态，资源占用趋近于零。
- **精确防抖防漂移**：处理网卡重置、系统重启引起的计数器归零；按真实时间属性进行内存分桶缓存落盘，降低跨时段统计漂移。
- **持久化存储**：开启 SQLite WAL 与 busy_timeout，降低读写冲突概率，适合低并发 VPS 监控面板。
- **完善 API**：提供 `/api/realtime`、`/api/summary`、`/api/hourly`、`/api/daily`、`/api/monthly`、`/api/system`。
- **实时监控**：深色 Dashboard，支持 24 小时 / 30 天 / 12 个月趋势图，实时网卡离线提示。

## 安全建议：127.0.0.1 vs 0.0.0.0

本项目提供 Basic Auth 认证。安装时建议优先选择：

- **监听 127.0.0.1（强烈推荐）**：面板仅允许本机访问，需要搭配 Nginx 反向代理对外暴露。这是更安全的生产级做法。
- **监听 0.0.0.0（有风险）**：面板会直接暴露到公网，可通过 IP:端口 访问。只建议在有云防火墙安全组、内网 VPN 或其他访问控制保护下使用，并必须使用强密码。

## 部署方法

### 1. 源码一键安装

建议通过 git clone 获取源码，这样可以支持后续使用 `update.sh` 更新。

```bash
git clone https://github.com/your-username/vps-traffic-panel.git /opt/vps-traffic-panel-src
cd /opt/vps-traffic-panel-src
chmod +x scripts/*.sh
sudo ./scripts/install.sh
```

脚本将自动检测环境、检查端口占用、配置 Python 虚拟环境、配置 systemd 服务并启动。

### 2. Nginx 反向代理示例

如果安装时选择 `127.0.0.1`，端口选择 `8088`，可以在 Nginx 中加入：

```nginx
server {
    listen 80;
    server_name monitor.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8088;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
```

测试配置并重新加载：

```bash
nginx -t
systemctl reload nginx
```

## systemd 管理命令

```bash
systemctl status vps-traffic-panel
systemctl restart vps-traffic-panel
journalctl -u vps-traffic-panel -f
```

## 常见问题排查

### 面板数据全部为 0，且左上角圆点为红色

说明系统内找不到指定网卡。运行：

```bash
ip a
```

找到公网网卡名称，例如 `eth0` 或 `ens3`，然后修改安装目录下的 `.env`：

```ini
INTERFACE=ens3
```

重启服务：

```bash
systemctl restart vps-traffic-panel
```

### 忘记密码

修改安装目录下的 `.env` 文件：

```ini
AUTH_PASSWORD=your_new_password
```

然后重启：

```bash
systemctl restart vps-traffic-panel
```

## 卸载与更新

卸载：

```bash
sudo ./scripts/uninstall.sh
```

更新：

```bash
sudo ./scripts/update.sh
```

## 自检命令

确认 README 没有 Markdown 链接污染：

```bash
grep -nE '\]\(https?://' README.md
grep -nE 'git clone \[|proxy_pass \[' README.md
```
