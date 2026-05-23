# MacBook Health Check Runbook
**Target:** macOS (Apple Silicon & Intel)
**Intended for:** AI Agent automated execution
**Cadence:** Weekly full run · Daily for sections marked `[DAILY]`

---

## Agent Instructions

Run every command block in order. Capture all stdout and stderr per section.
After completing all sections, analyse the combined output against the thresholds
and flags defined in each section's **Analyze** block.
Produce a final summary report with: ✅ OK · ⚠️ Warning · 🔴 Critical per category.

---

## 0. System Identity `[DAILY]`

### 0.1 Hostname & macOS Version

```bash
scutil --get ComputerName 2>/dev/null || hostname
scutil --get LocalHostName 2>/dev/null || true
sw_vers
uname -srm
system_profiler SPSoftwareDataType 2>/dev/null | grep -E "(System Version|Kernel Version|Boot Volume|Computer Name|User Name)"
```

**Analyze:**
- Extract and report: ComputerName, macOS version (name + build), kernel version, architecture
- Flag: macOS version that is end-of-life or more than 2 major versions behind current release
- This section provides the header values for the final report (Hostname / macOS Version)

---

## 1. Storage `[DAILY]`

### 1.1 Disk Space

```bash
df -h | grep -v tmpfs
diskutil list
```

**Analyze:**
- ⚠️ Warning: Any volume >80% used
- 🔴 Critical: Any volume >90% used
- Flag: root volume (/) separately — a full system disk causes crashes

### 1.2 Large Directories

```bash
du -sh ~/Downloads ~/Desktop ~/Documents ~/Movies ~/Library/Caches 2>/dev/null | sort -rh | head -15
du -sh /private/var/folders 2>/dev/null
```

**Analyze:**
- ⚠️ Warning: `~/Library/Caches` > 5GB
- Flag: `~/Downloads` or `~/Desktop` > 10GB (common clutter accumulation)
- Flag: `/private/var/folders` > 2GB

### 1.3 APFS Snapshot Usage

```bash
tmutil listlocalsnapshots / 2>/dev/null
tmutil listlocalsnapshotdates 2>/dev/null | tail -10
diskutil apfs listSnapshots disk1s1 2>/dev/null || true
```

**Analyze:**
- ⚠️ Warning: More than 5 local Time Machine snapshots pinned (consuming significant space)
- Flag: Snapshots older than 7 days not yet pruned

---

## 2. Performance `[DAILY]`

### 2.1 CPU & Load

```bash
uptime
sysctl -n hw.logicalcpu hw.physicalcpu
top -l 1 -n 5 -stats pid,command,cpu | head -20
```

**Analyze:**
- ⚠️ Warning: 1-minute load average > logical CPU count
- 🔴 Critical: 15-minute load average > 2× logical CPU count
- Flag: Any single process consuming >50% CPU at idle

### 2.2 Memory Pressure

```bash
vm_stat
sysctl -n hw.memsize
memory_pressure 2>/dev/null || true
```

**Analyze:**
- Compute `pages wired` + `pages active` to estimate RAM pressure
- 🔴 Critical: `memory_pressure` reports "System memory pressure is critical"
- ⚠️ Warning: `pageouts` or `swapouts` > 0 (system is compressing/swapping)
- Flag: `pages occupied by compressor` > 500,000 (active memory compression pressure)

### 2.3 Swap Usage

```bash
sysctl vm.swapusage
ls -lh /private/var/vm/swapfile* 2>/dev/null || echo "No swap files"
```

**Analyze:**
- ⚠️ Warning: Swap used > 1GB
- 🔴 Critical: Swap used > 4GB
- Flag: Multiple swap files present (sustained memory pressure)

### 2.4 Thermal State

```bash
pmset -g thermlog 2>/dev/null | tail -10
pmset -g log 2>/dev/null | grep -i "thermal\|throttle\|warning" | tail -10
sudo powermetrics --samplers smc -n 1 -i 1 2>/dev/null | grep -iE "(temperature|thermal|fan|power)" | head -20
```

**Analyze:**
- 🔴 Critical: `CPU_Scheduler_Limit` < 100 (CPU throttling active)
- ⚠️ Warning: Fan speed > 4000 RPM at idle
- Flag: `GPU_Thermal_Level` or `CPU_Thermal_Level` > 0

