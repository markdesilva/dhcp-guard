# DHCP-GUARD
Vibe coded (and heavly human edited) Web-Based Management for ISC-DHCP-Server

## History
ISC has moved to KEA DHCP and has their own UI, but didn't really meet what I needed and I still had multiple installations running off isc-dhcp-server. I didn't like glass and so I decided to make use of AI to vibe code a simple UI for what I had. It was painful, despite having plenty of ideas, trying to get the AI to remember what it did right previously and not mess it up was unbelievably painful! In anycase, after 4 days of battling Gemini and constantly remininding what code worked and what didn't and arguing with it on its logic, we finally managed to get this out.

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
``echo "local7.* /var/log/dhcpd.log" > /etc/rsyslog.d/dhcpd.log``

``echo "log-facility local7;" >> /etc/dhcp/dhcpd.conf``

``systemctl restart rsyslog``

``systemctl restart isc-dhcp-server``

### Clone the repo
``cd /opt; git clone https://github.com/markdesilva/DHCP-GUARD.git``
  
TO BE CONTINUED
