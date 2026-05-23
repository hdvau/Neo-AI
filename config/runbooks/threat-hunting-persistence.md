# Linux Threat Hunting — Persistence Mechanisms

## Agent Instructions

You are hunting for persistence mechanisms on a live Linux system.
Adversaries establish persistence to survive reboots and maintain access after initial compromise.
This runbook is read-only — collect and analyze, do not remove anything.

Focus areas: cron, systemd, shell profiles, SSH keys, SUID/SGID, LD_PRELOAD, init scripts, kernel modules.
Cross-reference findings: a single unusual entry may be noise; the same actor often plants multiple overlapping mechanisms.

Rules:
- 🔴 High confidence: clearly malicious pattern (reverse shell in cron, unusual SUID binary)
- ⚠️ Suspicious: warrants manual investigation
- ✅ Benign: known-good or expected
- **UNKNOWN**: command errored or returned nothing useful

## Agent Output Format

```
PERSISTENCE HUNT REPORT
Host: <hostname>  |  Date: <timestamp>

EXECUTIVE SUMMARY
- <finding 1>
- <finding 2>
...

CONFIRMED SUSPICIOUS (investigate immediately)
| Mechanism     | Location              | Detail                    | Risk  |
|---------------|-----------------------|---------------------------|-------|
| cron          | /etc/cron.d/update    | wget|bash to external IP   | 🔴    |

NEEDS REVIEW
| Mechanism     | Location              | Detail                    |
|---------------|-----------------------|---------------------------|

MITRE ATT&CK TECHNIQUES OBSERVED
- T1053.003: Cron | T1543.002: Systemd | T1546.004: .bashrc | T1098: SSH Keys

RECOMMENDED ACTIONS (prioritized)
1. ...
```

## Baseline Reference

- Expected cron jobs: system package manager timers, logrotate, unattended-upgrades
- Expected systemd user services: none unless documented
- Expected SUID binaries: passwd, su, sudo, ping, mount, umount, newgrp, chfn, chsh, gpasswd
- Expected kernel modules: standard distro modules only

---

## 1. Cron Jobs [T1053.003]

### 1.1 System-Wide Crontabs

```bash
echo "=== /etc/crontab ===" && cat /etc/crontab 2>/dev/null
echo "=== /etc/cron.d/ ===" && ls -la /etc/cron.d/ 2>/dev/null && cat /etc/cron.d/* 2>/dev/null
echo "=== /etc/cron.daily/ ===" && ls -la /etc/cron.daily/ 2>/dev/null
echo "=== /etc/cron.weekly/ ===" && ls -la /etc/cron.weekly/ 2>/dev/null
echo "=== /etc/cron.monthly/ ===" && ls -la /etc/cron.monthly/ 2>/dev/null
```

**Analyze:**
- 🔴 High: any entry running `wget`, `curl`, `nc`, `bash -i`, `python -c`, `perl -e`, `/tmp/*`, `/dev/shm/*`
- 🔴 High: base64-encoded payloads in cron commands
- ⚠️ Suspicious: cron jobs added/modified recently (check mtime vs expected)
- ⚠️ Suspicious: cron jobs running as root that download or pipe to shell
- ✅ Benign: `logrotate`, `apt`, `unattended-upgrades`, `updatedb`, `find /tmp`

### 1.2 User Crontabs

```bash
for user in $(cut -d: -f1 /etc/passwd); do
  crontab_out=$(crontab -u "$user" -l 2>/dev/null)
  if [ -n "$crontab_out" ]; then
    echo "=== $user ==="; echo "$crontab_out"
  fi
done
```

**Analyze:**
- 🔴 High: crontab for service accounts (`www-data`, `nobody`, `daemon`) with shell commands
- 🔴 High: reverse shell patterns (`/dev/tcp/`, `ncat`, `bash -i >&`)
- ⚠️ Suspicious: any crontab for a user that should not have scheduled tasks

### 1.3 Anacron Jobs

```bash
cat /etc/anacrontab 2>/dev/null
ls -la /var/spool/anacron/ 2>/dev/null
```

**Analyze:**
- ⚠️ Suspicious: additional anacron jobs not present in stock install

---

## 2. Systemd Persistence [T1543.002]

### 2.1 Non-Package-Managed Service Units

```bash
find /etc/systemd/system /lib/systemd/system /usr/lib/systemd/system -name "*.service" -newer /etc/passwd 2>/dev/null | head -30
```

**Analyze:**
- ⚠️ Suspicious: any `.service` file newer than `/etc/passwd` that was not expected
- 🔴 High: service units with `ExecStart` pointing to `/tmp`, `/dev/shm`, home directories, or base64 commands

### 2.2 All Enabled Services (Non-Standard)

```bash
systemctl list-unit-files --type=service --state=enabled --no-legend 2>/dev/null | grep -vE "(apt|cron|ssh|docker|ufw|rsyslog|systemd|getty|login|network|dns|ntp|time|dbus|journald|udev|polkit|pam|accounts|udisks|power|bluetooth|avahi|cups)"
```