---

## 3. Battery (skip if desktop Mac)

### 3.1 Battery Health

```bash
system_profiler SPPowerDataType 2>/dev/null | grep -E "(Charge Remaining|Full Charge Capacity|Cycle Count|Condition|State of Charge|Design Capacity)"
pmset -g batt
```

**Analyze:**
- ⚠️ Warning: Battery condition is "Fair" or cycle count > 800
- 🔴 Critical: Battery condition is "Poor" or "Replace Now"
- Flag: Capacity retention < 80% (design capacity vs full charge capacity)
- Flag: Battery not charging when power adapter is connected

### 3.2 Power Management

```bash
pmset -g
pmset -g assertions 2>/dev/null | head -20
```

**Analyze:**
- Flag: `sleep` disabled when it should be enabled (prevents power saving)
- Flag: Persistent `PreventUserIdleSystemSleep` assertions from unexpected apps

---

## 4. Security `[DAILY]`

### 4.1 System Integrity Protection & Gatekeeper

```bash
csrutil status
spctl --status
```

**Analyze:**
- 🔴 Critical: SIP disabled (`System Integrity Protection status: disabled`)
- 🔴 Critical: Gatekeeper disabled (`assessments disabled`)

### 4.2 FileVault Encryption

```bash
fdesetup status
```

**Analyze:**
- 🔴 Critical: FileVault is OFF on a laptop
- ⚠️ Warning: FileVault encryption/decryption still in progress

### 4.3 Firewall Status

```bash
/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate
/usr/libexec/ApplicationFirewall/socketfilterfw --getstealthmode
defaults read /Library/Preferences/com.apple.alf globalstate 2>/dev/null
```

**Analyze:**
- ⚠️ Warning: Application firewall disabled
- Flag: Stealth mode disabled (responds to ICMP probes)

### 4.4 Recent Authentication Events

```bash
log show --predicate 'eventMessage CONTAINS "authentication" OR eventMessage CONTAINS "sudo" OR eventMessage CONTAINS "failed password"' --last 24h 2>/dev/null | grep -iE "(fail|error|sudo|auth)" | tail -20
```

**Analyze:**
- 🔴 Critical: Repeated `sudo` failures (>10 in 24h) — brute-force or accident
- Flag: `sudo` used by unexpected users
- Flag: Authentication failures for local accounts

### 4.5 Listening Network Services

```bash
sudo lsof -i -P -n | grep LISTEN
netstat -an | grep LISTEN | grep -v "127.0.0.1\|::1"
```

**Analyze:**
- Flag: Any service listening on `0.0.0.0` or `::` that is unexpected
- Flag: Ports other than expected (e.g. 22 SSH if enabled, 5000/7000 AirPlay, 5353 mDNS)
- 🔴 Critical: Unknown process listening on external interface

### 4.6 Active Outbound Connections

```bash
lsof -i -P -n | grep ESTABLISHED | head -30
```

**Analyze:**
- Flag: Unknown processes with established outbound connections
- Flag: Connections to unexpected foreign IPs

---

## 5. Software & Updates

### 5.1 macOS System Updates

```bash
softwareupdate --list 2>&1
```

**Analyze:**
- 🔴 Critical: Security updates pending > 7 days
- ⚠️ Warning: Any recommended updates pending > 14 days
- Flag: macOS major version update available

### 5.2 Homebrew

```bash
brew update 2>/dev/null && brew outdated 2>/dev/null || echo "Homebrew not installed"
brew doctor 2>/dev/null | grep -v "^Your system is ready" | head -20 || true
```

**Analyze:**
- ⚠️ Warning: More than 10 packages outdated
- Flag: Any security-relevant formulae outdated (openssl, curl, git, openssh)
- Flag: `brew doctor` warnings that indicate broken state

### 5.3 Launch Agents & Daemons

```bash
launchctl list | grep -v "com.apple\|0\s" | head -30
ls ~/Library/LaunchAgents/ 2>/dev/null
ls /Library/LaunchAgents/ 2>/dev/null
ls /Library/LaunchDaemons/ 2>/dev/null
```

**Analyze:**
- Flag: Any non-Apple launch agent/daemon not recognised
- Flag: Third-party daemons in `/Library/LaunchDaemons/` from unknown vendors
- 🔴 Critical: Any item matching known malware persistence paths

