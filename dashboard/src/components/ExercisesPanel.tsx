import { useEffect, useRef, useState, type DragEvent } from "react";
import { CloudUpload, CopyPlus, Download, FilterX, PackageOpen, Pencil, Plus, RefreshCw, Search, UserCheck, UserX, X }
  from "lucide-react";
import { api } from "../api";
import type { ExerciseSummary, FullExercise, PackageResult } from "../types";
import { useLang, type Translate } from "../i18n";
import { useFeatures } from "../app/features";
import { describeError } from "../lib/errors";
import { DATE_RANGES, EXERCISE_SORTS, inDateRange, sortExercises, useExerciseSort, type DateRange,
         type ExerciseSort } from "../lib/exerciseOrder";
import { formatDate, formatDateTime, parseServerTime } from "../lib/time";
import { Button, CopyButton, EmptyState, Input, Loading, Notice, Select, useConfirm, useToast } from "./ui";
import { ExerciseFormModal, errorLines } from "./ExerciseFormModal";
import "../styles/exercises.css";
import { textDir } from "../lib/textDir";

type FormState =
  | { mode: "create"; initial?: undefined }
  | { mode: "edit" | "duplicate"; initial: FullExercise };

/** What the last upload ended in: installed, or refused (here or by the server). */
type Upload =
  | { ok: true; name: string; result: PackageResult; replaced: boolean }
  | { ok: false; name: string; errors: string[]; warnings: string[] };

type CardAction = "edit" | "duplicate" | "export" | "active";
type Titled = { title_en?: string | null; title_he?: string | null; exercise_id?: string };

// The server refuses bigger zips (backend/packages.py, _ZIP_MAX).
const MAX_ZIP_BYTES = 50_000_000;

const cardId = (id: string) => `vc-exercise-${id}`;
const looksLikeZip = (f: File) => /\.zip$/i.test(f.name) || /zip/i.test(f.type);

/** The file's bytes as base64. */
async function fileBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

function stepsText(n: number, t: Translate) {
  return n === 1 ? t("exOneStep") : t("exSteps", { n });
}

/** "Added 12 Nov 2026, changed 14 Nov 2026" (the change only on another day),
 *  and the exact times for the tooltip. A bundled sample has no date, unless
 *  the lecturer edited it. */
function datesText(ex: ExerciseSummary, t: Translate, lang: "en" | "he") {
  const added = parseServerTime(ex.added_at);
  const changed = parseServerTime(ex.changed_at);
  const day = (d: Date) => formatDate(d, lang);
  if (!added) {
    return changed
      ? { line: t("exChangedOnly", { date: day(changed) }), exact: t("exChangedOnly", { date: formatDateTime(changed, lang) }) }
      : null;
  }
  const line = [t("exAdded", { date: day(added) }),
    changed && day(changed) !== day(added) ? t("exChanged", { date: day(changed) }) : ""].filter(Boolean).join(", ");
  const exact = [t("exAdded", { date: formatDateTime(added, lang) }),
    changed ? t("exChanged", { date: formatDateTime(changed, lang) }) : ""].filter(Boolean).join(", ");
  return { line, exact };
}

