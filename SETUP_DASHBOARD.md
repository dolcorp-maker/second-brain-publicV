# Setting Up the Web Dashboard

The dashboard runs locally at `http://localhost:8080` out of the box.  
This guide makes it accessible from anywhere at `https://yourname.duckdns.org` with a real SSL certificate.

Everything here is free.

---

## What you need

- A machine with a static local IP (set a DHCP reservation in your router)
- Port 443 accessible from the internet (one router config change)
- About 20 minutes

---

## Step 1 — Get a free domain (DuckDNS)

DuckDNS gives you a free subdomain that always points to your home IP.

1. Go to [duckdns.org](https://duckdns.org)
2. Sign in with GitHub or Google
3. Create a subdomain — pick anything, e.g. `mysecondbrainn`
4. Copy your **token** from the top of the page

Add to your `.env`:
```bash
DUCKDNS_TOKEN=your-token-here
DUCKDNS_DOMAIN=mysecondbrainn   # just the subdomain, not the full URL
```

Set up the auto-updater so DuckDNS always has your current home IP:

```bash
# Create the update script
mkdir -p ~/duckdns
cat > ~/duckdns/duck.sh << 'EOF'
echo url="https://www.duckdns.org/update?domains=$DUCKDNS_DOMAIN&token=$DUCKDNS_TOKEN&ip=" | curl -k -o ~/duckdns/duck.log -K -
EOF

# Load your env vars and make it executable
chmod +x ~/duckdns/duck.sh

# Add to cron — runs every 5 minutes
(crontab -l 2>/dev/null; echo "*/5 * * * * source /home/master/second-brain-bot/.env && ~/duckdns/duck.sh >/dev/null 2>&1") | crontab -
```

Test it:
```bash
source /home/master/second-brain-bot/.env && ~/duckdns/duck.sh
cat ~/duckdns/duck.log   # should print "OK"
```

---

## Step 2 — Forward port 443 on your router

Every router is different, but the steps are the same:

1. Open your router admin panel — usually `http://192.168.1.1`
2. Find **Port Forwarding** (sometimes under Advanced, Firewall, or NAT)
3. Add a rule:
   - External port: `443`
   - Internal IP: your machine's local IP (e.g. `192.168.1.204`)
   - Internal port: `443`
   - Protocol: `TCP`
4. Save

Test from your phone (on mobile data, not wifi):
```
https://mysecondbrainn.duckdns.org
```
You should get a connection error or nginx page — that means the port is open. SSL comes next.

---

## Step 3 — Install nginx

```bash
sudo apt update
sudo apt install nginx -y
sudo systemctl enable nginx
```

---

## Step 4 — Get an SSL certificate (Let's Encrypt)

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d mysecondbrainn.duckdns.org
```

Follow the prompts — enter your email, agree to terms. Certbot will automatically configure nginx for HTTPS.

Test auto-renewal:
```bash
sudo certbot renew --dry-run
```

---

## Step 5 — Configure nginx as a reverse proxy

Replace the default nginx config with this:

```bash
sudo nano /etc/nginx/sites-available/secondbrain
```

Paste:
```nginx
server {
    listen 80;
    server_name mysecondbrainn.duckdns.org;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name mysecondbrainn.duckdns.org;

    ssl_certificate /etc/letsencrypt/live/mysecondbrainn.duckdns.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mysecondbrainn.duckdns.org/privkey.pem;

    # Pass real IP to Flask
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Host $host;

    location / {
        proxy_pass http://127.0.0.1:8080;
    }
}
```

Enable it:
```bash
sudo ln -s /etc/nginx/sites-available/secondbrain /etc/nginx/sites-enabled/
sudo nginx -t        # check for errors
sudo systemctl reload nginx
```

---

## Step 6 — Set your dashboard password

In your `.env`:
```bash
DASHBOARD_PASSWORD=choose-something-strong
FLASK_SECRET_KEY=   # generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
```

Restart the dashboard service:
```bash
sudo systemctl restart secondbrain-dashboard
```

---

## Step 7 — Test it

Open a browser and go to:
```
https://mysecondbrainn.duckdns.org
```

You should see the login screen. Enter your `DASHBOARD_PASSWORD`. Done.

---

## Optional: install as a systemd service

If you haven't already, make the dashboard start on boot:

```bash
sudo systemctl enable secondbrain-dashboard
```

---

## Troubleshooting

**502 Bad Gateway**  
Flask isn't running. Check: `sudo systemctl status secondbrain-dashboard`

**ERR_CONNECTION_REFUSED from outside**  
Port 443 isn't forwarded. Double-check your router config.

**Certificate errors**  
Your DuckDNS domain isn't pointing to your IP yet. Check: `cat ~/duckdns/duck.log` and wait a few minutes.

**Login loop / session not persisting**  
`FLASK_SECRET_KEY` is not set or keeps changing. Set a fixed value in `.env`.

---

## Security notes

- The dashboard is protected by password login — don't reuse a password you use elsewhere
- Your bot only responds to your `ALLOWED_USER_ID` — even if someone finds the Telegram bot, it ignores them
- The dashboard shows your tasks and thoughts — treat the password accordingly
- For maximum security, consider Cloudflare Tunnel instead of direct port forwarding (hides your home IP entirely) — but that's optional
