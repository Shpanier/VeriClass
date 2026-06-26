# Expose the backend over the web with **ngrok** (free)

Best for **small tests (2–3 students)**. Free tier gives 1 permanent domain but
caps you at **20,000 requests / month + 1 GB / month**. The plugin polls every
2 s (~1,900 req/hour/student), so:

| Class size | Requests in a 2-hour session | Fits free tier? |
|---|---|---|
| 2–3 students | ~7,500–11,500 | ✅ a couple sessions/month |
| 5–10 students | ~19,000–38,000 | ❌ one session blows the cap → use Cloudflare |

If you outgrow it, switch to `deploy/README-CLOUDFLARE.md` (unmetered).

```
student CLion plugin ──https──► your-domain.ngrok-free.app ──► your laptop :8000
```

---

## One-time setup

1. **Install ngrok**
   ```bash
   brew install ngrok                       # macOS
   ```
2. **Connect your account** — sign up free at https://dashboard.ngrok.com/signup,
   copy the authtoken, then:
   ```bash
   ngrok config add-authtoken <YOUR_AUTHTOKEN>
   ```
3. **Claim your free static domain** — ngrok dashboard → **Domains** →
   **Create Domain**. You get e.g. `chip-calm-mallard.ngrok-free.app`.
   This URL is **permanent** — that's the whole point (package the plugin once).
4. **Point the config at it** — edit `deploy/tunnel.conf`:
   ```ini
   PROVIDER=ngrok
   NGROK_DOMAIN=chip-calm-mallard.ngrok-free.app
   ```
5. **Build the student package once** (on a JDK-21 machine — NOT the dev box),
   stamping the SAME url (note the `https://`):
   ```bash
   cd clion_plugin
   ./packaging/make_exam_package.sh --backend-url https://chip-calm-mallard.ngrok-free.app
   ```
   → `clion_plugin/dist/OsLabExam.zip` — hand this to students. They install it
   once; they never touch ngrok.

---

## Each exam session

1. Make sure `.env` is in exam mode:
   ```ini
   STUDENT_CLIENT_MODE=ide
   EXAM_MODE=true
   FULLSCREEN=true
   GEMINI_API_KEY=...          # the only LLM key needed
   ```
2. Run the control macro — it starts the backend (if needed), opens the tunnel,
   and keeps the laptop awake:
   ```bash
   bash deploy/tunnel.sh --with-backend
   ```
   (or start the backend yourself with `bash scripts/dev_up.sh`, then just
   `bash deploy/tunnel.sh`)
3. Open your dashboard at http://localhost:5173 to watch students.
4. Students run their installer once and log in with personal codes.

---

## Notes
- **Stable URL ⇒ package once.** Only change the plugin package if you change
  `NGROK_DOMAIN`. Even then you don't need JDK again — just edit
  `clion_plugin/dist/OsLabExam/exam.conf` and re-zip.
- The ngrok "browser warning" page only affects real browsers, not the plugin.
- Watch your usage at https://dashboard.ngrok.com. Nearing the request/GB cap is
  your signal to move to Cloudflare.
