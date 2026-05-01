# Deploy — Duty Logger (VPS Ubuntu)

## Yêu cầu hệ thống
- Ubuntu 22.04 LTS
- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- Nginx
- Tối thiểu 1GB RAM, 10GB disk

## Cài đặt dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Python
sudo apt install python3.11 python3.11-venv python3-pip -y

# PostgreSQL
sudo apt install postgresql postgresql-contrib -y

# Redis
sudo apt install redis-server -y

# Nginx
sudo apt install nginx -y

# Tesseract (backup OCR)
sudo apt install tesseract-ocr tesseract-ocr-vie -y

# Build tools cho easyocr
sudo apt install libgl1 libglib2.0-0 -y
```

## Setup PostgreSQL

```bash
sudo -u postgres psql
CREATE USER duty_logger WITH PASSWORD 'STRONG_PASSWORD_HERE';
CREATE DATABASE duty_logger_db OWNER duty_logger;
GRANT ALL PRIVILEGES ON DATABASE duty_logger_db TO duty_logger;
\q
```

## Cài đặt dự án

```bash
cd /opt
sudo git clone <repo_url> duty-logger
sudo chown -R $USER:$USER duty-logger
cd duty-logger

python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env  # Điền các biến môi trường

# Chạy migration
alembic upgrade head
```

## Systemd service — Bot

```ini
# /etc/systemd/system/duty-bot.service
[Unit]
Description=Discord Duty Logger Bot
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/duty-logger
Environment=PATH=/opt/duty-logger/venv/bin
ExecStart=/opt/duty-logger/venv/bin/python bot/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

## Systemd service — Web Dashboard

```ini
# /etc/systemd/system/duty-web.service
[Unit]
Description=Duty Logger Web Dashboard
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/duty-logger
Environment=PATH=/opt/duty-logger/venv/bin
ExecStart=/opt/duty-logger/venv/bin/uvicorn web.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Kích hoạt cả hai service
sudo systemctl daemon-reload
sudo systemctl enable duty-bot duty-web
sudo systemctl start duty-bot duty-web
sudo systemctl status duty-bot duty-web
```

## Backup tự động hàng ngày

```bash
# scripts/backup_db.sh
#!/bin/bash
BACKUP_DIR="/opt/backups/duty-logger"
DATE=$(date +%Y%m%d_%H%M%S)
DB_NAME="duty_logger_db"
DB_USER="duty_logger"
ENCRYPT_KEY="your-fernet-key"

mkdir -p $BACKUP_DIR

# Dump database
pg_dump -U $DB_USER $DB_NAME | gzip > $BACKUP_DIR/backup_$DATE.sql.gz

# Xóa backup cũ hơn 30 ngày
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete

echo "Backup xong: backup_$DATE.sql.gz"
```

```bash
# Cài cron job chạy lúc 2AM mỗi ngày
crontab -e
0 2 * * * /opt/duty-logger/scripts/backup_db.sh >> /var/log/duty-backup.log 2>&1
```

## Pre-deploy Checklist

```
[ ] .env đã điền đầy đủ, không có giá trị mặc định nào còn để trống
[ ] .env KHÔNG được commit lên git
[ ] SECRET_KEY đủ mạnh (>= 32 ký tự random)
[ ] DB password mạnh
[ ] HTTPS đã bật, certificate hợp lệ
[ ] Redis đặt password (requirepass trong redis.conf)
[ ] PostgreSQL chỉ listen localhost
[ ] Firewall chỉ mở port 443, 22 (SSH)
[ ] Systemd service đã enable và running
[ ] Backup script đã chạy thử thành công
[ ] Alembic migration đã chạy
[ ] Bot đã được invite vào server với đúng permissions
[ ] /setup đã chạy trên Discord để cấu hình role + channel
[ ] Test /log upload với ảnh mẫu
[ ] Test /top day/week/month/quarter
[ ] Test /export csv + excel
[ ] Audit log ghi nhận được hành động
```