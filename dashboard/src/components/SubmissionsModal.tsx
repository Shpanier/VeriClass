import { useEffect, useId, useState, type FormEvent } from "react";
import { Check as CheckIcon, FileCode, FileUp, Minus, Plus, RotateCw, Sparkles, TriangleAlert, X } from "lucide-react";
import { api } from "../api";
import type { GradeRecommendation, Student, Submission } from "../types";
import { useLang, type StringKey } from "../i18n";
import { Button, EmptyState, Input, Loading, Modal, Notice, Time, useToast } from "./ui";
import { bandBadge } from "./StudentGrid";
import { textDir } from "../lib/textDir";

/**
 * Every "Send to teacher" submission for one student (IDE plugin), newest
 * first. Each shows the source file they sent and the console output captured
 * at that moment. Polls every 3s so a submission made during class appears
 * without a refresh.
 */
export function SubmissionsModal({ student, onClose }: { student: Student; onClose: () => void }) {
  const { t } = useLang();
  const [subs, setSubs] = useState<Submission[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    // A background poll: a failure stays quiet (the page reports a lost
    // server); only a list that never arrived says so, below.
    const tick = () => api.submissions(student.session_id)
      .then((list) => { if (alive) { setSubs(list); setFailed(false); } })
      .catch(() => { if (alive) setFailed(true); });
    tick();
    const id = window.setInterval(tick, 3000);
    return () => { alive = false; window.clearInterval(id); };
  }, [student.session_id]);

  const count = subs?.length ?? 0;
  const canGrade = subs ? count > 0 : (student.submission_count ?? 0) > 0;

  return (
    <Modal
      size="lg"
      onClose={onClose}
      title={<><bdi>{student.username}</bdi> · {t("submissions")}</>}
      subtitle={(subs || student.variant) && (
        <>
          {subs && (count === 1 ? t("subOne") : t("submissionsFooter", { n: count }))}
          {subs && student.variant && " · "}
          {student.variant && <span>{t("sgVersion", { v: student.variant })}</span>}
        </>
      )}
      footer={<><span className="u-push" /><Button onClick={onClose}>{t("close")}</Button></>}
    >
      <GradePanel sessionId={student.session_id} canGrade={canGrade} />
      {subs === null ? (
        failed ? <Notice tone="danger">{t("subLoadFailed")}</Notice> : <Loading />
      ) : subs.length === 0 ? (
        <EmptyState icon={<FileUp />} title={t("noSubmissions")}>{t("subEmptyText")}</EmptyState>
      ) : (
        subs.map((sub) => <SubmissionCard key={sub.id} sub={sub} />)
      )}
    </Modal>
  );
}

/**
 * The recommended grade for a session: correctness (from the real compile/run)
 * blended 30/70 with the LLM's wise-use judgment. Computed on demand (the
 * lecturer clicks "Recommend a grade") and overridable.
 */
function GradePanel({ sessionId, canGrade }: { sessionId: string; canGrade: boolean }) {
  const { t, lang } = useLang();
  const toast = useToast();
  const ovId = useId();
  const errId = useId();
  const [grade, setGrade] = useState<GradeRecommendation | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [ov, setOv] = useState("");
  const [ovError, setOvError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    api.gradeFor(sessionId)
      .then((g) => { if (alive) setGrade(g); })
      .catch(() => { /* no grade to show: "Recommend a grade" makes one */ })
      .finally(() => { if (alive) setLoaded(true); });
    return () => { alive = false; };
  }, [sessionId]);

  const compute = () => {
    setLoading(true);
    api
      .recommendGrade(sessionId, lang)
      .then((g) => setGrade(g))
      .catch((e) => toast.error(t("subGradeFailed"), e))
      .finally(() => setLoading(false));
  };

  const saveOverride = (e: FormEvent) => {
    e.preventDefault();
    const n = Number(ov);
    if (ov.trim() === "" || Number.isNaN(n) || n < 0 || n > 100) {
      setOvError(t("subOverrideInvalid"));
      return;
    }
    setSaving(true);
    api
      .overrideGrade(sessionId, n)
      .then(() => api.gradeFor(sessionId).then(setGrade))
      .then(() => setOv(""))
      .catch((err) => toast.error(t("subOverrideFailed"), err))
      .finally(() => setSaving(false));
  };

  const signals = grade?.components?.signals ?? [];

  return (
    <section className="vc-card vc-card--muted vc-card--tight vc-students-grade">
      <div className="u-row u-wrap">
        <h3 className="u-md">{t("recommendedGrade")}</h3>
        {grade?.band && <span className={`vc-badge ${bandBadge(grade.band)}`}>{t(`band_${grade.band}` as StringKey)}</span>}
        <Button
          className="u-push"
          size="sm"
          variant={grade ? "secondary" : "primary"}
          icon={grade ? <RotateCw /> : <Sparkles />}
          busy={loading}
          disabled={!canGrade}
          title={canGrade ? undefined : t("subNeedSubmission")}
          onClick={compute}
        >
          {loading ? t("recommending") : grade ? t("recomputeGrade") : t("recommendGrade")}
        </Button>
      </div>

      {!loaded ? (
        <Loading />
      ) : !grade && !loading && (
        <p className="u-sm u-muted u-mt-8">{canGrade ? t("noGradeYet") : t("subNeedSubmission")}</p>
      )}

      {grade && (
        <div className="u-mt-12">
          <div className="vc-students-scores">
            <BigScore value={grade.override_grade ?? grade.recommended} overridden={grade.override_grade != null} />
            <SubScore label={t("correctness")} value={grade.correctness} />
            <SubScore label={t("wiseUse")} value={grade.wise_use} brand />
          </div>

          {grade.wise_use == null && <Notice tone="warning" className="u-mt-8">{t("gradeUnavailable")}</Notice>}

          {grade.rationale && (
            <p className="u-mt-8 u-sm u-soft">
              <span className="u-muted">{t("gradeWhy")}: </span>
              <span dir={textDir(grade.rationale)}>{grade.rationale}</span>
            </p>
          )}

          {signals.length > 0 && (
            <ul className="vc-students-signals">
              {signals.map((sig, i) => {
                const against = sig.trim().startsWith("-");
                return (
                  <li key={i} className={against ? "u-danger" : "u-success"}>
                    {against ? <Minus aria-hidden="true" /> : <Plus aria-hidden="true" />}
                    <span dir={textDir(sig)}>{sig.replace(/^\s*[+-]\s*/, "")}</span>
                  </li>
                );
              })}
            </ul>
          )}

          <form className="vc-students-override u-mt-12" onSubmit={saveOverride} noValidate>
            <label htmlFor={ovId} className="vc-label">{t("overrideLabel")}</label>
            <div className="u-row u-wrap">
              <Input
                id={ovId}
                type="number"
                small
                inline
                dir="ltr"
                min={0}
                max={100}
                value={ov}
                placeholder="0–100"
                aria-invalid={ovError ? true : undefined}
                aria-describedby={ovError ? errId : undefined}
                onChange={(e) => { setOv(e.target.value); setOvError(null); }}
              />
              <Button type="submit" size="sm" busy={saving} disabled={ov === ""}>{t("saveOverride")}</Button>
              {grade.override_grade != null && (
                <span className="u-sm u-soft">{t("gradeOverridden", { g: grade.override_grade })}</span>
              )}
            </div>
            {ovError && <span className="vc-error" id={errId} role="alert">{ovError}</span>}
          </form>
        </div>
      )}
    </section>
  );
}

