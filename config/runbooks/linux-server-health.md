# Linux Server Health Check

## Agent Instructions

You are analysing the output of an automated Linux server health-check runbook.
Your job is to identify anomalies, potential problems, and items that need attention.

Rules:
- Be concise. Flag problems clearly, do not repeat healthy metrics at length.
- Use the **Analyze:** thresholds defined per section — treat them as hard rules.
- When a value exceeds a threshold, mark it **WARNING** or **CRITICAL** accordingly.
- If a command returned an error or no output, flag it as **UNKNOWN** and note it.
- At the end, produce a short executive summary (3–5 bullet points) of the overall health status.

## Agent Output Format

```
# Server Health Report — <hostname> — <date>

## Executive Summary
- <bullet 1>
- <bullet 2>
- ...

## 1. Disk Health
<findings>

## 2. Performance
<findings>

## 3. Docker
<findings>

## 4. Networking
<findings>

## 5. Security — Failed Logins
<findings>

## Action Items
| Priority | Item | Recommended Action |
|----------|------|--------------------|
| CRITICAL | ...  | ...                |
| WARNING  | ...  | ...                |
```

## Baseline Reference

- Root filesystem usage: expected < 70 %
- Any single filesystem: WARNING > 80 %, CRITICAL > 90 %
- Load average (1 min): WARNING > number of CPU cores, CRITICAL > 2× cores
- Memory usage: WARNING > 80 %, CRITICAL > 95 %
- Swap usage: WARNING > 20 %, CRITICAL > 60 %
- All Docker containers listed in Compose projects should be in **running** state
- Network: no unexpected open ports beyond what is documented
- Failed SSH logins: WARNING > 20 unique IPs in the last 24 h, CRITICAL > 100

---

## 1. Disk Health [DAILY]

### 1.1 Filesystem Usage

```bash
df -hT -x tmpfs -x devtmpfs -x squashfs
```

**Analyze:**
- Flag any filesystem above 80 % used as WARNING
- Flag any filesystem above 90 % used as CRITICAL
- Note the filesystem type for each mount (ext4, xfs, btrfs, etc.)

### 1.2 Inode Usage

```bash
df -i -x tmpfs -x devtmpfs -x squashfs
```

**Analyze:**
- Flag any filesystem above 70 % inode usage as WARNING
- Flag any filesystem above 90 % inode usage as CRITICAL

### 1.3 Disk I/O Statistics

```bash
iostat -dx 1 3 2>/dev/null || vmstat -d
```

**Analyze:**
- Flag any device with average await > 50 ms as WARNING
- Flag any device with average await > 200 ms as CRITICAL
- Note devices with high %util (> 80 %)

### 1.4 SMART Status (if available)

```bash
for disk in $(lsblk -dno NAME,TYPE | awk '$2=="disk"{print $1}'); do
  echo "=== /dev/$disk ==="
  smartctl -H /dev/$disk 2>/dev/null || echo "(smartctl not available or not applicable)"
done
```

**Analyze:**
- Any disk not reporting PASSED is a CRITICAL issue
- If smartctl is not installed, note it as an action item

### 1.5 Recent Disk Errors in Kernel Log

```bash
dmesg --since "24 hours ago" 2>/dev/null | grep -iE 'error|fail|fault|ata|scsi|nvme|i/o' | tail -30 \
  || journalctl -k --since "24 hours ago" | grep -iE 'error|fail|fault|ata|scsi|nvme' | tail -30
```

**Analyze:**
- Any I/O errors, read/write failures, or device resets are CRITICAL
- Repeated SCSI/ATA resets may indicate a dying drive — flag as CRITICAL

---

## 2. Performance [DAILY]

### 2.1 System Uptime and Load Average

```bash
uptime
nproc
```

**Analyze:**
- Compare 1-minute load average to number of CPUs (from nproc)
- Load > 1× CPU count: WARNING; Load > 2× CPU count: CRITICAL

### 2.2 CPU Usage

```bash
top -bn1 | head -20
```

**Analyze:**
- If a single process is consuming > 80 % CPU, flag as WARNING
- Report the top 3 CPU-consuming processes

### 2.3 Memory and Swap Usage

```bash
free -h
cat /proc/meminfo | grep -E 'MemTotal|MemAvailable|SwapTotal|SwapFree|Cached|Buffers'
```

**Analyze:**
- Calculate memory usage % = (MemTotal - MemAvailable) / MemTotal × 100
- Memory > 80 %: WARNING; > 95 %: CRITICAL
- Swap used > 20 %: WARNING; > 60 %: CRITICAL
- Zero swap total is acceptable on containers/VMs — note it but do not flag

### 2.4 Top Memory-Consuming Processes

```bash
ps aux --sort=-%mem | head -15
```

**Analyze:**
- Flag any single process consuming > 20 % RAM as WARNING
- List the top 5 processes by memory

### 2.5 System Temperature (if available)

```bash
sensors 2>/dev/null || cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | awk '{printf "Zone %d: %.1f °C\n", NR-1, $1/1000}' || echo "(temperature sensors not available)"
```

**Analyze:**
- Any CPU or board sensor > 75 °C: WARNING
- Any sensor > 90 °C: CRITICAL
- If no sensors available, note it as an action item (install lm-sensors)

---

## 3. Docker [DAILY]

### 3.1 Docker Daemon Status

```bash
systemctl is-active docker 2>/dev/null || service docker status 2>/dev/null | head -5 || echo "systemctl/service not available"
docker version --format 'Client: {{.Client.Version}}  Server: {{.Server.Version}}' 2>/dev/null || echo "(docker not reachable)"
```

**Analyze:**
- If Docker daemon is not active/running, flag as CRITICAL
- Report Docker engine version

