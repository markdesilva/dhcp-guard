import re
import os
import glob
import asyncio
import httpx
import sqlite3
import aiosqlite
import subprocess
from datetime import datetime, timedelta
from contextlib import asynccontextmanager # Added for lifespan
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext

# --- CONFIGURATION ---
MAIN_CONF = "/etc/dhcp/dhcpd.conf"
POOL_DIR = "/etc/dhcp/dhcpd-pools"
LOG_FILE = "/var/log/dhcpd.log"
LEASES_FILE = "/var/lib/dhcp/dhcpd.leases"
DB_PATH = "/opt/dhcp-guard/ping_history.db"
DETAILS_DB = "/opt/dhcp-guard/device_details.db"
USERS_DB = "/opt/dhcp-guard/users.db"

# Password Hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
reported_macs = set()

# --- LIFESPAN HANDLER (Replaces on_event) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    await init_db()
    asyncio.create_task(ping_scheduler())
    yield
    # Shutdown logic (if any) can go here

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_credentials=True)

class NewReservation(BaseModel):
    hostname: str
    mac: str
    ip: str
    target: str

class DeviceDetails(BaseModel):
    mac: str
    description: str = ""
    admin_name: str = ""
    comments: str = ""

class UserLogin(BaseModel):
    username: str
    password: str

# --- DATABASE & PING LOGIC ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS pings (ip TEXT, latency REAL, timestamp DATETIME)")
        await db.commit()
    async with aiosqlite.connect(DETAILS_DB) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS details
                          (mac TEXT PRIMARY KEY, description TEXT, admin_name TEXT, comments TEXT)''')
        await db.commit()
    async with aiosqlite.connect(USERS_DB) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users
                          (username TEXT PRIMARY KEY, password TEXT, is_admin INTEGER)''')
        # Create default admin if table is empty
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        if row and row[0] == 0:
            hashed_pw = pwd_context.hash("password")
            await db.execute("INSERT INTO users VALUES (?, ?, ?)", ("admin", hashed_pw, 1))
        await db.commit()

async def ping_ip_full(ip):
    try:
        proc = await asyncio.create_subprocess_exec(
            'ping', '-c', '1', '-W', '1', ip,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            match = re.search(r"time=([\d.]+)", stdout.decode())
            latency = float(match.group(1)) if match else 1.0
            return True, latency
        return False, 0.0
    except:
        return False, 0.0

async def ping_scheduler():
    while True:
        all_hosts = parse_dhcp_configs(MAIN_CONF) + get_live_leases()
        ips = list(set(h['ip'] for h in all_hosts if 'ip' in h))
        async with aiosqlite.connect(DB_PATH) as db:
            for ip in ips:
                online, latency = await ping_ip_full(ip)
                if online:
                    await db.execute("INSERT INTO pings VALUES (?, ?, ?)", (ip, latency, datetime.now()))
            await db.execute("DELETE FROM pings WHERE timestamp < ?", (datetime.now() - timedelta(hours=24),))
            await db.commit()
        await asyncio.sleep(300)

# --- DHCP PARSING & VALIDATION HELPERS ---
def get_all_config_files():
    files = [MAIN_CONF]
    if os.path.exists(POOL_DIR):
        files.extend(glob.glob(os.path.join(POOL_DIR, "*.conf")))
    return list(set(files))

def scan_for_conflicts(hostname, mac, ip):
    mac = mac.lower()
    for file_path in get_all_config_files():
        if not os.path.exists(file_path): continue
        try:
            with open(file_path, 'r') as f:
                content = f.read()
                blocks = re.findall(r'host\s+([^\s\{]+)\s*\{[^}]*hardware\s+ethernet\s+([0-9a-fA-F:]+);[^}]*fixed-address\s+([0-9.]+);', content, re.IGNORECASE | re.DOTALL)
                for h_name, h_mac, h_ip in blocks:
                    h_mac = h_mac.lower()
                    if h_name == hostname: return True, file_path, "HOSTNAME", h_name
                    if h_mac == mac: return True, file_path, "MAC", h_mac
                    if h_ip == ip: return True, file_path, "IP", h_ip
        except: pass
    return False, None, None, None

def parse_dhcp_configs(main_path):
    hosts = []
    files_to_read = [main_path]
    processed_files = set()
    while files_to_read:
        current_file = files_to_read.pop()
        if current_file in processed_files or not os.path.exists(current_file): continue
        try:
            with open(current_file, 'r') as f:
                content = re.sub(r'#.*', '', f.read())
                includes = re.findall(r'include\s+"?([^";]+)"?;', content)
                for inc in includes:
                    if "*" in inc: files_to_read.extend(glob.glob(inc))
                    else: files_to_read.append(inc)
                matches = re.findall(r'host\s+([^\s\{]+)\s*\{[^}]*hardware\s+ethernet\s+([0-9a-fA-F:]+);[^}]*fixed-address\s+([0-9.]+);', content, re.IGNORECASE | re.DOTALL)
                for m in matches:
                    hosts.append({"name": m[0], "mac": m[1].lower(), "ip": m[2], "source": os.path.basename(current_file)})
        except: pass
        processed_files.add(current_file)
    return hosts

def get_live_leases():
    leases = []
    if not os.path.exists(LEASES_FILE): return leases
    try:
        with open(LEASES_FILE, "r") as f:
            blocks = re.findall(r"lease (\d+\.\d+\.\d+\.\d+) \{(.*?)\}", f.read(), re.DOTALL)
            for ip, details in blocks:
                mac_m = re.search(r"hardware ethernet ([:a-f0-9]+);", details)
                host_m = re.search(r'client-hostname "(.*?)";', details)
                leases.append({"ip": ip, "mac": mac_m.group(1).lower() if mac_m else "unknown", "hostname": host_m.group(1) if host_m else "Dynamic Device"})
    except: pass
    return leases

# --- AUTHENTICATION ROUTES ---
@app.post("/api/login")
async def login(user: UserLogin):
    async with aiosqlite.connect(USERS_DB) as db:
        cursor = await db.execute("SELECT password FROM users WHERE username = ?", (user.username,))
        row = await cursor.fetchone()
        if row and pwd_context.verify(user.password, row[0]):
            return {"status": "success"}
        raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/api/settings/list-users")
async def list_users():
    async with aiosqlite.connect(USERS_DB) as db:
        cursor = await db.execute("SELECT username FROM users")
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

@app.post("/api/settings/add-user")
async def add_user(user: UserLogin):
    hashed_pw = pwd_context.hash(user.password)
    try:
        async with aiosqlite.connect(USERS_DB) as db:
            await db.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)", (user.username, hashed_pw, 0))
            await db.commit()
        return {"status": "success", "message": f"User {user.username} created"}
    except:
        return {"status": "error", "message": "User already exists"}

