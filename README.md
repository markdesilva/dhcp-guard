# UPDATES (29th March 2026)
+ Tiles and ping graph update dynamically and seamlessly without updating or refreshing the whole page
+ If new dynamic clients get an ip, the tiles will added to the grid, for static leases, the status icon will change from red to green
+ Ping graph updates every 5 minutes, tiles will check for changes and refresh every 10 seconds
+ For the ping graph, if you  want finer granularity over a shorter window (eg: ping every minute, show graph over a 30 minute window) you can make these changes

**main.py**
```
ping_scheduler()
await asyncio.sleep(300) -> await asyncio.sleep(60)

get_ping_history(ip)
timedelta(hours=2) -> timedelta(minutes=30)
```

**index.html**
```
Just before the </script> tag
}, 300000); -> }, 60000);
```


# UPDATES (27th March 2026)
+ Added remaining lease time to tiles for leased clients

<img width="603" height="169" alt="dg-lease_left" src="https://github.com/user-attachments/assets/96c89d8a-527f-4f90-8efc-95517b0c0171" />


# UPDATES (26th March 2026)
+ Added live stream for /var/lib/dhcp/dhcpd.leases under 'Live Activity' (new side panel entries)

<img width="152" height="134" alt="image" src="https://github.com/user-attachments/assets/52ca0865-c928-4022-a83b-f072cd8723bd" />

+ Added sort tiles by live hosts to 'Network Segments' subnets 

<img width="321" height="105" alt="image" src="https://github.com/user-attachments/assets/109ba1d2-dbbc-42a6-8816-35e503b135b6" />

+ Changed "Static Registration" to "Static Registration/Modification" under 'Add Host'

<img width="540" height="167" alt="image" src="https://github.com/user-attachments/assets/6cb8092b-a1b1-4ba0-bd99-47c32d554307" />

+ Changed "Systems Administration" to "User Administration" under 'Settings'

<img width="346" height="163" alt="image" src="https://github.com/user-attachments/assets/74812051-d38c-45c2-8f85-ed3698326d8d" />
<br>
<br>
<br>
<br>
<br>
<br>

# DHCP-GUARD
Vibe coded (and heavly human edited) Web-Based Management for ISC-DHCP-Server for leased and fixed IP client reservations.

## History
ISC has moved to KEA DHCP and has their own UI, but didn't really meet what I needed and I still had multiple installations running off isc-dhcp-server. [Akkadius/glass-isc-dhcp](https://github.com/Akkadius/glass-isc-dhcp) while rich in features, didn't manage fixed IP reservations. We make users register their machines for DHCP, so fixed IP client reservations were a must and hence I decided to make use of AI to vibe code a simple UI for what I needed. 

Despite having plenty of ideas, trying to get the AI to remember what it did right previously and not mess it up was unbelievably painful! In anycase, after 4 days of battling Gemini and constantly remininding it what code worked and what didn't and arguing with it on its logic of simplifying everything and wiping out entire blocks of working code and it refusing to accept my versions of code as correct, we finally managed to get this out.

I call this initial version v1.10 but its more like 1.1000 after all the back and forth.

Credit where credit is due, I set the author of the code as Gemini (as it should be) and myself as designer and editor.

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
+ Edit /etc/rsyslog.d/dhcpd.log
+ Add the following and save the file
```
# This 'if' check catches the message by either its ID or its Facility
if ($programname == 'dhcpd' or $syslogfacility-text == 'local7') then {
    action(type="omfile" file="/var/log/dhcpd.log")
    
    # This is the "Magic Ingredient" that prevents duplicates:
    stop
}
```
+ Note: If you still want the dhcp logs to go to syslog as well, comment out the 'stop'
+ Do the following
```
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
    SSLCertificateFile /full/path/to/your/certfile
    SSLCertificateKeyFile /full/path/to/your/keyfile

    <Directory /opt/dhcp-guard>
        Options FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>

    ProxyPreserveHost On

    # We use Location blocks to ensure the Upgrade header is handled correctly
    <Location /ws/logs>
        ProxyPass ws://127.0.0.1:8000/ws/logs
        ProxyPassReverse ws://127.0.0.1:8000/ws/logs
    </Location>

    <Location /ws/leases>
        ProxyPass ws://127.0.0.1:8000/ws/leases
        ProxyPassReverse ws://127.0.0.1:8000/ws/leases
    </Location>

    <Location /ws/active-tiles>
        ProxyPass ws://127.0.0.1:8000/ws/active-tiles
        ProxyPassReverse ws://127.0.0.1:8000/ws/active-tiles
    </Location>

    ProxyPass /api http://127.0.0.1:8000/api
    ProxyPassReverse /api http://127.0.0.1:8000/api

    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    Header always set Strict-Transport-Security "max-age=63072000"

    RequestHeader set X-Forwarded-Proto "https"
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
```
server {
    listen 443 ssl;
    server_name your.server.fqdn;

    ssl_certificate /full/path/to/your/certfile;
    ssl_certificate_key /full/path/to/your/keyfile;

    add_header Strict-Transport-Security "max-age=63072000" always;

    root /opt/dhcp-guard;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;

    location /ws/logs {
        proxy_pass http://127.0.0.1:8000/ws/logs;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400; 
    }

    location /ws/leases {
        proxy_pass http://127.0.0.1:8000/ws/leases;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }

    location /ws/active-tiles {
        proxy_pass http://127.0.0.1:8000/ws/active-tiles;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000/;
    }
}
```
+ Link the file to /etc/nginx/sites-enabled
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
+ We assume the DHCP config in /etc/dhcp/dhcpd.conf is structured reasonably similar to this
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

+ And your include files for fixed IPs structured reasonably similar to this
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

+ Note: Dchp-guard will only pick up *.conf files in the includes for its 'Add Host' section to add static leases into. You can have other includes with files without the .conf extension for other purposes (eg: .class, .deny, etc)

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
+ If you want to run it from the CLI and see whats happening at the server end then do:
```
cd /opt/dhcp-guard
source ./venv/bin/activate
```
+ You will be in the python virtual environment (your CLI prompt will be prefixed with a '(venv)'), then do
```
python3 main.py
```
+ This is especially good for testing changes you make to the code on your own
+ To exit the CLI run mode, do CTRL-C **TWICE**
+ To exit the python virtual environment do
```
deactivate
```
+ To access the web-ui, open a browser and navigate to https://your.server.fqdn (add the :port if you changed the port numbers)


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
+ The ping graph is for a fixed time period of 2 hours (ping is done every 5 minutes from when the session starts) - there is no historical data
+ The ping graph is static, you have to click on the *Subnet* again to refresh the graph
  
<img width="1474" height="509" alt="dg-networksegments" src="https://github.com/user-attachments/assets/dfc960fa-84e1-45e0-a8f0-a7a4ef60872b" />


+ Clicking on the *Details* footer at the base of the tile will pull up a form which you can add information for the clients (Description, Admin, Comments) - this information is saved seperately from the dhcp conf files.
+ The trash can icon in the form can be used to delete the host completely from the dhcp conf files and all information assigned to the host - USE WITH CAUTION!
+ You can set client information (Description, Admin, Comments) for *LEASE* clients, but you can't delete them, you will get a HOST not found error.


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
+ ~~Make the ping graph update without refreshing the page (non priority target)~~ (Done!)

### TO NEVER DO
+ Edit DHCP config options (other than hosts) directly from the UI 
