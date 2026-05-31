# Home Server Health Check Runbook
**Target:** Ubuntu/Debian Linux home server
**Intended for:** AI Agent automated execution — run after `linux-server-health` for full coverage
**Cadence:** Weekly full run · Daily for sections marked `[DAILY]`

> **Note:** This runbook covers home-server-specific checks only.
> General health (disk space, performance, Docker status, networking, security logins)
> is handled by `linux-server-health`. Run both runbooks for complete coverage.

---

## Agent Instructions

Run every command block in order. Capture all stdout and stderr per section.
After completing all sections, analyse the combined output against the thresholds
and flags defined in each section's **Analyze** block.
Produce a final summary report with: ✅ OK · ⚠️ Warning · 🔴 Critical per category.

---

## 0. System Identity [DAILY]

### 0.1 Hostname & OS Version

```bash
echo "HOSTNAME: $(hostname)"
echo "OS: $(lsb_release -ds 2>/dev/null || grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"')"
echo "KERNEL: $(uname -srm)"
echo "DATE: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "UPTIME: $(uptime -p 2>/dev/null || uptime)"
```

**Analyze:**
- Extract and report: hostname, OS name + version, kernel version, architecture, uptime
- Provide these values for the report header (`<hostname>` and `<date>` fields)
- Flag: OS that is end-of-life (Ubuntu < 22.04, Debian < 11, RHEL/CentOS < 8)

---

## 1. Storage — Extended `[DAILY]`

### 1.1 Large Files & Directory Sizes

```bash
du -sh /var/log/* 2>/dev/null | sort -rh | head -10
du -sh /var/lib/docker/volumes/* 2>/dev/null | sort -rh | head -10
du -sh /home/*/ 2>/dev/null | sort -rh | head -10
```

**Analyze:**
- Flag any single log file > 500MB (log rotation likely broken)
- Flag any Docker volume > 50GB if unexpected
- Flag unexpected growth in home directories

### 1.2 SMART Drive Health (Detailed)

```bash
for disk in $(lsblk -dno NAME,TYPE | awk '$2=="disk"{print $1}'); do
  echo "=== /dev/$disk ==="
  sudo smartctl -a /dev/$disk 2>/dev/null \
    | grep -E "(Device Model|Serial|Power_On_Hours|Temperature_Celsius|Reallocated_Sector_Ct|Current_Pending_Sector|Offline_Uncorrectable|UDMA_CRC_Error_Count|Raw_Read_Error_Rate)" \
    || sudo smartctl -a /dev/$disk --device=sat 2>/dev/null \
    | grep -E "(Device Model|Serial|Power_On_Hours|Temperature_Celsius|Reallocated_Sector_Ct|Current_Pending_Sector|Offline_Uncorrectable|UDMA_CRC_Error_Count|Raw_Read_Error_Rate)" \
    || echo "(smartctl not available or not applicable)"
done
```

**Analyze:**
- 🔴 Critical: `Reallocated_Sector_Ct` raw value > 0 (sectors remapped — drive failing)
- 🔴 Critical: `Current_Pending_Sector` raw value > 0 (unreadable sectors pending)
- 🔴 Critical: `Offline_Uncorrectable` raw value > 0
- ⚠️ Warning: `Temperature_Celsius` > 45°C (HDD) or > 60°C (SSD)
- ⚠️ Warning: `Power_On_Hours` > 35,000 (approaching end of typical HDD lifespan)
- Flag: `UDMA_CRC_Error_Count` > 0 (cable or controller issue)
- If smartctl not installed or permission denied: flag as action item (install smartmontools, add sudo)

---

## 2. Security — Extended `[DAILY]`

### 2.1 User Account Integrity

```bash
awk -F: '$3 >= 1000 && $1 != "nobody" {print $1, $3, $6, $7}' /etc/passwd
sudo awk -F: '$2 !~ /^[!*]/ {print $1}' /etc/shadow 2>/dev/null
```

**Analyze:**
- Flag: Any new UID ≥ 1000 account not in the Baseline Reference
- Flag: Any account with a valid (non-locked) password hash that should be locked
- 🔴 Critical: Any non-root account with UID 0

### 2.2 Failed Systemd Units

```bash
systemctl --failed --no-legend
```

**Analyze:**
- 🔴 Critical: Any unit in `failed` state — investigate immediately
- ⚠️ Warning: Any unit stuck in `activating` state

---

## 3. Docker — Extended

### 3.1 Container Log Errors (Last 24h)

```bash
for c in $(docker ps --format '{{.Names}}'); do
  errors=$(docker logs --since 24h "$c" 2>&1 | grep -icE "(error|fatal|panic|exception|OOM)")
  if [ "$errors" -gt 0 ]; then
    echo "=== $c ($errors matches) ==="
    docker logs --since 24h "$c" 2>&1 | grep -iE "(error|fatal|panic|exception|OOM)" | tail -5
  fi
done
echo "--- scan complete ---"
```

**Analyze:**
- 🔴 Critical: `OOM` (out of memory kill) in any container log
- 🔴 Critical: `panic` or `fatal` — may indicate imminent container failure
- ⚠️ Warning: Repeated `error` messages from the same container
- Containers with 0 matches are silently skipped — only flagged containers appear

