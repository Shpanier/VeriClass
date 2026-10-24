import { useCallback, useEffect, useRef, useState } from "react";
import { login, auth } from "../api";

interface Props {
  onLoggedIn: () => void;
}

// Dev-mode auto-login, mirroring the student app's DEV_AUTO_LOGIN_CODE. Set
// VITE_DEV_AUTO_LOGIN_CODE to a teacher code in dashboard/.env.local and the
// gate signs in automatically. Only ever honored when Vite runs in dev mode
// (import.meta.env.DEV) — production builds compile this down to "".
const DEV_CODE = import.meta.env.DEV
  ? ((import.meta.env.VITE_DEV_AUTO_LOGIN_CODE as string) || "").trim().toUpperCase()
  : "";

// The dashboard is now behind a teacher login. Only a user whose role is
// 'teacher' may see student data; a student code is rejected here even though
// it authenticates, because every dashboard endpoint requires require_teacher.
export function LoginGate({ onLoggedIn }: Props) {
  const [code, setCode] = useState(DEV_CODE);
  // Until the teacher sets a password, it is the login code (backend/passwords.py).
  const [password, setPassword] = useState(DEV_CODE);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const attempt = useCallback(
    async (raw: string, pass: string) => {
      setError(null);
      setBusy(true);
      try {
        const res = await login(raw.trim().toUpperCase(), pass);
        if (res.role !== "teacher") {
          setError("That code isn't an instructor account.");
          return;
        }
        auth.set(res.token);
        onLoggedIn();
      } catch (err) {
        setError(err instanceof Error && err.message === "bad-code"
          ? "Wrong code or password."
          : "Login failed — is the backend running?");
      } finally {
        setBusy(false);
      }
    },
    [onLoggedIn],
  );

  // In dev, sign in automatically once with the configured teacher code.
  const autoTried = useRef(false);
  useEffect(() => {
    if (DEV_CODE && !autoTried.current) {
      autoTried.current = true;
      attempt(DEV_CODE, DEV_CODE);
    }
  }, [attempt]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    attempt(code, password);
  };

  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "100vh", fontFamily: "system-ui" }}>
      <form
        onSubmit={submit}
        style={{ display: "flex", flexDirection: "column", gap: 12, width: 320,
                 padding: 24, border: "1px solid #e5e7eb", borderRadius: 10 }}
      >
        <strong style={{ fontSize: 18 }}>VeriClass · Instructor sign-in</strong>
        <span style={{ color: "#6b7280", fontSize: 13 }}>כניסת מרצה — enter your instructor code</span>
        <input
          autoFocus
          value={code}
          dir="auto"
          onChange={(e) => setCode(e.target.value)}
          placeholder="e.g. TEACH-01"
          aria-label="Instructor code"
          style={{ padding: "8px 10px", borderRadius: 6, border: "1px solid #d1d5db", fontSize: 15 }}
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password (at first: your code)"
          aria-label="Password"
          autoComplete="current-password"
          style={{ padding: "8px 10px", borderRadius: 6, border: "1px solid #d1d5db", fontSize: 15 }}
        />
        {DEV_CODE && (
          <span style={{ color: "#92400e", background: "#fef3c7", borderRadius: 6,
                         padding: "6px 8px", fontSize: 12 }}>
            🛠️ Dev mode: teacher code <code>{DEV_CODE}</code> — signing in…
          </span>
        )}
        {error && <span style={{ color: "#b91c1c", fontSize: 13 }}>{error}</span>}
        <button
          type="submit"
          disabled={busy || !code.trim() || !password}
          style={{ padding: "8px 16px", borderRadius: 6, border: "none", cursor: "pointer",
                   background: "#111827", color: "white", fontWeight: 600 }}
        >
          {busy ? "…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
