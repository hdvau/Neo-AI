# Network Threat Hunting — C2, Exfiltration & Anomalies

## Agent Instructions

You are hunting for network-based threats: C2 beaconing, DNS exfiltration, lateral movement,
and unusual outbound traffic from this Linux host.

This runbook is READ-ONLY — no traffic blocking or firewall changes.
Focus on: regularity of connections (beaconing), unusual destinations, DNS anomalies, and
traffic patterns that don't match normal service behavior.

Rules:
- 🔴 IOC: strong indicator of C2/exfiltration/attack
- ⚠️ Suspicious: warrants investigation — could be legitimate
- ✅ Benign: recognized service or known-good pattern
- Cross-reference IPs against your known-good list (package mirrors, CDNs, monitoring)

## Agent Output Format

```
NETWORK THREAT HUNT REPORT
Host: <hostname>  |  Date: <timestamp>  |  Primary IP: <ip>

SUSPICIOUS CONNECTIONS
| Destination IP:Port | Protocol | Process/PID | Pattern         | Risk |
|---------------------|----------|-------------|-----------------|------|
| 185.220.x.x:443    | TCP      | python3/1234| periodic 60s    | 🔴   |

DNS ANOMALIES
| Query                        | Count | Pattern          | Risk |
|------------------------------|-------|------------------|------|
| a.b.c.d.long-domain.xyz      | 847   | high entropy     | 🔴   |

RECOMMENDED ACTIONS
1. Block outbound to <IP> at firewall level
2. Isolate host if C2 confirmed
```

## Baseline Reference

- Expected outbound destinations: Debian/Ubuntu mirrors, Docker Hub, NTP pool, GitHub
- Expected listening ports: 22 (SSH), 80/443 (if web server), any app-specific ports
- Normal DNS: short names, low query rate, resolvable to known CDN/cloud ranges
- Beaconing threshold: connections to same external IP at intervals < 5 minutes = suspicious

---

## 1. Active Connections — C2 Beaconing [T1071]

### 1.1 All External Connections Right Now

```bash
ss -tunap 2>/dev/null | grep -v "127.0.0.1\|::1\|0\.0\.0\.0\*"
```

**Analyze:**
- List all ESTABLISHED external connections with process and PID
- 🔴 IOC: shell (`bash`, `sh`, `dash`) or interpreter (`python`, `perl`, `ruby`) with outbound TCP
- 🔴 IOC: connections to Tor exit nodes, known C2 hosting ranges (e.g., 185.220.x.x, 198.199.x.x)
- ⚠️ Suspicious: outbound connections on port 443 from non-web-server processes
- ⚠️ Suspicious: connections to IPs in unusual geographic regions for this server's purpose

### 1.2 Connection Count by Destination

```bash
ss -tun 2>/dev/null | awk 'NR>1 {print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn | head -20
```

**Analyze:**
- ⚠️ Suspicious: many connections to the same external IP (beaconing or data transfer)
- 🔴 IOC: >50 connections to a single IP that is not a known CDN/mirror

### 1.3 Connection History via Netstat/ss Socket States

```bash
ss -tan 2>/dev/null | awk '{print $1}' | sort | uniq -c | sort -rn
ss -tan state time-wait 2>/dev/null | awk '{print $4}' | cut -d: -f1 | sort | uniq -c | sort -rn | head -10
```

**Analyze:**
- ⚠️ Suspicious: large number of TIME_WAIT to the same external IP (repeated short connections = beaconing)
- 🔴 IOC: TIME_WAIT connections to the same IP at regular intervals

### 1.4 Reverse Shell Indicators

```bash
ss -tunap 2>/dev/null | grep -E "(bash|sh|python|perl|ruby|nc|ncat|socat|meterpreter)"
lsof -i -P -n 2>/dev/null | grep -E "(bash|sh|python|perl|ruby|nc|ncat|socat)"
```

**Analyze:**
- 🔴 IOC: any match here is a confirmed reverse shell or bind shell

---