@app.post("/api/settings/update-password")
async def update_password(user: UserLogin):
    hashed_pw = pwd_context.hash(user.password)
    async with aiosqlite.connect(USERS_DB) as db:
        await db.execute("UPDATE users SET password = ? WHERE username = ?", (hashed_pw, user.username))
        await db.commit()
    return {"status": "success", "message": "Password updated successfully"}

# --- STANDARD ROUTES ---
@app.get("/api/hostnames")
async def get_all_hostnames():
    hostnames = set()
    for file_path in get_all_config_files():
        if not os.path.exists(file_path): continue
        try:
            with open(file_path, 'r') as f:
                content = f.read()
                found = re.findall(r'host\s+([^\s\{]+)\s*\{', content, re.IGNORECASE)
                for name in found: hostnames.add(name)
        except: pass
    return sorted(list(hostnames))

@app.get("/api/config-schema")
async def get_config_schema():
    if not os.path.exists(MAIN_CONF): return {"subnets": [], "includes": []}
    temp_path = f"/tmp/dhcp-guard-{os.getpid()}.tmp"
    active_includes = []
    subnets = []
    try:
        with open(temp_path, "w") as tmp_file:
            subprocess.run(["grep", "-v", "#", MAIN_CONF], stdout=tmp_file)
        if os.path.exists(temp_path):
            with open(temp_path, "r") as f:
                content = f.read()
                subnet_matches = re.findall(r"subnet\s+(\d+\.\d+\.\d+\.\d+)\s+netmask\s+(\d+\.\d+\.\d+\.\d+)\s*\{.*?range\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+);", content, re.DOTALL)
                for net, mask, start, end in subnet_matches:
                    subnets.append({"network": net, "range": f"{start} - {end}", "prefix": ".".join(start.split('.')[:3]) + "."})
                include_paths = re.findall(r'include\s+"/etc/dhcp/dhcpd-pools/([^"]+)";', content)
                active_includes = sorted(list(set(include_paths)))
    finally:
        if os.path.exists(temp_path): os.remove(temp_path)
    return {"subnets": subnets, "includes": active_includes}

@app.get("/api/data")
async def get_data():
    all_hosts = parse_dhcp_configs(MAIN_CONF) + get_live_leases()
    ips = [h['ip'] for h in all_hosts]
    results = await asyncio.gather(*(ping_ip_full(ip) for ip in ips))
    for i, (online, _) in enumerate(results):
        all_hosts[i]['status'] = "online" if online else "offline"
    return {"hosts": all_hosts, "alerts_count": len(reported_macs)}

