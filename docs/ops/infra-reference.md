# Home Lab & `josearcos.me` Infrastructure Reference
_Last verified: 2026-05-30 — owner: José Arcos_
_Updated 2026-05-30: deployed **biblioHack** to the NAS at `biblio.josearcos.me`; enabled SSH pubkey auth; documented Synology deploy gotchas (see §12)._
_Updated 2026-05-31: **CI/CD auto-deploy** (GitHub Actions → NAS over Tailscale) live and verified — green push to `main` ships itself (see §13)._

This document captures the full, verified configuration of the home network, the Synology NAS, the self-hosted Docker stack, and how the `josearcos.me` domain is wired up. It also records the history/learnings from earlier troubleshooting so the same ground isn't re-covered.

---

## 1. Quick architecture overview

```
                         INTERNET
                            │
        ┌───────────────────┴───────────────────┐
        │                                         │
  Public websites                         Remote admin access
  josearcos.me, biblio.josearcos.me       (4 overlapping methods)
        │                                         │
  Cloudflare DNS (proxied)                 - Tailscale (works great)
        │                                  - Cloudflare Tunnel (web only)
  Cloudflare Tunnel "synology-nas"         - OpenVPN (DSM, enabled, unused)
        │ (outbound-only, no open ports)   - WireGuard (container, running)
  cloudflared container (on NAS)
        ├─ josearcos.me         → http://wordpress:80
        └─ biblio.josearcos.me  → http://bibliohack-frontend:4321
                                  (/catalog,/healthz → bibliohack-api:8000)
  WordPress + biblioHack (api / frontend / postgres / minio)
        (shared Docker network "tunnel" 172.18.0.0/16)

  Home network: DIGI fibre, public IPv4 79.112.76.73 (NO CG-NAT)
  NAS "Home-NAS" @ 192.168.1.130
```

---

## 2. ISP / network layer

| Item | Value |
|---|---|
| ISP | DIGI (fibre, Spain) |
| Router | ZTE **H3600P** (firmware `V9.0.0P5_DIGI`) |
| Public IPv4 (PPPoE WAN) | **79.112.76.73** / 255.255.255.255 |
| CG-NAT? | **No** — router PPPoE WAN holds the real public IP (verified 2026-05-30) |
| Secondary WAN | "VoIP" DHCP connection, 10.241.32.251/21, gateway 10.241.32.1 — DIGI's internal/VoIP VLAN, **not** the internet path |
| IPv6 | Currently "Connecting" — no global address assigned |
| LAN subnet | 192.168.1.0/24, router/gateway 192.168.1.1 |
| ISP DNS | 100.90.1.1 / 100.100.1.1 |

**Key learning:** CG-NAT was removed by the ISP. This was previously the root cause of all inbound-connection failures (SSH/OpenVPN timeouts). Inbound IPv4 now works, so direct port-forwarding is possible again — but note the public website never depended on it (see Cloudflare Tunnel).

**How to re-verify off-CG-NAT:** compare the router's PPPoE WAN IP (Router admin → Internet → Estado → "WanConnection") against the public IP from `https://ipv4.icanhazip.com`. If they match and it's not a `100.64.0.0/10` address → not CG-NAT.

---

## 3. Domain & DNS — `josearcos.me`

### Registrar (Namecheap)
- Registered at **Namecheap**, status ACTIVE, expires **Nov 23, 2026**, auto-renew **ON**, WHOIS privacy **ON**.
- **No Namecheap hosting plan** on the account.
- Nameservers set to **Custom DNS → Cloudflare**:
  - `desiree.ns.cloudflare.com`
  - `quentin.ns.cloudflare.com`
- Because DNS is delegated to Cloudflare, the Namecheap "Advanced DNS" tab is inert (shows generic placeholder text). **Manage all records in Cloudflare, not Namecheap.**

