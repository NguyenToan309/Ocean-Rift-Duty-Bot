# 🆓 Deploy Duty Logger lên Oracle Cloud Free Tier (HOÀN TOÀN MIỄN PHÍ VĨNH VIỄN)

## 🎁 Bạn nhận được

| Resource | Free Tier |
|---|---|
| 💻 VM ARM Ampere A1 | **4 OCPU + 24GB RAM** (lớn hơn VPS $20/tháng) |
| 💾 Storage | 200GB SSD |
| 🌐 Bandwidth | 10TB/tháng outbound |
| 📛 IP Address | 1 IPv4 public |
| 💰 Cost | **$0 vĩnh viễn** |

> ⚠️ Cần **thẻ Visa/Mastercard quốc tế** để verify (KHÔNG bị trừ tiền — chỉ block $0 hoặc $1 rồi refund).

---

## 📋 Tổng quan các bước

1. Tạo Oracle Cloud account
2. Tạo VM ARM Ampere A1 (4 OCPU + 24GB RAM)
3. Setup Network (open ports 22, 80, 443)
4. SSH vào VM
5. Tạo free domain qua DuckDNS
6. Chạy script deploy tự động
7. Setup SSL Let's Encrypt
8. Update Discord OAuth redirect

⏱️ Thời gian: ~30-45 phút

---

## 🅰️ BƯỚC 1: Tạo Oracle Cloud Account

### 1.1. Đăng ký

1. Mở https://signup.oraclecloud.com
2. Điền thông tin:
   - **Country**: Vietnam
   - **First name / Last name**: tên thật (cần khớp với CC)
   - **Email**: dùng email thật, sẽ verify
3. Verify email
4. Điền address (cần khớp CC)
5. **Verify card**: nhập thông tin thẻ Visa/Mastercard
   - Oracle sẽ block $0 hoặc $1 USD để verify (auto refund)
6. Chọn **Home Region**:
   - **Tokyo (ap-tokyo-1)** ⭐ — ping VN ~50ms, ARM thường còn quota
   - **Singapore (ap-singapore-1)** — ping ~30ms, hay full quota
   - **Seoul (ap-seoul-1)** — alternative
   - ⚠️ **Home Region không thể đổi** — chọn kỹ
7. Submit → đợi verify ~1-5 phút
8. Đăng nhập tại https://cloud.oracle.com

---

## 🅱️ BƯỚC 2: Tạo VM ARM Ampere A1

### 2.1. Vào Compute → Instances

1. Top-left menu (☰) → **Compute** → **Instances**
2. Click **Create instance**

### 2.2. Cấu hình instance

| Field | Giá trị |
|---|---|
| **Name** | `duty-logger` |
| **Compartment** | (default — root) |
| **Placement** | (default availability domain) |

### 2.3. Image — chọn Ubuntu

Click **Edit** ở section **Image and shape** → **Change image**:
- **Image**: **Canonical Ubuntu 22.04**
- Click **Select image**

### 2.4. Shape — chọn ARM Ampere A1

Click **Change shape**:
- **Instance type**: **Virtual machine**
- **Shape series**: **Ampere** (ARM)
- **Shape name**: **VM.Standard.A1.Flex**
- **Number of OCPUs**: **4**
- **Amount of memory (GB)**: **24**

> ⚠️ Nếu thấy "Out of capacity" / "Host capacity" — region đã hết quota. Thử:
> - Đổi Availability Domain (AD-1, AD-2, AD-3) trong cùng region
> - Hoặc tạo instance nhỏ hơn trước (1 OCPU + 6GB) rồi scale up sau
> - Hoặc retry sau vài giờ — quota refresh thường xuyên

### 2.5. Networking

Click **Edit** ở **Networking**:
- **Primary network**: **Create new virtual cloud network** (mặc định)
- **Subnet**: **Create new public subnet**
- ✅ **Assign a public IPv4 address** (BẮT BUỘC tick để có IP public)

### 2.6. SSH Keys

⚠️ **QUAN TRỌNG** — phải lưu SSH key để vào VM sau này.

Click **Add SSH keys**:

**Option A** (recommended): **Generate a key pair for me**
- Click **Save Private Key** → tải file `ssh-key-XXXX.key` về
- Click **Save Public Key**
- ⚠️ **Lưu file private key cẩn thận** — mất là không SSH được nữa

**Option B**: Upload public key của bạn (nếu đã có `~/.ssh/id_rsa.pub`)

### 2.7. Boot volume

Mặc định OK (47-50GB).

