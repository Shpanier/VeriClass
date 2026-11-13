import { useCallback, useEffect, useRef, useState } from "react";
import { login, auth } from "../api";
import { LanguageToggle, useLang } from "../i18n";
import { describeError } from "../lib/errors";
import { Button, Field, Notice } from "./ui";
import { Brand } from "../app/FirstRun";

interface Props {
  onLoggedIn: () => void;
}

// Dev-mode auto-login, mirroring the student app's DEV_AUTO_LOGIN_CODE. Set
// VITE_DEV_AUTO_LOGIN_CODE to a teacher code in dashboard/.env.local and the
// gate signs in automatically, once. Only ever honored when Vite runs in dev
// mode (import.meta.env.DEV); production builds compile this down to "".
const DEV_CODE = import.meta.env.DEV
  ? ((import.meta.env.VITE_DEV_AUTO_LOGIN_CODE as string) || "").trim().toUpperCase()
  : "";
// "Sign out" must stay signed out: the automatic sign-in happens once per page load.
let devAutoTried = false;

// The dashboard is behind a lecturer's sign-in. A student's username is refused
// here even though it authenticates: every dashboard endpoint needs a lecturer.
export function LoginGate({ onLoggedIn }: Props) {
  const { t } = useLang();
  const [code, setCode] = useState(devAutoTried ? "" : DEV_CODE);
  // Until a password is set, it is the username itself (backend/passwords.py).
  const [password, setPassword] = useState(devAutoTried ? "" : DEV_CODE);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const attempt = useCallback(
    async (raw: string, pass: string) => {
      setError(null);
      setBusy(true);
      try {
        const res = await login(raw.trim().toUpperCase(), pass);
        if (res.role !== "teacher") {
          setError(t("loginNotTeacher"));
          return;
        }
        auth.set(res.token);
        onLoggedIn();
      } catch (err) {
        setError(err instanceof Error && err.message === "bad-code" ? t("loginBad") : describeError(err, t));
      } finally {
        setBusy(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [onLoggedIn],
  );

  const started = useRef(false);
  useEffect(() => {
    if (DEV_CODE && !devAutoTried && !started.current) {
      started.current = true;
      devAutoTried = true;
      attempt(DEV_CODE, DEV_CODE);
    }
  }, [attempt]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    attempt(code, password);
  };

  return (
    <div className="vc-auth">
      <form className="vc-auth__card" onSubmit={submit}>
        <div className="vc-auth__top"><Brand /><LanguageToggle /></div>
        <h1 className="vc-auth__title">{t("loginTitle")}</h1>
        <p className="vc-auth__lead">{t("loginLead")}</p>
        <Field label={t("loginUser")} value={code} onChange={setCode} autoFocus autoComplete="username" />
        <Field label={t("loginPass")} value={password} onChange={setPassword} type="password"
               autoComplete="current-password" />
        {DEV_CODE && busy && <Notice tone="warning" className="u-mb-12">Dev mode: signing in as <code>{DEV_CODE}</code>…</Notice>}
        {error && <Notice tone="danger" className="u-mb-12">{error}</Notice>}
        <Button variant="primary" size="lg" block type="submit" disabled={!code.trim() || !password} busy={busy}>
          {t("loginBtn")}
        </Button>
        <p className="vc-auth__foot">{t("loginFoot")}</p>
      </form>
    </div>
  );
}
