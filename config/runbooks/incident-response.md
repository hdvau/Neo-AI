# Incident Response Playbook

## Agent Instructions

This runbook guides triage, containment, and eradication of an active security incident.
It is STRUCTURED — work through phases in order. Do not skip to eradication without completing triage.

IMPORTANT: All destructive actions (killing processes, blocking IPs, removing files) require
explicit user confirmation before execution. Present findings and recommended actions;
wait for the user to approve each containment step. This runbook collects and analyzes;
the user decides what to act on.

Phases:
1. TRIAGE — understand scope (read-only)
2. CONTAINMENT — isolate the threat (requires user approval per action)
3. EVIDENCE PRESERVATION — capture before cleanup
4. ERADICATION — remove attacker access (requires user approval)
5. RECOVERY VERIFICATION — confirm clean state

## Agent Output Format

```
INCIDENT RESPONSE REPORT
Host: <hostname>  |  Incident start: <time>  |  IR start: <time>
Classification: [Malware | Unauthorized Access | Ransomware | Cryptominer | Webshell | Unknown]
Severity: [P1-Critical | P2-High | P3-Medium]

PHASE 1 — TRIAGE FINDINGS
Scope: [Contained to this host | Potential lateral movement to: <IPs>]
Attacker entry point: <suspected vector>
Current attacker access: [Active | Likely dormant | Unclear]
Data exfiltration: [Confirmed | Suspected | No evidence]

PHASE 2 — CONTAINMENT ACTIONS (pending approval)
1. Block outbound to <IP> — [APPROVED/PENDING]
2. Kill process <PID> (<name>) — [APPROVED/PENDING]

PHASE 3 — EVIDENCE LOG
- Files preserved: <paths>
- Hashes recorded: yes/no

PHASE 4 — ERADICATION ACTIONS (pending approval)
1. Remove <file> — [APPROVED/PENDING]
2. Revoke SSH key for <user> — [APPROVED/PENDING]

PHASE 5 — RECOVERY VERIFICATION
- Clean state confirmed: yes/no
- Monitoring enhanced: yes/no
```

## Baseline Reference

- Escalate to P1 if: active attacker, data exfiltration confirmed, ransomware encrypting
- Escalate to P2 if: backdoor found, unauthorized access confirmed, cryptominer active
- Always preserve evidence before eradication

---

## PHASE 1 — TRIAGE (Read-Only) [Run immediately]

### T1. System Identity

```bash
hostname && date -u && uname -r && uptime
cat /etc/os-release | grep -E "^(NAME|VERSION)=" 2>/dev/null
```

**Analyze:**
- Record exact state at triage start — anchor for timeline reconstruction
- ⚠️ Anomaly: unexpected hostname or kernel version (OS tampering)

### T2. Active Attacker Presence

```bash
who && w
ss -tunap 2>/dev/null | grep -v "127.0.0.1\|::1" | grep ESTABLISHED
```

**Analyze:**
- 🔴 CRITICAL: active shell sessions from external IPs — attacker may be live
- 🔴 CRITICAL: shell or interpreter process with open outbound TCP socket
- If attacker appears live → recommend immediate network isolation before continuing

### T3. Suspicious Processes

```bash
ps auxf 2>/dev/null | grep -vE "(ps|grep|sshd|bash|python3.*neo|runbook)" | head -40
ls -la /proc/*/exe 2>/dev/null | grep -E "(deleted|/tmp|/dev/shm|/var/tmp)" | head -20
```

**Analyze:**
- 🔴 IOC: processes running from deleted paths — malware in memory after self-deletion
- 🔴 IOC: miners (`xmrig`, `minerd`, `cpuminer`), RATs, or backdoors by name
- Record all suspicious PIDs for containment phase

### T4. Recent Authentication Events

```bash
last -n 20 --time-format iso 2>/dev/null
journalctl -u ssh -u sshd --since "48 hours ago" 2>/dev/null | grep -E "(Accepted|Failed|Invalid)" | tail -30
```

**Analyze:**
- 🔴 IOC: successful logins from unexpected IPs in the last 48h
- Note: suspected entry point IP, time of first successful login