### 2.8. Create

- Click **Create** dưới cùng
- Đợi 1-2 phút, instance sẽ status **Running** (chấm xanh)
- **Ghi nhận Public IP** ở section Instance Details (vd: `158.179.20.123`)

---

## 🅲 BƯỚC 3: Open Ports (Firewall)

Oracle có 2 lớp firewall: VCN Security List + iptables. Cần mở cả 2.

### 3.1. Mở port 80, 443 trên VCN

1. Trong instance page → click vào tên Subnet (hyperlink)
2. Click vào **Default Security List for ...**
3. Section **Ingress Rules** → **Add Ingress Rules**
4. Thêm 2 rule:

| Source CIDR | IP Protocol | Destination Port |
|---|---|---|
| 0.0.0.0/0 | TCP | 80 |
| 0.0.0.0/0 | TCP | 443 |

(Port 22 SSH đã có sẵn)

5. Click **Add Ingress Rules**

### 3.2. iptables sẽ fix sau khi SSH vào (script tự lo)

---

## 🆔 BƯỚC 4: SSH vào VM

### Trên Windows (PowerShell)

#### 4.1. Đặt private key file

Copy file `ssh-key-XXXX.key` (download ở Bước 2.6) vào `C:\Users\YOUR_USER\.ssh\oracle.key`.

```powershell
mkdir $env:USERPROFILE\.ssh -ErrorAction SilentlyContinue
Move-Item ~\Downloads\ssh-key-*.key $env:USERPROFILE\.ssh\oracle.key
```

#### 4.2. Set permission

```powershell
icacls "$env:USERPROFILE\.ssh\oracle.key" /inheritance:r /grant:r "$($env:USERNAME):R"
```

#### 4.3. SSH

```powershell
ssh -i $env:USERPROFILE\.ssh\oracle.key ubuntu@YOUR_PUBLIC_IP
```

(Thay `YOUR_PUBLIC_IP` bằng IP ở Bước 2.8)

Lần đầu connect, nhập **yes** để confirm fingerprint.

Nếu thành công → hiện prompt `ubuntu@duty-logger:~$`.

---

## 🌐 BƯỚC 5: Tạo Free Domain qua DuckDNS

Discord OAuth yêu cầu HTTPS → cần domain. **DuckDNS** cho subdomain free vĩnh viễn.

### 5.1. Đăng ký DuckDNS

1. Mở https://www.duckdns.org
2. **Sign in** (login bằng GitHub/Google/Twitter — chọn 1)
3. Sau login → form tạo subdomain:
   - Nhập tên (vd: `oceanrift-duty`) → click **add domain**
   - Subdomain của bạn: `oceanrift-duty.duckdns.org`
4. Trong row vừa tạo:
   - **current ip**: dán IP public của Oracle VM (Bước 2.8)
   - Click **update ip**
5. Ghi nhận **token** (góc trên trang) — dùng để auto-update IP

> ⚠️ Subdomain là duy nhất toàn cầu. Nếu đã bị người khác lấy thì chọn tên khác.

### 5.2. Verify DNS

Trong PowerShell hoặc terminal SSH Oracle:
```bash
nslookup oceanrift-duty.duckdns.org
```
Phải trả về IP Oracle VM của bạn.

---

## 🚀 BƯỚC 6: Deploy Bot + Web (1 command)

Trên VM Oracle (đang SSH):

### 6.1. Clone repo

```bash
sudo mkdir -p /opt/duty-logger
sudo chown $USER:$USER /opt/duty-logger
cd /opt
sudo git clone https://github.com/NguyenToan309/Ocean-Rift-Duty-Bot.git duty-logger
sudo chown -R $USER:$USER /opt/duty-logger
cd /opt/duty-logger
```

