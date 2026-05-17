# KNX Dashboard

A self-hosted, containerised web dashboard for KNX bus automation.  
Controls Lights, Blinds, Heating, Sprinkler, and displays Sensor values.  
Devices are auto-discovered by monitoring the KNX bus or imported from an ETS project file.

---

## Features

- **Auto-discovery** — detects KNX group addresses in real-time as telegrams arrive
- **ETS import** — imports names, DPT types and addresses from `.knxproj` files
- **Grouped tiles** — related group addresses (switch + status + dimmer) merge into one card
- **Categories** — Lights, Blinds, Heating, Sprinkler, Sensors, Unknown
- **Real-time** — WebSocket push; no polling
- **Fully local** — no cloud, no account, no telemetry

---

## Architecture

```
Browser  ──►  nginx (port 3000)  ──►  FastAPI backend (port 8000, internal)
                                           │
                                       xknx library
                                           │
                                      KNX IP Gateway (UDP 3671)
```

Two Docker containers, one Compose stack, one persistent SQLite volume.

---

## Requirements

- Docker + Docker Compose v2
- SSH / terminal access to your server or NAS
- A KNX IP Interface or IP Router reachable from the host (tunneling or routing mode)

---

## Quick start

### 1. Clone

```bash
git clone https://github.com/<your-username>/knx-dashboard.git
cd knx-dashboard
```

### 2. Configure

```bash
cp .env.example .env
nano .env          # or your editor of choice
```

```env
KNX_GATEWAY_HOST=192.168.1.100   # IP of your KNX IP Interface / Router
KNX_GATEWAY_PORT=3671
KNX_CONNECTION_TYPE=tunneling    # tunneling (unicast) or routing (multicast)
SECRET_KEY=change-this-to-something-random
```

### 3. Build and start

```bash
docker compose up -d --build
```

First run takes ~2 minutes (downloads base images, installs Python packages).

### 4. Open the dashboard

```
http://<HOST-IP>:3000
```

Go to **Settings → KNX Gateway Connection**, enter your gateway IP and click **Connect**.

---

## Deploying to a NAS or remote server

```bash
# Copy files (adjust user/host/path)
rsync -avz ./ user@your-server:/opt/knx-dashboard/

ssh user@your-server
cd /opt/knx-dashboard
cp .env.example .env && nano .env
docker compose up -d --build
```

---

## Updating after code changes

```bash
# Pull latest changes
git pull

# Rebuild changed containers
docker compose up -d --build
```

---

## Quick reference

```bash
# Start
docker compose up -d

# Stop
docker compose down

# Restart (e.g. after .env change)
docker compose restart

# Rebuild after code changes
docker compose up -d --build

# Live logs (both containers)
docker compose logs -f

# Backend logs only
docker logs knx-backend -f

# Frontend / nginx logs only
docker logs knx-frontend -f

# Check container status
docker ps | grep knx
```

> On some systems (e.g. ZimaOS) you may need `sudo -E docker compose …` — see [ZimaOS notes](#zimaos-notes) below.

---

## Persistence & reboots

- Both containers have `restart: unless-stopped` — they start automatically on boot.
- Device data is stored in the Docker named volume `knx-dashboard_knx_data` (SQLite).
- The volume survives `docker compose down` and container rebuilds.
- Only `docker compose down -v` deletes the volume (destroys all device data).

---

## ETS project import

1. In ETS, export your project: **Project menu → Export → ETS Archive (.knxproj)**
2. In the dashboard, go to **Settings → Import ETS Project**
3. Upload the `.knxproj` file
4. All group addresses with names and DPT types are imported instantly
5. Manual edits (renamed devices, reassigned categories) are preserved on re-import

Max file size: 100 MB.

---

## KNX connection modes

| Mode | Use when | Notes |
|---|---|---|
| `tunneling` | KNX IP Interfaces (unicast) | Default; works with bridge networking |
| `routing` | KNX IP Routers (multicast) | Change backend to `network_mode: host` in compose |

### Routing / multicast mode

In `docker-compose.yml`, replace the backend service's `ports` and `networks` with:
```yaml
    network_mode: host
```
And set in `.env`:
```env
KNX_CONNECTION_TYPE=routing
```

---

## Troubleshooting

### Bad Gateway on connect
```bash
docker logs knx-backend --tail 50
```
Common causes:
- KNX IP Interface only allows 1–2 simultaneous connections → close ETS first
- Wrong IP or port in `.env`
- UDP port 3671 blocked by a firewall

### Import failed: Request Entity Too Large
The nginx limit is set to 100 MB. If you hit it, rebuild the frontend:
```bash
docker compose up -d --build frontend
```

### Containers not starting after reboot
```bash
docker ps -a | grep knx       # check exit codes
docker logs knx-backend       # see why it stopped
```

---

## ZimaOS notes

ZimaOS mounts `/root` as read-only. Two one-time workarounds:

**Docker config path:**
```bash
sudo mkdir -p /DATA/AppData/.docker
sudo tee /etc/profile.d/knx-env.sh <<'EOF'
export DOCKER_CONFIG=/DATA/AppData/.docker
export HISTFILE=/DATA/AppData/.bash_history
EOF
source /etc/profile.d/knx-env.sh
```

**Always use `sudo -E`** (passes the env var through sudo):
```bash
sudo -E docker compose up -d --build
```

**Deploy from your workstation:**
```bash
rsync -avz ./  user@your-nas:/DATA/AppData/knx-dashboard/
```

---

## Port reference

| Port | Protocol | Service |
|---|---|---|
| 3000 | TCP | Dashboard (nginx) — open in browser |
| 8000 | TCP | Backend API (internal, proxied by nginx) |
| 3671 | UDP | KNX IP tunneling (outbound to gateway) |

---

## License

MIT — Copyright (c) 2026 Mario Stephan &lt;mstephan@shared-files.de&gt; — see [LICENSE](LICENSE).

