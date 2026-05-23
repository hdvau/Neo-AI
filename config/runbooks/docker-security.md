# Docker Security Assessment

## Agent Instructions

You are running a CIS Docker Benchmark security assessment on this host.
This is read-only — inspect and report only, no configuration changes.

Rules:
- ✅ Pass: meets the benchmark recommendation
- ⚠️ Warning: partially meets or cannot fully verify
- 🔴 Fail: clearly violates the recommendation
- Mark items **UNKNOWN** if Docker is not running or a command errors.
- Produce a scored summary with overall risk rating at the end.

## Agent Output Format

```
DOCKER SECURITY ASSESSMENT
Host: <hostname>  |  Docker: <version>  |  Date: <timestamp>

SCORE: <pass>/<total> checks passed
Overall risk: Low / Medium / High / Critical

CRITICAL FINDINGS
- [CIS-Docker ID] <finding> → <fix>

WARNINGS
- [CIS-Docker ID] <finding> → <fix>

SECTION BREAKDOWN
1. Host Configuration        ✅/⚠️/🔴
2. Docker Daemon             ✅/⚠️/🔴
3. Docker Files              ✅/⚠️/🔴
4. Container Images          ✅/⚠️/🔴
5. Container Runtime         ✅/⚠️/🔴
6. Security Operations       ✅/⚠️/🔴
```

## Baseline Reference

- CIS Docker Benchmark v1.6
- Low risk: ≥ 85% pass | Medium: 70–84% | High: 50–69% | Critical: < 50%

---

## 1. Host Configuration [CIS-1]

### 1.1 Docker Group Members

```bash
getent group docker 2>/dev/null
```

**Analyze:**
- ⚠️ Warning: any non-administrative user in the `docker` group — equivalent to root access
- 🔴 Fail: service accounts or application users in the docker group

### 1.2 Auditd Rules for Docker

```bash
auditctl -l 2>/dev/null | grep -E "(docker|/var/lib/docker|/etc/docker|docker\.service|docker\.socket)"
```

**Analyze:**
- ✅ Pass: audit rules exist for `/var/lib/docker`, `/etc/docker`, `docker.service`, `docker.socket`
- ⚠️ Warning: missing audit rules (Docker daemon activity unlogged)

### 1.3 Docker Socket Permissions

```bash
stat -c "%a %U %G" /var/run/docker.sock 2>/dev/null
```

**Analyze:**
- ✅ Pass: `660 root docker`
- 🔴 Fail: world-readable/writable (`666`) — any user can control Docker

---

## 2. Docker Daemon Configuration [CIS-2]

### 2.1 Daemon Configuration File

```bash
cat /etc/docker/daemon.json 2>/dev/null || echo "(no daemon.json found)"
```

**Analyze:**
- Note all configured options for use in subsequent checks
- ⚠️ Warning: no daemon.json (all settings are daemon defaults, may not be hardened)

### 2.2 Network Traffic Between Containers

```bash
docker info --format '{{.DriverStatus}}' 2>/dev/null
cat /etc/docker/daemon.json 2>/dev/null | grep -i icc
docker network inspect bridge 2>/dev/null | grep -i "EnableICC"
```

**Analyze:**
- ✅ Pass: `"icc": false` in daemon.json or `EnableICC: false` in bridge network
- ⚠️ Warning: ICC enabled (containers can communicate freely on default bridge)

### 2.3 Logging Driver Configured

```bash
docker info 2>/dev/null | grep "Logging Driver"
cat /etc/docker/daemon.json 2>/dev/null | grep "log-driver"
```

**Analyze:**
- ✅ Pass: logging driver set to `json-file`, `journald`, or a remote shipper
- ⚠️ Warning: `none` logging driver (container logs are lost)

### 2.4 Live Restore Enabled

```bash
cat /etc/docker/daemon.json 2>/dev/null | grep "live-restore"
docker info 2>/dev/null | grep "Live Restore"
```

**Analyze:**
- ✅ Pass: `"live-restore": true` — containers survive daemon restarts
- ⚠️ Warning: not set (all containers stop on daemon restart)

### 2.5 Userland Proxy Disabled

```bash
cat /etc/docker/daemon.json 2>/dev/null | grep "userland-proxy"
```

**Analyze:**
- ✅ Pass: `"userland-proxy": false` (uses iptables DNAT instead)
- ⚠️ Warning: not explicitly disabled (minor exposure surface)

### 2.6 No-New-Privileges Default

```bash
cat /etc/docker/daemon.json 2>/dev/null | grep "no-new-privileges"
```

