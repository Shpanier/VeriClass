import { useEffect, useState } from "react";
import { Check, GraduationCap, MonitorSmartphone } from "lucide-react";
import { api, auth, createFirstTeacher, type LlmStatus } from "../api";
import { LanguageToggle, useLang } from "../i18n";
import { describeError } from "../lib/errors";
import { Button, Field, Loading, Notice } from "../components/ui";
import { TutorForm } from "./TutorForm";

/** A brand-new server: create the lecturer's account, then connect the AI
 *  tutor. Shown instead of the sign-in screen while no lecturer exists. */
export function FirstRun({ local, onDone }: { local: boolean; onDone: () => void }) {
  const { t } = useLang();
  const [step, setStep] = useState<1 | 2>(1);
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [llm, setLlm] = useState<LlmStatus | null>(null);

  useEffect(() => {
    if (step !== 2) return;
    api.settings().then((s) => setLlm(s.llm)).catch((e) => setError(describeError(e, t)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  if (!local) {
    return (
      <div className="vc-auth">
        <div className="vc-auth__card">
          <div className="vc-auth__top"><Brand /><LanguageToggle /></div>
          <Notice tone="info" title={t("frRemoteTitle")}>{t("frRemoteBody")}</Notice>
        </div>
      </div>
    );
  }

  const mismatch = password2.length > 0 && password !== password2;
  const ready = name.trim() && username.trim().length >= 3 && password.length >= 6 && password === password2;

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      const res = await createFirstTeacher(name.trim(), username.trim(), password);
      auth.set(res.token);
      setStep(2);
    } catch (err) {
      setError(describeError(err, t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="vc-auth">
      <div className="vc-auth__card vc-auth__card--wide">
        <div className="vc-auth__top"><Brand /><LanguageToggle /></div>
        <div className="vc-steps" aria-hidden="true">
          <span className="vc-steps__dot" data-state={step === 1 ? "now" : "done"}>{step === 1 ? "1" : <Check />}</span>
          <span>{t("frStepAccount")}</span>
          <span className="vc-steps__line" />
          <span className="vc-steps__dot" data-state={step === 2 ? "now" : "todo"}>2</span>
          <span>{t("frStepTutor")}</span>
        </div>

        {step === 1 ? (
          <form onSubmit={create}>
            <h1 className="vc-auth__title">{t("frWelcome")}</h1>
            <p className="vc-auth__lead">{t("frLead")}</p>
            <Field label={t("frName")} value={name} onChange={setName} autoFocus required autoComplete="name" />
            <Field label={t("frUsername")} value={username} onChange={setUsername} hint={t("frUsernameHint")}
                   required autoComplete="username" />
            <Field label={t("frPassword")} value={password} onChange={setPassword} type="password"
                   hint={t("frPasswordHint")} required autoComplete="new-password" />
            <Field label={t("frPassword2")} value={password2} onChange={setPassword2} type="password"
                   error={mismatch ? t("frMismatch") : undefined} required autoComplete="new-password" />
            {error && <Notice tone="danger" className="u-mb-12">{error}</Notice>}
            <Button variant="primary" size="lg" block type="submit" disabled={!ready} busy={busy}>{t("frCreate")}</Button>
          </form>
        ) : (
          <>
            <h1 className="vc-auth__title">{t("tuTitle")}</h1>
            <p className="vc-auth__lead">{t("tuLead")}</p>
            {error && <Notice tone="danger" className="u-mb-12">{error}</Notice>}
            {llm ? (
              <TutorForm
                llm={llm} saveLabel={t("tuSaveContinue")} onSaved={() => onDone()}
                extraActions={<Button variant="quiet" onClick={onDone}>{t("tuSkip")}</Button>}
              />
            ) : !error && <Loading />}
            <p className="vc-hint u-mt-12">{t("tuSkipNote")}</p>
          </>
        )}
      </div>
    </div>
  );
}

export function Brand() {
  return (
    <span className="vc-brand">
      <span className="vc-brand__mark"><GraduationCap /></span>
      VeriClass
    </span>
  );
}

/** Shown while the first request decides which screen comes next. */
export function Splash({ error, onRetry }: { error?: string | null; onRetry?: () => void }) {
  const { t } = useLang();
  return (
    <div className="vc-auth">
      <div className="vc-auth__card">
        <div className="vc-auth__top"><Brand /></div>
        {error ? (
          <Notice tone="danger" action={onRetry && <Button size="sm" onClick={onRetry}>{t("retry")}</Button>}>
            {error}
          </Notice>
        ) : <Loading />}
        {error && <p className="vc-auth__foot"><MonitorSmartphone size={13} style={{ verticalAlign: "-2px" }} /> start.command · start.bat · ./start.sh</p>}
      </div>
    </div>
  );
}