### DNS zone (Cloudflare — authoritative, 16 records)
| Purpose | Name | Type | Content | Proxy |
|---|---|---|---|---|
| Website | `josearcos.me` | CNAME | `eed2f48e-…cfargotunnel.com` (Tunnel) | Proxied |
| biblioHack | `biblio.josearcos.me` | CNAME | `eed2f48e-…cfargotunnel.com` (Tunnel) | Proxied — auto-created 2026-05-30 by the tunnel public-hostname UI |
| Mail (in) | `josearcos.me` | MX | `route1/2/3.mx.cloudflare.net` | DNS only |
| Mail SPF | `josearcos.me` | TXT | `v=spf1 include:_spf.mx.cloudflare.net ~all` | DNS only |
| Mailgun | `email.mail.josearcos.me` | CNAME | `eu.mailgun.org` | DNS only |
| Mailgun DKIM | `pdk1/pdk2._domainkey.mail` | CNAME | `…dkim2.eu.mgsend.org` | DNS only |
| Mailgun SPF | `mail.josearcos.me` | TXT | `v=spf1 include:mailgun.org ~all` | DNS only |
| Mailgun DKIM | `s1._domainkey.mail` | TXT | RSA public key | DNS only |
| Postmark | `pm-bounces.josearcos.me` | CNAME | `pm.mtasv.net` | Proxied |
| Postmark DKIM | `20260202…pm._domainkey` | TXT | RSA public key | DNS only |
| Cloudflare DKIM | `cf2024-1._domainkey` | TXT | RSA public key | DNS only |
| Leftover | `josearcos.me` | NS | `dns1/dns2.registrar-servers.com` | DNS only |

**Email stack:** Inbound via **Cloudflare Email Routing**; outbound/transactional via **Mailgun** (EU region) and **Postmark**.

**Cleanup note:** the two in-zone `registrar-servers.com` NS records are Namecheap leftovers and serve no purpose now that Cloudflare is authoritative.

**Cloudflare recommendations flagged:** add a DMARC record; add a `www` record/redirect (currently `www.josearcos.me` does not resolve).

---

## 4. Public website path (Cloudflare Tunnel)

| Item | Value |
|---|---|
| Tunnel name | **`synology-nas`** |
| Tunnel ID | `eed2f48e-8f3f-41cc-8106-fabc67b37acc` |
| Type | `cloudflared` |
| Replicas | 1 (replica `7eaede67-…`) |
| Origin IP | 79.112.76.73 (the NAS, at home) |
| Edge location | `mad05` (Madrid) |
| cloudflared version | **2025.11.1** (likely outdated) |
| Uptime | ~18 days |
| Status | **Degraded** (single replica + version) |
| Management | **Token-managed** (`TUNNEL_TOKEN` in the cloudflared compose) → public hostnames are configured in the **Cloudflare dashboard**, not a local `config.yml` |

**Public hostname routes** (Cloudflare → Zero Trust → Networks → **Connectors** → `synology-nas` → **"Published application routes"** tab; URL `…?tab=publicHostname`). Evaluated top-down:

| # | Hostname | Path | Service |
|---|---|---|---|
| 1 | `josearcos.me` | `*` | `http://wordpress:80` |
| 2 | `biblio.josearcos.me` | `^/(catalog\|healthz)` | `http://bibliohack-api:8000` |
| 3 | `biblio.josearcos.me` | `*` | `http://bibliohack-frontend:4321` |
| — | catch-all | | `http_status:404` |

**How it works:** the `cloudflared` container holds an **outbound-only** connection to Cloudflare. Public traffic enters Cloudflare, rides the tunnel down to the NAS, and is delivered to the target container **by name over the shared `tunnel` Docker network**. **No inbound ports, DDNS, or DSM reverse-proxy involved.**

> ⚠️ **Dashboard gotcha (2026-05-30):** in the current Cloudflare One UI, **"Published application routes"** is the classic public-hostname editor (captures public traffic via proxied DNS). The separate **"Hostname routes (Beta)"** tab is for **private/WARP** routing (requires the Cloudflare One client) and is the *wrong* place for a public website — its form even uses a `www.example.local` placeholder. Use "Published application routes".