### 6.2. Open port iptables (Oracle Ubuntu cần fix này)

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || sudo iptables-save | sudo tee /etc/iptables/rules.v4 >/dev/null
```

### 6.3. Chạy deploy script

```bash
chmod +x scripts/deploy-vps.sh
sudo ./scripts/deploy-vps.sh
```

Script sẽ hỏi:
- **Git clone URL**: bỏ trống (đã clone rồi) → Enter
- **Domain**: nhập `oceanrift-duty.duckdns.org`
- **Email Let's Encrypt**: email của bạn

Script tự động:
- Cài Docker + Docker Compose
- Generate secrets random (SECRET_KEY, FERNET_KEY, HMAC_SECRET, DB/Redis password)
- Set domain vào `.env`
- Build Docker images
- Start services
- Cài Nginx + Let's Encrypt SSL

⏱️ Đợi ~10-15 phút (build EasyOCR nặng).

---

## 🔐 BƯỚC 7: Điền Discord credentials

```bash
nano /opt/duty-logger/.env
```

Tìm các dòng có placeholder và điền:

```env
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_CLIENT_ID=1498049415355830437
DISCORD_CLIENT_SECRET=your_secret_here
```

Lấy từ https://discord.com/developers/applications → app của bạn → **Bot** tab (token), **OAuth2** tab (client_secret).

Save nano: **Ctrl+O** → Enter → **Ctrl+X**.

### 7.1. Restart services

```bash
cd /opt/duty-logger
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart
```

### 7.2. Run migration (lần đầu)

```bash
docker compose exec bot alembic upgrade head
```

---

## 🎯 BƯỚC 8: Update Discord Developer Portal

1. https://discord.com/developers/applications → app của bạn
2. **OAuth2** → **Redirects** → **Add Redirect**
3. Paste: `https://oceanrift-duty.duckdns.org/auth/callback`
4. **Save Changes**

5. **Bot** tab → đảm bảo:
   - ✅ SERVER MEMBERS INTENT
   - ✅ MESSAGE CONTENT INTENT

---

## ✅ BƯỚC 9: Verify

### 9.1. Check services

```bash
docker compose ps
```

Tất cả phải là `Up (healthy)`:
- duty_postgres
- duty_redis
- duty_bot
- duty_web
- duty_nginx

### 9.2. Bot logs

```bash
docker compose logs -f bot
```

Phải thấy:
```
[INFO] Bot đã online: Duty Bot#xxxx
[INFO] Đang phục vụ X guild(s)
```

`Ctrl+C` để thoát logs.

### 9.3. Test web

Mở browser → `https://oceanrift-duty.duckdns.org`

Phải hiện trang login (gradient indigo+purple). Click **Đăng nhập bằng Discord** → OAuth flow → vào dashboard.

---

## 🔁 Tự động giữ DuckDNS IP (nếu Oracle VM đổi IP)

Hiếm khi Oracle đổi IP, nhưng để chắc:

```bash
# Tạo cron job update DuckDNS mỗi 5 phút
TOKEN="your_duckdns_token"
DOMAIN="oceanrift-duty"
echo "*/5 * * * * curl -s 'https://www.duckdns.org/update?domains=${DOMAIN}&token=${TOKEN}&ip=' >/dev/null" | crontab -
```

Thay `your_duckdns_token` bằng token ở Bước 5.1.

---

## 💾 Backup tự động

```bash
(crontab -l 2>/dev/null; echo '0 3 * * * /opt/duty-logger/scripts/backup_db.sh') | crontab -
```

→ Backup PostgreSQL mỗi 3:00 AM.

---

## 🎯 Total cost

| Item | Cost |
|---|---|
| Oracle Cloud VM | **$0 vĩnh viễn** |
| DuckDNS subdomain | **$0 vĩnh viễn** |
| Let's Encrypt SSL | **$0** |
| Outbound bandwidth | $0 (tới 10TB/tháng) |
| **TOTAL** | **$0/tháng** ✅ |

---

## ❗ Troubleshooting

### "Out of capacity" khi tạo Ampere A1

Region thiếu quota. Solutions:
- Thử AD khác (AD-1 → AD-2 → AD-3) trong cùng region
- Tạo instance nhỏ hơn (1 OCPU + 6GB) trước, scale up sau
- Retry sau vài giờ
- Đổi region (nhưng phải tạo account mới)

### "Permission denied (publickey)" khi SSH

```bash
chmod 600 ~/.ssh/oracle.key   # Linux/Mac
# Windows: dùng icacls như Bước 4.2
```

Đảm bảo dùng user `ubuntu` (không phải `root` hay `oracle`).

### Bot không online sau deploy

```bash
docker compose logs bot --tail 50
```

Thường là:
- `DISCORD_BOT_TOKEN` sai → kiểm tra `.env`
- Privileged Intents chưa bật → vào Discord Portal tick

### Web 502 / không truy cập được

```bash
sudo systemctl status nginx
docker compose logs web --tail 50
```

Verify firewall đã mở:
```bash
sudo iptables -L INPUT -n | grep -E "80|443"
curl http://localhost:8000/health   # phải trả {"status":"ok"}
```

### Hết disk

```bash
df -h
docker system prune -a   # xóa images/containers cũ
```
