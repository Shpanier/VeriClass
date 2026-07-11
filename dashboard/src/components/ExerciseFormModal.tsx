import { useState } from "react";
import { api } from "../api";
import type { FullExercise, NewExercise, ParamLabel } from "../types";
import { scanBriefRefs, substituteBrief, type BriefRef } from "../params";
import { useLang } from "../i18n";
import { Modal } from "./ui/Modal";
import { Button } from "./ui/Button";
import { Field, labelStyle } from "./ui/Field";

// Local editing shape. `paramsText` is the raw JSON the teacher types; it's
// parsed (and validated) only on submit so intermediate keystrokes are allowed.
interface TestRow {
  input: string;
  expected_output: string;
}
interface VariantDraft {
  id: string;
  paramsText: string;
  tests: TestRow[];
}
interface ParamLabelDraft {
  key: string;
  label: string;
  note: string;
}

type Mode = "create" | "edit" | "duplicate";

const blankVariant = (): VariantDraft => ({ id: "", paramsText: "{}", tests: [{ input: "", expected_output: "" }] });

// Build initial form state from a source exercise (edit/duplicate), or empty.
function initVariants(src?: FullExercise): VariantDraft[] {
  if (!src || src.variants.length === 0) return [blankVariant()];
  return src.variants.map((v) => ({
    id: v.id,
    paramsText: JSON.stringify(v.params ?? {}, null, 2),
    tests: v.test_inputs.length ? v.test_inputs.map((t) => ({ ...t })) : [{ input: "", expected_output: "" }],
  }));
}