---

## 5. The NAS — "Home-NAS"

| Item | Value |
|---|---|
| LAN IP | 192.168.1.130 |
| DSM ports | HTTP **4998**, HTTPS **4999** (auto-redirect HTTP→HTTPS) |
| QuickConnect ID | `josearcos` → `josearcos.quickconnect.to` |
| Synology DDNS | `josearcos.synology.me` → 79.112.76.73 (Synology provider, status Normal) |
| Customized domain (Login Portal) | **(empty)** |
| Reverse proxy rules | **None** |
| Certificates | `synology` (default, exp 12/31/2026); `josearcos.direct.quickconnect.to` (QuickConnect, exp 07/07/2026) |
| SSH | Enabled on **port 2222** (port 22 is closed). Admin user `josearcos`. Pubkey auth enabled 2026-05-30 (see §12.2). Restart via `sudo synosystemctl restart sshd` |
| CPU arch | **x86_64** (`uname -m`; consistent with VMM being installed) — so amd64-only images like `timescale/timescaledb-ha:pg16` run fine |
| Docker (Container Manager) | binary at `/usr/local/bin/docker`; `josearcos` is in the **`docker` group (65536)** so docker runs **without sudo**. `/volume1/docker` is world-writable (`0777`) |

**Key learning:** `josearcos.me` is **not** referenced anywhere in DSM (no DDNS entry, no customized domain, no reverse proxy, no certificate). NAS admin access and the public website are two completely independent paths.

---

## 6. Docker stack (Container Manager)

**Summary:** 4 projects (`wordpress`, `cloudflared`, `finance-app`, `bibliohack`); `bibliohack` added 2026-05-30.

### Projects
| Project | Path | Containers | Status |
|---|---|---|---|
| `wordpress` | `/volume1/docker/wordpress` | 2 | ✅ Healthy |
| `cloudflared` | `/volume1/docker/cloudflared` | 1 | ✅ Healthy |
| `finance-app` | `/volume1/docker/finance-app` | 0 | ❌ Error (never built) |
| `bibliohack` | `/volume1/docker/bibliohack` | 4 | ✅ Healthy (deployed 2026-05-30, `docker-compose.prod.yml`) — see §12 |

### Containers
| Name | Image | Project | State | Uptime |
|---|---|---|---|---|
| `wordpress` | `wordpress:php8.2-apache` | wordpress | running | 53 d |
| `wp-db` | `mariadb:11` | wordpress | running | 53 d |
| `cloudflared` | `cloudflare/cloudflared:latest` | cloudflared | running | 53 d |
| `linuxserver-wireguard-1` | `linuxserver/wireguard:latest` | (standalone) | running | 53 d |
| `infra-telegram-bot-1` | `infra-telegram-bot:latest` | (standalone) | **stopped** | — |
| `bibliohack-postgres` | `timescale/timescaledb-ha:pg16` | bibliohack | running (healthy) | since 2026-05-30 |
| `bibliohack-api` | `bibliohack-api` (built, FastAPI/uvicorn :8000) | bibliohack | running | since 2026-05-30 |
| `bibliohack-frontend` | `bibliohack-frontend` (built, Astro static via `serve` :4321) | bibliohack | running | since 2026-05-30 |
| `bibliohack-minio` | `minio/minio:latest` | bibliohack | running (healthy) | since 2026-05-30 |

### `finance-app` (the broken project)
Self-hosted full-stack personal finance app, defined in compose but **never successfully built** (0 containers). Composition:
- **postgres** — `postgres:15-alpine` (container `finance-app-db-prod`), volume `postgres_data`, init via `./backend/database/init.sql`, network `finance-network`.
- **backend** — built from `./backend/Dockerfile` (`finance-app-backend-prod`), Node.js, `NODE_ENV=production`, `PORT=3001`, internal only. Requires env: `POSTGRES_PASSWORD`, **`OPENAI_API_KEY`** (AI-enabled), DB host `postgres:5432`.
- **frontend** — built from `./frontend/Dockerfile` (`finance-app-frontend-prod`).
- Needs a populated `.env` and a successful image build to come up.