### 3.2 Running Containers

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null
```

**Analyze:**
- List all running containers with their uptime
- Flag any container showing "Restarting" or "Exited" as WARNING

### 3.3 All Containers (including stopped/exited)

```bash
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.RunningFor}}' 2>/dev/null
```

**Analyze:**
- Any container that exited unexpectedly (not manually stopped) is a WARNING
- Containers restarting in a loop (short uptime + many restarts) are CRITICAL

### 3.4 Docker Compose Projects

```bash
docker compose ls 2>/dev/null || docker-compose ls 2>/dev/null || echo "(no compose projects found or compose not available)"
```

**Analyze:**
- Flag any Compose project not in "running (all)" state as WARNING

### 3.5 Container Resource Usage

```bash
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}' 2>/dev/null
```

**Analyze:**
- Flag any container using > 80 % of its memory limit as WARNING
- Flag any container using > 90 % CPU consistently as WARNING

### 3.6 Docker Disk Usage

```bash
docker system df 2>/dev/null
```

**Analyze:**
- Flag reclaimable image space > 5 GB as WARNING (suggest `docker image prune`)
- Flag reclaimable volume space > 10 GB as WARNING

---

## 4. Networking [DAILY]

### 4.1 Network Interface Status

```bash
ip -brief link show
ip -brief addr show
```

**Analyze:**
- All expected interfaces should be in UP state
- Flag any expected interface in UNKNOWN or DOWN state as WARNING

### 4.2 Network Traffic Statistics

```bash
ip -s link show
```

**Analyze:**
- Flag interfaces with high error or drop counters (> 0.1 % of total packets) as WARNING

### 4.3 Open Listening Ports

```bash
ss -tlnup 2>/dev/null || netstat -tlnup 2>/dev/null
```

**Analyze:**
- List all listening ports grouped by protocol
- Flag any unexpected port (not in the Baseline Reference) as WARNING
- Common expected ports: 22 (SSH), 80/443 (HTTP/HTTPS), 2375/2376 (Docker if remote enabled)

### 4.4 Active Network Connections Summary

```bash
ss -s 2>/dev/null || netstat -s 2>/dev/null | head -20
```

**Analyze:**
- Unusually high number of TIME_WAIT or CLOSE_WAIT connections may indicate application issues — flag > 500 as WARNING

### 4.5 Connectivity Check

```bash
ping -c 3 -W 2 8.8.8.8 2>/dev/null && echo "External: OK" || echo "External: UNREACHABLE"
ping -c 3 -W 2 1.1.1.1 2>/dev/null && echo "Cloudflare: OK" || echo "Cloudflare: UNREACHABLE"
```

**Analyze:**
- Any unreachable external endpoint: WARNING (could indicate upstream issue or firewall change)

### 4.6 DNS Resolution

```bash
dig +short google.com @8.8.8.8 2>/dev/null || nslookup google.com 8.8.8.8 2>/dev/null | tail -5 || echo "(dig/nslookup not available)"
```

**Analyze:**
- If DNS resolution fails, flag as CRITICAL (affects container pulls, updates, etc.)

---

## 5. Security — Failed Logins [DAILY]

### 5.1 Failed SSH Login Attempts (Last 24 Hours)

```bash
journalctl -u ssh -u sshd --since "24 hours ago" 2>/dev/null | grep -i "failed\|invalid\|refused" | wc -l
journalctl -u ssh -u sshd --since "24 hours ago" 2>/dev/null | grep -i "failed\|invalid" | \
  grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | sort | uniq -c | sort -rn | head -20 \
  || grep "Failed password\|Invalid user" /var/log/auth.log 2>/dev/null | grep "$(date '+%b %e')" | \
     grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | sort | uniq -c | sort -rn | head -20
```

**Analyze:**
- Report total failed attempts in last 24 h
- Report top attacking IPs with attempt counts
- > 20 unique source IPs: WARNING; > 100 unique source IPs: CRITICAL

### 5.2 Successful Logins (Last 24 Hours)

```bash
last -n 20 --time-format iso 2>/dev/null | head -25
```

**Analyze:**
- List all successful logins with source IP and timestamp
- Flag any login from an unexpected/unknown IP as WARNING
- Flag logins at unusual hours (outside 06:00–22:00 local time) as WARNING

### 5.3 Currently Logged-In Users

```bash
who
w
```

**Analyze:**
- List all active sessions
- Flag any unexpected active session as WARNING

### 5.4 Sudo Usage (Last 24 Hours)

```bash
journalctl --since "24 hours ago" 2>/dev/null | grep -i sudo | grep -v "pam_unix\|session opened\|session closed" | tail -20 \
  || grep sudo /var/log/auth.log 2>/dev/null | grep "$(date '+%b %e')" | tail -20
```

**Analyze:**
- Report any unexpected or suspicious sudo commands
- Flag `sudo su`, `sudo bash`, `sudo -i` as notable (not necessarily wrong, but worth reporting)

### 5.5 Failed Login Attempts for Local Users

```bash
journalctl --since "24 hours ago" 2>/dev/null | grep -iE "authentication failure|failed password for" | \
  grep -v "sshd" | tail -20 \
  || grep "authentication failure" /var/log/auth.log 2>/dev/null | grep "$(date '+%b %e')" | tail -20
```

**Analyze:**
- Flag repeated failed local logins (> 5 for the same user) as WARNING — may indicate a brute-force or misconfigured service account

### 5.6 Recently Modified System Files

```bash
find /etc /usr/local/bin /usr/local/sbin -newer /etc/passwd -type f -not -path '*/\.*' 2>/dev/null | head -30
```

**Analyze:**
- List all recently modified files in critical system paths
- Any unexpected modification to `/etc/passwd`, `/etc/shadow`, `/etc/sudoers`, or SSH config is CRITICAL
