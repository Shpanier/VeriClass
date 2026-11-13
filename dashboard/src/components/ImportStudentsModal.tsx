import { Fragment, useState, type DragEvent } from "react";
import { Check, Download, FileSpreadsheet, Upload, UserPlus } from "lucide-react";
import { api } from "../api";
import type { Course, RosterResult } from "../types";
import { useLang } from "../i18n";
import { describeError } from "../lib/errors";
import { Button, FormField, Modal, Notice, Select, Switch } from "./ui";
import "../styles/courses.css";

/** The file's bytes as base64, so a Hebrew CSV saved by Excel keeps its encoding. */
async function fileBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

/** Save text as a file (UTF-8 with a BOM, so Excel shows Hebrew correctly). */
function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob(["﻿" + text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** A class list the server can read: a CSV (or a plain-text list of names). */
function looksLikeText(file: File): boolean {
  return /\.(csv|txt|tsv)$/i.test(file.name) || file.type.startsWith("text/");
}

/** What a student types to sign in (the account's login code), or dots while
 *  usernames are hidden: until a password is set it is also the password. */
export function MaskedUsername({ code, show }: { code: string | null | undefined; show: boolean }) {
  const { t } = useLang();
  if (!code) return null;
  if (show) return <span className="vc-courses-code" dir="ltr">{code}</span>;
  return (
    <span className="vc-courses-code" data-hidden="true" title={t("coHiddenTitle")}>
      <span aria-hidden="true">••••••••</span>
      <span className="u-sr">{t("coHidden")}</span>
    </span>
  );
}

function Steps({ stage }: { stage: 1 | 2 | 3 }) {
  const { t } = useLang();
  const labels = [t("coImpStep1"), t("coImpStep2"), t("coImpStep3")];
  return (
    <div className="vc-steps" aria-hidden="true">
      {labels.map((label, i) => {
        const n = i + 1;
        const state = n < stage ? "done" : n === stage ? "now" : "todo";
        return (
          <Fragment key={n}>
            {i > 0 && <span className="vc-steps__line" />}
            <span className="vc-steps__dot" data-state={state}>{state === "done" ? <Check /> : n}</span>
            <span>{label}</span>
          </Fragment>
        );
      })}
    </div>
  );
}

/** Students from a CSV file (backend/roster.py), in three steps: choose the
 *  file, check the preview (nothing changes yet), import and hand out the
 *  usernames as a CSV. */
export function ImportStudentsModal({
  courses,
  onClose,
  onImported,
}: {
  courses: Course[];
  onClose: () => void;
  onImported: () => void;
}) {
  const { t } = useLang();
  const [file, setFile] = useState<File | null>(null);
  const [courseId, setCourseId] = useState<string>(courses.length === 1 ? courses[0].course_id : "");
  const [result, setResult] = useState<RosterResult | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [showCodes, setShowCodes] = useState(false);

  const choose = (f: File | null | undefined) => {
    if (!f) return;
    if (!looksLikeText(f)) {
      setError(t("coImpNotCsv"));
      return;
    }
    setFile(f);
    setResult(null);
    setDone(false);
    setError(null);
  };

  const run = async (dryRun: boolean) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.importStudents(await fileBase64(file), courseId || null, dryRun);
      setResult(r);
      if (!dryRun) {
        setDone(true);
        onImported();
      }
    } catch (e) {
      setError(describeError(e, t));
    } finally {
      setBusy(false);
    }
  };

  const onDragLeave = (e: DragEvent<HTMLLabelElement>) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false);
  };

  const stamp = new Date().toISOString().slice(0, 10);
  const stage: 1 | 2 | 3 = !result ? 1 : done ? 3 : 2;
  const importable = result ? result.counts.new + result.counts.existing : 0;
  const course = courses.find((c) => c.course_id === courseId);

  const footer =
    stage === 1 ? (
      <>
        <span className="u-push" />
        <Button onClick={onClose}>{t("cancel")}</Button>
        <Button variant="primary" busy={busy} disabled={!file} onClick={() => run(true)}>{t("importPreview")}</Button>
      </>
    ) : stage === 2 ? (
      <>
        <Button variant="quiet" disabled={busy} onClick={() => { setResult(null); setError(null); }}>{t("coImpBack")}</Button>
        <span className="u-push" />
        <Button onClick={onClose}>{t("cancel")}</Button>
        <Button variant="primary" icon={<UserPlus />} busy={busy} disabled={importable === 0} onClick={() => run(false)}>
          {t("coImpDo", { n: importable })}
        </Button>
      </>
    ) : (
      <>
        <span className="u-push" />
        <Button onClick={onClose}>{t("close")}</Button>
        {result?.codes_csv && (
          <Button
            variant="primary" icon={<Download />}
            onClick={() => download(`usernames-${courseId || "students"}-${stamp}.csv`, result.codes_csv!)}
          >
            {t("importDownloadCodes")}
          </Button>
        )}
      </>
    );

  return (
    <Modal
      title={t("importStudentsTitle")}
      subtitle={stage === 1 ? t("coImpSubChoose") : stage === 2 ? t("coImpSubPreview") : t("coImpSubDone")}
      size="lg" onClose={onClose} footer={footer}
    >
      {/* A file dropped anywhere in the dialog is taken (not opened by the browser). */}
      <div
        className="vc-courses-import"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); if (!done) choose(e.dataTransfer.files?.[0]); }}
      >
        <Steps stage={stage} />
        {error && <Notice tone="danger" title={t("coImpFailed")} className="u-mb-12">{error}</Notice>}

        {stage === 1 && (
          <>
            <div className="vc-card vc-card--muted vc-card--tight u-mb-16">
              <div className="u-bold u-sm">{t("coImpGetTitle")}</div>
              <ul className="vc-courses-get">
                <li>{t("coImpGet1")}</li>
                <li>{t("coImpGet2")}</li>
                <li>{t("coImpGet3")}</li>
              </ul>
            </div>

            <h3 className="vc-courses-sub u-mb-4">{t("coImpFileTitle")}</h3>
            <p className="u-soft u-sm u-mb-8">{t("importStudentsIntro")}</p>
            <pre className="vc-pre vc-pre--light u-mb-12" dir="ltr">
              name,email,student_id,course,group{"\n"}Israel Israeli,israel@example.ac.il,012345678,dl-2026,A
            </pre>

            <label
              className="vc-courses-drop u-mb-16" data-over={over} data-file={!!file}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }}
              onDragLeave={onDragLeave}
              onDrop={(e) => { e.preventDefault(); e.stopPropagation(); setOver(false); choose(e.dataTransfer.files?.[0]); }}
            >
              <input
                type="file" className="u-sr" accept=".csv,.txt,text/csv"
                onChange={(e) => { choose(e.target.files?.[0]); e.target.value = ""; }}
              />
              <span className="vc-courses-drop__icon">{file ? <FileSpreadsheet /> : <Upload />}</span>
              <span className="vc-courses-drop__title" dir="auto">{file ? file.name : t("coImpDrop")}</span>
              <span className="vc-courses-drop__note">{file ? t("coImpReplace") : t("coImpDropNote")}</span>
            </label>

            <FormField label={t("coImpCourseLabel")} hint={t("coImpCourseHint")}>
              <Select value={courseId} onChange={(e) => { setCourseId(e.target.value); setResult(null); }}>
                <option value="">{t("importNoCourse")}</option>
                {courses.map((c) => (
                  <option key={c.course_id} value={c.course_id}>{c.name} ({c.course_id})</option>
                ))}
              </Select>
            </FormField>
          </>
        )}

        {result && stage === 2 && (
          <>
            <div className="u-row u-wrap u-gap-8 u-mb-12 u-sm">
              <FileSpreadsheet size={16} aria-hidden="true" />
              <span className="u-bold" dir="auto">{file?.name}</span>
              <span className="u-muted">·</span>
              <span className="u-soft">
                {t("importCourse")}: <span dir="auto">{course ? course.name : t("importNoCourse")}</span>
              </span>
            </div>
            <div className="u-row u-wrap u-gap-6 u-mb-12">
              <span className="vc-badge vc-badge--success">{t("coImpNew", { n: result.counts.new })}</span>
              <span className="vc-badge vc-badge--info">{t("coImpExisting", { n: result.counts.existing })}</span>
              {result.counts.errors > 0 && (
                <span className="vc-badge vc-badge--danger">{t("coImpProblems", { n: result.counts.errors })}</span>
              )}
            </div>
            {importable === 0 ? (
              <Notice tone="warning" className="u-mb-12">{t("coImpNone")}</Notice>
            ) : result.counts.errors > 0 ? (
              <Notice tone="warning" className="u-mb-12">{t("coImpProblemsNote")}</Notice>
            ) : null}
            <RowsTable result={result} done={false} showCodes={false} />
          </>
        )}

        {result && stage === 3 && (
          <>
            <Notice tone="success" title={t("coImpDoneTitle")} className="u-mb-12">
              {t("coImpDoneText", { n: result.counts.new, e: result.counts.existing, x: result.counts.errors })}
            </Notice>
            {result.codes_csv && (
              <Notice tone="warning" title={t("coImpSecretTitle")} className="u-mb-12">{t("coImpSecretBody")}</Notice>
            )}
            <div className="u-row u-mb-8">
              <Switch checked={showCodes} onChange={setShowCodes}>{t("coShowUsernames")}</Switch>
            </div>
            <RowsTable result={result} done showCodes={showCodes} />
          </>
        )}
      </div>
    </Modal>
  );
}

