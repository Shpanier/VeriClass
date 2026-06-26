import { useEffect, useState } from "react";
import { api } from "../api";
import type { Lang, ProbeSuggestion, Student } from "../types";
import { useLang } from "../i18n";

interface Props {
  student: Student;
  onClose: () => void;
  onSent: () => void;
}

export function AskThemModal({ student, onClose, onSent }: Props) {
  const { t, lang: dashLang } = useLang();
  const [lang, setLang] = useState<Lang>(dashLang);
  const [suggestions, setSuggestions] = useState<ProbeSuggestion[]>([]);
  const [edited, setEdited] = useState<Record<number, string>>({});
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [own, setOwn] = useState("");
  const [loading, setLoading] = useState(true);

  const fetchSuggestions = () => {
    setLoading(true);
    api
      .suggestProbes(student.session_id, lang)
      .then((s) => {
        setSuggestions(s);
        setLoading(false);
      })
      .catch((e) => {
        console.error(e);
        setLoading(false);
      });
  };

  // Re-fetch when the session or the chosen language changes.
  useEffect(fetchSuggestions, [student.session_id, lang]);

  const send = async () => {
    const bodies: string[] = [];
    picked.forEach((i) => bodies.push(edited[i] ?? suggestions[i].body));
    if (own.trim()) bodies.push(own.trim());
    if (bodies.length === 0) return;
    await api.sendProbes(student.session_id, bodies, picked.size > 0 ? "suggested" : "manual");
    onSent();
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "grid",
        placeItems: "center",
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        style={{ background: "white", padding: 24, borderRadius: 8, width: 720, maxHeight: "80vh", overflow: "auto" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <h3 style={{ marginTop: 0 }}>
            {t("askTitle", { name: student.username, variant: student.variant })}
          </h3>
          {/* Language the probe questions are generated in. */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
            <span style={{ color: "#6b7280", fontSize: 12 }}>{t("answersIn")}:</span>
            {(["en", "he"] as Lang[]).map((opt) => (
              <button
                key={opt}
                onClick={() => setLang(opt)}
                style={{
                  padding: "3px 8px", borderRadius: 4, fontSize: 12, cursor: "pointer",
                  border: "1px solid " + (lang === opt ? "#111827" : "#d1d5db"),
                  background: lang === opt ? "#111827" : "white",
                  color: lang === opt ? "white" : "#374151",
                  fontWeight: 600,
                }}
              >
                {opt === "en" ? "EN" : "עב"}
              </button>
            ))}
          </div>
        </div>

        {loading && <p>{t("genSuggestions")}</p>}

        {suggestions.map((s, i) => (
          <div key={i} style={{ border: "1px solid #eee", borderRadius: 6, padding: 12, marginBottom: 8 }}>
            <label style={{ display: "flex", alignItems: "start", gap: 8 }}>
              <input
                type="checkbox"
                checked={picked.has(i)}
                onChange={(e) => {
                  const next = new Set(picked);
                  if (e.target.checked) next.add(i);
                  else next.delete(i);
                  setPicked(next);
                }}
              />
              <div style={{ flex: 1 }}>
                <div>
                  <strong>[{s.kind}]</strong>
                </div>
                <textarea
                  value={edited[i] ?? s.body}
                  dir="auto"
                  onChange={(e) => setEdited({ ...edited, [i]: e.target.value })}
                  style={{ width: "100%", minHeight: 60, marginTop: 4 }}
                />
                <div style={{ fontSize: 12, color: "#666", marginTop: 4 }}>{s.rationale}</div>
              </div>
            </label>
          </div>
        ))}

        <button onClick={fetchSuggestions} disabled={loading} style={{ marginRight: 8 }}>
          {t("suggestMore")}
        </button>

        <hr />
        <label>
          {t("writeOwn")}
          <textarea
            value={own}
            dir="auto"
            onChange={(e) => setOwn(e.target.value)}
            style={{ width: "100%", minHeight: 50, marginTop: 4 }}
          />
        </label>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
          <button onClick={onClose}>{t("cancel")}</button>
          <button
            onClick={send}
            style={{ background: "#f97316", color: "white", border: "none", padding: "8px 16px", borderRadius: 6 }}
          >
            {t("sendQuestions", { n: picked.size + (own.trim() ? 1 : 0) })}
          </button>
        </div>
      </div>
    </div>
  );
}