function BigScore({ value, overridden }: { value: number | null; overridden: boolean }) {
  const { t } = useLang();
  return (
    <div className="vc-students-score">
      <span className={overridden ? "vc-students-score__value u-soft" : "vc-students-score__value"}>
        {value == null ? "—" : Math.round(value)}
      </span>
      <span className="vc-students-score__of">{t("subOutOf")}</span>
    </div>
  );
}

function SubScore({ label, value, brand }: { label: string; value: number | null; brand?: boolean }) {
  return (
    <div>
      <div className="vc-students-subscore__label">{label}</div>
      <div className={brand ? "vc-students-subscore__value u-brand" : "vc-students-subscore__value"}>
        {value == null ? "—" : Math.round(value)}
      </div>
    </div>
  );
}

function SubmissionCard({ sub }: { sub: Submission }) {
  const { t } = useLang();
  const cases = sub.run_report ?? [];
  const passed = cases.filter((c) => c.passed).length;
  const output = sub.console_output ?? "";
  return (
    <article className="vc-students-sub">
      <div className="vc-students-sub__head">
        <FileCode aria-hidden="true" />
        {sub.filename ? <strong dir="ltr">{sub.filename}</strong> : <strong>{t("subUnnamedFile")}</strong>}
        {sub.language && <span className="u-muted">{sub.language}</span>}
        <span className="u-push u-xs u-muted"><Time value={sub.created_at} mode="clock" /></span>
      </div>

      {(sub.compile_ok === 0 || cases.length > 0) && (
        <div className="vc-students-sub__checks">
          {sub.compile_ok === 0 && (
            <span className="vc-badge vc-badge--danger"><TriangleAlert aria-hidden="true" /> {t("compileFailed")}</span>
          )}
          {cases.length > 0 && (
            <span className={`vc-badge ${passed === cases.length ? "vc-badge--success" : "vc-badge--warning"}`}>
              {t("subTestsPassed", { passed, total: cases.length })}
            </span>
          )}
          {cases.map((c, i) => {
            const what = t("subCase", { input: c.input, actual: c.actual, expected: c.expected });
            return (
              <span key={i} role="img" title={what}
                    aria-label={`${c.passed ? t("subCasePassed") : t("subCaseFailed")}: ${what}`}
                    className={`vc-students-sub__case ${c.passed ? "u-success" : "u-danger"}`}>
                {c.passed ? <CheckIcon aria-hidden="true" /> : <X aria-hidden="true" />}
              </span>
            );
          })}
        </div>
      )}

      <div className="vc-students-sub__label">{t("sourceCode")}</div>
      <pre className="vc-pre vc-pre--light" dir="ltr">{sub.source_code}</pre>
      <div className="vc-students-sub__label">{t("consoleOutput")}</div>
      {output.trim() ? (
        <pre className="vc-pre" dir="ltr">{output}</pre>
      ) : (
        <p className="vc-students-sub__empty">{t("noConsole")}</p>
      )}
    </article>
  );
}
