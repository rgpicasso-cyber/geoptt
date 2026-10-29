# GeoPTT Production Deployment Guide

> Target: Ubuntu 22.04 / 24.04 VPS (IP `163.176.229.20`), user `ubuntu`, SSH key only.

---

## 1. Provision the VPS

```bash
# On your local machine
ssh ubuntu@163.176.229.20
```

### 1.1 System packages & user

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y python3.12 python3.12-venv git nginx certbot python3-certbot-nginx ufw fail2ban unattended-upgrades

# Create dedicated app user
sudo useradd -m -s /bin/bash geoptt
sudo usermod -aG sudo geoptt
```

### 1.2 Firewall

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

---

## 2. Clone Repository

```bash
cd /opt
sudo git clone https://github.com/<your-org>/geoptt.git
sudo chown -R geoptt:geoptt /opt/geoptt
cd /opt/geoptt
```

> **Important**: the repo must **not** contain any secrets (`*.env`, `serviceAccountKey.json`, APNs `.p8` keys).

---

## 3. Python Virtualenv & Dependencies

```bash
sudo -u geoptt python3.12 -m venv .venv
sudo -u geoptt .venv/bin/pip install --upgrade pip
sudo -u geoptt .venv/bin/pip install -r backend/requirements.txt   # or pyproject.toml via pip install -e backend/
```

---

## 4. Configure Secrets (`.env`)

Create `/opt/geoptt/.env` **as the `geoptt` user** with **600** permissions.

```bash
sudo -u geoptt tee /opt/geoptt/.env > /dev/null <<'EOF'
ENV=production
DEBUG=false
DATABASE_URL=postgresql+asyncpg://geoptt:STRONG_DB_PASSWORD@127.0.0.1:5432/geoptt
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
API_PREFIX=/api/v1
FCM_ENABLED=true
FCM_CREDENTIALS_PATH=/opt/geoptt/secrets/serviceAccountKey.json
APNS_ENABLED=true
APNS_USE_SANDBOX=false
APNS_AUTH_KEY_PATH=/opt/geoptt/secrets/AuthKey_XXXXXXXX.p8
APNS_KEY_ID=XXXXXXXX
APNS_TEAM_ID=YYYYYYYY
APNS_BUNDLE_ID=com.geoptt
CORS_ORIGINS=https://geoptt.example.com
LOG_LEVEL=INFO
LOG_JSON=true
EOF
sudo chmod 600 /opt/geoptt/.env
```

> **Never** commit this file. Keep it only on the server.

---

## 5. Place FCM / APNs Credentials

```bash
sudo mkdir -p /opt/geoptt/secrets
sudo chown geoptt:geoptt /opt/geoptt/secrets
sudo chmod 700 /opt/geoptt/secrets

# Copy your files (from your local machine)
# scp serviceAccountKey.json ubuntu@163.176.229.20:/opt/geoptt/secrets/
# scp AuthKey_XXXXXXXX.p8 ubuntu@163.176.229.20:/opt/geoptt/secrets/

sudo chown geoptt:geoptt /opt/geoptt/secrets/*
sudo chmod 400 /opt/geoptt/secrets/*
```

---

## 6. Database Setup

```bash
sudo bash deploy/setup_db.sh
```

> Ensure `DB_PASSWORD` environment variable is exported before running, or edit the script to embed the password.

---

## 6.1 Run Alembic Migrations

```bash
cd /opt/geoptt
sudo -u geoptt .venv/bin/alembic upgrade head
```

---

## 7. Install Systemd Service

```bash
sudo cp deploy/geoptt.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now geoptt
sudo systemctl status geoptt
```

---

## 8. Nginx + TLS (Certbot)

```bash
sudo cp deploy/nginx_geoptt.conf /etc/nginx/sites-available/geoptt
sudo ln -sf /etc/nginx/sites-available/geoptt /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Obtain TLS cert (run once)
sudo certbot --nginx -d geoptt.example.com --non-interactive --agree-tos -m ops@geoptt.example.com
```

Certbot will edit the Nginx config to add the SSL lines automatically.

---

## 9. Verify End‑to‑End

```bash
# Health check
curl -k https://geoptt.example.com/health
# Expected: {"status":"ok"}

# WebSocket test (requires token)
# Use a small python script or wscat with a valid JWT.
```

---

## 10. Post‑Deploy Monitoring

```bash
# Logs
journalctl -u geoptt -f
tail -f /var/log/nginx/access.log /var/log/nginx/error.log

# Enable automatic security updates
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

---

## 11. Rollback Procedure

1. `git -C /opt/geoptt checkout <previous-tag>`
2. `sudo -u geoptt .venv/bin/pip install -r backend/requirements.txt`
3. `sudo -u geoptt .venv/bin/alembic downgrade -1` (if DB schema changed)
4. `sudo systemctl restart geoptt`
5. `sudo systemctl reload nginx`

---

## 12. Contacts

| Role | Name | Email |
|------|------|-------|
| Infra Lead | … | infra@geoptt.example.com |
| Backend Lead | … | backend@geoptt.example.com |
| Mobile Lead | … | mobile@geoptt.example.com |

---

*Document version 1.0 – keep this file in `docs/DEPLOY_GUIDE.md` and update on every infra change.*