### T5. Entry Point Assessment

```bash
grep "Accepted" /var/log/auth.log 2>/dev/null | tail -20
grep -E "(POST|GET).*(cmd|exec|shell|eval|system|passthru)" /var/log/nginx/access.log /var/log/apache2/access.log 2>/dev/null | tail -20
find /var/www /srv -name "*.php" -newer /etc/passwd 2>/dev/null | head -10
```

**Analyze:**
- Identify the likely entry vector: SSH brute-force, webshell, supply chain, insider
- 🔴 IOC: POST requests to unusual PHP files (webshell interaction)
- 🔴 IOC: recently added .php files in web roots

### T6. Lateral Movement Scope

```bash
ss -tun 2>/dev/null | grep -E "192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\." | grep ESTABLISHED
for dir in /root /home/*/; do [ -f "$dir/.ssh/known_hosts" ] && echo "=== $dir ===" && cat "$dir/.ssh/known_hosts" 2>/dev/null; done
```

**Analyze:**
- 🔴 IOC: active connections to other internal hosts (lateral movement in progress)
- Record all internal IPs that may be compromised for escalation

---

## PHASE 2 — CONTAINMENT ACTIONS

**STOP HERE** — present Phase 1 findings to user and get approval for each action below.
Do NOT execute containment commands until explicitly approved.

### C1. Network Isolation (if attacker is live)

```bash
# PENDING APPROVAL — blocks all traffic except SSH from trusted IP
ufw default deny incoming && ufw default deny outgoing && ufw allow from <TRUSTED_IP> to any port 22
```

**Analyze:**
- Execute ONLY if attacker is confirmed live and user approves full isolation
- Risk: cuts all services — coordinate with stakeholders first

### C2. Block Specific Attacker IP

```bash
# PENDING APPROVAL
ufw insert 1 deny from <ATTACKER_IP> to any
iptables -I INPUT -s <ATTACKER_IP> -j DROP
iptables -I OUTPUT -d <ATTACKER_IP> -j DROP
```

**Analyze:**
- Targeted block — less disruptive than full isolation
- Does NOT help if attacker has persistence and can reconnect via a different IP

### C3. Terminate Attacker Session

```bash
# PENDING APPROVAL — shows active sessions for targeting
who -a
pkill -9 -t pts/<N>  # Replace <N> with attacker's terminal number
```

**Analyze:**
- Terminates a specific terminal session
- ⚠️ Warning: attacker may have persistence and reconnect immediately

### C4. Disable Compromised User Account

```bash
# PENDING APPROVAL
usermod -L <USERNAME>   # Lock the account
passwd -l <USERNAME>    # Lock password
```

**Analyze:**
- Prevents further logins via compromised credentials
- Does NOT terminate existing sessions — follow with C3

---

## PHASE 3 — EVIDENCE PRESERVATION

### E1. Capture Process List Before Changes

```bash
ps auxf 2>/dev/null > /tmp/ir_processes_$(date +%Y%m%d_%H%M%S).txt && echo "Saved"
ss -tunap 2>/dev/null > /tmp/ir_connections_$(date +%Y%m%d_%H%M%S).txt && echo "Saved"
```

**Analyze:**
- Confirm files were created
- These snapshots are critical if processes are killed in Phase 2

### E2. Hash Suspicious Files

```bash
find /tmp /var/tmp /dev/shm -type f 2>/dev/null | xargs md5sum 2>/dev/null
find /tmp /var/tmp /dev/shm -type f 2>/dev/null | xargs sha256sum 2>/dev/null
```

**Analyze:**
- Record all hashes — needed for threat intelligence lookup and legal evidence
- Submit hashes to VirusTotal: `curl -s https://www.virustotal.com/vtapi/v2/file/report?apikey=<KEY>&resource=<HASH>`

### E3. Capture Auth Logs

```bash
cp /var/log/auth.log /tmp/ir_auth_log_$(date +%Y%m%d_%H%M%S).bak 2>/dev/null && echo "Auth log preserved"
journalctl --since "7 days ago" --no-pager 2>/dev/null > /tmp/ir_journal_$(date +%Y%m%d_%H%M%S).txt && echo "Journal preserved"
```