**Analyze:**
- ✅ Pass: `"no-new-privileges": true`
- 🔴 Fail: not set — containers can acquire new privileges via setuid/setgid

### 2.7 Content Trust Enabled

```bash
echo $DOCKER_CONTENT_TRUST
```

**Analyze:**
- ✅ Pass: `DOCKER_CONTENT_TRUST=1`
- ⚠️ Warning: not set (unsigned images can be pulled)

---

## 3. Docker Files & Permissions [CIS-3]

### 3.1 Docker Daemon File Permissions

```bash
stat -c "%a %U %G %n" /etc/docker 2>/dev/null
stat -c "%a %U %G %n" /etc/docker/daemon.json 2>/dev/null
find /etc/docker -type f | xargs stat -c "%a %U %G %n" 2>/dev/null
```

**Analyze:**
- ✅ Pass: `/etc/docker` owned `root:root`, permissions `755` or stricter
- ✅ Pass: `daemon.json` permissions `644` or stricter
- 🔴 Fail: any config file writable by non-root

### 3.2 Docker Socket File

```bash
stat -c "%a %U %G %n" /var/run/docker.sock
```

**Analyze:**
- ✅ Pass: `660 root docker`
- 🔴 Fail: world-writable — full Docker control without authentication

### 3.3 Docker Service File

```bash
stat -c "%a %U %G %n" $(systemctl show docker.service -p FragmentPath | cut -d= -f2) 2>/dev/null
```

**Analyze:**
- ✅ Pass: owned `root:root`, permissions `644`
- 🔴 Fail: writable by non-root (service hijacking possible)

---

## 4. Container Images [CIS-4]

### 4.1 Image Vulnerability Overview

```bash
docker images --format "table {{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.CreatedSince}}\t{{.Size}}" 2>/dev/null
```

**Analyze:**
- ⚠️ Warning: images older than 90 days (may contain unpatched CVEs)
- ⚠️ Warning: images tagged `latest` (non-deterministic, update boundary unclear)
- Flag: images with no tag or `<none>` (dangling — prune candidates)

### 4.2 Images Using Root User

```bash
for img in $(docker images -q 2>/dev/null | sort -u); do
  user=$(docker inspect "$img" --format '{{.Config.User}}' 2>/dev/null)
  name=$(docker inspect "$img" --format '{{index .RepoTags 0}}' 2>/dev/null)
  echo "$name: user='${user:-root}'"
done
```

**Analyze:**
- ⚠️ Warning: images where user is empty or `root` — containers run as root by default
- ✅ Pass: explicit non-root user set in image config

### 4.3 Trivy Scan (if available)

```bash
which trivy 2>/dev/null && trivy image --severity HIGH,CRITICAL --no-progress $(docker images --format "{{.Repository}}:{{.Tag}}" 2>/dev/null | head -5) 2>/dev/null || echo "(trivy not installed — install with: curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh)"
```

**Analyze:**
- 🔴 Fail: any CRITICAL CVE in running container images
- ⚠️ Warning: HIGH severity CVEs — plan remediation
- ✅ Pass: no HIGH/CRITICAL findings

---

## 5. Container Runtime Configuration [CIS-5]

### 5.1 Running Container Overview

```bash
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null
```

**Analyze:**
- List all running containers as context for subsequent checks
- Flag: containers with ports bound to `0.0.0.0` (exposed on all interfaces)

### 5.2 Privileged Containers

```bash
docker ps -q 2>/dev/null | xargs docker inspect --format '{{.Name}}: Privileged={{.HostConfig.Privileged}}' 2>/dev/null | grep "Privileged=true"
```

**Analyze:**
- ✅ Pass: no output
- 🔴 Fail: any container running `Privileged=true` — full host access, container escape trivial

### 5.3 Sensitive Host Mounts

```bash
docker ps -q 2>/dev/null | xargs docker inspect --format '{{.Name}}: {{range .Mounts}}{{.Source}} -> {{.Destination}} {{end}}' 2>/dev/null | grep -E "(/etc|/root|/proc|/sys|/dev|/var/run/docker)"
```

**Analyze:**
- 🔴 Fail: `/etc`, `/root`, `/var/run/docker.sock` mounted into a container (host takeover path)
- ⚠️ Warning: `/proc` or `/sys` mounted (potential kernel info leak)

### 5.4 Host Network Mode

```bash
docker ps -q 2>/dev/null | xargs docker inspect --format '{{.Name}}: NetworkMode={{.HostConfig.NetworkMode}}' 2>/dev/null | grep "NetworkMode=host"
```

