import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { api, type KeyCheck, type LlmStatus } from "../api";
import { useLang } from "../i18n";
import { describeError } from "../lib/errors";
import { Button, FormField, Input, Notice } from "../components/ui";

/** Choose the provider and paste its API key: the same form in the first-run
 *  screen and in Settings. The key is checked with the provider before it is
 *  saved; a refused key is not saved. */
export function TutorForm({ llm, onSaved, saveLabel, extraActions }: {
  llm: LlmStatus;
  onSaved: (llm: LlmStatus, check: KeyCheck) => void;
  saveLabel: string;
  /** Buttons next to Save (first run: "Skip for now"). */
  extraActions?: React.ReactNode;
}) {
  const { t } = useLang();
  // Nothing connected yet: start on the recommended provider, not on the
  // server's built-in default.
  const [provider, setProvider] = useState(
    llm.ready ? llm.provider : (llm.providers.find((p) => p.key_set)?.id ?? llm.providers[0].id));
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState<"check" | "save" | null>(null);
  const [check, setCheck] = useState<KeyCheck | null>(null);
  const [error, setError] = useState<string | null>(null);

  const spec = llm.providers.find((p) => p.id === provider) ?? llm.providers[0];
  const canSubmit = key.trim().length > 0 || spec.key_set;

  const pick = (id: string) => { setProvider(id); setKey(""); setCheck(null); setError(null); };

  const run = async (what: "check" | "save") => {
    setBusy(what);
    setError(null);
    setCheck(null);
    try {
      if (what === "check") {
        setCheck(await api.testLlm(provider, key.trim() || undefined));
      } else {
        const r = await api.saveLlm(provider, key.trim() || undefined);
        setKey("");
        onSaved(r.llm, r.check);
      }
    } catch (e) {
      setError(describeError(e, t));
    } finally {
      setBusy(null);
    }
  };

  return (
    <form onSubmit={(e) => { e.preventDefault(); if (canSubmit) run("save"); }}>
      <div className="vc-choice" role="group" aria-label={t("setTutor")}>
        {llm.providers.map((p) => (
          <button key={p.id} type="button" className="vc-choice__item" aria-pressed={p.id === provider}
                  onClick={() => pick(p.id)}>
            <span className="vc-choice__name">{p.label}</span>
            <span className="vc-choice__note">{t(p.id === "anthropic" ? "tuAnthropicNote" : "tuGeminiNote")}</span>
          </button>
        ))}
      </div>

      <FormField
        label={t("tuKey")}
        hint={<>
          {spec.key_set ? t("tuKeyKeep", { hint: spec.key_hint }) : t("tuKeyHint")}{" "}
          <a href={spec.key_url} target="_blank" rel="noreferrer">
            {t("tuGetKey", { provider: spec.label })} <ExternalLink size={12} style={{ verticalAlign: "-1px" }} />
          </a>
        </>}
      >
        <Input type="password" dir="ltr" mono autoComplete="off" spellCheck={false} value={key}
               placeholder={spec.key_set ? "••••••••••••" + spec.key_hint.replace("…", "") : ""}
               onChange={(e) => { setKey(e.target.value); setCheck(null); setError(null); }} />
      </FormField>

      {check && <Notice tone={check.ok ? (check.model_ok === false ? "warning" : "success") : "danger"} className="u-mb-12">{check.message}</Notice>}
      {error && <Notice tone="danger" className="u-mb-12">{error}</Notice>}

      <div className="u-row u-wrap">
        <Button variant="primary" type="submit" disabled={!canSubmit || busy !== null} busy={busy === "save"}>{saveLabel}</Button>
        <Button onClick={() => run("check")} disabled={!canSubmit || busy !== null} busy={busy === "check"}>{t("tuCheck")}</Button>
        <span className="u-push" />
        {extraActions}
      </div>
    </form>
  );
}