## 2. DNS Analysis — Tunneling & Exfiltration [T1071.004]

### 2.1 Recent DNS Query Log (systemd-resolved)

```bash
journalctl -u systemd-resolved --since "24 hours ago" 2>/dev/null | grep -i "query\|NXDOMAIN\|SERVFAIL" | tail -50
```

**Analyze:**
- 🔴 IOC: queries with very long subdomains (>50 chars) — DNS tunneling indicator
- 🔴 IOC: high volume queries to a single domain with varying subdomains (data exfiltration via DNS)
- ⚠️ Suspicious: NXDOMAIN storms — malware trying to reach dead C2 via DGA

### 2.2 DNS Queries via tcpdump (Short Capture)

```bash
timeout 30 tcpdump -i any -n port 53 2>/dev/null | head -60 || echo "(tcpdump not available or no permission)"
```

**Analyze:**
- 🔴 IOC: queries with high-entropy subdomain labels (e.g., `a3f9b2c1.evil.com`) — DGA or DNS tunnel
- ⚠️ Suspicious: queries to non-configured DNS servers (bypassing resolv.conf)
- Note: compare queried domains against the configured resolvers in `/etc/resolv.conf`

### 2.3 Current DNS Resolver Config

```bash
cat /etc/resolv.conf
resolvectl status 2>/dev/null | grep -E "(DNS Server|DNS Domain)"
```

**Analyze:**
- 🔴 IOC: DNS server changed to an unknown external IP (DNS hijacking)
- ⚠️ Suspicious: DNS server pointing to a VPS or unusual IP range

### 2.4 Hosts File Tampering

```bash
cat /etc/hosts | grep -v "^#" | grep -v "^$" | grep -v "localhost"
```

**Analyze:**
- 🔴 IOC: legitimate domains (google.com, apt.debian.org, github.com) redirected to non-standard IPs
- ⚠️ Suspicious: any unexpected entries added since system provisioning

---

## 3. Outbound Traffic Analysis [T1041]

### 3.1 Connections by Port

```bash
ss -tun 2>/dev/null | awk 'NR>1 {print $5}' | grep -oE ':[0-9]+$' | sort | uniq -c | sort -rn | head -20
```

**Analyze:**
- ⚠️ Suspicious: large volume of connections on non-standard ports (not 22, 80, 443, 53)
- 🔴 IOC: outbound connections on IRC ports (6667, 6697) — classic botnet C2
- 🔴 IOC: outbound connections on 4444, 4445, 1234, 8888 — common C2/shell ports

### 3.2 Bandwidth Usage by Process

```bash
nethogs -t -c 3 2>/dev/null | head -30 || \
  iftop -t -s 3 2>/dev/null | head -20 || \
  cat /proc/net/dev 2>/dev/null
```

**Analyze:**
- 🔴 IOC: high outbound bandwidth from unexpected processes (data exfiltration)
- ⚠️ Suspicious: consistent low-rate outbound from system processes (slow exfil or beaconing)

### 3.3 Recent Connection Log (if fail2ban/ufw active)

```bash
grep -E "(UFW|BLOCK|DROP|REJECT)" /var/log/ufw.log 2>/dev/null | tail -30
fail2ban-client status 2>/dev/null && fail2ban-client status sshd 2>/dev/null
```

**Analyze:**
- Report blocked IPs and the services they targeted
- 🔴 IOC: fail2ban jails showing hundreds of banned IPs — active scanning/brute-force in progress

---

## 4. Lateral Movement Indicators [T1021]

### 4.1 Internal Network Connections

```bash
ss -tun 2>/dev/null | grep -E "192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\." | grep ESTABLISHED
```

**Analyze:**
- 🔴 IOC: SSH connections to other internal hosts from this server (lateral movement)
- ⚠️ Suspicious: connections to internal IPs on unusual ports (SMB 445, RDP 3389, WinRM 5985)
- Note: document all internal connections — build the lateral movement map

### 4.2 SSH Known Hosts (Signs of Lateral Movement)