**Analyze:**
- ⚠️ Suspicious: any enabled service not recognized as part of the installed software
- 🔴 High: services with generic names (`update.service`, `helper.service`, `sync.service`)

### 2.3 User-Level Systemd Units

```bash
find /home /root -name "*.service" -o -name "*.timer" 2>/dev/null | head -20
find /home /root -path "*/.config/systemd/user/*.service" 2>/dev/null
```

**Analyze:**
- ⚠️ Suspicious: any user-level systemd service (runs without root but persists per-user login)
- 🔴 High: user services with network callback commands

### 2.4 Systemd Timers

```bash
systemctl list-timers --all --no-legend 2>/dev/null | grep -v "systemd-"
```

**Analyze:**
- Flag: timers with frequent schedules (every minute) for unknown units
- ⚠️ Suspicious: timers associated with unrecognized service names

---

## 3. Shell Profile Modifications [T1546.004]

### 3.1 System-Wide Shell Profiles

```bash
echo "=== /etc/profile ===" && cat /etc/profile 2>/dev/null
echo "=== /etc/profile.d/ ===" && ls -la /etc/profile.d/ 2>/dev/null && cat /etc/profile.d/*.sh 2>/dev/null
echo "=== /etc/bash.bashrc ===" && cat /etc/bash.bashrc 2>/dev/null
echo "=== /etc/environment ===" && cat /etc/environment 2>/dev/null
```

**Analyze:**
- 🔴 High: any `curl|bash`, `wget|sh`, reverse shell, or LD_PRELOAD injection in these files
- ⚠️ Suspicious: added entries not part of the standard distro install
- Note modification times of all files

### 3.2 User Shell Profiles

```bash
for dir in /root /home/*/; do
  for f in .bashrc .bash_profile .profile .zshrc .zprofile .bash_logout; do
    [ -f "$dir/$f" ] && echo "=== $dir/$f ===" && cat "$dir/$f" 2>/dev/null
  done
done
```

**Analyze:**
- 🔴 High: reverse shell or network callback in any of these files
- 🔴 High: `alias` overriding common commands (`alias ls='ls;curl...'`, `alias sudo='...'`)
- ⚠️ Suspicious: `export PATH` modified to include unusual directories (e.g., `/tmp`, `/dev/shm`)
- ⚠️ Suspicious: LD_PRELOAD set for a user

### 3.3 Recently Modified Profile Files

```bash
find /etc /root /home -maxdepth 3 \( -name ".bashrc" -o -name ".bash_profile" -o -name ".profile" -o -name ".zshrc" -o -name "*.sh" \) -newer /etc/passwd -ls 2>/dev/null
```

**Analyze:**
- ⚠️ Suspicious: any profile file modified more recently than `/etc/passwd` (system install baseline)

---

## 4. SSH Authorized Keys [T1098.004]

### 4.1 All Authorized Keys Files

```bash
find /root /home -name "authorized_keys" -exec echo "=== {} ===" \; -exec cat {} \; 2>/dev/null
find /etc/ssh -name "authorized_keys*" 2>/dev/null -exec cat {} \;
```

**Analyze:**
- 🔴 High: keys with `command=` prefix that restrict to a specific command (may be a backdoor shell)
- 🔴 High: keys added for root or privileged users not in the known-good list
- ⚠️ Suspicious: keys with `no-pty,no-agent-forwarding` restrictions stripped — unrestricted access
- ⚠️ Suspicious: authorized_keys file modified recently

### 4.2 SSH Keys Without Passphrases (Private Keys Accessible)

```bash
find /root /home -name "id_rsa" -o -name "id_ed25519" -o -name "id_ecdsa" 2>/dev/null | while read k; do
  echo "=== $k ===" && head -3 "$k" 2>/dev/null
done
```

**Analyze:**
- ⚠️ Suspicious: private keys not encrypted (`BEGIN RSA PRIVATE KEY` without `ENCRYPTED`)
- 🔴 High: private keys in unexpected locations (`/tmp`, `/var/www`, application directories)

---

## 5. SUID / SGID Binaries [T1548.001]

### 5.1 SUID Binaries

```bash
find / -xdev -perm -4000 -type f -ls 2>/dev/null | sort -k11
```

**Analyze:**
- Compare against known-good SUID list: `passwd`, `su`, `sudo`, `ping`, `mount`, `umount`, `newgrp`, `chfn`, `chsh`, `gpasswd`, `pkexec`, `fusermount`
- 🔴 High: any shell interpreter with SUID (`bash`, `sh`, `python`, `perl`, `vim`, `nano`, `find`, `awk`)
- 🔴 High: SUID binary in `/tmp`, `/dev/shm`, `/var/tmp`, or home directories
- ⚠️ Suspicious: SUID binaries not in `/usr/bin`, `/usr/sbin`, `/bin`, `/sbin`

### 5.2 SGID Binaries

```bash
find / -xdev -perm -2000 -type f -ls 2>/dev/null | sort -k11
```

