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
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                clean_content = re.sub(r'#.*', '', content)
                
                blocks = re.findall(r'host\s+(["\']?[^\s\{]+["\']?)\s*\{([^}]+)\}', clean_content, re.IGNORECASE)
                for name, block_data in blocks:
                    clean_name = name.strip('"\'')
                    
                    # Loosened extraction to handle single-line setups seamlessly
                    mac_match = re.search(r'hardware\s+ethernet\s+([0-9a-fA-F:]+)', block_data, re.IGNORECASE)
                    ip_match = re.search(r'fixed-address\s+([0-9.]+)', block_data, re.IGNORECASE)
                    
                    h_mac = mac_match.group(1).lower() if mac_match else ""
                    h_ip = ip_match.group(1) if ip_match else ""
                    
                    if clean_name == hostname: return True, file_path, "HOSTNAME", clean_name
                    if h_mac == mac: return True, file_path, "MAC", h_mac
                    if h_ip == ip: return True, file_path, "IP", h_ip
        except Exception as e:
            print(f"Error scanning conflicts in {file_path}: {e}")
    return False, None, None, None

def parse_dhcp_configs(main_path):
    hosts = []
    files_to_read = [main_path]
    processed_files = set()
    while files_to_read:
        current_file = files_to_read.pop()
        if current_file in processed_files or not os.path.exists(current_file): continue
        try:
            with open(current_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                clean_content = re.sub(r'#.*', '', content)
                
                includes = re.findall(r'include\s+"?([^";]+)"?;', clean_content)
                for inc in includes:
                    if "*" in inc: files_to_read.extend(glob.glob(inc))
                    else: files_to_read.append(inc)
                
                blocks = re.findall(r'host\s+(["\']?[^\s\{]+["\']?)\s*\{([^}]+)\}', clean_content, re.IGNORECASE)
                for name, block_data in blocks:
                    clean_name = name.strip('"\'')
                    
                    mac_match = re.search(r'hardware\s+ethernet\s+([0-9a-fA-F:]+)', block_data, re.IGNORECASE)
                    ip_match = re.search(r'fixed-address\s+([0-9.]+)', block_data, re.IGNORECASE)
                    
                    if mac_match and ip_match:
                        hosts.append({
                            "name": clean_name, 
                            "mac": mac_match.group(1).lower(), 
                            "ip": ip_match.group(1), 
                            "source": os.path.basename(current_file)
                        })
        except Exception as e: 
            print(f"Error parsing {current_file}: {e}")
            
        processed_files.add(current_file)
        
    return hosts

def get_live_leases():
    active_by_mac = {}
    if not os.path.exists(LEASES_FILE): return []
    try:
        with open(LEASES_FILE, "r") as f:
            blocks = re.findall(r"lease (\d+\.\d+\.\d+\.\d+) \{(.*?)\}", f.read(), re.DOTALL)
            for ip, details in blocks:
                state_m = re.search(r"binding state (.*?);", details)
                mac_m = re.search(r"hardware ethernet ([:a-f0-9]+);", details)
                host_m = re.search(r'client-hostname "(.*?)";', details)
                ends_m = re.search(r"ends \d+ (\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2});", details)
                
                # Only process blocks that have a MAC and are actively bound
                if mac_m and state_m and state_m.group(1) == "active":
                    mac = mac_m.group(1).lower()
                    
                    # By assigning to a dictionary by MAC, older duplicate blocks 
                    # are safely overwritten by the newest lease block at the bottom of the file
                    active_by_mac[mac] = {
                        "ip": ip, 
                        "mac": mac, 
                        "hostname": host_m.group(1) if host_m else "Dynamic Device",
                        "ends": ends_m.group(1) if ends_m else None
                    }
    except: pass
    
    return list(active_by_mac.values())


def get_active_leases(filepath):
    """Parses the dhcpd.leases file and returns active leases, deduplicated by MAC."""
    active_by_mac = {}
    current_ip = None
    current_lease = {}

    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith("lease "):
                    current_ip = line.split()[1]
                    current_lease = {
                        "ip": current_ip, 
                        "state": "unknown", 
                        "mac": "", 
                        "hostname": "Unknown Device", 
                        "ends": None
                    }
                elif line.startswith("binding state "):
                    current_lease["state"] = line.split()[2].strip(";")
                elif line.startswith("hardware ethernet "):
                    current_lease["mac"] = line.split()[2].strip(";")
                elif line.startswith("client-hostname "):
                    parts = line.split(maxsplit=1)
                    if len(parts) > 1:
                        current_lease["hostname"] = parts[1].strip('";')
                elif line.startswith("ends "): 
                    parts = line.split()
                    if len(parts) >= 4:
                        current_lease["ends"] = f"{parts[2]} {parts[3].strip(';')}"
                elif line == "}":
                    if current_ip and current_lease.get("mac"):
                        active_by_mac[current_lease["mac"]] = current_lease.copy()
                        current_ip = None
    except FileNotFoundError:
        pass

    return [lease for lease in active_by_mac.values() if lease["state"] == "active"]

def modify_host_block(content: str, hostname: str, new_block: str = None) -> tuple[str, bool]:
    """
    Safely removes or replaces a host block by parsing { and } line-by-line.
    It ignores braces found inside # comments, preventing syntax corruption.
    """
    lines = content.split('\n')
    new_lines = []
    in_target = False
    brace_count = 0
    found = False
    
    # Matches the start of the block: (spaces) host (hostname) {
    start_regex = re.compile(r'^[ \t]*host\s+(["\']?' + re.escape(hostname) + r'["\']?)\s*\{', re.IGNORECASE)
    
    for line in lines:
        if not in_target:
            if not line.lstrip().startswith('#') and start_regex.search(line):
                in_target = True
                found = True
                code_part = line.split('#')[0]
                brace_count += code_part.count('{')
                brace_count -= code_part.count('}')
                
                if brace_count <= 0:
                    in_target = False
                    if new_block:
                        new_lines.append(new_block)
            else:
                new_lines.append(line)
        else:
            code_part = line.split('#')[0]
            brace_count += code_part.count('{')
            brace_count -= code_part.count('}')
            
            if brace_count <= 0:
                in_target = False
                if new_block:
                    new_lines.append(new_block.strip("\n"))
                    new_block = None 
                    
    return '\n'.join(new_lines), found

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
                raw_includes = re.findall(r'include\s+"/etc/dhcp/dhcpd-pools/([^"]+)";', content)
                active_includes = sorted(list(set(inc for inc in raw_includes if inc.endswith('.conf'))))
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

@app.get("/api/service/status")
async def get_service_status():
    try:
        result = subprocess.run(["systemctl", "is-active", "isc-dhcp-server"], capture_output=True, text=True)
        is_active = result.stdout.strip() == "active"
        return {"active": is_active}
    except:
        return {"active": False}

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

    # The new block we want to write
    block = f"\nhost {res.hostname} {{\n  hardware ethernet {res.mac.lower()};\n  fixed-address {res.ip};\n}}"

    if exists:
        source_name = os.path.basename(source_path)
        if source_name != (res.target if res.target=="main" else res.target):
            return {"status": "error", "message": f"CONFLICT: {m_type} ({m_val}) exists in {source_name}"}

        with open(source_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
        # Use our safe parser to replace the old block with the new block
        new_content, found = modify_host_block(content, res.hostname, new_block=block)
        
        if found:
            with open(source_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            os.system("sudo systemctl restart isc-dhcp-server")
            return {"status": "success", "message": f"Updated {res.hostname} in {source_name}"}
        else:
            return {"status": "error", "message": f"CONFLICT: {m_type} ({m_val}) already exists in {source_name}"}

    # If it's a completely new host, append it to the bottom
    with open(target_path, "a", encoding='utf-8') as f: 
        f.write(f"{block}\n")
    os.system("sudo systemctl restart isc-dhcp-server")
    return {"status": "success", "message": "Host successfully registered!"}

@app.delete("/api/delete-host/{hostname}")
async def delete_host(hostname: str):
    found = False
    for file_path in get_all_config_files():
        if not os.path.exists(file_path): continue
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
        # Use our safe parser to delete the block (new_block is None by default)
        new_content, block_found = modify_host_block(content, hostname)
        
        if block_found:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            found = True
            
    if found:
        os.system("sudo systemctl restart isc-dhcp-server")
        return {"status": "success", "message": f"Deleted {hostname} and restarted service"}
    return {"status": "error", "message": f"Host {hostname} not found in any config"}

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            try:
                current_ino = os.stat(LOG_FILE).st_ino
                with open(LOG_FILE, "r") as f:
                    f.seek(0, os.SEEK_END)
                    while True:
                        line = f.readline()
                        if line: 
                            await websocket.send_text(line)
                        else: 
                            await asyncio.sleep(0.5)
                            if os.stat(LOG_FILE).st_ino != current_ino:
                                break 
            except FileNotFoundError:
                await asyncio.sleep(0.5) 
    except Exception:
        pass

@app.websocket("/ws/leases")
async def websocket_leases_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        try:
            with open(LEASES_FILE, "r") as f:
                content = f.read()
                if content:
                    await websocket.send_text(content)
        except FileNotFoundError:
            pass 

        while True:
            try:
                current_ino = os.stat(LEASES_FILE).st_ino
                
                with open(LEASES_FILE, "r") as f:
                    f.seek(0, os.SEEK_END)
                    while True:
                        line = f.readline()
                        if line: 
                            await websocket.send_text(line)
                        else: 
                            await asyncio.sleep(1)
                            
                            current_stats = os.stat(LEASES_FILE)
                            
                            if current_stats.st_ino != current_ino or current_stats.st_size < f.tell():
                                await websocket.send_text("__CLEAR_STREAM__")
                                
                                with open(LEASES_FILE, "r") as new_f:
                                    new_content = new_f.read()
                                    if new_content:
                                        await websocket.send_text(new_content)
                                        
                                break 
            except FileNotFoundError:
                await asyncio.sleep(1)
    except Exception as e:
        print(f"Lease WS Error: {e}")

@app.websocket("/ws/active-tiles")
async def websocket_tiles_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        await websocket.send_json(get_active_leases(LEASES_FILE))
        try:
            current_ino = os.stat(LEASES_FILE).st_ino
            current_size = os.stat(LEASES_FILE).st_size
        except FileNotFoundError:
            current_ino, current_size = 0, 0

        while True:
            await asyncio.sleep(1) 
            try:
                stats = os.stat(LEASES_FILE)
                if stats.st_ino != current_ino or stats.st_size != current_size:
                    await websocket.send_json(get_active_leases(LEASES_FILE))
                    current_ino = stats.st_ino
                    current_size = stats.st_size
            except FileNotFoundError:
                pass
    except Exception as e:
        print(f"Tiles WS Error: {e}")

app.mount("/", StaticFiles(directory="/opt/dhcp-guard", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
