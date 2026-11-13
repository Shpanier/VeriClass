import { Fragment, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { AlertCircle, ArrowDown, ArrowUp, CheckCircle2, ChevronDown, ChevronRight, Eye, EyeOff, Plus, Trash2, XCircle } from "lucide-react";
import { api } from "../api";
import type { AnswerInChat, FullExercise, NewExercise, ParamLabel, QuizReview, StepDraft, Variant } from "../types";
import { scanBriefRefs, substituteBrief, type BriefRef } from "../params";
import { useLang, type StringKey, type Translate } from "../i18n";
import { useFeatures } from "../app/features";
import { ApiError, describeError } from "../lib/errors";
import { Button, Field, FormField, Input, Modal, Notice, Select, Switch, Textarea, useConfirm } from "./ui";
import "../styles/exercises.css";

// Local editing shape. `paramsText` is the raw JSON the lecturer types; it's
// parsed (and validated) only on save so intermediate keystrokes are allowed.
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
type OutputInChat = "confirm" | "accept" | "ask" | "off";

// A step as typed: numbers stay text until saved.
interface StepRow {
  title: string;
  text: string;
  minutes: string;
  expected: string;
  questions: string;
  expected_output: string;
  checks: { match: string; hint: string }[];
}
const toRow = (s: StepDraft): StepRow => ({
  title: s.title ?? "", text: s.text ?? "", minutes: s.minutes != null ? String(s.minutes) : "",
  expected: s.expected ?? "", questions: s.questions != null ? String(s.questions) : "",
  expected_output: s.expected_output ?? "",
  checks: (s.expect_output ?? []).map((c) => ({ match: c.match, hint: c.hint ?? "" })),
});
const blankStep = (): StepRow => ({
  title: "", text: "", minutes: "", expected: "", questions: "", expected_output: "", checks: [],
});

const blankVariant = (): VariantDraft => ({ id: "", paramsText: "{}", tests: [{ input: "", expected_output: "" }] });

// The one variant of an exercise in which every student gets the same thing
// (the server needs at least one, and stores this one as a variant named "default").
const SAME_FOR_ALL: Variant = { id: "default", params: {}, test_inputs: [] };

/** Exactly one variant named "default", without values or tests: every student gets the same exercise. */
function isSameForAll(vs: Variant[]): boolean {
  return vs.length === 1 && vs[0].id === "default" && Object.keys(vs[0].params ?? {}).length === 0
    && (vs[0].test_inputs ?? []).length === 0;
}

// Build initial form state from a source exercise (edit/duplicate), or empty.
function initVariants(src?: FullExercise): VariantDraft[] {
  if (!src || src.variants.length === 0) return [blankVariant()];
  return src.variants.map((v) => ({
    id: v.id,
    paramsText: JSON.stringify(v.params ?? {}, null, 2),
    tests: v.test_inputs.length ? v.test_inputs.map((t) => ({ ...t })) : [{ input: "", expected_output: "" }],
  }));
}

const variantHasContent = (v: VariantDraft) =>
  !!v.id.trim() || !["", "{}"].includes(v.paramsText.replace(/\s/g, ""))
  || v.tests.some((r) => r.input.trim() || r.expected_output.trim());
const stepHasContent = (s: StepRow) =>
  [s.title, s.text, s.minutes, s.expected, s.questions, s.expected_output].some((x) => x.trim()) || s.checks.length > 0;

/** A server error as lines: a 422 lists one problem per field ("field: msg; field: msg"). */
export function errorLines(err: unknown, t: Translate): string[] {
  const text = describeError(err, t);
  return err instanceof ApiError && err.status === 422 ? text.split("; ").filter(Boolean) : [text];
}

type SectionKey = "basics" | "tutor" | "steps" | "chat" | "advanced";
/** Problems found on save, by field: "id", "titleEn", "brief", "variants", "v0.id", "s2.text", "s2.c0", … */
type Errors = Record<string, string>;

function sectionOf(field: string): SectionKey {
  if (/^s\d/.test(field)) return "steps";
  if (field === "variants" || /^v\d/.test(field)) return "advanced";
  return "basics";
}

const OUTPUT_HINT: Record<OutputInChat, StringKey> = {
  confirm: "exfOutConfirmHint", accept: "exfOutAcceptHint", ask: "exfOutAskHint", off: "exfOutOffHint",
};
const ANSWER_HINT: Record<AnswerInChat, StringKey> = {
  detect: "exfAnsDetectHint", confirm: "exfAnsConfirmHint", answer: "exfAnsAnswerHint",
};
const QUIZ_HINT: Record<QuizReview, StringKey> = {
  partial: "exfQuizPartialHint", zero: "exfQuizZeroHint", off: "exfQuizOffHint",
};

/** One titled part of the form that folds away. */
function Section({ title, hint, open, onToggle, problems, extra, children }: {
  title: ReactNode;
  hint?: ReactNode;
  open: boolean;
  onToggle: () => void;
  /** Fields in this part that need attention. */
  problems: number;
  /** A badge next to the title (how many steps, versions). */
  extra?: ReactNode;
  children: ReactNode;
}) {
  const { t } = useLang();
  const bodyId = useId();
  return (
    <section className="vc-exercises-sec">
      <h3>
        <button type="button" className="vc-exercises-sec__toggle" aria-expanded={open} aria-controls={bodyId}
                onClick={onToggle}>
          {open ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}
          <span className="u-grow">
            <span className="vc-exercises-sec__title">{title}</span>
            {hint && <span className="vc-exercises-sec__hint">{hint}</span>}
          </span>
          {extra}
          {problems > 0 && (
            <span className="vc-badge vc-badge--danger">
              {problems === 1 ? t("exfAttentionOne") : t("exfAttention", { n: problems })}
            </span>
          )}
        </button>
      </h3>
      <div id={bodyId} className="vc-exercises-sec__body" hidden={!open}>{children}</div>
    </section>
  );
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
  /** After a save, with the saved exercise's id. */
  onSaved: (exerciseId?: string) => void;
}) {
  const { t } = useLang();
  const { plugin } = useFeatures();
  const confirm = useConfirm();
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
  // A new exercise, one the server keeps without variants, or one whose only
  // variant is the plain "default": every student gets the same exercise.
  const [sameForAll, setSameForAll] = useState(
    () => !initial || !!initial.implicit_variant || isSameForAll(initial.variants));
  const [variants, setVariants] = useState<VariantDraft[]>(
    () => (!initial || initial.implicit_variant || isSameForAll(initial.variants) ? [blankVariant()] : initVariants(initial)));
  const [steps, setSteps] = useState<StepRow[]>(() => (initial?.steps ?? []).map(toRow));
  const [tutorNotes, setTutorNotes] = useState(initial?.tutor_notes ?? "");
  const [language, setLanguage] = useState(initial?.language ?? "");
  const [courseName, setCourseName] = useState(initial?.course_name ?? "");
  // The IDE plugin's fields: shown only with the plugin, sent unchanged either way.
  const [checkCommand, setCheckCommand] = useState(initial?.check_command ?? "");
  const [blockedHint, setBlockedHint] = useState(
    typeof initial?.terminal?.blocked_hint === "string" ? (initial.terminal.blocked_hint as string) : "");
  const [chatHistory, setChatHistory] = useState(initial?.chat_history ?? true);
  const [outputInChat, setOutputInChat] = useState<OutputInChat>(initial?.output_in_chat ?? "confirm");
  const [answerInChat, setAnswerInChat] = useState<AnswerInChat>(initial?.answer_in_chat ?? "detect");
  const [quizReview, setQuizReview] = useState<QuizReview>(initial?.quiz_review ?? "partial");
  const [resumeMinutes, setResumeMinutes] = useState(
    initial?.resume_minutes_set && initial.resume_minutes != null ? String(initial.resume_minutes) : "");
  const [preview, setPreview] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  const [open, setOpen] = useState<Record<SectionKey, boolean>>(
    { basics: true, tutor: true, steps: true, chat: false, advanced: false });
  const toggle = (k: SectionKey) => setOpen((o) => ({ ...o, [k]: !o[k] }));
  // Anything typed or changed: closing asks first, so a stray click can't lose the exercise.
  const [dirty, setDirty] = useState(false);
  const touch = () => setDirty(true);
  // After the first Save, problems are shown (and updated) next to their fields.
  const [attempted, setAttempted] = useState(false);
  const [serverError, setServerError] = useState<string[] | null>(null);
  const [jump, setJump] = useState<{ field: string } | null>(null);
  const body = useRef<HTMLDivElement>(null);
  const serverNotice = useRef<HTMLDivElement>(null);

  const patchStep = (i: number, patch: Partial<StepRow>) =>
    setSteps((xs) => xs.map((x, idx) => (idx === i ? { ...x, ...patch } : x)));
  const moveStep = (i: number, d: -1 | 1) => {
    touch();
    setSteps((xs) => {
      const j = i + d;
      if (j < 0 || j >= xs.length) return xs;
      const next = [...xs];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };
  const removeStep = async (i: number) => {
    if (stepHasContent(steps[i]) && !(await confirm({
      title: t("exfRemoveStepTitle", { n: i + 1 }), body: t("exfRemoveBody"),
      confirmLabel: t("exfRemoveStepConfirm"), danger: true,
    }))) return;
    touch();
    setSteps((xs) => xs.filter((_, idx) => idx !== i));
  };

  const patchVariant = (i: number, patch: Partial<VariantDraft>) =>
    setVariants((vs) => vs.map((v, idx) => (idx === i ? { ...v, ...patch } : v)));
  const removeVariant = async (i: number) => {
    const v = variants[i];
    if (variantHasContent(v) && !(await confirm({
      title: t("exfRemoveVersionTitle", { id: v.id.trim() || String(i + 1) }), body: t("exfRemoveBody"),
      confirmLabel: t("exfRemoveVersion"), danger: true,
    }))) return;
    touch();
    setVariants((vs) => vs.filter((_, idx) => idx !== i));
  };
  const changeSameForAll = async (on: boolean) => {
    if (on && variants.some(variantHasContent) && !(await confirm({
      title: t("exfSameAskTitle"), body: t("exfSameAskBody"), confirmLabel: t("exfSameAsk"),
    }))) return;
    touch();
    setSameForAll(on);
  };

  // "Check and preview": validate the brief's @-refs against the authored param
  // labels and preview the brief with the first variant's real values filled in.
  const [briefCheck, setBriefCheck] = useState<
    { refs: BriefRef[]; preview: string; sampleId: string | null } | null
  >(null);

  const currentLabels = (): ParamLabel[] =>
    paramLabels
      .filter((p) => p.key.trim())
      .map((p) => ({ key: p.key.trim(), label: p.label.trim() || null, note: p.note.trim() || null }));

  const sampleVariant = (): { id: string; params: Record<string, unknown> } | null => {
    if (sameForAll) return null;
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

  // Every problem at once (by field), and the payload when there are none.
  const build = (): { errors: Errors; payload: NewExercise | null } => {
    const errors: Errors = {};
    const id = exerciseId.trim();
    if (!id) errors.id = t("errIdRequired");
    else if (!/^[a-z0-9][a-z0-9-]*$/.test(id)) errors.id = t("errIdSlug");
    if (!titleEn.trim()) errors.titleEn = t("errTitleRequired");
    if (!briefMd.trim()) errors.brief = t("errBriefRequired");

    const builtSteps: StepDraft[] = [];
    for (const [i, st] of steps.entries()) {
      if (!st.title.trim() && !st.text.trim()) continue;
      if (!st.title.trim()) errors[`s${i}.title`] = t("exfErrStepTitle");
      const minutes = st.minutes.trim() ? Number(st.minutes) : null;
      if (minutes !== null && Number.isNaN(minutes)) errors[`s${i}.minutes`] = t("exfErrNumber");
      if (!st.text.trim()) errors[`s${i}.text`] = t("exfErrStepText");
      const questions = st.questions.trim() ? Math.round(Number(st.questions)) : null;
      if (questions !== null && Number.isNaN(questions)) errors[`s${i}.questions`] = t("exfErrNumber");
      for (const [ci, c] of st.checks.entries()) {
        if (!c.match.trim()) continue;
        try {
          new RegExp(c.match);
        } catch {
          errors[`s${i}.c${ci}`] = t("exfErrRegex");
        }
      }
      const checks = st.checks.filter((c) => c.match.trim());
      builtSteps.push({
        title: st.title.trim(), text: st.text, minutes, expected: st.expected, questions,
        expected_output: st.expected_output,
        expect_output: checks.map((c) => ({ match: c.match, hint: c.hint.trim() || null })),
      });
    }

    const built: Variant[] = [];
    if (sameForAll) {
      // A lab the server already keeps without variants sends its own back, as before;
      // anything else gets the single "default" variant.
      built.push(...(initial?.implicit_variant ? initial.variants : [{ ...SAME_FOR_ALL }]));
    } else {
      if (variants.length === 0) errors.variants = t("errNoVariants");
      const seen = new Set<string>();
      for (const [i, v] of variants.entries()) {
        const vid = v.id.trim();
        if (!vid) errors[`v${i}.id`] = t("errVariantId");
        else if (seen.has(vid)) errors[`v${i}.id`] = t("errDupVariant");
        seen.add(vid);
        let params: Record<string, unknown> = {};
        try {
          params = v.paramsText.trim() ? JSON.parse(v.paramsText) : {};
        } catch {
          errors[`v${i}.params`] = t("errParamsJson", { id: vid });
        }
        built.push({
          id: vid,
          params,
          test_inputs: v.tests
            .filter((r) => r.input.trim() !== "" || r.expected_output.trim() !== "")
            .map((r) => ({ input: r.input, expected_output: r.expected_output })),
        });
      }
    }
    if (Object.keys(errors).length) return { errors, payload: null };

    const lines = (s: string) => s.split("\n").map((l) => l.trim()).filter(Boolean);
    const terminal = initial?.terminal || blockedHint.trim()
      ? { ...(initial?.terminal ?? {}), blocked_hint: blockedHint.trim() || undefined }
      : null;
    return {
      errors,
      payload: {
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
        terminal,
        tutor_notes: tutorNotes,
        language: language.trim() || undefined,
        course_name: courseName.trim() || undefined,
        check_command: checkCommand.trim() || undefined,
        chat_history: chatHistory,
        output_in_chat: outputInChat,
        answer_in_chat: answerInChat,
        quiz_review: quizReview,
        resume_minutes: resumeMinutes.trim() !== "" ? Math.max(0, Math.round(Number(resumeMinutes))) : undefined,
        steps: builtSteps.length || initial?.steps?.length ? builtSteps : undefined,
      },
    };
  };

  const errors: Errors = attempted ? build().errors : {};
  const problemFields = Object.keys(errors);
  const problemsIn = (s: SectionKey) => problemFields.filter((f) => sectionOf(f) === s).length;
  const invalid = (f: string) => (errors[f] ? true : undefined);

  // Open the part of the form that holds a field, then bring the field into view.
  const goTo = (field: string) => {
    setOpen((o) => ({ ...o, [sectionOf(field)]: true }));
    setJump({ field });
  };
  useEffect(() => {
    if (!jump) return;
    const spot = body.current?.querySelector<HTMLElement>(`[data-field="${jump.field}"]`);
    if (!spot) return;
    spot.scrollIntoView({ behavior: "smooth", block: "center" });
    spot.querySelector<HTMLElement>("input:not([disabled]), textarea, select")?.focus({ preventScroll: true });
  }, [jump]);
  useEffect(() => {
    if (serverError) serverNotice.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [serverError]);

  const save = async () => {
    setAttempted(true);
    const { errors: found, payload } = build();
    const first = Object.keys(found)[0];
    if (first || !payload) {
      if (first) goTo(first);
      return;
    }
    setServerError(null);
    setSaving(true);
    try {
      const saved = mode === "edit" && initial
        ? await api.updateExercise(initial.exercise_id, payload)
        : await api.createExercise(payload);
      onSaved(saved?.exercise_id ?? payload.exercise_id);
    } catch (e) {
      setServerError(errorLines(e, t));
    } finally {
      setSaving(false);
    }
  };

  const cancel = async () => {
    if (dirty && !(await confirm({
      title: t("discardAsk"), confirmLabel: t("discard"), cancelLabel: t("keepEditing"), danger: true,
    }))) return;
    onClose();
  };

  const title =
    mode === "edit" ? t("editExerciseTitle") : mode === "duplicate" ? t("duplicateExerciseTitle") : t("newExerciseTitle");
  const stepCount = steps.length === 1 ? t("exOneStep") : t("exSteps", { n: steps.length });
  const shownStep = preview !== null && steps[preview] ? preview : null;

  const footer = (
    <>
      {problemFields.length > 0 ? (
        <button type="button" className="vc-exercises-attention" onClick={() => goTo(problemFields[0])}>
          <AlertCircle aria-hidden="true" />
          {problemFields.length === 1 ? t("exfAttentionOne") : t("exfAttention", { n: problemFields.length })}
        </button>
      ) : serverError ? (
        <span className="vc-exercises-attention"><AlertCircle aria-hidden="true" />{t("exfNotSaved")}</span>
      ) : null}
      <span className="u-push" />
      <Button onClick={cancel}>{t("cancel")}</Button>
      <Button variant="primary" busy={saving} onClick={save}>{saving ? t("saving") : t("saveExercise")}</Button>
    </>
  );

  return (
    <Modal
      size="lg" title={title} dirty={dirty} onClose={onClose} footer={footer}
      subtitle={initial && <span className="vc-mono" dir="ltr">{initial.exercise_id}</span>}
    >
      {/* Every field's change bubbles here: from then on, closing asks first. */}
      <div ref={body} onChange={touch}>
        <Notice className="u-mb-12">{t("exfFormOnly")}</Notice>
        {mode === "edit" && initial?.source === "package" && initial.folder && (
          <p className="u-sm u-soft u-mb-12">{t("exfSavesTo")} <code dir="ltr">{initial.folder}</code></p>
        )}
        {serverError && (
          <div ref={serverNotice} className="u-mb-12">
            <Notice tone="danger" title={t("exfNotSaved")}>
              {serverError.length === 1 ? <span dir="auto">{serverError[0]}</span> : (
                <ul className="vc-exercises-list">
                  {serverError.map((line, i) => <li key={i} dir="auto">{line}</li>)}
                </ul>
              )}
            </Notice>
          </div>
        )}

        {/* ---- Basics ---- */}
        <Section title={t("exfSecBasics")} open={open.basics} onToggle={() => toggle("basics")}
                 problems={problemsIn("basics")}>
          <div data-field="id">
            {idLocked ? (
              <FormField label={t("fldExerciseId")} hint={t("exfIdLocked")}>
                <Input value={exerciseId} disabled mono dir="ltr" />
              </FormField>
            ) : (
              <Field label={t("fldExerciseId")} value={exerciseId} onChange={setExerciseId} placeholder="my-task-1"
                     monospace required hint={t("exfIdHint")} error={errors.id} />
            )}
          </div>
          <div className="vc-exercises-grid">
            <div data-field="titleEn">
              <Field label={t("fldTitleEn")} value={titleEn} onChange={setTitleEn} required error={errors.titleEn}
                     autoFocus={idLocked} />
            </div>
            <Field label={t("fldTitleHe")} value={titleHe} onChange={setTitleHe} />
          </div>
          <div data-field="brief">
            <Field label={t("exfBrief")} value={briefMd} onChange={setBriefMd} textarea minHeight={140}
                   required hint={t("exfBriefHint")} error={errors.brief} />
          </div>
          <div className="u-row u-wrap u-gap-8">
            <Button size="sm" icon={<Eye />} onClick={runBriefCheck}>{t("applyBrief")}</Button>
            <span className="u-xs u-muted">{t("applyBriefHint")}</span>
          </div>
          {briefCheck && (
            <div className="vc-exercises-preview u-mt-12">
              {briefCheck.refs.length === 0 ? (
                <p className="u-sm u-muted u-mb-8">{t("applyNoRefs")}</p>
              ) : (
                <ul className="vc-exercises-refs">
                  {briefCheck.refs.map((r) => (
                    <li key={r.ref} className={r.ok ? "u-success" : "u-danger"}>
                      {r.ok ? <CheckCircle2 aria-hidden="true" /> : <XCircle aria-hidden="true" />}
                      <code dir="ltr">@{r.ref}</code>
                      <span className="u-soft" dir="auto">{r.ok ? r.label : t("applyUnknownRef")}</span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="vc-exercises-preview__label">
                {sameForAll ? t("exfPreviewAsWritten")
                  : briefCheck.sampleId ? t("applyPreviewFor", { id: briefCheck.sampleId }) : t("applyPreviewNoVariant")}
              </div>
              <div className="vc-exercises-preview__text" dir="auto">{briefCheck.preview}</div>
            </div>
          )}
        </Section>

        {/* ---- Tutor ---- */}
        <Section title={t("exfSecTutor")} hint={t("exfSecTutorHint")} open={open.tutor}
                 onToggle={() => toggle("tutor")} problems={0}>
          <div className="vc-exercises-grid">
            <FormField label={t("fldDefaultMode")}>
              <Select value={defaultMode} onChange={(e) => setDefaultMode(e.target.value as "mentor" | "coding_partner")}>
                <option value="mentor">{t("mentor")}</option>
                <option value="coding_partner">{t("codingPartner")}</option>
              </Select>
            </FormField>
            <Field label={t("fldCourseName")} value={courseName} onChange={setCourseName} />
          </div>
          <p className="vc-hint u-mb-12">{t("exfModeHint")}</p>
          <Field label={t("fldTutorNotes")} value={tutorNotes} onChange={setTutorNotes} textarea minHeight={90}
                 hint={t("exfTutorNotesHint")} />
          <Field label={t("fldWelcome")} value={welcome} onChange={setWelcome} textarea hint={t("exfWelcomeHint")} />
        </Section>

        {/* ---- Steps ---- */}
        <Section title={t("exfSecSteps")} hint={t("exfSecStepsHint")} open={open.steps}
                 onToggle={() => toggle("steps")} problems={problemsIn("steps")}
                 extra={steps.length > 0 ? <span className="vc-badge">{stepCount}</span> : undefined}>
          {steps.length === 0 && <p className="u-sm u-muted u-mb-12">{t("exfNoSteps")}</p>}
          {steps.length > 0 && (
            <div className="u-mb-12">
              <Button size="sm" variant="quiet" icon={shownStep === null ? <Eye /> : <EyeOff />}
                      onClick={() => setPreview(shownStep === null ? 0 : null)}>
                {shownStep === null ? t("exfPreviewSteps") : t("exfHidePreview")}
              </Button>
            </div>
          )}
          {shownStep !== null && (
            <div className="vc-exercises-preview">
              <div className="vc-exercises-preview__label">{t("exfPreviewAsWritten")}</div>
              <div className="vc-segmented vc-exercises-stepnav u-mb-8" role="group" aria-label={t("exfSecSteps")}>
                {steps.map((_, i) => (
                  <button key={i} type="button" aria-pressed={i === shownStep} aria-label={t("previewStep", { n: i + 1 })}
                          onClick={() => setPreview(i)}>
                    {i + 1}
                  </button>
                ))}
              </div>
              <div className="vc-exercises-preview__text" dir="auto">
                <strong>{t("exfStepOf", { n: shownStep + 1, total: steps.length, title: steps[shownStep].title })}</strong>
                {"\n\n"}{steps[shownStep].text}
              </div>
            </div>
          )}

          {steps.map((st, i) => (
            <div key={i} className="vc-exercises-step">
              <div className="vc-exercises-step__head">
                <span className="vc-exercises-step__n">{t("previewStep", { n: i + 1 })}</span>
                <Button variant="quiet" size="sm" iconOnly icon={<ArrowUp />} aria-label={t("moveUp")}
                        disabled={i === 0} onClick={() => moveStep(i, -1)} />
                <Button variant="quiet" size="sm" iconOnly icon={<ArrowDown />} aria-label={t("moveDown")}
                        disabled={i === steps.length - 1} onClick={() => moveStep(i, 1)} />
                <Button variant="quiet" size="sm" iconOnly icon={<Trash2 />} aria-label={t("exfRemoveStep", { n: i + 1 })}
                        onClick={() => removeStep(i)} />
              </div>
              <div className="vc-exercises-row">
                <div data-field={`s${i}.title`}>
                  <FormField label={t("fldStepTitle")} required error={errors[`s${i}.title`]}>
                    <Input value={st.title} aria-invalid={invalid(`s${i}.title`)}
                           onChange={(e) => patchStep(i, { title: e.target.value })} />
                  </FormField>
                </div>
                <div data-field={`s${i}.minutes`}>
                  <FormField label={t("exfStepMinutes")} error={errors[`s${i}.minutes`]}>
                    <Input value={st.minutes} inputMode="decimal" dir="ltr" aria-invalid={invalid(`s${i}.minutes`)}
                           onChange={(e) => patchStep(i, { minutes: e.target.value })} />
                  </FormField>
                </div>
              </div>
              <div data-field={`s${i}.text`}>
                <FormField label={t("fldStepText")} required error={errors[`s${i}.text`]}>
                  <Textarea value={st.text} mono rows={6} aria-invalid={invalid(`s${i}.text`)}
                            onChange={(e) => patchStep(i, { text: e.target.value })} />
                </FormField>
              </div>
              <div className="vc-exercises-row">
                <FormField label={t("fldStepExpected")}>
                  <Textarea value={st.expected} rows={3} onChange={(e) => patchStep(i, { expected: e.target.value })} />
                </FormField>
                <div data-field={`s${i}.questions`}>
                  <FormField label={t("exfStepQuestions")} hint={t("exfStepQuestionsHint")} error={errors[`s${i}.questions`]}>
                    <Input value={st.questions} inputMode="numeric" dir="ltr" aria-invalid={invalid(`s${i}.questions`)}
                           onChange={(e) => patchStep(i, { questions: e.target.value })} />
                  </FormField>
                </div>
              </div>
              <FormField label={t("exfStepOutput")} hint={t("exfStepOutputHint")}>
                <Textarea value={st.expected_output} mono dir="ltr" rows={3}
                          onChange={(e) => patchStep(i, { expected_output: e.target.value })} />
              </FormField>

              <div className="vc-exercises-sub">{t("fldStepChecks")}</div>
              <p className="vc-hint u-mb-8">{t("fldStepChecksHint")}</p>
              {st.checks.map((c, ci) => (
                <div key={ci} className="vc-exercises-check-row" data-field={`s${i}.c${ci}`}>
                  <FormField label={t("exfCheckMatch")} error={errors[`s${i}.c${ci}`]}>
                    <Input value={c.match} mono dir="ltr" placeholder="Python 3" aria-invalid={invalid(`s${i}.c${ci}`)}
                           onChange={(e) => patchStep(i, { checks: st.checks.map((x, k) => (k === ci ? { ...x, match: e.target.value } : x)) })} />
                  </FormField>
                  <FormField label={t("fldStepCheckHint")}>
                    <Input value={c.hint}
                           onChange={(e) => patchStep(i, { checks: st.checks.map((x, k) => (k === ci ? { ...x, hint: e.target.value } : x)) })} />
                  </FormField>
                  <Button variant="quiet" size="sm" iconOnly icon={<Trash2 />} aria-label={t("exfRemoveCheck")}
                          onClick={() => { touch(); patchStep(i, { checks: st.checks.filter((_, k) => k !== ci) }); }} />
                </div>
              ))}
              <Button size="sm" variant="quiet" icon={<Plus />}
                      onClick={() => { touch(); patchStep(i, { checks: [...st.checks, { match: "", hint: "" }] }); }}>
                {t("exfAddCheck")}
              </Button>
            </div>
          ))}
          <Button size="sm" icon={<Plus />} onClick={() => { touch(); setSteps((xs) => [...xs, blankStep()]); }}>
            {t("addStep")}
          </Button>
        </Section>

        {/* ---- Chat behaviour ---- */}
        <Section title={t("exfSecChat")} hint={t("exfSecChatHint")} open={open.chat}
                 onToggle={() => toggle("chat")} problems={0}>
          <Switch checked={chatHistory} onChange={setChatHistory}>{t("fldChatHistory")}</Switch>
          <p className="vc-hint u-mb-12">{t("fldChatHistoryHint")}</p>
          <div className="vc-exercises-grid">
            <FormField label={t("fldResumeMinutes")} hint={t("fldResumeHint")}>
              <Input value={resumeMinutes} inputMode="numeric" dir="ltr"
                     placeholder={initial?.resume_minutes != null ? String(initial.resume_minutes) : "30"}
                     onChange={(e) => setResumeMinutes(e.target.value.replace(/[^0-9]/g, ""))} />
            </FormField>
          </div>
          <FormField label={t("exfOutputLabel")} hint={t(OUTPUT_HINT[outputInChat])}>
            <Select value={outputInChat} onChange={(e) => setOutputInChat(e.target.value as OutputInChat)}>
              <option value="confirm">{t("exfOutConfirm")}</option>
              <option value="accept">{t("exfOutAccept")}</option>
              <option value="ask">{t("exfOutAsk")}</option>
              <option value="off">{t("exfOutOff")}</option>
            </Select>
          </FormField>
          <FormField label={t("exfAnswerLabel")} hint={t(ANSWER_HINT[answerInChat])}>
            <Select value={answerInChat} onChange={(e) => setAnswerInChat(e.target.value as AnswerInChat)}>
              <option value="detect">{t("exfAnsDetect")}</option>
              <option value="confirm">{t("exfAnsConfirm")}</option>
              <option value="answer">{t("exfAnsAnswer")}</option>
            </Select>
          </FormField>
          <FormField label={t("exfQuizLabel")} hint={t(QUIZ_HINT[quizReview])} className="u-mb-0">
            <Select value={quizReview} onChange={(e) => setQuizReview(e.target.value as QuizReview)}>
              <option value="partial">{t("exfQuizPartial")}</option>
              <option value="zero">{t("exfQuizZero")}</option>
              <option value="off">{t("exfQuizOff")}</option>
            </Select>
          </FormField>
        </Section>

        {/* ---- Advanced ---- */}
        <Section title={t("exfSecAdvanced")} hint={t("exfSecAdvancedHint")} open={open.advanced}
                 onToggle={() => toggle("advanced")} problems={problemsIn("advanced")}
                 extra={!sameForAll ? <span className="vc-badge">{t("exVersions", { n: variants.length })}</span> : undefined}>
          <Switch checked={sameForAll} onChange={changeSameForAll}>{t("exfSame")}</Switch>
          <p className="vc-hint u-mb-12">{sameForAll ? t("exfSameOnHint") : t("exfSameOffHint")}</p>

          {!sameForAll && (
            <div data-field="variants" className="u-mb-12">
              {errors.variants && <p className="vc-error u-mb-8" role="alert">{errors.variants}</p>}
              {variants.map((v, i) => (
                <div key={i} className="vc-exercises-step">
                  <div className="vc-exercises-step__head">
                    <span className="vc-exercises-step__n">{t("exfVersionN", { n: i + 1 })}</span>
                    {variants.length > 1 && (
                      <Button variant="quiet" size="sm" iconOnly icon={<Trash2 />} aria-label={t("removeVariant")}
                              onClick={() => removeVariant(i)} />
                    )}
                  </div>
                  <div data-field={`v${i}.id`}>
                    <FormField label={t("fldVariantId")} required hint={t("exfVersionIdHint")} error={errors[`v${i}.id`]}>
                      <Input value={v.id} mono dir="ltr" placeholder="A" aria-invalid={invalid(`v${i}.id`)}
                             onChange={(e) => patchVariant(i, { id: e.target.value })} />
                    </FormField>
                  </div>
                  <div data-field={`v${i}.params`}>
                    <FormField label={t("fldParams")} hint={t("exfParamsHint")} error={errors[`v${i}.params`]}>
                      <Textarea value={v.paramsText} mono dir="ltr" rows={3} aria-invalid={invalid(`v${i}.params`)}
                                placeholder='{"max_number": 100, "operators": ["+","-"], "allow_parens": false}'
                                onChange={(e) => patchVariant(i, { paramsText: e.target.value })} />
                    </FormField>
                  </div>
                  <div className="vc-exercises-sub">{t("testInputs")}</div>
                  <p className="vc-hint u-mb-8">{t("exfTestsHint")}</p>
                  {v.tests.length > 0 && (
                    <table className="vc-exercises-tests">
                      <thead>
                        <tr>
                          <th scope="col">{t("thInput")}</th>
                          <th scope="col">{t("thExpected")}</th>
                          <th scope="col"><span className="u-sr">{t("remove")}</span></th>
                        </tr>
                      </thead>
                      <tbody>
                        {v.tests.map((row, ri) => (
                          <tr key={ri}>
                            <td>
                              <Input small mono value={row.input} aria-label={`${t("thInput")} ${ri + 1}`}
                                     onChange={(e) => patchVariant(i, { tests: v.tests.map((r, idx) => (idx === ri ? { ...r, input: e.target.value } : r)) })} />
                            </td>
                            <td>
                              <Input small mono value={row.expected_output} aria-label={`${t("thExpected")} ${ri + 1}`}
                                     onChange={(e) => patchVariant(i, { tests: v.tests.map((r, idx) => (idx === ri ? { ...r, expected_output: e.target.value } : r)) })} />
                            </td>
                            <td>
                              <Button variant="quiet" size="sm" iconOnly icon={<Trash2 />} aria-label={t("exfRemoveTest")}
                                      onClick={() => { touch(); patchVariant(i, { tests: v.tests.filter((_, idx) => idx !== ri) }); }} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  <Button size="sm" variant="quiet" icon={<Plus />}
                          onClick={() => { touch(); patchVariant(i, { tests: [...v.tests, { input: "", expected_output: "" }] }); }}>
                    {t("addTestInput")}
                  </Button>
                </div>
              ))}
              <Button size="sm" icon={<Plus />} onClick={() => { touch(); setVariants((vs) => [...vs, blankVariant()]); }}>
                {t("addVariant")}
              </Button>
            </div>
          )}

          {(!sameForAll || paramLabels.length > 0) && (
            <>
              <hr className="vc-divider" />
              <div className="vc-exercises-sub">{t("paramLabelsSection")}</div>
              <p className="vc-hint u-mb-8">{t("paramLabelsHint")}</p>
              {paramLabels.length > 0 && (
                <div className="vc-exercises-names">
                  <span className="vc-exercises-names__head" aria-hidden="true">{t("fldParamKey")}</span>
                  <span className="vc-exercises-names__head" aria-hidden="true">{t("fldParamLabel")}</span>
                  <span className="vc-exercises-names__head" aria-hidden="true">{t("fldParamNote")}</span>
                  <span />
                  {paramLabels.map((pl, i) => (
                    <Fragment key={i}>
                      <Input small mono dir="ltr" value={pl.key} aria-label={t("fldParamKey")}
                             onChange={(e) => setParamLabels((ps) => ps.map((p, idx) => (idx === i ? { ...p, key: e.target.value } : p)))} />
                      <Input small value={pl.label} aria-label={t("fldParamLabel")}
                             onChange={(e) => setParamLabels((ps) => ps.map((p, idx) => (idx === i ? { ...p, label: e.target.value } : p)))} />
                      <Input small value={pl.note} aria-label={t("fldParamNote")}
                             onChange={(e) => setParamLabels((ps) => ps.map((p, idx) => (idx === i ? { ...p, note: e.target.value } : p)))} />
                      <Button variant="quiet" size="sm" iconOnly icon={<Trash2 />} aria-label={t("exfRemoveName")}
                              onClick={() => { touch(); setParamLabels((ps) => ps.filter((_, idx) => idx !== i)); }} />
                    </Fragment>
                  ))}
                </div>
              )}
              <Button size="sm" variant="quiet" icon={<Plus />}
                      onClick={() => { touch(); setParamLabels((ps) => [...ps, { key: "", label: "", note: "" }]); }}>
                {t("addParamLabel")}
              </Button>
            </>
          )}

          <hr className="vc-divider" />
          <Field label={t("fldErrorStrings")} value={errorStrings} onChange={setErrorStrings} textarea monospace
                 hint={t("exfErrorStringsHint")} />
          <div className="vc-exercises-grid">
            <Field label={t("fldLanguage")} value={language} onChange={setLanguage} monospace hint={t("exfLanguageHint")} />
            {plugin && (
              <Field label={t("fldCheckCommand")} value={checkCommand} onChange={setCheckCommand} monospace
                     hint={t("exfCheckCommandHint")} />
            )}
          </div>
          {plugin && (
            <Field label={t("fldBlockedHint")} value={blockedHint} onChange={setBlockedHint} hint={t("exfBlockedHintHint")} />
          )}
        </Section>
      </div>
    </Modal>
  );
}