### Docker networks
| Network | Driver | Containers | Notes |
|---|---|---|---|
| **`tunnel`** | bridge | **wordpress, cloudflared, bibliohack-api, bibliohack-frontend** | 172.18.0.0/16, gw 172.18.0.1, IP masquerade on. **This is how cloudflared resolves containers by name.** Declared `external: true` in bibliohack's compose so its api/frontend attach to it. |
| `bibliohack_default` | bridge | bibliohack postgres / api / minio | internal — postgres + minio bind to `192.168.1.130:5432/9000/9001` (LAN only, never the tunnel) |
| `wordpress_default` | bridge | 2 (wordpress, wp-db) | |
| `cloudflared_default` | bridge | 1 | |
| `infra_default` | bridge | 1 | |
| `frienddraft-bot_default` | bridge | 0 | orphaned |
| `bridge` / `host` | bridge/host | 1 / 0 | defaults |

---

## 7. Remote-access methods (four, overlapping)

| Method | Where | State | Notes |
|---|---|---|---|
| **Tailscale** | DSM package | ✅ Working | The reliable solution; works regardless of CG-NAT/IP. Also installed on a laptop and confirmed working. |
| **Cloudflare Tunnel** | cloudflared container | ✅ Working | Web only (`josearcos.me` → WordPress). |
| **OpenVPN** | DSM VPN Server | Enabled, 0 connections | Range 10.8.0.0/24. The one from earlier troubleshooting; effectively unused. |
| **WireGuard** | `linuxserver/wireguard` container | Running | Standalone; never fully validated historically. |

PPTP and L2TP/IPSec: **disabled**.

**SSH (separate from the above):** enabled on **port 2222**, key-based auth working as of 2026-05-30. A dedicated **passphraseless deploy key** (`~/.ssh/bibliohack_deploy` on the Mac, alias `nas-deploy` in `~/.ssh/config`) is authorized for unattended deploys. Revoke by removing its line from `~/.ssh/authorized_keys` on the NAS. Getting pubkey auth working required sshd config changes — see §12.2.

**Recommendation:** consolidate. With Tailscale working and CG-NAT gone, OpenVPN and the WireGuard container are redundant and can likely be retired to reduce attack surface and maintenance.

---

## 8. Other installed DSM packages

DNS Server, DHCP Server, Virtual Machine Manager, Active Backup for Google Workspace (+ Portal), Cloud Sync, Synology Drive (+ Admin Console, ShareSync), Synology Photos, MariaDB 10 (DSM package — separate from the `wp-db` MariaDB 11 container), Container Manager, Tailscale, VPN Server.

---

## 9. Historical troubleshooting (learnings to avoid repeating)

From the ChatGPT "NAS" project (Apr–May 2026):

1. **SSH from outside failed** (`josearcos.synology.me:2222` timeout). Root cause: **CG-NAT + IPv6-only public path**. Conclusion at the time: use Tailscale. _(CG-NAT now removed — 2026-05-30.)_
2. **OpenVPN (Synology → Mac/Tunnelblick)**: long fight with TCP/UDP mismatch, missing CA/peer-fingerprint (status 251), repeated `TLS key negotiation failed`. Handshake eventually worked after IP/firewall fixes, but **traffic never flowed through the tunnel** (`tcpdump` showed 0 packets on `tun0`). Left unresolved; superseded by Tailscale.
3. **WireGuard in Docker** (`linuxserver/wireguard`): attempted as alternative, historically not configured cleanly.
4. **Tailscale-in-Docker on the work laptop**: investigated to bypass corporate IT restrictions; concluded usually blocked/policy-violating — use another device as a Tailscale entry point instead.

⚠️ **Security note:** the OpenVPN troubleshooting chat contains a full client `.ovpn` including the **CA certificate and the static TLS key in plaintext**. Consider regenerating that key on the NAS and re-exporting the client config.

