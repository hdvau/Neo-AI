# CIS Linux Security Assessment

## Agent Instructions

You are running a read-only CIS Benchmark Level 1 compliance check on a live Linux server.
Do NOT run any remediation commands — this runbook only inspects and reports.

Rules:
- ✅ Pass: setting meets CIS recommendation
- ⚠️ Warning: partially meets or cannot verify
- 🔴 Fail: clearly violates the recommendation
- If a command errors or returns nothing, mark the item **UNKNOWN** and note it.
- At the end produce a scored summary: Pass / Fail / Unknown counts and an overall risk rating (Low / Medium / High / Critical).

## Agent Output Format

```
CIS LINUX LEVEL 1 ASSESSMENT
Host: <hostname>  |  OS: <distro + version>  |  Date: <timestamp>

SCORE: <pass>/<total> checks passed

SUMMARY
-------
✅ Pass    : X
⚠️  Warning : X
🔴 Fail    : X
❓ Unknown : X
Overall risk: Low / Medium / High / Critical

CRITICAL FINDINGS (fix immediately)
- [CIS ID] <finding> → <recommended fix>

WARNINGS (fix within 30 days)
- [CIS ID] <finding> → <recommended fix>

SECTION BREAKDOWN
1. Filesystem         ✅/⚠️/🔴
2. Services           ✅/⚠️/🔴
3. Network            ✅/⚠️/🔴
4. SSH Hardening      ✅/⚠️/🔴
5. User Accounts      ✅/⚠️/🔴
6. Audit & Logging    ✅/⚠️/🔴
7. Permissions        ✅/⚠️/🔴
```

## Baseline Reference

- CIS Benchmark: Linux Level 1 (Server profile)
- Pass threshold for Low risk: ≥ 85% of checks passing
- Pass threshold for Medium risk: 70–84%
- High risk: 50–69% | Critical risk: < 50%

---

## 0. System Identity [CIS-0]

### 0.1 Hostname & OS Version

```bash
echo "HOSTNAME: $(hostname)"
echo "OS: $(lsb_release -ds 2>/dev/null || grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"')"
echo "KERNEL: $(uname -srm)"
echo "DATE: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
```

**Analyze:**
- Extract hostname, OS name + version, kernel version, and timestamp
- These values populate the report header: `Host: <hostname> | OS: <distro + version> | Date: <timestamp>`
- Flag: OS that is end-of-life or missing active security support

---

## 1. Filesystem Configuration [CIS-1]

### 1.1 Unused Filesystem Modules

```bash
for fs in cramfs freevxfs jffs2 hfs hfsplus squashfs udf; do
  result=$(modprobe -n -v $fs 2>/dev/null | grep -c "install /bin/true" || lsmod | grep -c "^$fs " || echo 0)
  echo "$fs: $([ "$result" -gt 0 ] && echo DISABLED || echo LOADED)"
done
```

**Analyze:**
- ✅ Pass: each filesystem shows DISABLED (blacklisted in modprobe.d)
- 🔴 Fail: any filesystem shows LOADED (increases attack surface)

### 1.2 /tmp Partition and Mount Options

```bash
findmnt /tmp
grep -E "\s/tmp\s" /proc/mounts
```

**Analyze:**
- ✅ Pass: /tmp is a separate mount with `nosuid`, `nodev`, `noexec` options
- ⚠️ Warning: /tmp exists but missing one of nosuid/nodev/noexec
- 🔴 Fail: /tmp is not a separate partition (shared with root)

### 1.3 /dev/shm Mount Options

```bash
grep -E "\s/dev/shm\s" /proc/mounts
```

**Analyze:**
- ✅ Pass: mounted with `nosuid,nodev,noexec`
- 🔴 Fail: any of those options missing

### 1.4 Sticky Bit on World-Writable Directories

```bash
df --local -P | awk 'NR!=1 {print $6}' | xargs -I'{}' find '{}' -xdev -type d -perm -0002 ! -perm -1000 2>/dev/null | head -20
```

**Analyze:**
- ✅ Pass: no output (all world-writable dirs have sticky bit)
- 🔴 Fail: any directory listed (privilege escalation risk)

---

## 2. Services [CIS-2]

### 2.1 Unnecessary Services Disabled

```bash
for svc in avahi-daemon cups rpcbind nfs-server ypserv tftp xinetd telnet rsync; do
  status=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
  echo "$svc: $status"
done
```

**Analyze:**
- ✅ Pass: all show `inactive` or `not-found`
- 🔴 Fail: any shows `active` — disable if not explicitly required

### 2.2 Time Synchronization Active