---

## 6. System Logs & Errors

### 6.1 Kernel Panics

```bash
ls -lht /Library/Logs/DiagnosticReports/*.panic 2>/dev/null | head -5 || echo "No kernel panics found"
ls -lht ~/Library/Logs/DiagnosticReports/*.crash 2>/dev/null | head -10 || echo "No crash reports found"
```

**Analyze:**
- 🔴 Critical: Any `.panic` file newer than 7 days
- ⚠️ Warning: More than 3 `.crash` reports for the same app in 7 days

### 6.2 Recent System Errors

```bash
log show --predicate 'eventType == logEvent AND messageType == error' --last 1h 2>/dev/null | grep -v "com.apple" | tail -20
```

**Analyze:**
- Flag: Repeated errors from the same process
- Flag: Disk-related errors (`IOKit`, `disk0`, `APFS`)

### 6.3 System Uptime & Recent Reboots

```bash
uptime
last reboot | head -10
```

**Analyze:**
- Flag: More than 2 reboots in the last 7 days (may indicate kernel panics or forced shutdowns)
- Flag: Very short uptimes between reboots

---

## 7. Network

### 7.1 Connectivity

```bash
ping -c 3 8.8.8.8 2>&1
ping -c 3 1.1.1.1 2>&1
curl -s --max-time 10 https://www.apple.com -o /dev/null -w "HTTP %{http_code} in %{time_total}s\n"
```

**Analyze:**
- 🔴 Critical: All pings fail (no outbound connectivity)
- ⚠️ Warning: Packet loss > 0%
- ⚠️ Warning: HTTP response time > 2s

### 7.2 DNS Resolution

```bash
dig +short apple.com @8.8.8.8
scutil --dns | grep "nameserver\[0\]" | head -5
networksetup -getdnsservers Wi-Fi 2>/dev/null
```

**Analyze:**
- 🔴 Critical: DNS resolution fails
- Flag: Unexpected DNS servers configured (possible hijack)

### 7.3 Network Interfaces

```bash
ifconfig | grep -E "(^[a-z]|inet |status)"
networksetup -listallhardwareports 2>/dev/null | head -30
```

**Analyze:**
- Flag: Unexpected VPN or tunnel interfaces active
- Flag: Multiple active network interfaces (possible unintended bridging)

### 7.4 VPN & Proxy

```bash
scutil --proxy
networksetup -getsocksfirewallproxy Wi-Fi 2>/dev/null
networksetup -getwebproxy Wi-Fi 2>/dev/null
```

**Analyze:**
- Flag: Unexpected proxy configured (possible MITM risk)
- Flag: SOCKS proxy enabled pointing to unknown host

---

## 8. Backup (Time Machine)

### 8.1 Time Machine Status

```bash
tmutil status 2>/dev/null
tmutil latestbackup 2>/dev/null || echo "No backup found"
```

**Analyze:**
- 🔴 Critical: No successful backup in the last 7 days
- 🔴 Critical: No backup destination configured
- ⚠️ Warning: Last backup > 48h ago
- Flag: Backup currently failing (`Running: 1, Stopping: 1`)

### 8.2 Backup Destinations

```bash
tmutil destinationinfo 2>/dev/null || echo "No Time Machine destination configured"
```

**Analyze:**
- Flag: No destination configured
- Flag: Destination is a local volume only (no offsite/cloud copy)

---

## Agent Output Format

After running all sections, produce a report in this structure:

```
MACBOOK HEALTH REPORT
Generated: <timestamp>
Hostname: <hostname>
macOS Version: <version>

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
- Uptime              :
- CPU load (1m)       :
- Memory pressure     :
- Swap used           :
- Root disk used      :
- Battery condition   :
- Battery cycles      :
- Last Time Machine   :
- Pending updates     :
- SIP status          :
- FileVault           :
- Firewall            :

TREND FLAGS (compare with last run)
- [any metrics that have changed significantly]

RECOMMENDED ACTIONS (prioritized)
1. [highest priority]
2. ...
```

---

## Baseline Reference

| Item | Expected value |
|------|---------------|
| SIP | enabled |
| Gatekeeper | enabled |
| FileVault | On |
| Firewall | On |
| Battery condition | Normal |
| Time Machine | configured, last backup < 24h |
| Expected listening ports | none external (or only known services) |