// The "Exercises" tab: lists every exercise (built-in samples, ones written in
// the form, and packages from the private data folder), lets the lecturer pick
// the one students without a course get, create / edit / duplicate, upload a
// package zip, export, and reload the packages from disk. New labs are written
// in Claude Code (the exercise skill) and installed with the MCP tool
// push_exercise, or uploaded here.
export function ExercisesPanel({ onActiveChanged }: { onActiveChanged: () => void }) {
  const { t, lang } = useLang();
  const { plugin } = useFeatures();
  const toast = useToast();
  const confirm = useConfirm();
  const [exercises, setExercises] = useState<ExerciseSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [busy, setBusy] = useState<{ id: string; what: CardAction } | null>(null);
  const [loadErrors, setLoadErrors] = useState<{ folder: string; error: string }[]>([]);
  const [folder, setFolder] = useState<string | null>(null);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useExerciseSort();
  const [range, setRange] = useState<DateRange>("any");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [flashId, setFlashId] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const titleOf = (ex: Titled) =>
    (lang === "he" ? ex.title_he || ex.title_en : ex.title_en) || ex.exercise_id || "";

  const refresh = async () => {
    api.exercisesStatus()
      .then((s) => { setLoadErrors(s.load_errors); setFolder(s.exercises_dir); })
      .catch(() => { /* the list below reports a server that doesn't answer */ });
    try {
      setExercises(await api.exercises());
      setListError(null);
    } catch (e) {
      setListError(describeError(e, t));
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A card that was just installed or saved: bring it into view and light it up briefly.
  useEffect(() => {
    if (!flashId || !exercises?.some((ex) => ex.exercise_id === flashId)) return;
    document.getElementById(cardId(flashId))?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    const timer = window.setTimeout(() => setFlashId(null), 2600);
    return () => window.clearTimeout(timer);
  }, [flashId, exercises]);

  const uploadZip = async (file: File) => {
    if (uploading) return;
    setUpload(null);
    if (!looksLikeZip(file)) {
      setUpload({ ok: false, name: file.name, errors: [t("exUpNotZip", { name: file.name })], warnings: [] });
      if (fileInput.current) fileInput.current.value = "";
      return;
    }
    if (file.size > MAX_ZIP_BYTES) {
      const size = (file.size / 1_000_000).toFixed(1);
      setUpload({ ok: false, name: file.name, errors: [t("exUpTooBig", { name: file.name, size })], warnings: [] });
      if (fileInput.current) fileInput.current.value = "";
      return;
    }
    setUploading(file.name);
    try {
      const zip = await fileBase64(file);
      // First without replacing: an installed exercise with the same id is replaced only when the lecturer says so.
      let result = await api.importExercise(zip, false);
      let replaced = false;
      if (!result.ok && result.errors.some((e) => e.includes("already installed"))) {
        const id = result.summary.exercise_id ?? file.name;
        const yes = await confirm({
          title: t("exUpReplaceTitle"),
          body: t("exUpReplaceBody", { id }),
          confirmLabel: t("exUpReplace"),
        });
        if (!yes) {
          toast.info(t("exUpKept", { id }));
          return;
        }
        result = await api.importExercise(zip, true);
        replaced = true;
      }
      if (result.ok) {
        setUpload({ ok: true, name: file.name, result, replaced });
        clearFilters();
        setFlashId(result.summary.exercise_id ?? null);
      } else {
        setUpload({ ok: false, name: file.name, errors: result.errors, warnings: result.warnings });
      }
      refresh();
      onActiveChanged();
    } catch (e) {
      setUpload({ ok: false, name: file.name, errors: errorLines(e, t), warnings: [] });
    } finally {
      setUploading(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const onDragOver = (e: DragEvent<HTMLLabelElement>) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = uploading ? "none" : "copy";
    setDragOver(true);
  };
  const onDragLeave = (e: DragEvent<HTMLLabelElement>) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false);
  };
  const onDrop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file && !uploading) uploadZip(file);
  };

  const reload = async () => {
    setReloading(true);
    try {
      const r = await api.reloadExercises();
      setExercises(r.exercises);
      setLoadErrors(r.load_errors);
      setListError(null);
      onActiveChanged();
      if (r.load_errors.length) toast.info(t("exReloadedErrors", { n: r.load_errors.length }));
      else toast.success(t("exReloaded"));
    } catch (e) {
      toast.error(t("exReloadFailed"), e);
    } finally {
      setReloading(false);
    }
  };

  const exportZip = async (id: string) => {
    setBusy({ id, what: "export" });
    try {
      const url = URL.createObjectURL(await api.exportExercise(id));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${id}.zip`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success(t("exExported", { file: `${id}.zip` }));
    } catch (e) {
      toast.error(t("exExportFailed"), e);
    } finally {
      setBusy(null);
    }
  };

  // makeActive=false switches it off: no exercise for students without a course.
  const setActive = async (ex: ExerciseSummary, makeActive: boolean) => {
    setBusy({ id: ex.exercise_id, what: "active" });
    try {
      await (makeActive ? api.setActiveExercise(ex.exercise_id) : api.disableActiveExercise());
      toast.success(makeActive ? t("exActiveOn", { title: titleOf(ex) }) : t("exActiveOff"));
      await refresh();
      onActiveChanged(); // keep the monitor tab's header in sync
    } catch (e) {
      toast.error(t("exActiveFailed"), e);
    } finally {
      setBusy(null);
    }
  };

  // Edit and Duplicate both need the FULL exercise (variants, params, tests),
  // which the list endpoint doesn't carry: fetch it, then open the form.
  const openWith = async (id: string, mode: "edit" | "duplicate") => {
    setBusy({ id, what: mode });
    try {
      const full = await api.exercise(id);
      setForm({ mode, initial: full });
    } catch (e) {
      toast.error(t("exOpenFailed"), e);
    } finally {
      setBusy(null);
    }
  };

  function clearFilters() {
    setQuery("");
    setRange("any");
    setFrom("");
    setTo("");
  }

  const afterSave = (savedId?: string) => {
    setForm(null);
    toast.success(t("exSaved"));
    if (savedId) {
      clearFilters();
      setFlashId(savedId);
    }
    refresh();
    onActiveChanged(); // an edit may have touched the active exercise
  };

  // The list as the lecturer asked for it: matching the search (title or id) and
  // the date filter (added or changed in that period), in the chosen order.
  const q = query.trim().toLowerCase();
  const filtering = !!q || range !== "any";
  const shown = !exercises ? [] : sortExercises(exercises.filter((ex) =>
    (!q || [ex.exercise_id, ex.title_en, ex.title_he ?? ""].some((s) => s.toLowerCase().includes(q)))
    && inDateRange(ex, range, from, to)), sort, lang);
  const anyActive = !!exercises?.some((ex) => ex.is_active);

  const dropCls = ["vc-exercises-drop", dragOver && !uploading ? "vc-exercises-drop--over" : "",
    uploading ? "vc-exercises-drop--busy" : ""].filter(Boolean).join(" ");

  return (
    <section>
      <div className="vc-section__head">
        <div className="u-grow">
          <h2>{t("exercisesTitle")}</h2>
          <p className="vc-exercises-lead">{t("exLead")}</p>
        </div>
        <div className="vc-section__actions">
          <Button variant="primary" icon={<Plus />} onClick={() => setForm({ mode: "create" })}>
            {t("newExercise")}
          </Button>
        </div>
      </div>

      {/* Uploading a package: the label is the drop zone and opens the file picker. */}
      <div className="vc-card u-mb-16">
        <label className={dropCls} onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}
               aria-busy={uploading ? true : undefined}>
          <input
            ref={fileInput}
            type="file"
            accept=".zip,application/zip"
            className="u-sr"
            disabled={!!uploading}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadZip(f); }}
          />
          <span className="vc-exercises-drop__icon" aria-hidden="true">
            {uploading ? <span className="vc-spinner" /> : <CloudUpload />}
          </span>
          <span className="u-grow">
            <span className="vc-exercises-drop__title">
              {uploading ? t("exUpBusy", { name: uploading }) : (
                <>{t("exUpDrop")} <span className="vc-exercises-drop__choose">{t("exUpChoose")}</span></>
              )}
            </span>
            <span className="vc-exercises-drop__text">{t("exUpWhat")}</span>
          </span>
        </label>
        <details className="vc-exercises-details">
          <summary>{t("exUpDetails")}</summary>
          <dl className="vc-exercises-files">
            <dt dir="ltr">exercise.yaml</dt><dd>{t("exUpPkgExercise")}</dd>
            <dt dir="ltr">teacher.yaml</dt><dd>{t("exUpPkgTeacher")}</dd>
            <dt dir="ltr">faq.yaml</dt><dd>{t("exUpPkgFaq")}</dd>
            <dt dir="ltr">files/</dt><dd>{t("exUpPkgFiles")}</dd>
          </dl>
          <p className="u-muted">{t("exUpPkgZip")}</p>
        </details>
      </div>

      {upload && <UploadResult upload={upload} titleOf={titleOf} onDismiss={() => setUpload(null)} />}

      {loadErrors.length > 0 && (
        <Notice tone="danger" className="u-mb-16" title={t("exLoadErrorsTitle")}>
          <p>{t("exLoadErrorsHint")}</p>
          <ul className="vc-exercises-list u-mt-8">
            {loadErrors.map((e) => (
              <li key={e.folder}>
                <code dir="ltr">{e.folder}</code>
                <div dir={textDir(e.error)}>{e.error}</div>
              </li>
            ))}
          </ul>
        </Notice>
      )}

      {listError && (
        <Notice tone="danger" className="u-mb-16" title={t("exLoadFailed")}
                action={<Button size="sm" icon={<RefreshCw />} onClick={() => refresh()}>{t("exRetry")}</Button>}>
          {listError}
        </Notice>
      )}
      {exercises === null && !listError && <Loading />}
      {exercises?.length === 0 && (
        <EmptyState icon={<PackageOpen />} title={t("exEmptyTitle")}
                    actions={<Button icon={<Plus />} onClick={() => setForm({ mode: "create" })}>{t("newExercise")}</Button>}>
          {t("noExercises")}
        </EmptyState>
      )}

      {!!exercises?.length && (
        <>
          <p className="u-sm u-muted u-mb-12">{t("exActiveHint")}</p>
          {exercises.length > 1 && (
            <div className="vc-exercises-tools u-mb-12" role="group" aria-label={t("exSearch")}>
              <div className="vc-exercises-search">
                <Search aria-hidden="true" />
                <Input type="search" small value={query} onChange={(e) => setQuery(e.target.value)}
                       placeholder={t("exSearchPlaceholder")} aria-label={t("exSearch")} />
              </div>
              <label className="vc-exercises-tool">
                <span>{t("exSort")}</span>
                <Select small value={sort} onChange={(e) => setSort(e.target.value as ExerciseSort)}>
                  {EXERCISE_SORTS.map((s) => <option key={s} value={s}>{t(`exSort.${s}`)}</option>)}
                </Select>
              </label>
              <label className="vc-exercises-tool" title={t("exDateTitle")}>
                <span>{t("exDate")}</span>
                <Select small value={range} onChange={(e) => setRange(e.target.value as DateRange)}>
                  {DATE_RANGES.map((r) => <option key={r} value={r}>{t(`exDate.${r}`)}</option>)}
                </Select>
              </label>
              {range === "custom" && (
                <>
                  <label className="vc-exercises-tool">
                    <span>{t("exDateFrom")}</span>
                    <Input type="date" small dir="ltr" value={from} max={to || undefined}
                           onChange={(e) => setFrom(e.target.value)} />
                  </label>
                  <label className="vc-exercises-tool">
                    <span>{t("exDateTo")}</span>
                    <Input type="date" small dir="ltr" value={to} min={from || undefined}
                           onChange={(e) => setTo(e.target.value)} />
                  </label>
                </>
              )}
              {filtering && (
                <span className="vc-exercises-tools__count" aria-live="polite">
                  {t("exShowing", { shown: shown.length, n: exercises.length })}
                </span>
              )}
            </div>
          )}
          {!anyActive && <Notice tone="warning" className="u-mb-12">{t("noActiveExercise")}</Notice>}
          {shown.length === 0 && (
            <div className="u-row u-wrap u-gap-8 u-mb-12">
              <p className="u-muted">
                {range === "any" ? t("exNoMatch", { q: query.trim() }) : t("exNoMatchFilters")}
              </p>
              <Button size="sm" variant="quiet" icon={<FilterX />} onClick={clearFilters}>{t("exClearFilters")}</Button>
            </div>
          )}

          <div className="vc-grid vc-grid--wide">
            {shown.map((ex) => {
              const mine = busy?.id === ex.exercise_id ? busy.what : null;
              const cls = ["vc-card", "vc-exercises-card", ex.is_active ? "vc-exercises-card--active" : "",
                flashId === ex.exercise_id ? "vc-exercises-card--flash" : ""].filter(Boolean).join(" ");
              const meta = [
                ex.steps ? stepsText(ex.steps, t) : ex.variant_count > 1 ? t("exVersions", { n: ex.variant_count }) : "",
                ex.bank_questions ? t("exBank", { n: ex.bank_questions }) : "",
                t("exTutor", { mode: ex.default_mode === "coding_partner" ? t("codingPartner") : t("mentor") }),
              ].filter(Boolean);
              const dates = datesText(ex, t, lang);
              return (
                <article key={ex.exercise_id} id={cardId(ex.exercise_id)} className={cls}
                         aria-labelledby={`${cardId(ex.exercise_id)}-title`}>
                  <div>
                    <h3 className="vc-exercises-card__title" id={`${cardId(ex.exercise_id)}-title`} dir={textDir(titleOf(ex))}>
                      {titleOf(ex)}
                    </h3>
                    <div className="vc-exercises-card__id" dir="ltr">{ex.exercise_id}</div>
                  </div>
                  <div className="u-row u-wrap u-gap-6">
                    {ex.is_active && (
                      <span className="vc-badge vc-badge--success"><UserCheck aria-hidden="true" />{t("activeBadge")}</span>
                    )}
                    <span className="vc-badge" title={ex.folder ?? undefined}>
                      {ex.source === "console" ? t("sourceConsole") : ex.source === "package" ? t("sourcePackage")
                        : ex.edited ? t("sourceYamlEdited") : t("sourceYaml")}
                    </span>
                    {plugin && !!ex.os_errors && (
                      <span className="vc-badge vc-badge--warning">{t("osErrorsBadge", { n: ex.os_errors })}</span>
                    )}
                  </div>
                  <div className="vc-exercises-card__meta" dir={textDir(meta.join(" · "))}>{meta.join(" · ")}</div>
                  {dates && <div className="vc-exercises-card__dates" title={dates.exact}>{dates.line}</div>}
                  <div className="vc-exercises-card__actions">
                    <Button variant="brand-soft" size="sm" icon={<Pencil />} busy={mine === "edit"} disabled={!!mine}
                            onClick={() => openWith(ex.exercise_id, "edit")}>
                      {t("edit")}
                    </Button>
                    <Button variant="quiet" size="sm" icon={<CopyPlus />} busy={mine === "duplicate"} disabled={!!mine}
                            onClick={() => openWith(ex.exercise_id, "duplicate")}>
                      {t("duplicate")}
                    </Button>
                    <Button variant="quiet" size="sm" icon={<Download />} busy={mine === "export"} disabled={!!mine}
                            onClick={() => exportZip(ex.exercise_id)}>
                      {t("exportExercise")}
                    </Button>
                  </div>
                  <div className="vc-exercises-card__foot">
                    <Button variant="quiet" size="sm" icon={ex.is_active ? <UserX /> : <UserCheck />}
                            busy={mine === "active"} disabled={!!mine}
                            onClick={() => setActive(ex, !ex.is_active)}>
                      {ex.is_active ? t("disableActive") : t("setActive")}
                    </Button>
                  </div>
                </article>
              );
            })}
          </div>
        </>
      )}

      <section className="vc-card vc-card--flat vc-card--muted u-mt-24" aria-labelledby="vc-exercises-folder-title">
        <h3 className="u-md u-mb-4" id="vc-exercises-folder-title">{t("exFolderTitle")}</h3>
        <p className="u-sm u-soft u-mb-8">{t("exFolderHint")}</p>
        <div className="vc-exercises-folder">
          {folder && <code className="vc-exercises-path" dir="ltr">{folder}</code>}
          {folder && <CopyButton text={folder} size="sm" />}
          <Button size="sm" icon={<RefreshCw />} busy={reloading} onClick={reload}>{t("reloadExercises")}</Button>
        </div>
      </section>

      {form && (
        <ExerciseFormModal
          mode={form.mode}
          initial={form.initial}
          onClose={() => setForm(null)}
          onSaved={afterSave}
        />
      )}
    </section>
  );
}

/** What the last upload ended in: what was installed and what to do next, or why it wasn't. */
function UploadResult({ upload, titleOf, onDismiss }: {
  upload: Upload;
  titleOf: (s: Titled) => string;
  onDismiss: () => void;
}) {
  const { t } = useLang();
  const dismiss = (
    <Button variant="quiet" size="sm" iconOnly icon={<X />} aria-label={t("exUpDismiss")} onClick={onDismiss} />
  );
  const warnings = upload.ok ? upload.result.warnings : upload.warnings;
  const notes = warnings.length > 0 && (
    <details className="u-mt-8">
      <summary className="u-bold">{t("exUpNotes", { n: warnings.length })}</summary>
      <ul className="vc-exercises-list u-mt-4">
        {warnings.map((w, i) => <li key={i} dir={textDir(w)}>{w}</li>)}
      </ul>
    </details>
  );

  if (!upload.ok) {
    return (
      <Notice tone="danger" className="u-mb-16" action={dismiss}
              title={<span>{t("exUpFailed", { name: upload.name })}</span>}>
        <ul className="vc-exercises-list">
          {upload.errors.map((e, i) => <li key={i} dir={textDir(e)}>{e}</li>)}
        </ul>
        {notes}
      </Notice>
    );
  }

  // The server's summary also carries the Hebrew title (not in the shared type).
  const s = upload.result.summary as PackageResult["summary"] & { title_he?: string | null };
  const counts = [stepsText(s.steps ?? 0, t), t("exBank", { n: s.bank_questions ?? 0 })].join(" · ");
  return (
    <Notice tone="success" className="u-mb-16" action={dismiss}
            title={<span>{t(upload.replaced ? "exUpReplaced" : "exUpInstalled", { title: titleOf(s) })}</span>}>
      <div className="u-row u-wrap u-gap-8">
        {s.exercise_id && <code dir="ltr">{s.exercise_id}</code>}
        <span>{counts}</span>
      </div>
      <p className="u-mt-4 u-bold">{t("exUpNext")}</p>
      {notes}
    </Notice>
  );
}