**Analyze:**
- Flag unexpected SGID binaries outside standard system paths
- 🔴 High: shells or interpreters with SGID bit

### 5.3 Capabilities on Binaries

```bash
getcap -r / 2>/dev/null | grep -v "^$"
```

**Analyze:**
- 🔴 High: `cap_setuid`, `cap_setgid`, `cap_sys_admin`, `cap_net_admin=ep` on interpreters or shells
- ⚠️ Suspicious: capabilities on binaries outside `/usr/bin`, `/usr/sbin`
- ✅ Expected: `cap_net_raw` on `ping`, `cap_dac_read_search` on `dumpcap`

---

## 6. LD_PRELOAD Injection [T1574.006]

### 6.1 System-Wide Preload

```bash
cat /etc/ld.so.preload 2>/dev/null || echo "(file does not exist)"
```

**Analyze:**
- 🔴 High: ANY entry in `/etc/ld.so.preload` — this file intercepts ALL dynamic library loads system-wide
- The presence of this file with any content is almost always malicious on a production server

### 6.2 LD_PRELOAD in User Environments

```bash
grep -rh "LD_PRELOAD" /etc/environment /etc/profile /etc/profile.d/ /root /home 2>/dev/null | grep -v "^#"
```

**Analyze:**
- 🔴 High: LD_PRELOAD pointing to files in `/tmp`, `/dev/shm`, or home directories
- ⚠️ Suspicious: any LD_PRELOAD set to a file not part of a known software package

---

## 7. Init Scripts & rc.local [T1037]

### 7.1 rc.local and Init Scripts

```bash
cat /etc/rc.local 2>/dev/null
ls -la /etc/init.d/ 2>/dev/null
find /etc/init.d -newer /etc/passwd -type f 2>/dev/null
```

**Analyze:**
- ⚠️ Suspicious: `/etc/rc.local` exists and is non-empty (legacy but still executes on boot)
- 🔴 High: network callbacks or downloaders in rc.local
- ⚠️ Suspicious: init.d scripts newer than `/etc/passwd` not from a known package

### 7.2 At Jobs

```bash
atq 2>/dev/null
ls -la /var/spool/at/ 2>/dev/null
find /var/spool/at -type f 2>/dev/null | xargs cat 2>/dev/null
```

**Analyze:**
- ⚠️ Suspicious: any pending `at` jobs (rarely used legitimately in modern systems)
- 🔴 High: `at` jobs containing network callbacks

---

## 8. Kernel Modules [T1547.006]

### 8.1 Loaded Kernel Modules

```bash
lsmod | sort
```

**Analyze:**
- ⚠️ Suspicious: modules with generic names not matching known hardware or drivers
- 🔴 High: modules loaded from non-standard paths (rootkit indicator)

### 8.2 Recently Loaded or Modified Modules

```bash
find /lib/modules/$(uname -r) -name "*.ko" -newer /etc/passwd -ls 2>/dev/null | head -20
```

**Analyze:**
- ⚠️ Suspicious: kernel module files newer than system install baseline
- 🔴 High: `.ko` files in unexpected paths (not under `/lib/modules/$(uname -r)`)

### 8.3 Module Signing Status

```bash
cat /proc/sys/kernel/modules_disabled 2>/dev/null
grep "module.sig_enforce" /proc/cmdline 2>/dev/null || echo "(sig_enforce not in cmdline)"
```

**Analyze:**
- ✅ Pass: `modules_disabled=1` or `sig_enforce` in cmdline
- ⚠️ Warning: neither set (unsigned modules can be loaded — rootkit risk)

---

## 9. Recently Modified System Files [T1070]

### 9.1 Recently Modified Binaries and Config

```bash
find /usr/bin /usr/sbin /bin /sbin /usr/local/bin /usr/local/sbin -newer /etc/passwd -type f -ls 2>/dev/null
```

**Analyze:**
- ⚠️ Suspicious: any system binary modified after the OS install date (may be trojanized)
- 🔴 High: `ssh`, `sshd`, `sudo`, `su`, `passwd`, `login` modified after install — classic rootkit targets

### 9.2 Files Modified in /etc in Last 7 Days

```bash
find /etc -newer /etc/passwd -type f -not -path "*/\.*" -ls 2>/dev/null | sort -k8,9 | head -30
```

**Analyze:**
- Flag: `/etc/passwd`, `/etc/shadow`, `/etc/sudoers`, `/etc/hosts`, `/etc/crontab` modifications unexpected
- ⚠️ Suspicious: SSH config, PAM config, or nsswitch.conf changed unexpectedly

### 9.3 Files in World-Writable Locations

```bash
ls -la /tmp /var/tmp /dev/shm 2>/dev/null
find /tmp /var/tmp /dev/shm -type f -ls 2>/dev/null | head -30
```

**Analyze:**
- 🔴 High: executable files in `/tmp`, `/var/tmp`, `/dev/shm`
- 🔴 High: `.sh`, `.py`, `.pl`, `.elf` files in these locations
- ⚠️ Suspicious: hidden files (starting with `.`) in these directories