---

## 10. Recommended next actions

- [ ] **Update cloudflared** (pending image update) and/or add a 2nd tunnel replica to clear the **Degraded** status and remove the single point of failure.
- [ ] Apply the **4 pending Docker image updates** (WordPress / MariaDB / cloudflared etc.).
- [ ] Decide on **`finance-app`**: supply `.env` (`POSTGRES_PASSWORD`, `OPENAI_API_KEY`) and build, or remove the project to clear the error.
- [ ] **Consolidate remote access**: retire OpenVPN (DSM) and the WireGuard container if Tailscale is sufficient.
- [ ] **Cloudflare DNS hygiene**: add DMARC, add `www` record/redirect, remove leftover `registrar-servers.com` NS records.
- [ ] Remove stale Docker leftovers: stopped `infra-telegram-bot-1`, empty `frienddraft-bot_default` network.
- [ ] **Rotate the OpenVPN static TLS key** that was exposed in chat history.
- [ ] (Optional) Now that CG-NAT is gone, decide whether you want any direct inbound services (port forward + NAS firewall) — though the Cloudflare Tunnel already covers the website without it.
- [ ] **biblioHack**: populate the catalog (run the off-NAS crawler against `192.168.1.130:5432`); the live site is empty until then.
- [ ] **Security review of the SSH changes** (§12.2): `StrictModes no` is now global on the NAS sshd, and a passphraseless deploy key is authorized. Fine for a LAN/admin homelab, but consider scoping the key (`from=`/`command=` in `authorized_keys`) or removing it when not actively deploying.
- [ ] Note: the `synology-nas` tunnel now serves **two** sites (`josearcos.me` + `biblio.josearcos.me`), so clearing its **Degraded** status (2nd replica / update) matters a bit more now.

---

## 11. Reference IDs & endpoints

| Thing | Value |
|---|---|
| Cloudflare account | `josearcoscampos@gmail.com` (acct `b7bf834ca542593a51aa8ffa7ed52879`) |
| Cloudflare Tunnel ID | `eed2f48e-8f3f-41cc-8106-fabc67b37acc` |
| Public IPv4 | 79.112.76.73 |
| NAS LAN IP | 192.168.1.130 (DSM HTTPS :4999) |
| QuickConnect | `josearcos` / `josearcos.quickconnect.to` |
| Synology DDNS | `josearcos.synology.me` |
| Domain | `josearcos.me` (Namecheap reg, Cloudflare DNS) |
| OpenVPN range | 10.8.0.0/24 |
| Docker "tunnel" net | 172.18.0.0/16 |
| biblioHack site | `biblio.josearcos.me` (frontend + API via the `synology-nas` tunnel) |
| biblioHack path | `/volume1/docker/bibliohack` (compose: `docker-compose.prod.yml`) |
| NAS SSH | `josearcos@192.168.1.130 -p 2222` (Mac alias `nas-deploy`, key `~/.ssh/bibliohack_deploy`) |
| NAS Postgres (LAN) | `192.168.1.130:5432` db/user `bibliohack` (pw in NAS `…/bibliohack/.env`, chmod 600) |
| Mac (deploy host) LAN IP | 192.168.1.141 |
| Tailnet | `tailbd4f91.ts.net` (NAS Tailscale IP `100.76.144.26`, MagicDNS `home-nas.tailbd4f91.ts.net`) |
| CI deploy SSH key | `~/.ssh/bibliohack_ci` (Mac) → NAS `authorized_keys`; GitHub secret `NAS_SSH_KEY` |
| Tailscale CI tag / OAuth client | `tag:ci` (owner `autogroup:admin`); OAuth client `kZNhFNznqS11CNTRL` (scope auth_keys:write, tag:ci) |
| Auto-deploy kill switch | repo variable `AUTODEPLOY_ENABLED` (`true`/`false`) on `jarcos/biblioHack` |

---

## 12. biblioHack deployment & Synology deploy runbook (2026-05-30)