/** The file's rows: what happens to each (preview) or happened (after the import). */
function RowsTable({ result, done, showCodes }: { result: RosterResult; done: boolean; showCodes: boolean }) {
  const { t } = useLang();
  return (
    <div className="vc-table-wrap vc-courses-import__table">
      <table className="vc-table">
        <thead>
          <tr>
            <th scope="col">{t("coColLine")}</th>
            <th scope="col">{t("colName")}</th>
            <th scope="col">{t("coColEmail")}</th>
            <th scope="col">{t("importCourse")}</th>
            <th scope="col">{t("importStatus")}</th>
            {done && <th scope="col">{t("colUsername")}</th>}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((r) => (
            <tr key={r.line}>
              <td className="u-muted">{r.line}</td>
              <td><span dir="auto">{r.username ?? r.name}</span></td>
              <td className="u-soft"><span dir="ltr">{r.email ?? ""}</span></td>
              <td><span dir="ltr">{r.course ?? ""}</span></td>
              <td>
                {r.error ? (
                  <span className="vc-courses-problem">
                    <span className="vc-badge vc-badge--danger">{t("coImpProblem")}</span>
                    <span className="vc-courses-problem__text" dir="auto">{r.error}</span>
                  </span>
                ) : r.status === "new" ? (
                  <span className="vc-badge vc-badge--success">{t("importNew")}</span>
                ) : (
                  <span className="vc-badge vc-badge--info">{t("importExisting")}</span>
                )}
              </td>
              {done && <td><MaskedUsername code={r.error ? null : r.code} show={showCodes} /></td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