**Analyze:**
- ⚠️ Warning: any container using host networking (bypasses network isolation)
- 🔴 Fail: database or internal-only containers using host network

### 5.5 Host PID / IPC Namespace Sharing

```bash
docker ps -q 2>/dev/null | xargs docker inspect --format '{{.Name}}: PidMode={{.HostConfig.PidMode}} IpcMode={{.HostConfig.IpcMode}}' 2>/dev/null | grep -E "(host|shareable)"
```

**Analyze:**
- 🔴 Fail: `PidMode=host` — container sees all host processes (credential theft risk)
- ⚠️ Warning: `IpcMode=host` — shared memory with host

### 5.6 Read-Only Root Filesystem

```bash
docker ps -q 2>/dev/null | xargs docker inspect --format '{{.Name}}: ReadOnly={{.HostConfig.ReadonlyRootfs}}' 2>/dev/null | grep "ReadOnly=false"
```

**Analyze:**
- ⚠️ Warning: containers without read-only root filesystem (malware can persist inside container)
- ✅ Pass: `ReadOnly=true` (writes only allowed to explicitly mounted volumes)

### 5.7 Memory Limits Set

```bash
docker ps -q 2>/dev/null | xargs docker inspect --format '{{.Name}}: Memory={{.HostConfig.Memory}}' 2>/dev/null | grep "Memory=0"
```

**Analyze:**
- ⚠️ Warning: containers with `Memory=0` (no limit — single container can OOM the host)

### 5.8 CPU Limits Set

```bash
docker ps -q 2>/dev/null | xargs docker inspect --format '{{.Name}}: CpuShares={{.HostConfig.CpuShares}} CpuQuota={{.HostConfig.CpuQuota}}' 2>/dev/null
```

**Analyze:**
- ⚠️ Warning: `CpuShares=0` and `CpuQuota=-1` (no CPU limits — noisy neighbor / cryptominer risk)

### 5.9 Dropped Capabilities

```bash
docker ps -q 2>/dev/null | xargs docker inspect --format '{{.Name}}: CapAdd={{.HostConfig.CapAdd}} CapDrop={{.HostConfig.CapDrop}}' 2>/dev/null
```

**Analyze:**
- ✅ Pass: `CapDrop=[ALL]` with minimal CapAdd (least privilege)
- ⚠️ Warning: `CapAdd=[NET_ADMIN]`, `[SYS_ADMIN]`, `[SYS_PTRACE]` — high-risk capabilities
- 🔴 Fail: `CapAdd=[ALL]` or `Privileged=true` combined with sensitive caps

---

## 6. Security Operations [CIS-6]

### 6.1 Docker Bench Security (Full Run)

```bash
docker run --rm --net host --pid host --userns host --cap-add audit_control \
  -e DOCKER_CONTENT_TRUST=$DOCKER_CONTENT_TRUST \
  -v /etc:/etc:ro \
  -v /lib/systemd/system:/lib/systemd/system:ro \
  -v /usr/bin/containerd:/usr/bin/containerd:ro \
  -v /usr/bin/runc:/usr/bin/runc:ro \
  -v /usr/lib/systemd:/usr/lib/systemd:ro \
  -v /var/lib:/var/lib:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  --label docker_bench_security \
  docker/docker-bench-security 2>/dev/null | grep -E "\[(PASS|WARN|FAIL|INFO|NOTE)\]"
```

**Analyze:**
- Tally all `[FAIL]` items — each is a 🔴 finding
- Tally all `[WARN]` items — each is a ⚠️ finding
- Include the section number from docker-bench output in findings (e.g., `[FAIL] 2.1`)

### 6.2 Container Restart Policies

```bash
docker ps -q 2>/dev/null | xargs docker inspect --format '{{.Name}}: RestartPolicy={{.HostConfig.RestartPolicy.Name}} MaxRetry={{.HostConfig.RestartPolicy.MaximumRetryCount}}' 2>/dev/null
```

**Analyze:**
- ⚠️ Warning: `RestartPolicy=always` with no retry limit on containers that restart frequently (crash loop masking)
- ✅ Pass: `on-failure:5` or `unless-stopped` for production containers

### 6.3 Exposed Ports vs Documented Baseline

```bash
docker ps --format '{{.Names}}: {{.Ports}}' 2>/dev/null
ss -tlnp | grep docker 2>/dev/null
```

**Analyze:**
- Flag: any port bound to `0.0.0.0` that is not documented in the baseline
- 🔴 Fail: management ports (e.g., 2375 Docker API, database ports) exposed on all interfaces