biblioHack (reverse catalog for the Andalusian public libraries) is deployed to the NAS and live at **`https://biblio.josearcos.me`**. This section records the working setup **and** every Synology-specific gotcha hit on the way, so the next deploy is fast.

### 12.0 Topology — two planes
Only the **read + serve plane** runs on the NAS (`docker-compose.prod.yml`): `postgres` (timescaledb-ha:pg16, migrated, with pgvector/timescaledb/pg_trgm/unaccent), `api` (FastAPI), `frontend` (Astro static served by `serve`), `minio` (cover store, storage only for now). The heavy **compute plane** (Scrapling/Camoufox crawler + BGE-M3 embedder) does **not** run on the NAS — it runs off-box and reaches the NAS Postgres over LAN/Tailscale (`192.168.1.130:5432`). Public surface is **read-only**; Postgres/MinIO are bound to the LAN IP only, never the tunnel.

### 12.1 Deploy / redeploy runbook (from the Mac)
1. **Transfer code** — `rsync` does **not** work to this NAS (Synology gates `/usr/bin/rsync` behind the Network-Backup service → SSH auth succeeds then the remote `rsync --server` returns "Permission denied"). **Use tar-over-ssh instead:**
   `tar czf - -C <repo> --exclude='*/.git*' --exclude='*node_modules*' --exclude='*/.venv*' … . | ssh nas-deploy 'mkdir -p /volume1/docker/bibliohack && tar xzf - -C /volume1/docker/bibliohack'`
2. **Secrets** — write `/volume1/docker/bibliohack/.env` (chmod 600) with `POSTGRES_PASSWORD`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` (generated with `openssl rand -hex 24`).
3. **Pre-create bind-mount dirs** — Docker on Synology does **not** auto-create host bind paths: `mkdir -p /volume1/docker/bibliohack/{pgdata,minio}` before `up`, or it fails with "Bind mount failed: … does not exist".
4. **Build + start** — `/usr/local/bin/docker compose -f docker-compose.prod.yml up -d --build` (no sudo; `josearcos` is in the `docker` group). First pull of the 1.7 GB timescaledb image is slow.
5. **Migrations** — run Alembic **from the Mac** against the NAS Postgres (LAN): `DATABASE_URL_SYNC=postgresql+psycopg://bibliohack:<pw>@192.168.1.130:5432/bibliohack .venv/bin/python -m alembic upgrade head`.
6. **Tunnel routes** — already configured (see §4). Adding new ones = Cloudflare dashboard → "Published application routes".
7. **Verify** — `https://biblio.josearcos.me/healthz` → `{"status":"ok"}`; `/catalog/search?q=…` → JSON; `/` → frontend.