@app.get("/api/ping-history/{ip}")
async def get_ping_history(ip: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT latency, timestamp FROM pings WHERE ip = ? AND timestamp > ? ORDER BY timestamp ASC", (ip, datetime.now() - timedelta(hours=2)))
        rows = await cursor.fetchall()
        return [{"y": r[0], "x": r[1]} for r in rows]

@app.get("/api/get-details/{mac}")
async def get_details(mac: str):
    async with aiosqlite.connect(DETAILS_DB) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM details WHERE mac = ?", (mac.lower(),))
        row = await cursor.fetchone()
        return dict(row) if row else {"description": "", "admin_name": "", "comments": ""}

@app.post("/api/save-details")
async def save_details(det: DeviceDetails):
    async with aiosqlite.connect(DETAILS_DB) as db:
        await db.execute('''INSERT INTO details (mac, description, admin_name, comments)
                          VALUES (?,?,?,?) ON CONFLICT(mac)
                          DO UPDATE SET description=excluded.description, admin_name=excluded.admin_name, comments=excluded.comments''',
                          (det.mac.lower(), det.description, det.admin_name, det.comments))
        await db.commit()
    return {"status": "success"}

@app.post("/api/service/{action}")
async def service_control(action: str):
    if action not in ["start", "stop", "restart"]: return {"status": "error", "message": "Invalid action"}
    try:
        os.system(f"sudo systemctl {action} isc-dhcp-server")
        return {"status": "success", "message": f"DHCP service {action}ed"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.post("/api/add-host")
async def add_host(res: NewReservation):
    ip_pattern = r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$"
    mac_pattern = r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$"
    if not re.match(ip_pattern, res.ip) or any(int(o)>255 for o in res.ip.split('.')):
        return {"status": "error", "message": "Invalid IP Address format or range"}
    if not re.match(mac_pattern, res.mac):
        return {"status": "error", "message": "Invalid MAC Address format"}

    exists, source_path, m_type, m_val = scan_for_conflicts(res.hostname, res.mac, res.ip)
    target_path = MAIN_CONF if res.target == "main" else os.path.join(POOL_DIR, res.target)

    if exists:
        source_name = os.path.basename(source_path)
        if source_name != (res.target if res.target=="main" else res.target):
            return {"status": "error", "message": f"CONFLICT: {m_type} ({m_val}) exists in {source_name}"}

        with open(source_path, 'r') as f:
            content = f.read()
            if f"host {res.hostname}" in content:
                pattern = r'\n?host\s+' + re.escape(res.hostname) + r'\s*\{.*?\n\}'
                content = re.sub(pattern, '', content, flags=re.DOTALL)
                block = f"\nhost {res.hostname} {{\n  hardware ethernet {res.mac.lower()};\n  fixed-address {res.ip};\n}}\n"
                with open(source_path, 'w') as f: f.write(content.strip() + "\n" + block)
                os.system("sudo systemctl restart isc-dhcp-server")
                return {"status": "success", "message": f"Updated {res.hostname} in {source_name}"}
            else:
                return {"status": "error", "message": f"CONFLICT: {m_type} ({m_val}) already exists in {source_name}"}

    block = f"\nhost {res.hostname} {{\n  hardware ethernet {res.mac.lower()};\n  fixed-address {res.ip};\n}}\n"
    with open(target_path, "a") as f: f.write(block)
    os.system("sudo systemctl restart isc-dhcp-server")
    return {"status": "success", "message": "Host successfully registered!"}

@app.delete("/api/delete-host/{hostname}")
async def delete_host(hostname: str):
    found = False
    for file_path in get_all_config_files():
        if not os.path.exists(file_path): continue
        with open(file_path, 'r') as f:
            content = f.read()
        pattern = r'\n?host\s+' + re.escape(hostname) + r'\s*\{.*?\n\}'
        if re.search(pattern, content, flags=re.DOTALL):
            new_content = re.sub(pattern, '', content, flags=re.DOTALL)
            with open(file_path, 'w') as f:
                f.write(new_content.strip() + "\n")
            found = True
    if found:
        os.system("sudo systemctl restart isc-dhcp-server")
        return {"status": "success", "message": f"Deleted {hostname} and restarted service"}
    return {"status": "error", "message": f"Host {hostname} not found in any config"}

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        with open(LOG_FILE, "r", 1) as f:
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if line: await websocket.send_text(line)
                else: await asyncio.sleep(0.5)
    except: pass

app.mount("/", StaticFiles(directory="/opt/dhcp-guard", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