```bash
for dir in /root /home/*/; do
  [ -f "$dir/.ssh/known_hosts" ] && echo "=== $dir/.ssh/known_hosts ===" && cat "$dir/.ssh/known_hosts" 2>/dev/null | head -20
done
```

**Analyze:**
- ⚠️ Suspicious: recently added entries in known_hosts (this host may have connected to new destinations)
- Note all internal IPs in known_hosts — these are potential lateral movement targets

### 4.3 SSH Auth Log — Outbound Connections

```bash
journalctl --since "48 hours ago" 2>/dev/null | grep "ssh" | grep -i "connecting to\|debug1: Connecting" | tail -20
grep "Connecting to" /var/log/auth.log 2>/dev/null | tail -20
```

**Analyze:**
- ⚠️ Suspicious: outbound SSH connections to unexpected hosts
- 🔴 IOC: SSH connections from automated processes (cron, www-data, daemon)

---

## 5. ARP & Layer 2 Anomalies [T1557.002]

### 5.1 ARP Table

```bash
arp -n 2>/dev/null || ip neigh show 2>/dev/null
```

**Analyze:**
- 🔴 IOC: two IPs sharing the same MAC address (ARP spoofing/MITM)
- ⚠️ Suspicious: gateway IP pointing to an unexpected MAC address

### 5.2 Interface Promiscuous Mode

```bash
ip link show 2>/dev/null | grep -i promisc
cat /sys/class/net/*/flags 2>/dev/null | while IFS= read -r f; do printf "%s: %s\n" "$(basename $(dirname ...))" "$f"; done
ip link show | grep PROMISC
```

**Analyze:**
- 🔴 IOC: any network interface in PROMISC mode without a known packet capture tool running (passive sniffing)

---

## 6. Port Scanning Detection

### 6.1 Recent Inbound Scan Indicators

```bash
grep -E "DPT=(1|22|23|25|80|110|143|443|445|3306|3389|5432|8080|8443)" /var/log/ufw.log 2>/dev/null | awk '{print $13}' | grep -oE "SRC=[0-9.]+" | sort | uniq -c | sort -rn | head -20
journalctl --since "24 hours ago" 2>/dev/null | grep -i "port scan\|nmap\|masscan\|connection refused" | tail -20
```

**Analyze:**
- ⚠️ Suspicious: IPs probing many ports in sequence (port scanner)
- 🔴 IOC: scan followed by successful connection on a discovered port

### 6.2 Fail2ban Banned IPs

```bash
fail2ban-client banned 2>/dev/null || fail2ban-client status 2>/dev/null | grep "Jail list" | sed 's/.*Jail list://' | tr ',' '\n' | xargs -I{} fail2ban-client status {} 2>/dev/null | grep "Banned IP"
```

**Analyze:**
- Report number of currently banned IPs per jail
- ⚠️ Suspicious: >100 banned IPs in sshd jail (under active brute-force attack)

---

## 7. Network Configuration Integrity

### 7.1 Listening Services vs Expected Baseline

```bash
ss -tlnup 2>/dev/null
```

**Analyze:**
- List all listening ports and owning processes
- 🔴 IOC: services listening on 0.0.0.0 that should be localhost-only (databases, admin panels)
- ⚠️ Suspicious: any port not in the documented baseline

### 7.2 Firewall Status

```bash
ufw status numbered 2>/dev/null || iptables -L INPUT -n --line-numbers 2>/dev/null || nft list ruleset 2>/dev/null | head -40
```

**Analyze:**
- 🔴 IOC: firewall disabled entirely (`ufw status: inactive`) on an internet-facing server
- ⚠️ Suspicious: permissive rules allowing all inbound traffic
- Note any rules that were recently added (cross-reference with incident timeline)

### 7.3 Routing Table Anomalies

```bash
ip route show
ip rule show 2>/dev/null
```

**Analyze:**
- 🔴 IOC: unexpected default gateway (traffic may be routed through attacker-controlled host)
- ⚠️ Suspicious: policy routing rules not in the baseline config