### 12.2 SSH pubkey auth — what it took (Synology DSM)
Enabling key-based SSH (so deploys can run unattended) required, in order:
- SSH service on **port 2222** (DSM → Control Panel → Terminal & SNMP).
- Run the authorize/`chmod` commands **on the NAS**, not the Mac — easy to mistake which host you're on (macOS BSD `sed` errors vs Linux GNU `sed` is the tell; `whoami` is `josearcos` on both).
- Perms: `~` `0755`, `~/.ssh` `0700`, `authorized_keys` `0600`.
- `/etc/ssh/sshd_config`: `PubkeyAuthentication yes`, `AuthorizedKeysFile .ssh/authorized_keys`, **`StrictModes no`** (Synology's `/volume1/homes` is group-accessible by design, which fails StrictModes — so the key was *accepted* then auth *refused*). **`StrictModes` must be in the global section, not inside a `Match` block** (the DSM config ends with `Match User root/admin/anonymous` — appending there makes `sshd -t` fail and sshd won't start).
- Restart with `sudo synosystemctl restart sshd` (use `start` if it's stopped; `synoservicectl`/`systemctl` are not the right tools here).
- **Diagnosis trick:** DSM doesn't log SSH auth failures to `auth.log`. To see the real reason, run a one-shot debug daemon: `sudo synosystemctl stop sshd; sudo $(command -v sshd) -ddd -p 2222 > /tmp/sshd_dbg.log 2>&1 &`, connect, then read `/tmp/sshd_dbg.log` (then `start sshd`).
- **Root cause of the long fight:** the Mac's default `id_ed25519` was **passphrase-protected with no ssh-agent**, so non-interactive ssh could *offer* the key (log shows "Server accepts key … Postponed") but couldn't *sign* → "Permission denied". Fix = a dedicated **passphraseless** key (`~/.ssh/bibliohack_deploy`).

### 12.3 Other Synology deploy gotchas
- **BuildKit DNS** — `docker compose build` RUN steps couldn't resolve DNS (`dns error … Try again`) even though image pulls worked. Fix: add **`network: host`** under each service's `build:` in compose. **Do not** change the Docker daemon's DNS / restart Container Manager — that would drop the live WordPress site + tunnel.
- **Astro `preview` host allowlist** — `astro preview` (Vite) rejects unknown `Host` headers with "This host is not allowed", and it **ignores `vite.preview.allowedHosts`** for static output. Since Astro output is fully static, the frontend image now serves `dist/` with **`serve`** (`npm i -g serve`; `CMD serve dist -l tcp://0.0.0.0:4321`) — no host check.
- **`docker` not on the non-interactive PATH** over SSH — use the full path `/usr/local/bin/docker`.
- **Cloudflare "Hostname routes (Beta)" ≠ public hostnames** — see the §4 gotcha box.

### 12.4 Operations
- **Logs/status:** `ssh nas-deploy 'cd /volume1/docker/bibliohack && /usr/local/bin/docker compose -f docker-compose.prod.yml ps'` / `… logs --tail 50 bibliohack-api`.
- **Restart one service:** `… up -d --build frontend` (rebuilds + recreates just that service).
- **DB shell:** `… docker exec -it bibliohack-postgres psql -U bibliohack -d bibliohack`.
- **Populate the mirror:** the catalog starts empty; run the crawler (off-NAS) with `DATABASE_URL` pointed at `192.168.1.130:5432`.
- **Scratch left on NAS (safe to delete):** `/volume1/docker/bibliohack/{deploy-build,up,fe,fe2}.log`, `*.done`, and `/tmp/sshd_dbg.log`.

---

## 13. CI/CD auto-deploy (GitHub Actions → NAS over Tailscale)

**Live since 2026-05-31.** A green push to `main` on `jarcos/biblioHack` auto-deploys to the NAS; a red pipeline never deploys. Design rationale is in the repo's `ARCHITECTURE.md` §10.1; this section is the operational "how it's wired + how to run it" for the home lab.

### 13.1 How it works (the green-only path)
The deploy is a `deploy` job in `.github/workflows/ci.yml`, gated three ways:
- `needs: [backend, frontend, docker-build]` — runs only after all CI jobs pass.
- `if: github.event_name == 'push' && github.ref == 'refs/heads/main' && vars.AUTODEPLOY_ENABLED == 'true'` — push to `main` only (never PRs/forks), and only while the kill-switch variable is on.
- `environment: production` + `concurrency: deploy-prod` (no overlapping deploys).

The job (on a GitHub-hosted runner): **Tailscale GitHub Action** joins the tailnet as an ephemeral `tag:ci` node → SSH to the NAS at its Tailscale IP `100.76.144.26:2222` with a dedicated CI key → **tar the checkout over SSH** (rsync is gated on Synology) into `/volume1/docker/bibliohack` → `docker compose -f docker-compose.prod.yml up -d --build` → `docker compose exec -T api alembic upgrade head` → **poll `https://biblio.josearcos.me/healthz`**; if it isn't `{"status":"ok"}` the job fails (and, target state with GHCR, would roll back). This is "strategy A" (build on the NAS); no auto-rollback yet.

### 13.2 One-time setup (what was created — to recreate or rotate)
**On the NAS:** a dedicated **passphraseless** CI key `~/.ssh/bibliohack_ci` (Mac) authorized in the NAS `~/.ssh/authorized_keys` — *separate* from `bibliohack_deploy` (manual/interactive), so it can be revoked independently.

**In Tailscale** (admin console, `tailbd4f91.ts.net`):
- A tag **`tag:ci`** owned by `autogroup:admin` — created via **Access controls → Visual editor → Definitions → Tags → Create tag** (the raw JSON editor is a React-controlled textarea that resists automation; the visual editor is the reliable path). The default allow-all grant already lets `tag:ci` reach the NAS, so no extra ACL grant was needed.
- An **OAuth client** "biblioHack CI auto-deploy" with scope **Auth Keys → Write** and tag **`tag:ci`**, created under **Settings → Trust credentials → + Credential → OAuth**. The client secret is shown once.

**In GitHub** (`gh` CLI, authenticated as `jarcos`) — repo secrets + variable + environment:
```bash
gh secret set NAS_SSH_KEY  -R jarcos/biblioHack < ~/.ssh/bibliohack_ci
gh secret set NAS_SSH_HOST -R jarcos/biblioHack -b '100.76.144.26'   # NAS Tailscale IP
gh secret set NAS_SSH_USER -R jarcos/biblioHack -b 'josearcos'
gh secret set NAS_SSH_PORT -R jarcos/biblioHack -b '2222'
gh secret set TS_OAUTH_CLIENT_ID -R jarcos/biblioHack -b '<client id>'
gh secret set TS_OAUTH_SECRET    -R jarcos/biblioHack -b '<client secret>'
gh api -X PUT repos/jarcos/biblioHack/environments/production   # no required reviewers
gh variable set AUTODEPLOY_ENABLED -R jarcos/biblioHack -b 'true'   # the kill switch
```

### 13.3 Operating it
- **Disable instantly** (no code change): `gh variable set AUTODEPLOY_ENABLED -R jarcos/biblioHack -b 'false'` → the deploy job is skipped on every run.
- **Trigger:** any push to `main`. To force one: `git commit --allow-empty -m 'redeploy' && git push`.
- **Watch:** `gh run watch -R jarcos/biblioHack` or `gh run view <id> --json jobs`.
- **Read a failed step:** `gh run view <id> -R jarcos/biblioHack --log-failed`.
- **Revoke CI access:** delete the OAuth client in Tailscale **Trust credentials**, and remove the `bibliohack_ci` line from the NAS `~/.ssh/authorized_keys`.

### 13.4 Gotchas hit while building it (so they aren't re-debugged)
- **Migrations need Alembic in the image.** The api `Dockerfile` runtime stage copies only `.venv` + `src`; it now also `COPY`s `alembic/` + `alembic.ini` so `docker compose exec api alembic upgrade head` works in-container.
- **🐞 macOS AppleDouble `._*` files break Alembic.** Earlier *manual* deploys used BSD `tar` (on the Mac), which wrote AppleDouble `._*` sidecar files (binary, null bytes) onto the NAS. `COPY backend/alembic` then baked `._<migration>.py` into the image; Alembic globs `versions/*.py`, tried to load it, and died with `SyntaxError: source code string cannot contain null bytes`. **Fix:** a repo **`.dockerignore`** excluding `**/._*`, `**/.DS_Store`, `__pycache__`, `.venv`, `node_modules`, etc. (Also clean existing cruft: `ssh nas-deploy "find /volume1/docker/bibliohack -name '._*' -delete"`.)
- **The gate works (verified twice):** a stray `ruff format` miss made `backend` CI red → deploy **skipped**; the AppleDouble build failure → deploy step **failed loudly**, health gate **skipped**, live site **untouched**.
- **`gh` is authenticated on the Mac** (account `jarcos`, keyring) — so secrets/variables/environments can be set from the CLI without the browser.
- **Tailscale JSON ACL editor** is automation-hostile (React-controlled `<textarea>` whose display decouples from state); use the **Visual editor** for tag/grant changes.