**Analyze:**
- Confirm both files written successfully
- These may be the only evidence of attacker activity after eradication

### E4. Memory Dump (if volatility available)

```bash
which avml 2>/dev/null && echo "AVML available — run: avml /tmp/ir_memory_$(date +%Y%m%d_%H%M%S).lime" || echo "(AVML not installed — memory dump skipped)"
ls -la /proc/*/maps 2>/dev/null | grep -c "maps" && echo "processes in memory"
```

**Analyze:**
- Recommend memory capture only if legal/forensic requirements demand it
- Memory dumps can be very large — verify disk space before running

---

## PHASE 4 — ERADICATION

**STOP HERE** — present evidence to user. Get explicit approval for each removal action.

### R1. Remove Malicious Files

```bash
# PENDING APPROVAL — list first, then remove
ls -la /tmp /var/tmp /dev/shm 2>/dev/null
# After user approval:
# rm -f <specific file path>
```

**Analyze:**
- Never `rm -rf /tmp` blindly — list and selectively remove malicious files only
- Preserve hashes (Phase 3) before removal

### R2. Remove Malicious Cron Jobs

```bash
# PENDING APPROVAL — show then remove
crontab -l -u <USER> 2>/dev/null
# After user approval:
# crontab -r -u <USER>  OR edit specific entries: crontab -e -u <USER>
```

**Analyze:**
- Document what is removed — needed for post-incident report

### R3. Revoke Unauthorized SSH Keys

```bash
# PENDING APPROVAL — show first
find /root /home -name "authorized_keys" -exec cat {} \;
# After user approval — remove specific key lines:
# sed -i '/ATTACKER_KEY_FINGERPRINT/d' /home/<USER>/.ssh/authorized_keys
```

**Analyze:**
- Remove ONLY the unauthorized key — leave legitimate keys intact

### R4. Reset Compromised Credentials

```bash
# PENDING APPROVAL
passwd <USERNAME>   # Force password change
# Also rotate any API keys or tokens found in user environment
```

**Analyze:**
- Change passwords for all accounts that could have been compromised
- Rotate all API keys and tokens accessible from the compromised account

---

## PHASE 5 — RECOVERY VERIFICATION

### V1. Verify No Malicious Processes

```bash
ps aux 2>/dev/null | grep -E "(nc |ncat|socat|xmrig|minerd|cryptonight)" | grep -v grep
ls -la /tmp /var/tmp /dev/shm 2>/dev/null | grep -vE "^total|^d"
```

**Analyze:**
- ✅ Clean: no matches
- 🔴 Fail: eradication incomplete — repeat Phase 4

### V2. Verify No Unauthorized Accounts

```bash
awk -F: '$3 >= 1000 {print $1, $3}' /etc/passwd
awk -F: '$2 !~ /^[!*]/ {print $1}' /etc/shadow 2>/dev/null
```

**Analyze:**
- Confirm only expected user accounts exist
- ✅ Clean: matches the known-good user list

### V3. Verify Listening Services (No Backdoors)

```bash
ss -tlnup 2>/dev/null
```

**Analyze:**
- ✅ Clean: only expected services listening
- 🔴 Fail: unexpected listener still present — persistence not fully eradicated

### V4. Verify Firewall Active

```bash
ufw status verbose 2>/dev/null || iptables -L -n --line-numbers 2>/dev/null | head -20
```

**Analyze:**
- ✅ Pass: firewall active and blocking unexpected inbound
- Confirm rules tightened as part of containment are still in place

### V5. Enable Enhanced Logging

```bash
# Check if auditd is collecting the right events post-incident
auditctl -l 2>/dev/null | wc -l
systemctl is-active auditd 2>/dev/null
systemctl is-active fail2ban 2>/dev/null
```

**Analyze:**
- Confirm auditd has rules in place post-incident
- Confirm fail2ban is active (and tuned if brute-force was the entry vector)
- Recommend: increase log retention period and set up alerting for repeat IOCs
