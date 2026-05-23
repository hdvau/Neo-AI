# Linux Incident Forensics — Volatile Evidence Collection

## Agent Instructions

You are collecting volatile forensic evidence from a potentially compromised Linux system.
Volatile data (RAM contents, network state, process table) is lost on reboot — collect it first.
This runbook is READ-ONLY: observe and record. Do not kill processes, delete files, or modify anything.

Priority: speed over completeness. Volatile data decays; complete each section before moving on.
If a command hangs for more than 10 seconds, skip it and mark SKIPPED.

Rules:
- Record ALL output verbatim — the AI must not summarize or truncate raw artifacts
- Timestamp every section header with the actual clock time
- 🔴 IOC: Indicator of Compromise — confirmed suspicious artifact
- ⚠️ Anomaly: requires investigation but not yet confirmed malicious
- Note any commands that error or return nothing

## Agent Output Format

```
LINUX FORENSICS REPORT
Host: <hostname>  |  IP: <primary IP>  |  Date/Time: <ISO timestamp>
OS: <distro + kernel>  |  Uptime: <uptime>

INCIDENT TIMELINE (reconstruct from evidence)
- <time>: <event>

INDICATORS OF COMPROMISE
| Type       | Value                        | Source section | Confidence |
|------------|------------------------------|----------------|------------|
| IP         | 185.220.x.x                  | 1.3 Connections| 🔴 High    |

ANOMALIES REQUIRING INVESTIGATION
- <description> (Section X.X)

RECOMMENDED IMMEDIATE ACTIONS
1. [isolate / preserve / escalate]
```

## Baseline Reference

- Document known-good process list before starting if possible
- Expected outbound connections: package mirrors, monitoring agents, NTP
- Capture start time of this runbook — all timestamps should be relative to it

---

## 1. System State Snapshot [VOLATILE — collect first]

### 1.1 System Identity and Uptime

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ" && hostname && uname -a && uptime && who -b
```

**Analyze:**
- Record exact timestamp — anchor for all subsequent findings
- ⚠️ Anomaly: unexpectedly short uptime (system was recently rebooted — evidence may be lost)

### 1.2 Running Processes (Full Tree)

```bash
ps auxf 2>/dev/null || ps aux 2>/dev/null
```

**Analyze:**
- 🔴 IOC: processes named to mimic system processes with slight variations (`sshdd`, `crond`, `kthreadd` in userspace)
- 🔴 IOC: processes running from `/tmp`, `/dev/shm`, `/var/tmp`, `/run`, deleted paths
- 🔴 IOC: processes with parent PID 1 that are shells (`bash`, `sh`, `dash`) with no terminal
- ⚠️ Anomaly: processes with no associated command name `[]` that are NOT kernel threads
- ⚠️ Anomaly: `python`, `perl`, `ruby`, `nc`, `ncat`, `socat` running as root with no obvious purpose

### 1.3 Process Binary Paths (Verify on Disk)

```bash
ls -la /proc/*/exe 2>/dev/null | grep -v "^total" | grep -v "Permission denied" | head -50
```

**Analyze:**
- 🔴 IOC: `/proc/<pid>/exe` pointing to a deleted file (`/path/to/exe (deleted)`) — malware running from memory after binary was wiped
- 🔴 IOC: exe path pointing to `/tmp`, `/dev/shm`, `/var/tmp`

### 1.4 Open Network Connections

```bash
ss -tunap 2>/dev/null || netstat -tunap 2>/dev/null
```

**Analyze:**
- 🔴 IOC: ESTABLISHED connections to unexpected external IPs (non-CDN, non-package-mirror)
- 🔴 IOC: LISTEN on ports not in the documented baseline
- ⚠️ Anomaly: high port (>32768) listening bound to 0.0.0.0 with no known process
- ⚠️ Anomaly: process names that are shells (`bash`, `sh`) with open sockets
- Record all ESTABLISHED external connections with PID for cross-reference

### 1.5 Network Connections with Process Detail

```bash
ss -tunap 2>/dev/null | grep -v "127.0.0.1\|::1\|0.0.0.0:*" | grep ESTABLISHED
lsof -i -P -n 2>/dev/null | grep -v "127.0.0.1\|::1" | grep -E "(ESTABLISHED|LISTEN)"
```

**Analyze:**
- Map each connection: process name → PID → binary path → remote IP:port
- 🔴 IOC: shell or interpreter with active outbound connection (reverse shell)

---

## 2. User Activity [VOLATILE]

### 2.1 Currently Logged-In Users

```bash
who
w
last -n 30 --time-format iso 2>/dev/null | head -30
```

**Analyze:**
- 🔴 IOC: root logged in interactively from an external IP
- ⚠️ Anomaly: users logged in at unusual hours or from unusual IPs
- Record all active sessions: user, terminal, source IP, login time

### 2.2 Recent Command History (All Users)

```bash
for dir in /root /home/*/; do
  user=$(basename "$dir")
  for hist in .bash_history .zsh_history .python_history .psql_history; do
    [ -f "$dir/$hist" ] && echo "=== $user: $hist ===" && tail -50 "$dir/$hist" 2>/dev/null
  done
