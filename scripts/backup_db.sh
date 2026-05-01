#!/bin/bash
# backup_db.sh — Backup PostgreSQL hàng ngày, mã hoá bằng GPG
# Crontab: 0 2 * * * /opt/duty-logger/scripts/backup_db.sh >> /var/log/duty-backup.log 2>&1

set -euo pipefail

BACKUP_DIR="/srv/duty-logger/backups"
DATE=$(date +%Y%m%d_%H%M%S)
FILENAME="duty_logger_${DATE}.sql.gz"
ENCRYPTED="${FILENAME}.gpg"
RETENTION_DAYS=7

# Load env
source /opt/duty-logger/.env 2>/dev/null || true

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Bắt đầu backup..."

# Dump + nén
PGPASSWORD="$DB_PASSWORD" pg_dump \
    -h "$DB_HOST" -p "$DB_PORT" \
    -U "$DB_USER" "$DB_NAME" \
    | gzip > "${BACKUP_DIR}/${FILENAME}"

# Mã hoá bằng GPG symmetric (dùng HMAC_SECRET làm passphrase)
echo "$HMAC_SECRET" | gpg --batch --yes --passphrase-fd 0 \
    --symmetric --cipher-algo AES256 \
    --output "${BACKUP_DIR}/${ENCRYPTED}" \
    "${BACKUP_DIR}/${FILENAME}"

# Xóa file chưa mã hoá
rm "${BACKUP_DIR}/${FILENAME}"

# Dọn backup cũ hơn RETENTION_DAYS ngày
find "$BACKUP_DIR" -name "*.gpg" -mtime "+${RETENTION_DAYS}" -delete

echo "[$(date)] Backup hoàn thành: ${ENCRYPTED}"
echo "[$(date)] Dung lượng: $(du -sh "${BACKUP_DIR}/${ENCRYPTED}" | cut -f1)"
