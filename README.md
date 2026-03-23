# DHCP-GUARD
Vibe coded (and heavly human edited) Web-Based Management for ISC-DHCP-Server for leased and fixed IP client reservations.

## History
ISC has moved to KEA DHCP and has their own UI, but didn't really meet what I needed and I still had multiple installations running off isc-dhcp-server. [Akkadius/glass-isc-dhcp](https://github.com/Akkadius/glass-isc-dhcp) while rich in features, didn't manage fixed IP reservations. We make users register their machines for DHCP, so fixed IP client reservations were a must and hence I decided to make use of AI to vibe code a simple UI for what I needed. 

Despite having plenty of ideas, trying to get the AI to remember what it did right previously and not mess it up was unbelievably painful! In anycase, after 4 days of battling Gemini and constantly remininding it what code worked and what didn't and arguing with it on its logic and it refusing to accept my code as correct, we finally managed to get this out.

I call it v1.10 but its more like 1.1000 after all the back and forth.

## Description
DHCP Guard is a modern, lightweight FastAPI application designed to provide a real-time dashboard and management interface for the Linux isc-dhcp-server for leased and fixed IP client reservations. 

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


<img width="512" height="503" alt="image" src="https://github.com/user-attachments/assets/3f6a4c0d-0eeb-4404-af36-72925f1182be" />


+ The default login credentials are
```
userid: admin
password: password
```

<img width="1487" height="894" alt="dg-live_activity" src="https://github.com/user-attachments/assets/26c401e0-942c-4107-bea6-ac204ffd87f9" />


+ Go to *Admin -> Settings* in the side panel and change the password for the admin user and add other users if you want.


+ All views will show the START/STOP/RESTART buttons at the top right corner and the server status icon - if the dhcp server is running, the status icon is green, if not it will be red.


<img width="191" height="48" alt="image" src="https://github.com/user-attachments/assets/117269dc-f296-4711-85df-8ec19dcac42e" />

   
+ The *Live View* shows a live stream of the dhcpd.logs, color coded for easier visibility for DHCPREQUEST, DHCPACK, DHCPDISCOVER and general messages.
+ You can increase or decrease the fonts, clear the stream.


<img width="172" height="77" alt="image" src="https://github.com/user-attachments/assets/fcf59de3-6402-4288-9c20-0fba61913e2e" />


+ You can also search for strings in the stream.


<img width="238" height="128" alt="image" src="https://github.com/user-attachments/assets/b90729f8-a52e-4005-980b-2ab11c6152b1" />


+ The *Network Segments* will show you your Shared Network and the *Subnets* as defined in your /etc/dhcp/dhcpd.conf.
+ Clicking on the *Subnets* will show tiles of all the leased and fixed IP clients defined in that segment (status icon will be either a green *LEASED* or blue *STATIC* icon)- tiles can be sorted by hostname or IP.
+ Each tile will show the hostname, IP and MAC address of the client
+ A ping graph for the client is also availabe when clicking on the area of the tile above the *Details* footer.
+ The ping graph is static, you have to click on the *Subnet* again
+ The ping graph is for a fixed time period of 2 hours (ping is done every 5 minutes from when the session starts) - there is no historical data

  
<img width="1474" height="509" alt="dg-networksegments" src="https://github.com/user-attachments/assets/dfc960fa-84e1-45e0-a8f0-a7a4ef60872b" />


+ Clicking on the *Details* footer at the base of the tile will pull up a form which you can add information for the clients (Description, Admin, Comments) - this information is saved seperately from the dhcp conf files.
+ The trash can icon in the form can be used to delete the host completely from the dhcp conf files and all information assigned to the host - USE WITH CAUTION!


<img width="422" height="496" alt="image" src="https://github.com/user-attachments/assets/efd03ac4-0f5a-4fd8-a7cc-b8c3cc011315" />


+ Under *Admin -> Add Host* the user can add a host to either the main dhcpd.conf file or any of the include conf files (shown in the drop down list).


<img width="553" height="591" alt="dg-addhost" src="https://github.com/user-attachments/assets/b01af275-584f-44d2-bfb5-85a63974199e" />


+ You can select the hostname field and click on it to reveal all fixed IP hosts and selecting them will auto populate the other fields.
+ Trying to save the same hostname, IP or MAC in a different file will inform the user of a conflict and which file the conflict exists in.
+ Changes to hostname, IP or MAC while keeping the other fields the same will be treated as an 'update'.
+ Under *Admin -> Settings* you can add a new admin user or change the password for any of the created users.


<img width="935" height="336" alt="image" src="https://github.com/user-attachments/assets/a6fb9387-accb-4e8c-8469-a0627d7c0830" />


+ Click on *Admin -> Sign Out* to log out - you will be prompted to confirm the log out.


<img width="391" height="178" alt="dg-logout" src="https://github.com/user-attachments/assets/24fca1e9-f95f-4782-8b94-8ca76551f541" />


### Files 
+ The ping user credentials, timing information and client descriptions/information are stored in SQLite databases in /opt/dhcp-guard
+ If you forget your password, just download the user.db file from the repo again and use the default credentials
+ If you lose the client description you will have to recreate them - best to have a cron back them up
+ The ping timing db is auto generated, if you lose the db file, it will regenerate

### TO DO
+ Make the ping graph update without refreshing the page (non priority target)
