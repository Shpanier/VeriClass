# deploy/ — put the VeriExam backend on the web for an exam

Run the backend on your laptop and expose it through a tunnel so students'
CLion plugins can reach it from anywhere. **Teacher-side only** — students just
install the plugin package once.

## Files
| File | What it is |
|---|---|
| `tunnel.sh` | The control macro. One command: starts backend + tunnel, keeps laptop awake. |
| `tunnel.conf` | Your settings: which provider + your domain. **Edit this first.** |
| `README-NGROK.md` | ngrok setup — easiest free option for **2–3 students**. |
| `README-CLOUDFLARE.md` | Cloudflare setup — **unmetered**, use when you outgrow ngrok (5–10+). |

## Which one?
| Students | Use | Why |
|---|---|---|
| 2–3 | **ngrok** | Free static URL, no domain needed. Within the 20k req/month cap. |
| 5–10+ | **Cloudflare** | ngrok's free request cap blows in one session; Cloudflare is unmetered. |

## Quick start
1. Pick a provider and follow its README for the one-time setup + plugin packaging.
2. Set `PROVIDER` (and domain) in `tunnel.conf`.
3. Each session:
   ```bash
   bash deploy/tunnel.sh --with-backend
   ```
4. Open the dashboard at http://localhost:5173 to watch students.

Switching providers later = change `PROVIDER` in `tunnel.conf`, re-stamp the
plugin's `exam.conf` with the new URL, re-zip, resend once. (No JDK needed to
re-stamp — only the first plugin build needs JDK 21.)
