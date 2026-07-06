import { useState } from "react";
import { login, auth } from "../api";

interface Props {
  onLoggedIn: () => void;
}

// The dashboard is now behind a teacher login. Only a user whose role is
// 'teacher' may see student data; a student code is rejected here even though
// it authenticates, because every dashboard endpoint requires require_teacher.
export function LoginGate({ onLoggedIn }: Props) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await login(code.trim().toUpperCase());
      if (res.role !== "teacher") {
        setError("That code isn't an instructor account.");
        return;
      }
      auth.set(res.token);
      onLoggedIn();
    } catch (err) {
      setError(err instanceof Error && err.message === "bad-code"
        ? "Code not recognized."
        : "Login failed — is the backend running?");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "100vh", fontFamily: "system-ui" }}>
      <form
        onSubmit={submit}
        style={{ display: "flex", flexDirection: "column", gap: 12, width: 320,
                 padding: 24, border: "1px solid #e5e7eb", borderRadius: 10 }}
      >
        <strong style={{ fontSize: 18 }}>OS Lab · Instructor sign-in</strong>
        <span style={{ color: "#6b7280", fontSize: 13 }}>כניסת מרצה — enter your instructor code</span>
        <input
          autoFocus
          value={code}
          dir="auto"
          onChange={(e) => setCode(e.target.value)}
          placeholder="e.g. TEACH-01"
          style={{ padding: "8px 10px", borderRadius: 6, border: "1px solid #d1d5db", fontSize: 15 }}
        />
        {error && <span style={{ color: "#b91c1c", fontSize: 13 }}>{error}</span>}
        <button
          type="submit"
          disabled={busy || !code.trim()}
          style={{ padding: "8px 16px", borderRadius: 6, border: "none", cursor: "pointer",
                   background: "#111827", color: "white", fontWeight: 600 }}
        >
          {busy ? "…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
