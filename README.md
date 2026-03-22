# DHCP-GUARD
Vibe coded (and heavly human edited) Web-Based Management for ISC-DHCP-Server

## History
ISC has moved to KEA DHCP and has their own UI, but didn't really meet what I needed and I still had multiple installations running off isc-dhcp-server. I didn't like [Akkadius/glass-isc-dhcp](https://github.com/Akkadius/glass-isc-dhcp) and so I decided to make use of AI to vibe code a simple UI for what I had. It was painful, despite having plenty of ideas, trying to get the AI to remember what it did right previously and not mess it up was unbelievably painful! In anycase, after 4 days of battling Gemini and constantly remininding what code worked and what didn't and arguing with it on its logic, we finally managed to get this out.

I call it v1.08 but its more like 1.188 after all the back and forth.

## Description
DHCP Guard is a modern, lightweight FastAPI application designed to provide a real-time dashboard and management interface for the Linux isc-dhcp-server. 

It features live log streaming via WebSockets, device latency monitoring, and secure static host registration.

## Features
+ Live Log Streaming: Real-time visibility into DHCP requests, acknowledges, and releases using WebSockets.
+ Device Monitoring: Automatic ping scheduler tracks device uptime and latency over a 24-hour period.
+ Static Reservations: Easily add or delete static hosts through the UI; changes are automatically written to your .conf files.
+ Multi-Subnet Support: Automatically parses your DHCP configuration to categorize devices by network segment.
+ Secure Access: Built-in authentication system with password hashing (Bcrypt).
+ Service Control: Start, stop, and restart the DHCP service directly from the browser.
    
## Pre Requisites
+ Linux Server (Ubuntu, Debian, etc)
+ ISC-DHCP-Server (obviously)
+ Apache or NGINX webserver
+ Python3 and Python3 tools (pip3)
+ RSyslog with a config entry to log DHCP logs to /var/log/dhcpd.log

## Installation
### Setting up RSyslog
```
echo "local7.* /var/log/dhcpd.log" > /etc/rsyslog.d/dhcpd.log
echo "log-facility local7;" >> /etc/dhcp/dhcpd.conf
systemctl restart rsyslog
systemctl restart isc-dhcp-server
```

### Setting up Logrotate
+ Edit /etc/logrotate.d/dhcpd
+ Add the following and save the file
```
/var/log/dhcpd.log {
    rotate 7
    daily
    missingok
    notifempty
    compress
    delaycompress
    sharedscripts
    postrotate
        /usr/lib/rsyslog/rsyslog-rotate
    endscript
}
```

### Clone the repo into /opt
``cd /opt; git clone https://github.com/markdesilva/DHCP-GUARD.git``

### Preparing the Python environment
```
cd /opt/dhcp-guard
apt install python3.10-venv
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn httpx uvicorn websockets aiosqlite pydantic install "bcrypt==4.0.1"
```

### Webserver config
#### Apache
+ Enable the mods (if not already enabled)
```
a2enmod ssl proxy_wstunnel rewrite proxy proxy_http rewrite headers
systemctl restart apache2
```
+ Create the config file /etc/apache2/sites-available/dhcp-guard-ssl.conf
+ Add the following and save the file
```
<VirtualHost *:443>
    ServerName your.server.fqdn
    DocumentRoot /opt/dhcp-guard

    SSLEngine on
    SSLCertificateFile /path/to/your/certificate.crt
    SSLCertificateKeyFile /path/to/your/private.key
    # If using a CA bundle, uncomment below:
    # SSLCertificateChainFile /path/to/your/chainfile.pem

    <Directory /opt/dhcp-guard>
        Options FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>

    <Proxy *>
        Require all granted
    </Proxy>

    ProxyPreserveHost On
    RewriteEngine On

    RewriteCond %{HTTP:Upgrade} websocket [NC]
    RewriteCond %{Connection} upgrade [NC]
    RewriteRule ^/ws/logs(.*) ws://127.0.0.1:8000/ws/logs$1 [P,L]

    ProxyPass /ws/logs ws://127.0.0.1:8000/ws/logs
    ProxyPassReverse /ws/logs ws://127.0.0.1:8000/ws/logs

    ProxyPass /api http://127.0.0.1:8000/api
    ProxyPassReverse /api http://127.0.0.1:8000/api

    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    # Security Headers (Optional but Recommended)
    Header always set Strict-Transport-Security "max-age=63072000"
</VirtualHost>
```

### Creating a startup service
+ Edit /etc/systemd/system/dhcp-guard.service
+ Add the following and save the file
```
[Unit]
Description=DHCP Guard Web UI Backend
After=network.target isc-dhcp-server.service

[Service]
User=root
WorkingDirectory=/opt/dhcp-guard
ExecStart=/opt/dhcp-guard/venv/bin/python3 main.py
Restart=always

[Install]
WantedBy=multi-user.target
```
+ Restart the systemd daemon
```
systemctl daemon-reload
systemctl enable dhcp-guard
systemctl start dhcp-guard
```


TO BE CONTINUED