---

## 4. System Logs — Extended

### 4.1 Recent Reboots

```bash
last reboot | head -10
journalctl --list-boots | head -10
```

**Analyze:**
- ⚠️ Warning: More than 1 unplanned reboot in the last 7 days
- Flag: Reboots at unexpected times (not matching scheduled maintenance)
- Flag: Very short uptimes between reboots (crash loop)

### 4.2 Log File Sizes & Rotation

```bash
ls -lh /var/log/*.log /var/log/syslog /var/log/auth.log 2>/dev/null | sort -k5 -rh | head -15
journalctl --disk-usage
```

**Analyze:**
- ⚠️ Warning: Any single log file > 200MB (rotation may be broken)
- ⚠️ Warning: journald disk usage > 2GB
- Flag: `auth.log` or `syslog` not updated in last 24h (logging service broken)

---

## 5. Updates & Packages

### 5.1 Available Updates

```bash
apt list --upgradable 2>/dev/null
apt-get -s upgrade 2>/dev/null | grep "^[0-9]"
```

**Analyze:**
- 🔴 Critical: Any security update (`-security`) pending > 7 days
- ⚠️ Warning: More than 20 packages upgradable
- Flag: Kernel updates pending (require reboot to apply)

### 5.2 Pending Reboot Check

```bash
[ -f /var/run/reboot-required ] && cat /var/run/reboot-required.pkgs || echo "No reboot required"
```

**Analyze:**
- ⚠️ Warning: Reboot required flag is set
- Flag: Reboot required flag present for > 7 days (kernel update unapplied)

### 5.3 Unattended Upgrades Status

```bash
systemctl status unattended-upgrades --no-pager | tail -5
cat /var/log/unattended-upgrades/unattended-upgrades.log 2>/dev/null | tail -20
```

**Analyze:**
- ⚠️ Warning: `unattended-upgrades` service not active
- Flag: Errors in the unattended-upgrades log

---

## 6. Backup Verification `[DAILY]`

### 6.1 Backup Recency

```bash
ls -lht /media/snapshots/ 2>/dev/null | head -10
ls -lht /media/data/backups/ 2>/dev/null | head -10
find /media/snapshots/ /media/data/backups/ \
  \( -name "*.tar*" -o -name "*.gz" -o -name "*.zst" -o -name "*.borg" \) 2>/dev/null \
  | xargs ls -lt 2>/dev/null | head -10
```

**Analyze:**
- 🔴 Critical: No backup file newer than 7 days (if daily backups configured)
- 🔴 Critical: No backup file newer than 30 days (if weekly backups configured)
- 🔴 Critical: Backup destination not mounted or empty
- Flag: Backup destination disk usage has not grown since last run (job may be silently failing)

### 6.2 Backup Job Status

```bash
systemctl list-timers --no-pager | grep -iE "(backup|rsync|borg|restic|snapshot)"
crontab -l 2>/dev/null
cat /etc/cron.d/* 2>/dev/null | grep -v "^#" | grep -v "^$"
```

**Analyze:**
- ⚠️ Warning: No backup timer or cron job found at all
- Flag: Last trigger time older than the expected backup interval

---

## 7. Hardware — Extended

### 7.1 Memory Errors (ECC / MCE)

```bash
edac-util -s 0 2>/dev/null || echo "EDAC not available (non-ECC RAM or driver not loaded)"
dmesg | grep -iE "mce|machine check|memory error|edac" | tail -10
```

**Analyze:**
- 🔴 Critical: Any corrected or uncorrected ECC memory errors
- 🔴 Critical: `machine check` events in dmesg (hardware fault)
- If EDAC not available on a server with ECC RAM: flag as action item (load edac kernel module)

---

## Agent Output Format

After running all sections, produce a report in this structure:

```
HOME SERVER EXTENDED HEALTH REPORT
Generated: <timestamp>
Hostname: <hostname>

SUMMARY
-------
✅ OK       : [count] categories
⚠️  Warning  : [count] categories
🔴 Critical  : [count] categories

CRITICAL ISSUES (action required immediately)
- [description] → [section] → [recommended action]

WARNINGS (action required this week)
- [description] → [section] → [recommended action]

METRICS SNAPSHOT
- Largest Docker volume  :
- SMART status (all disks):
- Pending security updates:
- Reboot required        :
- Last backup            :
- Backup job configured  :
- Memory errors (ECC)    :
- Failed systemd units   :

RECOMMENDED ACTIONS (prioritized)
1. [highest priority]
2. ...
```

---

## Baseline Reference

> Customise these values for your server in `homeserver-runbook.local.md` (gitignored).
> The local file overrides this reference when running the runbook privately.

| Item | Expected value |
|------|---------------|
| Primary disk | `<your primary disk, e.g. /dev/sda>` |
| Data disk | `<your data disk → /media/data or similar>` |
| Snapshots/backup disk | `<your backup disk → /media/snapshots or similar>` |
| Expected SSH source | `<your LAN subnet, e.g. 192.168.x.x>` |
| Docker running | yes / no |
| Backup cadence | daily / weekly |
| Expected pending updates | 0 security, < 10 total |
