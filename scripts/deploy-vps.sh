#!/usr/bin/env bash
# =============================================================================
# Duty Logger — VPS Deploy Script (Ubuntu 22.04+)
#
# Usage:
#   1. SSH vào VPS với quyền root
#   2. Copy hoặc clone code lên /opt/duty-logger (hoặc dùng git clone)
#   3. chmod +x deploy-vps.sh && ./deploy-vps.sh
# =============================================================================
set -euo pipefail

INSTALL_DIR="/opt/duty-logger"
SERVICE_USER="dutybot"
DOMAIN=""

cyan()   { echo -e "\033[36m$*\033[0m"; }
green()  { echo -e "\033[32m$*\033[0m"; }
yellow() { echo -e "\033[33m$*\033[0m"; }
red()    { echo -e "\033[31m$*\033[0m"; }

# ------ Yêu cầu root ------
if [[ $EUID -ne 0 ]]; then
   red "Script này phải chạy với quyền root. Thử: sudo $0"
   exit 1
fi

cyan "═══════════════════════════════════════════════════"
cyan "  Duty Logger — VPS Deploy"
cyan "═══════════════════════════════════════════════════"

# ------ Step 1: Update system + install Docker ------
yellow "[1/7] Update system + install dependencies…"
apt-get update -qq
apt-get install -y -qq curl git ca-certificates gnupg ufw

if ! command -v docker &> /dev/null; then
    yellow "[1.1] Installing Docker…"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    green "✓ Docker installed."
fi

# ------ Step 2: Setup install dir ------
yellow "[2/7] Setup install directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

# Nếu chưa có code, hỏi git URL
if [[ ! -f "$INSTALL_DIR/docker-compose.yml" ]]; then
    yellow "Code chưa có ở $INSTALL_DIR."
    read -rp "Git clone URL (hoặc Enter để skip — bạn tự rsync code): " GIT_URL
    if [[ -n "$GIT_URL" ]]; then
        git clone "$GIT_URL" "$INSTALL_DIR"
    else
        red "Skip clone. Vui lòng copy code lên $INSTALL_DIR rồi chạy lại script."
        exit 1
    fi
fi

cd "$INSTALL_DIR"

# ------ Step 3: Generate .env ------
yellow "[3/7] Generate .env file…"
if [[ ! -f .env ]]; then
    if [[ ! -f .env.example ]]; then
        red ".env.example không tồn tại — không thể generate .env"
        exit 1
    fi

    SECRET_KEY=$(openssl rand -hex 32)
    FERNET_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || openssl rand -base64 32)
    HMAC_SECRET=$(openssl rand -hex 32)
    DB_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)
    REDIS_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)

    cp .env.example .env
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" .env
    sed -i "s|^FERNET_KEY=.*|FERNET_KEY=$FERNET_KEY|" .env
    sed -i "s|^HMAC_SECRET=.*|HMAC_SECRET=$HMAC_SECRET|" .env
    sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=$DB_PASSWORD|" .env
    sed -i "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$REDIS_PASSWORD|" .env
    sed -i "s|^DEBUG=.*|DEBUG=False|" .env

    green "✓ .env created với secrets random."
    yellow "  → Bạn cần edit .env để điền:"
    yellow "      DISCORD_BOT_TOKEN, DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET"
    yellow "      DISCORD_REDIRECT_URI, ALLOWED_ORIGINS"
else
    green "✓ .env đã tồn tại — skip generate."
fi

# ------ Step 4: Domain setup (optional) ------
yellow "[4/7] Domain setup"
read -rp "Bạn có domain trỏ về VPS này? (vd: duty.example.com — Enter để skip): " DOMAIN
if [[ -n "$DOMAIN" ]]; then
    sed -i "s|^DISCORD_REDIRECT_URI=.*|DISCORD_REDIRECT_URI=https://$DOMAIN/auth/callback|" .env
    sed -i "s|^ALLOWED_ORIGINS=.*|ALLOWED_ORIGINS=https://$DOMAIN|" .env
    green "✓ Domain $DOMAIN đã set vào .env"
fi

# ------ Step 5: Firewall ------
yellow "[5/7] Configure firewall (ufw)…"
ufw allow 22/tcp comment 'SSH' >/dev/null
ufw allow 80/tcp comment 'HTTP' >/dev/null
ufw allow 443/tcp comment 'HTTPS' >/dev/null
ufw --force enable >/dev/null
green "✓ Firewall: 22, 80, 443 open."

# ------ Step 6: Build + start ------
yellow "[6/7] Build Docker images + start services…"
docker compose pull -q || true
docker compose build -q
docker compose up -d
sleep 5

# Run migrations
yellow "[6.1] Run alembic migrations…"
docker compose exec -T bot alembic upgrade head || yellow "  (Migration sẽ chạy khi bot lần đầu start)"

green "✓ Services started."

# ------ Step 7: Nginx + SSL ------
yellow "[7/7] Setup Nginx + Let's Encrypt SSL"
if [[ -n "$DOMAIN" ]]; then
    apt-get install -y -qq nginx certbot python3-certbot-nginx

    # Copy nginx config
    if [[ -f scripts/nginx-prod.conf ]]; then
        sed "s|YOUR_DOMAIN|$DOMAIN|g" scripts/nginx-prod.conf > /etc/nginx/sites-available/duty-logger
        ln -sf /etc/nginx/sites-available/duty-logger /etc/nginx/sites-enabled/duty-logger
        rm -f /etc/nginx/sites-enabled/default
        nginx -t && systemctl reload nginx

        # Issue SSL cert
        yellow "[7.1] Issue Let's Encrypt cert…"
        read -rp "Email cho Let's Encrypt notifications: " EMAIL
        if [[ -n "$EMAIL" ]]; then
            certbot --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive --redirect || \
                red "  Cert issue thất bại — kiểm tra DNS A record của $DOMAIN trỏ về VPS này."
        fi
    fi
else
    yellow "  Skip Nginx — không có domain. Web tạm chạy http://VPS_IP:8000"
fi

# ------ Summary ------
echo
green "═══════════════════════════════════════════════════"
green "  ✓ Deploy hoàn tất!"
green "═══════════════════════════════════════════════════"
echo
cyan "Next steps:"
echo "  1. Edit .env để điền Discord credentials:"
echo "     nano $INSTALL_DIR/.env"
echo
echo "  2. Restart services sau khi edit .env:"
echo "     cd $INSTALL_DIR && docker compose restart"
echo
echo "  3. Check status:"
echo "     docker compose ps"
echo "     docker compose logs -f bot"
echo
echo "  4. Discord Developer Portal → OAuth2 → Redirects → thêm:"
if [[ -n "$DOMAIN" ]]; then
    echo "     https://$DOMAIN/auth/callback"
else
    echo "     http://VPS_IP:8000/auth/callback"
fi
echo
echo "  5. Setup backup cron (optional):"
echo "     (crontab -l 2>/dev/null; echo '0 3 * * * $INSTALL_DIR/scripts/backup_db.sh') | crontab -"
echo
green "Bot và web giờ chạy 24/24, auto-restart khi crash hoặc reboot."
