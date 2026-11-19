import "../styles/review.css";
import { useEffect, useId, useRef, useState } from "react";
import { RefreshCw, Send } from "lucide-react";
import { api } from "../api";
import type { Lang, ProbeSuggestion, Student } from "../types";
import { useLang, type StringKey } from "../i18n";
import { Button, FormField, Loading, Modal, Notice, Textarea, useToast } from "./ui";
import { textDir } from "../lib/textDir";

interface Props {
  student: Student;
  onClose: () => void;
  onSent: () => void;
}

/** The kinds of question the tutor suggests (backend/agents/probe.py), in plain words. */
const KIND: Record<string, StringKey> = {
  trace: "askKindTrace",
  why: "askKindWhy",
  counterfactual: "askKindWhatIf",
  "failure-mode": "askKindFailure",
  "bug-localization": "askKindBug",
};

/** The lecturer's own questions to one student: the tutor suggests some, the
 *  lecturer picks, edits or writes their own, and the student is asked them in the chat. */
export function AskThemModal({ student, onClose, onSent }: Props) {
  const { t, lang: dashLang } = useLang();
  const toast = useToast();
  const langLabel = useId();
  const [lang, setLang] = useState<Lang>(dashLang);
  const [suggestions, setSuggestions] = useState<ProbeSuggestion[]>([]);
  const [edited, setEdited] = useState<Record<number, string>>({});
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [own, setOwn] = useState("");
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [sending, setSending] = useState(false);
  // Only the latest request's answer is used: one still out when the language
  // is switched (or that React's development mode started twice) is ignored.
  const latest = useRef(0);

  const fetchSuggestions = () => {
    const mine = ++latest.current;
    setLoading(true);
    setFailed(false);
    // Reset index-keyed selection/edits: after a refetch the list contents
    // change, so a stale checkbox #2 or edit would attach to a different (or
    // missing) question. Clear them so indices always match the new list.
    setPicked(new Set());
    setEdited({});
    api
      .suggestProbes(student.session_id, lang)
      .then((s) => {
        if (mine === latest.current) setSuggestions(s);
      })
      .catch(() => {
        if (mine === latest.current) setFailed(true);
      })
      .finally(() => {
        if (mine === latest.current) setLoading(false);
      });
  };

  // Re-fetch when the session or the chosen language changes; an answer that
  // arrives after that (or after the dialog closed) is ignored.
  useEffect(() => {
    fetchSuggestions();
    return () => { latest.current += 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [student.session_id, lang]);

  // What a send would send. Guard suggestions[i]: a refetch may have shortened the list.
  const bodies: string[] = [];
  picked.forEach((i) => {
    const body = edited[i] ?? suggestions[i]?.body;
    if (body) bodies.push(body);
  });
  if (own.trim()) bodies.push(own.trim());
  const dirty = own.trim() !== "" || picked.size > 0 || Object.keys(edited).length > 0;

  const send = async () => {
    if (bodies.length === 0 || sending) return;
    setSending(true);
    try {
      await api.sendProbes(student.session_id, bodies, picked.size > 0 ? "suggested" : "manual");
      toast.success(bodies.length === 1
        ? t("askSentOne", { name: student.username })
        : t("askSentMany", { n: bodies.length, name: student.username }));
      onSent();
    } catch (e) {
      toast.error(t("askSendFailed"), e);
      setSending(false);
    }
  };

  const togglePick = (i: number, on: boolean) => {
    const next = new Set(picked);
    if (on) next.add(i);
    else next.delete(i);
    setPicked(next);
  };

  const kindName = (kind: string) => {
    const key = KIND[kind.trim().toLowerCase()];
    return key ? t(key) : kind;
  };

  return (
    <Modal
      title={t("askTitle", { name: student.username })}
      subtitle={t("askLead")}
      size="lg"
      dirty={dirty && !sending}
      onClose={onClose}
      footer={
        <>
          <span className="u-push" />
          <Button onClick={onClose}>{t("cancel")}</Button>
          <Button variant="primary" icon={<Send />} busy={sending} disabled={bodies.length === 0} onClick={send}>
            {bodies.length === 0 ? t("askSendNone")
              : bodies.length === 1 ? t("askSendOne") : t("askSendMany", { n: bodies.length })}
          </Button>
        </>
      }
    >
      <div className="u-row u-wrap u-between u-gap-12 u-mb-12">
        <h3 className="u-md">{t("askSuggestions")}</h3>
        <div className="u-row u-wrap">
          {/* The language the questions are written in. */}
          <span className="u-muted u-sm" id={langLabel}>{t("askLang")}</span>
          <div className="vc-segmented" role="group" aria-labelledby={langLabel}>
            {(["en", "he"] as Lang[]).map((opt) => (
              <button key={opt} type="button" lang={opt} aria-pressed={lang === opt} onClick={() => setLang(opt)}>
                {opt === "en" ? "English" : "עברית"}
              </button>
            ))}
          </div>
          <Button size="sm" icon={<RefreshCw />} disabled={loading} onClick={fetchSuggestions}>{t("suggestMore")}</Button>
        </div>
      </div>

      {failed && <Notice tone="warning" className="u-mb-12">{t("askSuggestFailed")}</Notice>}
      {loading ? (
        <Loading>{t("genSuggestions")}</Loading>
      ) : suggestions.length === 0 ? (
        !failed && <p className="u-muted u-sm">{t("askNoSuggestions")}</p>
      ) : (
        <div className="u-col">
          {suggestions.map((s, i) => (
            <div key={i} className="vc-review-ask" data-picked={picked.has(i)}>
              <input type="checkbox" checked={picked.has(i)} aria-label={t("askPick", { n: i + 1 })}
                     onChange={(e) => togglePick(i, e.target.checked)} />
              <div className="u-grow u-col u-gap-6">
                <div><span className="vc-badge vc-badge--brand">{kindName(s.kind)}</span></div>
                <Textarea
                  value={edited[i] ?? s.body}
                  rows={3}
                  aria-label={t("askEditLabel", { n: i + 1 })}
                  onChange={(e) => setEdited({ ...edited, [i]: e.target.value })}
                />
                {s.rationale && <div className="vc-hint" dir={textDir(s.rationale)}>{s.rationale}</div>}
              </div>
            </div>
          ))}
        </div>
      )}

      <hr className="vc-divider" />
      <FormField label={t("writeOwn")} className="u-mb-0">
        <Textarea value={own} rows={3} onChange={(e) => setOwn(e.target.value)} />
      </FormField>
    </Modal>
  );
}