export function ExerciseFormModal({
  mode,
  initial,
  onClose,
  onSaved,
}: {
  mode: Mode;
  initial?: FullExercise;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useLang();
  const idLocked = mode === "edit";
  const [exerciseId, setExerciseId] = useState(
    mode === "duplicate" && initial ? `${initial.exercise_id}-copy` : initial?.exercise_id ?? ""
  );
  const [titleEn, setTitleEn] = useState(initial?.title_en ?? "");
  const [titleHe, setTitleHe] = useState(initial?.title_he ?? "");
  const [defaultMode, setDefaultMode] = useState<"mentor" | "coding_partner">(initial?.default_mode ?? "mentor");
  const [briefMd, setBriefMd] = useState(initial?.brief_md ?? "");
  const [welcome, setWelcome] = useState((initial?.welcome_suggestions ?? []).join("\n"));
  const [errorStrings, setErrorStrings] = useState((initial?.required_error_strings ?? []).join("\n"));
  const [paramLabels, setParamLabels] = useState<ParamLabelDraft[]>(
    () => (initial?.param_labels ?? []).map((p) => ({ key: p.key, label: p.label ?? "", note: p.note ?? "" }))
  );
  const [variants, setVariants] = useState<VariantDraft[]>(() => initVariants(initial));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const patchVariant = (i: number, patch: Partial<VariantDraft>) =>
    setVariants((vs) => vs.map((v, idx) => (idx === i ? { ...v, ...patch } : v)));

  // "Apply": validate the brief's @-refs against the authored param labels and
  // preview the brief with the first variant's real values filled in.
  const [briefCheck, setBriefCheck] = useState<
    { refs: BriefRef[]; preview: string; sampleId: string | null } | null
  >(null);

  const currentLabels = (): ParamLabel[] =>
    paramLabels
      .filter((p) => p.key.trim())
      .map((p) => ({ key: p.key.trim(), label: p.label.trim() || null, note: p.note.trim() || null }));

  const sampleVariant = (): { id: string; params: Record<string, unknown> } | null => {
    for (const v of variants) {
      try {
        const params = v.paramsText.trim() ? JSON.parse(v.paramsText) : {};
        return { id: v.id.trim() || "?", params };
      } catch {
        // skip variants whose params JSON doesn't parse yet
      }
    }
    return null;
  };

  const runBriefCheck = () => {
    const labels = currentLabels();
    const refs = scanBriefRefs(briefMd, labels);
    const sample = sampleVariant();
    setBriefCheck({
      refs,
      preview: substituteBrief(briefMd, sample?.params, labels),
      sampleId: sample?.id ?? null,
    });
  };

  const build = (): NewExercise | { error: string } => {
    const id = exerciseId.trim();
    if (!id) return { error: t("errIdRequired") };
    if (!/^[a-z0-9][a-z0-9-]*$/.test(id)) return { error: t("errIdSlug") };
    if (!titleEn.trim()) return { error: t("errTitleRequired") };
    if (!briefMd.trim()) return { error: t("errBriefRequired") };
    if (variants.length === 0) return { error: t("errNoVariants") };

    const seen = new Set<string>();
    const built: NewExercise["variants"] = [];
    for (const v of variants) {
      const vid = v.id.trim();
      if (!vid) return { error: t("errVariantId") };
      if (seen.has(vid)) return { error: t("errDupVariant") };
      seen.add(vid);
      let params: Record<string, unknown>;
      try {
        params = v.paramsText.trim() ? JSON.parse(v.paramsText) : {};
      } catch {
        return { error: t("errParamsJson", { id: vid }) };
      }
      built.push({
        id: vid,
        params,
        test_inputs: v.tests
          .filter((r) => r.input.trim() !== "" || r.expected_output.trim() !== "")
          .map((r) => ({ input: r.input, expected_output: r.expected_output })),
      });
    }

    const lines = (s: string) => s.split("\n").map((l) => l.trim()).filter(Boolean);
    return {
      exercise_id: id,
      title_en: titleEn.trim(),
      title_he: titleHe.trim() || undefined,
      default_mode: defaultMode,
      brief_md: briefMd,
      variants: built,
      welcome_suggestions: lines(welcome),
      required_error_strings: lines(errorStrings),
      param_labels: paramLabels
        .filter((p) => p.key.trim() !== "")
        .map((p) => ({ key: p.key.trim(), label: p.label.trim() || undefined, note: p.note.trim() || undefined })),
    };
  };

  const save = async () => {
    const result = build();
    if ("error" in result) {
      setError(result.error);
      return;
    }
    setError(null);
    setSaving(true);
    try {
      if (mode === "edit" && initial) {
        await api.updateExercise(initial.exercise_id, result);
      } else {
        await api.createExercise(result);
      }
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const title =
    mode === "edit" ? t("editExerciseTitle") : mode === "duplicate" ? t("duplicateExerciseTitle") : t("newExerciseTitle");

  return (
    <Modal onClose={onClose} width={760}>
      <h3 style={{ marginTop: 0 }}>{title}</h3>

      {idLocked ? (
        <label style={{ display: "block", marginBottom: 12 }}>
          <span style={labelStyle}>{t("fldExerciseId")}</span>
          <input
            value={exerciseId}
            disabled
            style={{ width: "100%", padding: "6px 8px", border: "1px solid #e5e7eb", borderRadius: 6, fontSize: 13, fontFamily: "ui-monospace, monospace", background: "#f9fafb", color: "#6b7280", boxSizing: "border-box" }}
          />
        </label>
      ) : (
        <Field label={t("fldExerciseId")} value={exerciseId} onChange={setExerciseId} placeholder="my-task-1" monospace />
      )}

      <Field label={t("fldTitleEn")} value={titleEn} onChange={setTitleEn} />
      <Field label={t("fldTitleHe")} value={titleHe} onChange={setTitleHe} />

      <label style={{ display: "block", marginBottom: 12 }}>
        <span style={labelStyle}>{t("fldDefaultMode")}</span>
        <select
          value={defaultMode}
          onChange={(e) => setDefaultMode(e.target.value as "mentor" | "coding_partner")}
          style={{ padding: "6px 8px", borderRadius: 6, border: "1px solid #d1d5db", fontSize: 13 }}
        >
          <option value="mentor">{t("mentor")}</option>
          <option value="coding_partner">{t("codingPartner")}</option>
        </select>
      </label>

      <Field label={t("fldBrief")} value={briefMd} onChange={setBriefMd} textarea minHeight={120} />
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: -6, marginBottom: 12 }}>
        <Button onClick={runBriefCheck}>{t("applyBrief")}</Button>
        <span style={{ fontSize: 12, color: "#6b7280" }} dir="auto">{t("applyBriefHint")}</span>
      </div>
      {briefCheck && (
        <div style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 12, marginBottom: 12, background: "#f9fafb" }}>
          {briefCheck.refs.length === 0 ? (
            <div style={{ fontSize: 12, color: "#6b7280" }} dir="auto">{t("applyNoRefs")}</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 3, marginBottom: 10 }}>
              {briefCheck.refs.map((r) => (
                <div key={r.ref} style={{ fontSize: 13, color: r.ok ? "#065f46" : "#b91c1c" }} dir="auto">
                  {r.ok ? "✓" : "✗"} <code>@{r.ref}</code>
                  {r.ok ? ` → ${r.label}` : ` — ${t("applyUnknownRef")}`}
                </div>
              ))}
            </div>
          )}
          <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 4 }} dir="auto">
            {briefCheck.sampleId
              ? t("applyPreviewFor", { id: briefCheck.sampleId })
              : t("applyPreviewNoVariant")}
          </div>
          <div style={{ fontSize: 13, whiteSpace: "pre-wrap", background: "white", border: "1px solid #e5e7eb", borderRadius: 6, padding: 10 }} dir="auto">
            {briefCheck.preview}
          </div>
        </div>
      )}
      <Field label={t("fldWelcome")} value={welcome} onChange={setWelcome} textarea minHeight={60} />
      <Field label={t("fldErrorStrings")} value={errorStrings} onChange={setErrorStrings} textarea monospace minHeight={60} />

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 8, marginBottom: 4 }}>
        <strong style={{ fontSize: 14 }}>{t("paramLabelsSection")}</strong>
        <Button onClick={() => setParamLabels((ps) => [...ps, { key: "", label: "", note: "" }])}>
          {t("addParamLabel")}
        </Button>
      </div>
      <p style={{ fontSize: 12, color: "#6b7280", marginTop: 0, marginBottom: 8 }} dir="auto">{t("paramLabelsHint")}</p>
      {paramLabels.map((pl, i) => (
        <div key={i} style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6 }}>
          <input
            value={pl.key}
            dir="auto"
            placeholder={t("fldParamKey")}
            onChange={(e) => setParamLabels((ps) => ps.map((p, idx) => (idx === i ? { ...p, key: e.target.value } : p)))}
            style={{ flex: "0 0 28%", padding: "5px 7px", border: "1px solid #d1d5db", borderRadius: 4, fontSize: 13, fontFamily: "ui-monospace, monospace", boxSizing: "border-box" }}
          />
          <input
            value={pl.label}
            dir="auto"
            placeholder={t("fldParamLabel")}
            onChange={(e) => setParamLabels((ps) => ps.map((p, idx) => (idx === i ? { ...p, label: e.target.value } : p)))}
            style={{ flex: "0 0 32%", padding: "5px 7px", border: "1px solid #d1d5db", borderRadius: 4, fontSize: 13, boxSizing: "border-box" }}
          />
          <input
            value={pl.note}
            dir="auto"
            placeholder={t("fldParamNote")}
            onChange={(e) => setParamLabels((ps) => ps.map((p, idx) => (idx === i ? { ...p, note: e.target.value } : p)))}
            style={{ flex: 1, padding: "5px 7px", border: "1px solid #d1d5db", borderRadius: 4, fontSize: 13, boxSizing: "border-box" }}
          />
          <button
            onClick={() => setParamLabels((ps) => ps.filter((_, idx) => idx !== i))}
            style={{ border: "none", background: "none", color: "#b91c1c", cursor: "pointer", fontSize: 12 }}
            aria-label={t("remove")}
          >
            ✕
          </button>
        </div>
      ))}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 12, marginBottom: 8 }}>
        <strong style={{ fontSize: 14 }}>{t("variantsSection")}</strong>
        <Button onClick={() => setVariants((vs) => [...vs, blankVariant()])}>{t("addVariant")}</Button>
      </div>

      {variants.map((v, i) => (
        <div key={i} style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 12, marginBottom: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
            <div style={{ flex: 1 }}>
              <Field label={t("fldVariantId")} value={v.id} onChange={(val) => patchVariant(i, { id: val })} placeholder="V-A1" monospace />
            </div>
            {variants.length > 1 && (
              <button
                onClick={() => setVariants((vs) => vs.filter((_, idx) => idx !== i))}
                style={{ marginInlineStart: 8, marginTop: 22, border: "none", background: "none", color: "#b91c1c", cursor: "pointer", fontSize: 12 }}
              >
                {t("removeVariant")}
              </button>
            )}
          </div>

          <Field
            label={t("fldParams")}
            value={v.paramsText}
            onChange={(val) => patchVariant(i, { paramsText: val })}
            textarea
            monospace
            minHeight={50}
            placeholder='{"max_number": 100, "operators": ["+","-"], "allow_parens": false}'
          />

          <span style={labelStyle}>{t("testInputs")}</span>
          <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 6 }}>
            <thead>
              <tr style={{ color: "#6b7280", fontSize: 12, textAlign: "start" }}>
                <th style={{ textAlign: "start", fontWeight: 500 }}>{t("thInput")}</th>
                <th style={{ textAlign: "start", fontWeight: 500 }}>{t("thExpected")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {v.tests.map((row, ri) => (
                <tr key={ri}>
                  <td style={{ paddingBottom: 4, paddingInlineEnd: 6 }}>
                    <input
                      value={row.input}
                      dir="auto"
                      onChange={(e) => patchVariant(i, { tests: v.tests.map((r, idx) => (idx === ri ? { ...r, input: e.target.value } : r)) })}
                      style={{ width: "100%", padding: "4px 6px", border: "1px solid #d1d5db", borderRadius: 4, fontSize: 13, fontFamily: "ui-monospace, monospace", boxSizing: "border-box" }}
                    />
                  </td>
                  <td style={{ paddingBottom: 4, paddingInlineEnd: 6 }}>
                    <input
                      value={row.expected_output}
                      dir="auto"
                      onChange={(e) => patchVariant(i, { tests: v.tests.map((r, idx) => (idx === ri ? { ...r, expected_output: e.target.value } : r)) })}
                      style={{ width: "100%", padding: "4px 6px", border: "1px solid #d1d5db", borderRadius: 4, fontSize: 13, fontFamily: "ui-monospace, monospace", boxSizing: "border-box" }}
                    />
                  </td>
                  <td style={{ width: 1, whiteSpace: "nowrap" }}>
                    <button
                      onClick={() => patchVariant(i, { tests: v.tests.filter((_, idx) => idx !== ri) })}
                      style={{ border: "none", background: "none", color: "#b91c1c", cursor: "pointer", fontSize: 12 }}
                      aria-label={t("remove")}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Button onClick={() => patchVariant(i, { tests: [...v.tests, { input: "", expected_output: "" }] })}>
            {t("addTestInput")}
          </Button>
        </div>
      ))}

      {error && (
        <div style={{ color: "#b91c1c", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 6, padding: "8px 12px", marginTop: 8, fontSize: 13 }} dir="auto">
          {error}
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
        <Button onClick={onClose}>{t("cancel")}</Button>
        <Button variant="primary" onClick={save} disabled={saving}>
          {saving ? t("saving") : t("saveExercise")}
        </Button>
      </div>
    </Modal>
  );
}
