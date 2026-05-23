---
mode: claude
priority: 2
---

## Security Tool Awareness

This context loads only for cloud models with large context windows.
Local models receive the compact runbook catalog in default.md instead.

### Runbook vs Ad-Hoc Decision Guide

Prefer a runbook when the task is multi-step, generates large output for analysis, or benefits from structured reporting. Use `<mcp:security>` or `<mcp:terminal>` for quick one-off checks.

| User intent | Recommended approach |
|---|---|
| "is this server hardened?" / "CIS check" | `neo-run cis-linux-assessment` |
| "check Docker security" / "container audit" | `neo-run docker-security` |
| "check for backdoors" / "persistence" / "rootkit" | `neo-run threat-hunting-persistence` |
| "server may be compromised" / "was it hacked?" | `neo-run linux-forensics` → then `neo-run incident-response` |
| "suspicious traffic" / "C2" / "beaconing" | `neo-run network-threat-hunting` |
| "check web logs for attacks" | `neo-run webserver-log-analysis` |
| "daily health check" | `neo-run linux-server-health` or `neo-run homeserver-runbook` |
| "check open ports" / "who is logged in?" | `<mcp:security>ports</mcp:security>` / `<mcp:security>logins</mcp:security>` |
| "any persistence on this box?" | `<mcp:security>authorized-keys</mcp:security>` + `<mcp:security>ld-preload</mcp:security>` |
| "check for rootkits" | `<mcp:security>rootkits</mcp:security>` |
| "any NOPASSWD sudo?" | `<mcp:security>nopasswd-sudo</mcp:security>` |
| "show active connections" | `<mcp:security>connections</mcp:security>` |

### Security CLI Tool Reference

**Scanning & Vulnerability Assessment**
- `nmap` — network/port scanner. `nmap -sV -O <target>`, `nmap --script vuln <target>`
- `trivy` — container CVE scanner. `trivy image <image>`, `trivy fs .`
- `grype` — SBOM vulnerability scanner. `grype dir:. --severity high`
- `lynis` — comprehensive host security audit. `lynis audit system`
- `nikto` — web server scanner. `nikto -h http://<target>`
- `nuclei` — CVE/template scanner. `nuclei -u http://<target> -severity high,critical`
- `testssl.sh` — TLS/SSL configuration check. `testssl.sh <host>:443`

**Host-Based Detection & Hardening**
- `rkhunter` — rootkit hunter. `rkhunter --check --skip-keypress`
- `chkrootkit` — rootkit/backdoor checker. `chkrootkit`
- `aide` — file integrity monitor. `aide --check` (requires DB init first)
- `osquery` — SQL host interrogation. `osqueryi "SELECT * FROM listening_ports;"`
- `auditctl` — Linux audit rules. `auditctl -l` (list), `auditctl -w /etc/passwd -p wa`
- `lynis` — security audit & hardening guide. `lynis audit system --quiet`

**Malware Analysis**
- `yara` — pattern matching. `yara rules.yar /suspicious/dir/`
- `strings` — printable strings from binaries. `strings -n 8 binary | grep -iE "http|cmd|bash"`
- `binwalk` — firmware/binary analysis. `binwalk -e firmware.bin`
- `volatility3` — memory forensics. `python3 vol.py -f mem.dmp windows.pslist`
- `foremost` — file carving. `foremost -i image.dd -o output/`
- `upx` — unpack UPX-packed malware. `upx -d packed_binary`
- `peepdf` — malicious PDF analysis. `peepdf -i suspicious.pdf`

**Network Analysis**
- `tcpdump` — packet capture. `tcpdump -i any -w cap.pcap 'not port 22'`
- `tshark` — CLI Wireshark. `tshark -r cap.pcap -Y "http.request" -T fields -e ip.src -e http.request.uri`
- `zeek` — network traffic analysis. `zeek -r cap.pcap` (generates conn.log, dns.log, etc.)
- `suricata` — IDS/IPS. `suricata -r cap.pcap -l logs/`
- `fail2ban-client` — brute-force status. `fail2ban-client status sshd`
- `arpwatch` — ARP change detection daemon
- `ss` / `netstat` — socket statistics. `ss -tunap`, `ss -tan state established`

**Web Application Security**
- `sqlmap` — SQL injection (authorized only). `sqlmap -u "http://target/page?id=1" --dbs`
- `ffuf` — web fuzzer. `ffuf -w wordlist.txt -u http://target/FUZZ -fc 404`
- `gobuster` — directory/DNS brute-forcer. `gobuster dir -u http://target -w common.txt`
- `curl` — manual HTTP probing. `curl -sv -H "X-Custom: test" http://target/endpoint`

**OSINT & Reconnaissance**
- `subfinder` — passive subdomain discovery. `subfinder -d domain.com`
- `amass` — attack surface mapping. `amass enum -d domain.com`
- `theHarvester` — emails/hosts/DNS gathering. `theHarvester -d domain.com -b all`
- `dnstwist` — typosquatting detection. `dnstwist domain.com --registered`
- `whois` / `dig` — domain info. `whois domain.com`, `dig +short MX domain.com`

**Secrets & Supply Chain**
- `gitleaks` — secrets in git history. `gitleaks detect --source .`
- `trufflehog` — deep secret scanning. `trufflehog git file://./repo --only-verified`
- `syft` — SBOM generator. `syft dir:. -o spdx-json > sbom.json`
- `grype` — scan SBOM for CVEs. `grype sbom:./sbom.json`
- `semgrep` — SAST. `semgrep --config=auto src/`
- `checkov` — IaC security. `checkov -d . --framework terraform`

**Forensics & Evidence Collection**
- `sleuthkit` — disk forensics. `fls -r image.dd`, `icat image.dd <inode>`
- `dc3dd` / `dcfldd` — forensic disk imaging with hash. `dc3dd if=/dev/sda hash=sha256 of=image.dd`
- `hindsight` — browser forensics. `hindsight -i "~/.config/google-chrome/Default" -o report`
- `volatility3` — memory analysis. `python3 vol.py -f mem.dmp linux.pslist`
- `velociraptor` — IR collection agent. `velociraptor -v artifacts collect Linux.Sys.Users`

### Security Output Analysis Rules

When analysing output from security commands or runbooks:

- **Report exact values verbatim**: IPs, hashes, timestamps, usernames, file paths. Never paraphrase or round.
- **Classify findings**: ✅ Benign / ⚠️ Suspicious / 🔴 IOC — always include a one-line justification.
- **MITRE ATT&CK tags**: For any 🔴 IOC, add the technique if applicable (e.g., `T1053.003 — Scheduled Task/Cron`).
- **Cross-reference**: A single anomaly may be noise. Overlapping indicators (e.g., SUID binary + cron job + new user account) confirm compromise.
- **Containment boundary**: Clearly separate "collect and observe" actions (safe, no approval needed) from "kill / remove / block" actions (always require explicit user approval).
- **Severity escalation triggers**: Recommend immediate isolation if: active outbound shell detected, attacker appears live, ransomware indicators found, data exfiltration in progress.
