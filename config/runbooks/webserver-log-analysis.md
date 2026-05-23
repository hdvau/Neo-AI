# Web Server Log Analysis — Intrusion Detection

## Agent Instructions

You are analyzing web server logs (nginx/Apache) for signs of intrusion, scanning, and exploitation.
This runbook is READ-ONLY — analyze logs, do not modify web server config or block IPs directly.

Focus on: attack patterns (SQLi, XSS, path traversal, webshell), scanners, error spikes,
unusual user agents, and anomalous IP behavior.

Adapt paths to what exists on this system — check both nginx and Apache log locations.
If a log file is not found, note it as UNKNOWN and continue.

Rules:
- 🔴 Attack: confirmed exploitation attempt or webshell interaction
- ⚠️ Suspicious: scanning, probing, or unusual behavior
- ✅ Benign: known bot, CDN, or expected traffic
- Include the source IP and timestamp for every finding

## Agent Output Format

```
WEB SERVER LOG ANALYSIS
Host: <hostname>  |  Log period: <first entry> → <last entry>  |  Date: <timestamp>
Server: nginx <version> / Apache <version>

ATTACK FINDINGS
| Timestamp           | Source IP     | Attack Type      | URL                | Risk |
|---------------------|---------------|------------------|--------------------|------|
| 2024-01-15 03:12:44 | 185.220.x.x  | SQL Injection    | /login.php?id=1 OR | 🔴   |

TOP ATTACKING IPs
| IP            | Requests | Attack Types           | First seen |
|---------------|----------|------------------------|------------|

SCANNER SIGNATURES DETECTED
- <tool name> from <IP>

RECOMMENDATIONS
1. Block <IP range> — <reason>
2. Patch <vulnerability> — <affected endpoint>
```

## Baseline Reference

- Normal 4xx rate: < 5% of total requests
- Normal 5xx rate: < 1% of total requests
- Suspicious: single IP with > 100 requests in 10 minutes
- Scanner indicators: `/wp-admin`, `/.env`, `/phpmyadmin`, `/manager/html` in logs on non-WordPress/PHP/Tomcat servers

---

## 0. Log File Discovery

```bash
ls -lh /var/log/nginx/*.log /var/log/nginx/access.log /var/log/nginx/error.log 2>/dev/null
ls -lh /var/log/apache2/*.log /var/log/apache2/access.log /var/log/apache2/error.log 2>/dev/null
ls -lh /var/log/httpd/*.log /var/log/httpd/access_log /var/log/httpd/error_log 2>/dev/null
find /var/log -name "*access*" -o -name "*error*" 2>/dev/null | grep -v ".gz" | head -10
```

**Analyze:**
- Identify which log files exist and their sizes
- Note the time range covered by each log
- If logs are very large (>1GB), subsequent commands will sample the last 100k lines

---

## 1. Traffic Overview

### 1.1 Log Time Range and Volume

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && echo "=== $log ===" && wc -l "$log" && head -1 "$log" && tail -1 "$log"
done
```

**Analyze:**
- Record total request count and time range for context
- ⚠️ Suspicious: log file truncated to zero bytes (evidence wiping)

### 1.2 Request Rate by Hour

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log; do
  [ -f "$log" ] && awk '{print $4}' "$log" | cut -d: -f2 | sort | uniq -c | sort -k2 -n 2>/dev/null
done
```

**Analyze:**
- Identify traffic spikes at unusual hours (3–5 AM local time)
- ⚠️ Suspicious: sudden 10x traffic spike (DDoS, scan, or crawler)

### 1.3 HTTP Status Code Distribution

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && echo "=== $log ===" && awk '{print $9}' "$log" 2>/dev/null | sort | uniq -c | sort -rn
done
```

**Analyze:**
- ✅ Healthy: 2xx dominant, < 5% 4xx, < 1% 5xx
- ⚠️ Suspicious: high 404 rate from a single IP (directory scanning)
- ⚠️ Suspicious: high 403 rate (blocked access attempts to restricted areas)
- 🔴 Attack: high 500 rate from specific endpoints (possible SQLi/code injection causing errors)

---

## 2. Attack Pattern Detection

### 2.1 SQL Injection Patterns

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && grep -iE "(union.+select|select.+from|insert.+into|drop.+table|or.+1=1|and.+1=1|'.+or.+'|%27.+or|xp_cmdshell|information_schema|sleep\([0-9]|benchmark\(|waitfor.+delay)" "$log" | tail -20
done
```

**Analyze:**
- 🔴 Attack: any SQL keyword combinations in URL parameters
- Note source IP and targeted endpoint — these indicate active exploitation attempts

### 2.2 Cross-Site Scripting (XSS)

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && grep -iE "(<script|%3cscript|javascript:|onerror=|onload=|alert\(|document\.cookie|%3Cscript|<img.+onerror|<svg.+onload)" "$log" | tail -20
done
```

**Analyze:**
- 🔴 Attack: XSS payloads in URL parameters or form submissions
- Note if attack reached 200 status (potential stored XSS)

### 2.3 Path Traversal & Local File Inclusion

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && grep -iE "(\.\./|\.\.\%2f|%2e%2e%2f|%252e%252e|/etc/passwd|/etc/shadow|/proc/self|/var/log|boot\.ini|win\.ini)" "$log" | tail -20
done
```

**Analyze:**
- 🔴 Attack: path traversal attempts to read `/etc/passwd`, `/etc/shadow`, or other sensitive files
- 🔴 Attack: if response was 200 — attacker may have successfully read the file

