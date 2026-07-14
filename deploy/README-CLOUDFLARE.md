# Expose the backend over the web with **Cloudflare Tunnel** (free, unmetered)

Best **fallback when you cross ngrok's limits** — Cloudflare Tunnel has **no
request or bandwidth cap**, so it handles 5–10+ polling students fine for free.

```
student CLion plugin ──https──► your tunnel hostname ──► your laptop :8000
```

Two modes — pick by whether you own a domain:

| Mode | Stable URL? | Needs a domain? | Use when |
|---|---|---|---|
| **Named tunnel** | ✅ permanent | ✅ yes (added to Cloudflare) | real exams — package plugin once |
| **Quick tunnel** | ❌ random each run | ❌ no account | a throwaway 5-min test |

---

## Install (both modes)

```bash
brew install cloudflared            # macOS
```
Students never install this — teacher-side only.

---

## Mode A — Named tunnel (recommended, stable URL)

Requires a domain whose nameservers point to Cloudflare (free Cloudflare account
→ add your domain). One-time:

```bash
# 1. Log in (opens a browser to authorize a domain on your account)
cloudflared tunnel login

# 2. Create a named tunnel (stores credentials locally)
cloudflared tunnel create oslab-exam

# 3. Route a hostname on your domain to that tunnel
cloudflared tunnel route dns oslab-exam exam.yourdomain.com
```

Point the config at it — edit `deploy/tunnel.conf`:
```ini
PROVIDER=cloudflare
CF_TUNNEL_NAME=oslab-exam
```

Build the student package once (JDK-21 machine) with the **routed hostname**:
```bash
cd oslab_plugin
./packaging/make_exam_package.sh --backend-url https://exam.yourdomain.com
```

Each session:
```bash
bash deploy/tunnel.sh --with-backend     # PROVIDER=cloudflare → runs the named tunnel
```

---

## Mode B — Quick tunnel (no domain, random URL)

For a quick throwaway test only. No login, no config:
```bash
bash deploy/tunnel.sh cloudflare-quick --with-backend
```
It prints a random `https://<words>.trycloudflare.com` URL.

⚠️ **The URL changes every run.** Each time you must re-stamp it into the plugin
package and students must reinstall:
```bash
# edit oslab_plugin/dist/OsLabExam/exam.conf → BACKEND_URL=https://<new>.trycloudflare.com
cd oslab_plugin/dist && rm -f OsLabExam.zip && zip -rqX OsLabExam.zip OsLabExam
```
Avoid this mode for real exams — use a named tunnel.

---

## Switching from ngrok to Cloudflare mid-course
1. Set up a **named tunnel** (Mode A) so the URL is stable.
2. Re-stamp the plugin package with the new hostname (edit `exam.conf` + re-zip —
   no JDK needed) and resend `OsLabExam.zip` to students **once**.
3. Flip `PROVIDER=cloudflare` in `deploy/tunnel.conf`. Done — `tunnel.sh` now
   uses Cloudflare every session.