done
```

**Analyze:**
- 🔴 IOC: `wget`, `curl` downloading from external IPs followed by execution
- 🔴 IOC: commands creating/modifying `/etc/passwd`, `/etc/shadow`, `/etc/sudoers`
- 🔴 IOC: `useradd`, `usermod` adding users or modifying privileges
- 🔴 IOC: `chmod +s` or `chown root` on non-system files
- 🔴 IOC: encoded payloads: `base64 -d | bash`, `echo <hex> | xxd -r | sh`
- ⚠️ Anomaly: `history -c` or `unset HISTFILE` (history clearing attempt)
- Note timestamps of suspicious commands and cross-reference with auth logs

### 2.3 Failed and Successful Authentication (Last 24h)

```bash
journalctl -u ssh -u sshd --since "24 hours ago" 2>/dev/null | grep -iE "(accepted|failed|invalid|closed)" | tail -50
grep -E "(Accepted|Failed|Invalid)" /var/log/auth.log 2>/dev/null | tail -50
```

**Analyze:**
- 🔴 IOC: successful login shortly after a burst of failed attempts from the same IP (brute-force success)
- 🔴 IOC: login for a service account (`www-data`, `daemon`, `nobody`) that should never login
- Record all successful logins: user, source IP, timestamp

### 2.4 Sudo Usage

```bash
journalctl --since "24 hours ago" 2>/dev/null | grep -i "sudo" | grep -v "session\|pam_unix" | tail -30
grep "sudo:" /var/log/auth.log 2>/dev/null | grep -v "session" | tail -30
```

**Analyze:**
- 🔴 IOC: `sudo bash`, `sudo su`, `sudo -i` — interactive root shells via sudo
- 🔴 IOC: sudo by a user not authorized for sudo
- ⚠️ Anomaly: sudo commands downloading/executing files

---

## 3. File System Artifacts

### 3.1 Recently Created or Modified Files (Last 24h)

```bash
find / -xdev -newer /proc/1 -type f -not -path "/proc/*" -not -path "/sys/*" -not -path "/run/*" -not -path "/dev/*" 2>/dev/null | grep -vE "(\.(log|pid|lock|tmp|cache|stamp))$" | head -40
```

**Analyze:**
- 🔴 IOC: new executables in `/tmp`, `/dev/shm`, `/var/tmp`, `/run`
- 🔴 IOC: new or modified files in `/usr/bin`, `/usr/sbin`, `/bin`, `/sbin` (trojanized binaries)
- ⚠️ Anomaly: new files in web root directories (webshell indicator)
- ⚠️ Anomaly: new hidden files (`.` prefix) in system directories

### 3.2 Files in Suspicious Locations

```bash
find /tmp /var/tmp /dev/shm /run -type f -ls 2>/dev/null
find /var/www /srv /opt -name "*.php" -newer /etc/passwd 2>/dev/null | head -20
find /var/www /srv /opt -name "*.jsp" -newer /etc/passwd 2>/dev/null | head -10
```

**Analyze:**
- 🔴 IOC: compiled binaries (`ELF`) in /tmp, /dev/shm
- 🔴 IOC: `.php`, `.jsp` files recently added to web roots (webshells)
- ⚠️ Anomaly: archive files (`.tar`, `.zip`) in web directories

### 3.3 File Type Verification (Mismatched Extensions)

```bash
find /tmp /var/tmp /dev/shm -type f 2>/dev/null | xargs file 2>/dev/null | grep -iE "(ELF|executable|script)"
```

**Analyze:**
- 🔴 IOC: ELF executables with `.txt`, `.jpg`, `.conf` extensions (extension masquerading)

### 3.4 Deleted Files Still Open (Running Malware)

```bash
lsof +L1 2>/dev/null | grep -v "^COMMAND"
```

**Analyze:**
- 🔴 IOC: any entry here — process holding open a deleted file means malware wiped its binary while still running
- Record: process name, PID, user, and deleted file path

---

## 4. Network Artifacts

### 4.1 ARP Table (Potential Poisoning)

```bash
arp -n 2>/dev/null || ip neigh show 2>/dev/null
```

**Analyze:**
- ⚠️ Anomaly: multiple IPs sharing the same MAC address (ARP poisoning/MITM)
- ⚠️ Anomaly: gateway MAC address changed from baseline

### 4.2 DNS Configuration

```bash
cat /etc/resolv.conf
cat /etc/hosts | grep -v "^#" | grep -v "^$"
```

**Analyze:**
- 🔴 IOC: DNS server changed to an unknown/external IP (DNS hijacking)
- 🔴 IOC: `/etc/hosts` entries redirecting legitimate domains to attacker IPs

### 4.3 Listening Services

```bash
ss -tlnup 2>/dev/null
```

**Analyze:**
- 🔴 IOC: services listening on high ports (>1024) with root ownership and no known process
- ⚠️ Anomaly: any new listening port not in the documented baseline

### 4.4 Firewall Rules

```bash
iptables -L -n -v 2>/dev/null || nft list ruleset 2>/dev/null
ufw status verbose 2>/dev/null
```

**Analyze:**
- 🔴 IOC: rules added to ACCEPT all traffic or DISABLE logging
- ⚠️ Anomaly: rules allowing inbound on unexpected ports

---

## 5. Persistence Quick-Check

### 5.1 Crontab Summary

```bash
crontab -l 2>/dev/null; for u in $(cut -d: -f1 /etc/passwd); do crontab -u "$u" -l 2>/dev/null | grep -v "^#" | sed "s/^/$u: /"; done
cat /etc/cron.d/* 2>/dev/null
```

**Analyze:**
- 🔴 IOC: cron jobs with network callbacks or running from /tmp
- Cross-reference with Section 3 (recently modified files)

### 5.2 Authorized Keys Check

```bash
find /root /home -name "authorized_keys" 2>/dev/null -exec echo "=== {} ===" \; -exec cat {} \;
```

**Analyze:**
- 🔴 IOC: keys not in the known-good list
- Record all key fingerprints for threat intelligence lookup

### 5.3 New User Accounts

```bash
awk -F: '$3 >= 1000 {print $1, $3, $6, $7}' /etc/passwd
awk -F: '$2 !~ /^[!*]/ {print $1, "has valid password hash"}' /etc/shadow 2>/dev/null
```

**Analyze:**
- 🔴 IOC: accounts created after the expected system provisioning date
- 🔴 IOC: non-root accounts with UID 0

---

## 6. Log Integrity Check

### 6.1 Auth Log Gaps

```bash
ls -la /var/log/auth.log* 2>/dev/null
journalctl --verify 2>/dev/null | tail -5
```

**Analyze:**
- 🔴 IOC: auth.log missing or truncated to zero bytes (log wiping)
- ⚠️ Anomaly: gaps in log timestamps (possible selective deletion)

### 6.2 Last System Log Entry

```bash
tail -20 /var/log/syslog 2>/dev/null || journalctl --no-pager -n 20 2>/dev/null
```

**Analyze:**
- ⚠️ Anomaly: last log entry is much older than expected (logging stopped — possibly killed by attacker)

### 6.3 Syslog/Journald Status

```bash
systemctl is-active rsyslog syslog systemd-journald 2>/dev/null
```

**Analyze:**
- 🔴 IOC: logging daemon not running during an active incident (attacker may have killed it)