### 2.4 Remote File Inclusion & Command Injection

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && grep -iE "(http://|https://).+(php\?|=http|include=|require=|cmd=|exec=|system=|passthru=|eval=|base64_decode)" "$log" | tail -20
done
```

**Analyze:**
- 🔴 Attack: RFI/RCE via parameter injection
- 🔴 Attack: `cmd=`, `exec=`, `system=` in URLs — confirmed command injection attempt

### 2.5 Webshell Interaction Patterns

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && grep -iE "POST.*(\.php|\.jsp|\.aspx).*(cmd|exec|shell|upload|eval|system|base64)" "$log" | tail -20
done
```

**Analyze:**
- 🔴 Attack: POST requests to PHP/JSP files with command-related parameters
- 🔴 Attack: repeated POST requests from a single IP to the same script (active webshell use)
- Cross-reference: check if the file exists on disk with `find /var/www -name "<filename>"`

---

## 3. Scanner & Reconnaissance Detection

### 3.1 Common Scanner Signatures

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && grep -iE "(nikto|nmap|sqlmap|masscan|acunetix|nessus|openvas|burpsuite|zgrab|dirbuster|gobuster|ffuf|wfuzz|nuclei|w3af|skipfish)" "$log" | awk '{print $1,$7}' | sort -u | head -20
done
```

**Analyze:**
- ⚠️ Suspicious: any scanner signature — active security tool targeting this server
- Note: could be authorized pentest (confirm with server owner) or malicious reconnaissance

### 3.2 Directory Enumeration (404 Storms)

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && awk '$9==404 {print $1}' "$log" 2>/dev/null | sort | uniq -c | sort -rn | head -10
done
```

**Analyze:**
- ⚠️ Suspicious: single IP generating >100 404s (directory/file enumeration)
- 🔴 Attack: rapid 404 pattern followed by a 200 (scanner found something)

### 3.3 Common Attack Probe Paths

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && grep -iE "(\.(env|git|svn|bak|old|backup|config|conf|sql|zip|tar|gz|log)|wp-admin|wp-login|phpmyadmin|adminer|manager/html|\.well-known/.*\.php|/api/v[0-9]+/.*\.\.|/cgi-bin/)" "$log" | awk '{print $7}' | sort | uniq -c | sort -rn | head -20
done
```

**Analyze:**
- ⚠️ Suspicious: probes for `.env`, `.git`, config files (credential harvesting)
- ⚠️ Suspicious: WordPress-specific paths on a non-WordPress server (automated scanner)
- 🔴 Attack: successful (200) access to `.env` or `.git/config`

---

## 4. IP Analysis

### 4.1 Top Requesting IPs

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && echo "=== $log ===" && awk '{print $1}' "$log" | sort | uniq -c | sort -rn | head -20
done
```

**Analyze:**
- Flag IPs with request counts far above the median
- ⚠️ Suspicious: single IP accounting for >10% of total requests
- Note: some CDN IPs may aggregate many users — check user agents before blocking

### 4.2 IPs with High Error Rates

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && awk '$9 ~ /^[45]/ {print $1}' "$log" 2>/dev/null | sort | uniq -c | sort -rn | head -15
done
```

**Analyze:**
- 🔴 Attack: IPs generating mostly 4xx/5xx (scanner behavior)
- ⚠️ Suspicious: IPs with >50 errors in the log period

### 4.3 Geographic Anomalies (via reverse DNS)

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && awk '{print $1}' "$log" | sort -u | head -20 | xargs -I{} host {} 2>/dev/null | head -20
done
```

**Analyze:**
- Flag IPs resolving to Tor exit nodes, bulletproof hosting, or unexpected countries
- ⚠️ Suspicious: IPs from regions this server has no legitimate user base

---

## 5. User Agent Analysis

### 5.1 Top User Agents

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && awk -F'"' '{print $6}' "$log" | sort | uniq -c | sort -rn | head -20
done
```

**Analyze:**
- ⚠️ Suspicious: empty user agent (`"-"`) — automated tools often omit this
- ⚠️ Suspicious: generic user agents (`python-requests`, `Go-http-client`, `curl/`)
- 🔴 Attack: scanner user agents (`Nikto`, `sqlmap`, `Nessus`, `Acunetix`, `Nuclei`)
- Flag: unusually old user agents (IE 6/7, old Chrome) — may be spoofed or vulnerability scanner

### 5.2 Requests with No User Agent

```bash
for log in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/httpd/access_log; do
  [ -f "$log" ] && awk -F'"' '$6=="-" || $6=="" {print $1}' "$log" | sort | uniq -c | sort -rn | head -10
done
```

**Analyze:**
- ⚠️ Suspicious: high volume of requests with no user agent from a single IP

---

## 6. Error Log Analysis

### 6.1 Nginx/Apache Error Log

```bash
tail -100 /var/log/nginx/error.log 2>/dev/null || tail -100 /var/log/apache2/error.log 2>/dev/null || tail -100 /var/log/httpd/error_log 2>/dev/null
```

**Analyze:**
- 🔴 IOC: PHP errors including eval, base64_decode, system, exec — code injection succeeding
- 🔴 IOC: file inclusion errors pointing to `/etc/passwd`, `/proc/` (LFI attempt partially succeeded)
- ⚠️ Suspicious: repeated permission denied errors to sensitive directories
- ⚠️ Suspicious: upstream connection failures to backend services during attack window

### 6.2 PHP Error Patterns (if PHP app)

```bash
grep -iE "(eval\(|base64_decode|system\(|exec\(|passthru\(|shell_exec)" /var/log/nginx/error.log /var/log/apache2/error.log /var/log/php*.log 2>/dev/null | tail -20
```

**Analyze:**
- 🔴 IOC: PHP function abuse in error logs — attacker successfully executed server-side code