```bash
systemctl is-active chronyd 2>/dev/null || systemctl is-active systemd-timesyncd 2>/dev/null || systemctl is-active ntpd 2>/dev/null
timedatectl status 2>/dev/null | grep -E "(NTP|synchronized)"
```

**Analyze:**
- ✅ Pass: NTP service active and `NTP synchronized: yes`
- 🔴 Fail: no time sync service running (log timestamps unreliable, audit trails compromised)

---

## 3. Network Configuration [CIS-3]

### 3.1 IP Forwarding Disabled

```bash
# Docker detection (ip_forward = 1 is required for container networking)
if systemctl is-active docker &>/dev/null || command -v docker &>/dev/null; then
  echo "DOCKER_DETECTED=true"
else
  echo "DOCKER_DETECTED=false"
fi
sysctl net.ipv4.ip_forward
sysctl net.ipv6.conf.all.forwarding 2>/dev/null
```

**Analyze:**
- ✅ Pass: both return `= 0` (no Docker detected)
- ℹ️ Expected: `ip_forward = 1` when `DOCKER_DETECTED=true` — IP forwarding is a hard requirement for Docker container networking; do NOT flag as a finding on Docker hosts
- 🔴 Fail: either returns `= 1` AND `DOCKER_DETECTED=false` (host acting as unexpected router)

### 3.2 ICMP Redirects Disabled

```bash
sysctl net.ipv4.conf.all.accept_redirects
sysctl net.ipv4.conf.all.send_redirects
sysctl net.ipv4.conf.all.secure_redirects
```

**Analyze:**
- ✅ Pass: all return `= 0`
- 🔴 Fail: any returns `= 1` (susceptible to MITM routing attacks)

### 3.3 Source Routing Disabled

```bash
sysctl net.ipv4.conf.all.accept_source_route
sysctl net.ipv6.conf.all.accept_source_route 2>/dev/null
```

**Analyze:**
- ✅ Pass: all return `= 0`
- 🔴 Fail: any returns `= 1`

### 3.4 TCP SYN Cookies Enabled

```bash
sysctl net.ipv4.tcp_syncookies
```

**Analyze:**
- ✅ Pass: returns `= 1` (SYN flood protection active)
- 🔴 Fail: returns `= 0`

### 3.5 Martian Packet Logging

```bash
sysctl net.ipv4.conf.all.log_martians
sysctl net.ipv4.conf.default.log_martians
```

