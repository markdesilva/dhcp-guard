# DHCP-GUARD
Vibe coded (and heavly human edited) Web-Based Management for ISC-DHCP-Server

## History
ISC has moved to KEA DHCP and has their own UI, but didn't really meet what I needed and I still had multiple installations running off isc-dhcp-server. I didn't like [Akkadius/glass-isc-dhcp](https://github.com/Akkadius/glass-isc-dhcp) and so I decided to make use of AI to vibe code a simple UI for what I had. 

Despite having plenty of ideas, trying to get the AI to remember what it did right previously and not mess it up was unbelievably painful! In anycase, after 4 days of battling Gemini and constantly remininding it what code worked and what didn't and arguing with it on its logic and it refusing to accept my code as correct, we finally managed to get this out.

I call it v1.10 but its more like 1.1000 after all the back and forth.

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
You can change the port numbers if you want, configure your webserver and config below accordingly.

#### APACHE
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
+ Link the file to /etc/apache2/sites-enabled
```
cd /etc/apache2/sites-enabled
ln -s ../sites-available/dhcp-guard-ssl.conf .
```

#### NGINX
+ Create the config file /etc/nginx/sites-available/dhcp-guard-ssl
+ Add the following and save the file
```server {
    listen 443 ssl;
    server_name your.server.fqdn;

    root /opt/dhcp-guard;

    # SSL Configuration
    ssl_certificate /path/to/your/certificate.crt;
    ssl_certificate_key /path/to/your/private.key;
    # If you have a chain file, Nginx expects it concatenated inside the .crt file
    # or you can use ssl_trusted_certificate /path/to/your/chainfile.pem;

    # Security Headers
    add_header Strict-Transport-Security "max-age=63072000" always;

    # Global Proxy Settings
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # WebSocket Proxy (Rewrite and ProxyPass replacement)
    location /ws/logs {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
    }

    # API Proxy
    location /api {
        proxy_pass http://127.0.0.1:8000;
    }

    # Main Application Proxy (Root)
    location / {
        proxy_pass http://127.0.0.1:8000;
    }
}
```
+ Link the file to /etc/apache2/sites-enabled
```
cd /etc/nginx/sites-enabled
ln -s ../sites-available/dhcp-guard-ssl .
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

### DHCP Config
We assume the DHCP config in /etc/dhcp/dhcpd.conf is structured reasonably similar to this
```
server-identifier <IP>;
option domain-name "<domain being served>";
option domain-name-servers <DNS 1>, <DNS 2>,...,<DNS N>;
default-lease-time <default lease time>;
max-lease-time <max lease time>;

log-facility local7;

shared-network <YOUR-NETWORK-NAME> {
        option ...;
        option ...;
        option ...;
        option ...;
        
        subnet <network-address 1> netmask <net mask 1> {
                option ...;
                option ...;
                option ...;
        }

        subnet <network-address 2> netmask <net mask 2> {
                option ...;
                option ...;
                option ...;
        }
...
...
...
        subnet <network-address N> netmask <net mask N> {
                option ...;
                option ...;
                option ...;
        }
        
}

include "</include path/config 1>";
include "</include path/config 2>";
...
...
...
include "</include path/config N>";

```

And your include files for fixed IPs structured reasonably similar to this
```
host <host 1> {
hardware ethernet <MAC of host 1>;
fixed-address <Fixed IP of host 1>;
}

host <host 2> {
hardware ethernet <MAC of host 2>;
fixed-address <Fixed IP of host 2>;
}
...
...
...
host <host N> {
hardware ethernet <MAC of host N>;
fixed-address <Fixed IP of host N>;
}
```

### Running DHCP-GUARD
+ If you have created DHCP-GUARD as a service just do
```
systemctl start dhcp-guard
```
+ To stop the service
```
systemctl stop dhcp-guard
```
+ To restart the service
```
systemctl start dhcp-guard
```

+ Open a browser and navigate to https://your.server.fqdn (add the :port if you changed the port numbers)
+ The default login credentials are
```
userid: admin
password: password
```
+ Go to *Admin -> Settings* in the side panel and change the password for the admin user and add other users if you want.

TO BE CONTINUED