**Analyze:**
- ✅ Pass: both return `= 1`
- ⚠️ Warning: returns `= 0` (suspicious spoofed packets won't be logged)

---

## 4. SSH Server Hardening [CIS-5.2]

### 4.1 SSH Configuration Audit

```bash
sshd -T 2>/dev/null | grep -iE "^(protocol|loglevel|maxauthtries|permitrootlogin|permitemptypasswords|passwordauthentication|x11forwarding|allowtcpforwarding|clientaliveinterval|clientalivecountmax|maxstartups|logingracetime|permituserenvironment|banner)"
```

**Analyze:**
- ✅ Pass: `permitrootlogin no`
- ✅ Pass: `passwordauthentication no`
- ✅ Pass: `permitemptypasswords no`
- ✅ Pass: `x11forwarding no`
- ✅ Pass: `maxauthtries` ≤ 4
- ✅ Pass: `loglevel VERBOSE` or `INFO`
- ✅ Pass: `clientaliveinterval` between 1 and 300
- ✅ Pass: `allowtcpforwarding no`
- 🔴 Fail: `permitrootlogin yes` — direct root SSH login allowed
- 🔴 Fail: `passwordauthentication yes` — brute-force risk
- ⚠️ Warning: `maxauthtries` > 4
- ⚠️ Warning: `x11forwarding yes`

### 4.2 SSH Host Key Permissions

```bash
ls -la /etc/ssh/ssh_host_*_key 2>/dev/null
stat -c "%a %U %G %n" /etc/ssh/ssh_host_*_key 2>/dev/null
```

**Analyze:**
- ✅ Pass: permissions `600`, owner `root:root`
- 🔴 Fail: any key readable by group or other (private key exposure)

---

## 5. User Accounts & Password Policy [CIS-5]

### 5.1 UID 0 Accounts (Root Equivalents)

```bash
awk -F: '$3 == 0 {print $1}' /etc/passwd
```

**Analyze:**
- ✅ Pass: only `root` listed
- 🔴 Fail: any other account with UID 0 (backdoor root account)

### 5.2 Accounts with Empty Passwords

```bash
awk -F: '($2 == "" || $2 == " ") {print $1}' /etc/shadow 2>/dev/null
```

**Analyze:**
- ✅ Pass: no output
- 🔴 Fail: any account listed (login without password possible)

### 5.3 Password Policy (login.defs)

```bash
grep -E "^(PASS_MAX_DAYS|PASS_MIN_DAYS|PASS_WARN_AGE)" /etc/login.defs
```

**Analyze:**
- ✅ Pass: `PASS_MAX_DAYS` ≤ 365, `PASS_MIN_DAYS` ≥ 1, `PASS_WARN_AGE` ≥ 7
- ⚠️ Warning: `PASS_MAX_DAYS 99999` (passwords never expire)

### 5.4 Inactive Account Lock

```bash
useradd -D | grep INACTIVE
```

**Analyze:**
- ✅ Pass: `INACTIVE=30` or less
- 🔴 Fail: `INACTIVE=-1` (inactive accounts never locked)

### 5.5 Accounts Without Valid Shell (Service Accounts)

```bash
awk -F: '($7 != "/usr/sbin/nologin" && $7 != "/bin/false" && $7 != "/sbin/nologin" && $3 >= 1000) {print $1, $7}' /etc/passwd
```

**Analyze:**
- ✅ Pass: only expected interactive users listed
- ⚠️ Warning: service accounts (mail, www-data, etc.) with valid shells — potential lateral movement path

### 5.6 Sudo Configuration

```bash
grep -r "NOPASSWD" /etc/sudoers /etc/sudoers.d/ 2>/dev/null
grep -r "ALL=(ALL)" /etc/sudoers /etc/sudoers.d/ 2>/dev/null | grep -v "^#"
```

**Analyze:**
- 🔴 Fail: `NOPASSWD:ALL` for any non-emergency account
- ⚠️ Warning: broad `ALL=(ALL) ALL` grants — review if necessary

---

## 6. Audit & Logging [CIS-4]

### 6.1 Auditd Status

```bash
systemctl is-active auditd 2>/dev/null
auditctl -s 2>/dev/null | grep -E "(enabled|backlog)"
```

**Analyze:**
- ✅ Pass: `active` and `enabled 1`
- 🔴 Fail: auditd not running (no audit trail)

### 6.2 Audit Rules Coverage

```bash
auditctl -l 2>/dev/null | grep -E "(sudoers|passwd|shadow|group|ssh|login|mount|chmod|chown|unlink|rename|rmdir)"
```

**Analyze:**
- ✅ Pass: rules covering `/etc/passwd`, `/etc/shadow`, `/etc/sudoers`, `chmod`, `chown`
- ⚠️ Warning: missing rules for key files (audit gaps)

### 6.3 Rsyslog / Journald Active

```bash
systemctl is-active rsyslog 2>/dev/null || systemctl is-active syslog 2>/dev/null
journalctl --disk-usage 2>/dev/null
```

**Analyze:**
- ✅ Pass: logging service active
- 🔴 Fail: no logging service running (blind to all events)

### 6.4 Log File Permissions

```bash
stat -c "%a %U %G %n" /var/log/auth.log /var/log/syslog /var/log/kern.log 2>/dev/null
```

**Analyze:**
- ✅ Pass: permissions `640` or more restrictive, owner `root`
- 🔴 Fail: world-readable logs (`644` or `666`) — may expose credentials

---

## 7. File Permissions & SUID/SGID [CIS-6]

### 7.1 World-Writable Files

```bash
df --local -P | awk 'NR!=1 {print $6}' | xargs -I'{}' find '{}' -xdev -type f -perm -0002 2>/dev/null | grep -v "/proc" | head -20
```

**Analyze:**
- ✅ Pass: no output
- 🔴 Fail: any file listed (writable by all users — malware drop point)

### 7.2 SUID Executables

```bash
find / -xdev -perm -4000 -type f 2>/dev/null | sort
```

**Analyze:**
- Compare against known-good SUID list: `passwd`, `su`, `sudo`, `ping`, `mount`, `umount`, `newgrp`, `chfn`, `chsh`, `gpasswd`
- 🔴 Fail: any unexpected SUID binary not in the known-good list (privilege escalation vector)
- ⚠️ Warning: interpreters with SUID (`python`, `perl`, `bash`, `sh`, `vim`) — immediate escalation risk

### 7.3 SGID Executables

```bash
find / -xdev -perm -2000 -type f 2>/dev/null | sort
```

**Analyze:**
- ⚠️ Warning: any unexpected SGID binary outside `/usr/bin`, `/usr/sbin`, `/bin`
- 🔴 Fail: shells or interpreters with SGID bit

### 7.4 Unowned Files and Directories

```bash
find / -xdev \( -nouser -o -nogroup \) -ls 2>/dev/null | head -20
```

**Analyze:**
- ✅ Pass: no output
- ⚠️ Warning: any files found — may be leftover from deleted accounts or installed packages
