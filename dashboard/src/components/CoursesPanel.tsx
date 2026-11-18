import { useEffect, useId, useMemo, useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { BookOpen, Check, KeyRound, Plus, RefreshCw, RotateCcw, Save, Search, Trash2, Upload, Users, X } from "lucide-react";
import { api } from "../api";
import type { Course, ExerciseSummary, UserAccount } from "../types";
import { useLang } from "../i18n";
import { describeError } from "../lib/errors";
import { sortExercises, useExerciseSort } from "../lib/exerciseOrder";
import { Button, EmptyState, FormField, Input, Loading, Notice, Switch, useConfirm, useToast } from "./ui";
import { ImportStudentsModal, MaskedUsername } from "./ImportStudentsModal";
import { MeetingsSection } from "./MeetingsSection";
import "../styles/courses.css";

// The "Courses & students" tab: which students are in which course, which
// exercises each course offers, and the one preselected after login
// (backend/courses.py). Below the courses: each account's password
// (backend/passwords.py).
//
// Words: the data's `username` is the person's name; `login_code` is what they
// type to sign in, and the screen calls it their "username".

/** A course card's unsaved changes, kept as a difference from the saved
 *  course. A reload (after a meeting, an import, a password, another card's
 *  save) then neither loses the ticks nor undoes what the reload brought in. */
interface Draft {
  name?: string;
  def?: string | null; // the default exercise, when changed
  exOn: string[];
  exOff: string[];
  memOn: number[];
  memOff: number[];
}
const NO_DRAFT: Draft = { exOn: [], exOff: [], memOn: [], memOff: [] };

// Kept while another tab is open, so looking something up doesn't lose ticks.
let keptDrafts: Record<string, Draft> = {};

function merge<T>(saved: T[], on: T[], off: T[]): T[] {
  return [...saved.filter((x) => !off.includes(x)), ...on.filter((x) => !saved.includes(x))];
}

/** Include [id] (want) or not, as a difference from [saved]. */
function flip<T>(saved: T[], on: T[], off: T[], id: T, want: boolean): [T[], T[]] {
  const nextOn = on.filter((x) => x !== id);
  const nextOff = off.filter((x) => x !== id);
  const has = saved.includes(id);
  if (want && !has) nextOn.push(id);
  if (!want && has) nextOff.push(id);
  return [nextOn, nextOff];
}

/** The course as its card shows it: the saved course with the draft on top. */
function withDraft(c: Course, d: Draft | undefined): Course {
  if (!d) return c;
  const exercises = merge(c.exercises, d.exOn, d.exOff);
  let def = d.def !== undefined ? d.def : c.default_exercise;
  if (exercises.length === 0) def = null;
  else if (!def || !exercises.includes(def)) def = exercises[0];
  return { ...c, name: d.name ?? c.name, exercises, default_exercise: def, members: merge(c.members, d.memOn, d.memOff) };
}

const sameSet = <T,>(a: T[], b: T[]) => a.length === b.length && a.every((x) => b.includes(x));

function differs(a: Course, b: Course): boolean {
  return a.name !== b.name || a.default_exercise !== b.default_exercise
    || !sameSet(a.exercises, b.exercises) || !sameSet(a.members, b.members);
}

function SearchBox({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <div className="vc-courses-search">
      <Search aria-hidden="true" />
      <Input small type="search" value={value} onChange={(e) => onChange(e.target.value)} placeholder={label} aria-label={label} />
    </div>
  );
}

export function CoursesPanel() {
  const { t } = useLang();
  const toast = useToast();
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [exercises, setExercises] = useState<ExerciseSummary[]>([]);
  const [users, setUsers] = useState<UserAccount[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() => keptDrafts);
  const [creating, setCreating] = useState(false);
  const [justCreated, setJustCreated] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [showCodes, setShowCodes] = useState(false);
  const loaded = useRef(false);
  const nameInput = useRef<HTMLInputElement>(null);
  const startHead = useId();
  const coursesHead = useId();

  useEffect(() => { keptDrafts = drafts; }, [drafts]);

  const load = () =>
    Promise.all([api.courses(), api.exercises(), api.users()])
      .then(([c, e, u]) => {
        loaded.current = true;
        setCourses(c);
        setExercises(e);
        setUsers(u);
        setLoadError(null);
        // A course deleted elsewhere takes its unsaved changes with it.
        setDrafts((all) => {
          const ids = new Set(c.map((x) => x.course_id));
          const keep = Object.keys(all).filter((k) => ids.has(k));
          return keep.length === Object.keys(all).length ? all : Object.fromEntries(keep.map((k) => [k, all[k]]));
        });
      })
      .catch((err) => {
        if (loaded.current) toast.error(t("coLoadFailed"), err);
        else setLoadError(describeError(err, t));
      });

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const setDraft = (id: string, d: Draft | undefined) =>
    setDrafts((all) => {
      const next = { ...all };
      if (d) next[id] = d;
      else delete next[id];
      return next;
    });

  const onSaved = (c: Course) => {
    setCourses((list) => list?.map((x) => (x.course_id === c.course_id ? c : x)) ?? list);
    setDraft(c.course_id, undefined);
    if (justCreated === c.course_id) setJustCreated(null);
    load();
  };

  const openCreate = () => {
    if (creating) nameInput.current?.focus();
    else setCreating(true);
  };

  const students = useMemo(() => users.filter((u) => u.role === "student"), [users]);
  const courseNames = useMemo(() => new Map((courses ?? []).map((c) => [c.course_id, c.name])), [courses]);
  const hasCourses = !!courses && courses.length > 0;
  const hasStudents = students.length > 0;
  const setUp = !!courses && courses.some((c) => c.exercises.length > 0 && c.members.length > 0);
  // The first thing to do gets the page's main button.
  const importFirst = courses !== null && !hasStudents;

  const steps: { done: boolean; title: string; hint: string; action?: string; icon?: ReactNode; run?: () => void }[] = [
    { done: hasStudents, title: t("coStart1"), hint: t("coStart1Hint"), action: t("importStudents"), icon: <Upload />,
      run: () => setImporting(true) },
    { done: hasCourses, title: t("coStart2"), hint: t("coStart2Hint"), action: t("newCourse"), icon: <Plus />, run: openCreate },
    { done: setUp, title: t("coStart3"), hint: t("coStart3Hint") },
  ];

  return (
    <div className="vc-courses">
      <header className="vc-courses-head">
        <div className="vc-courses-head__text">
          <h1 className="vc-courses-head__title">{t("coPageTitle")}</h1>
          <p className="vc-courses-head__lead">{t("coursesIntro")}</p>
        </div>
        <div className="vc-courses-head__actions">
          <Button variant={importFirst ? "primary" : "secondary"} icon={<Upload />} onClick={() => setImporting(true)}>
            {t("importStudents")}
          </Button>
          <Button variant={importFirst || creating ? "secondary" : "primary"} icon={<Plus />} disabled={courses === null} onClick={openCreate}>
            {t("newCourse")}
          </Button>
        </div>
      </header>

      {courses === null && !loadError && <Loading />}
      {courses === null && loadError && (
        <Notice tone="danger" title={t("coLoadFailed")}
                action={<Button size="sm" icon={<RefreshCw />} onClick={() => { setLoadError(null); load(); }}>{t("retry")}</Button>}>
          {loadError}
        </Notice>
      )}

      {courses !== null && (
        <>
          {!setUp && (
            <section className="vc-card vc-card--brand vc-card--pad-lg vc-courses-start" aria-labelledby={startHead}>
              <h2 id={startHead} className="vc-section__title">{t("coStartTitle")}</h2>
              <div className="vc-checklist">
                {steps.map((s, i) => (
                  <div key={i} className="vc-checklist__item" data-done={s.done}>
                    <span className="vc-checklist__mark">{s.done ? <Check /> : i + 1}</span>
                    <div className="vc-checklist__text">
                      <div className="vc-checklist__title">{s.title}</div>
                      {!s.done && <div className="vc-checklist__hint">{s.hint}</div>}
                    </div>
                    {!s.done && s.run && <Button size="sm" icon={s.icon} onClick={s.run}>{s.action}</Button>}
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="vc-section" aria-labelledby={coursesHead}>
            <div className="vc-section__head">
              <h2 id={coursesHead} className="vc-section__title">
                <BookOpen /> {t("coursesTitle")} <span className="vc-badge vc-badge--count">{courses.length}</span>
              </h2>
            </div>

            {creating && (
              <CreateCourse
                nameRef={nameInput}
                onCancel={() => setCreating(false)}
                onCreated={async (id) => { await load(); setCreating(false); setJustCreated(id); }}
              />
            )}

            {courses.length === 0 && !creating && (
              <div className="vc-card">
                <EmptyState icon={<BookOpen />} title={t("coNoCoursesTitle")}
                            actions={<Button icon={<Plus />} onClick={openCreate}>{t("newCourse")}</Button>}>
                  {t("coNoCoursesText")}
                </EmptyState>
              </div>
            )}

            <div className="vc-courses-cards">
              {courses.map((c) => (
                <CourseCard
                  key={c.course_id}
                  course={c}
                  draft={drafts[c.course_id]}
                  onDraft={(d) => setDraft(c.course_id, d)}
                  exercises={exercises}
                  students={students}
                  courseNames={courseNames}
                  showCodes={showCodes}
                  isNew={justCreated === c.course_id}
                  onDismissNew={() => setJustCreated(null)}
                  onSaved={onSaved}
                  onDeleted={() => { setDraft(c.course_id, undefined); load(); }}
                  onChanged={load}
                  onImport={() => setImporting(true)}
                />
              ))}
            </div>
          </section>

          <PasswordsSection
            users={users}
            hasStudents={hasStudents}
            showCodes={showCodes}
            onShowCodes={setShowCodes}
            onChanged={load}
            onImport={() => setImporting(true)}
          />
        </>
      )}

      {importing && (
        <ImportStudentsModal courses={courses ?? []} onClose={() => setImporting(false)} onImported={load} />
      )}
    </div>
  );
}

/** The new-course form: a name and a permanent id. */
function CreateCourse({ nameRef, onCancel, onCreated }: {
  nameRef: RefObject<HTMLInputElement>;
  onCancel: () => void;
  onCreated: (courseId: string) => Promise<unknown>;
}) {
  const { t } = useLang();
  const form = useRef<HTMLFormElement>(null);
  const head = useId();
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { form.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const c = await api.createCourse(id.trim(), name.trim());
      await onCreated(c.course_id);
    } catch (err) {
      setError(describeError(err, t));
      setBusy(false);
    }
  };

  return (
    <form ref={form} className="vc-card vc-card--brand vc-courses-create" onSubmit={submit} aria-labelledby={head}>
      <h3 id={head} className="vc-courses-sub"><Plus /> {t("coNewCourseTitle")}</h3>
      <div className="vc-courses-create__fields">
        <FormField label={t("courseName")} hint={t("coNameHint")} required>
          <Input ref={nameRef} autoFocus value={name} onChange={(e) => setName(e.target.value)}
                 placeholder={t("courseNamePlaceholder")} />
        </FormField>
        <FormField label={t("courseId")} hint={t("coIdHint")} required>
          <Input mono dir="ltr" value={id} onChange={(e) => setId(e.target.value)} placeholder={t("courseIdPlaceholder")}
                 autoComplete="off" spellCheck={false} />
        </FormField>
      </div>
      {error && <Notice tone="danger" className="u-mb-12">{error}</Notice>}
      <div className="u-row u-wrap">
        <Button variant="primary" type="submit" icon={<Plus />} busy={busy} disabled={!id.trim() || !name.trim()}>
          {t("createCourse")}
        </Button>
        <Button onClick={onCancel}>{t("cancel")}</Button>
      </div>
    </form>
  );
}

function CourseCard({
  course, draft, onDraft, exercises, students, courseNames, showCodes, isNew, onDismissNew, onSaved, onDeleted,
  onChanged, onImport,
}: {
  course: Course;
  draft: Draft | undefined;
  onDraft: (d: Draft | undefined) => void;
  exercises: ExerciseSummary[];
  students: UserAccount[];
  courseNames: Map<string, string>;
  showCodes: boolean;
  isNew: boolean;
  onDismissNew: () => void;
  onSaved: (c: Course) => void;
  onDeleted: () => void;
  onChanged: () => void;
  onImport: () => void;
}) {
  const { t, lang } = useLang();
  const [exSort] = useExerciseSort();
  const toast = useToast();
  const confirm = useConfirm();
  const card = useRef<HTMLElement>(null);
  const nameId = useId();
  const exHead = useId();
  const stHead = useId();
  const [exFilter, setExFilter] = useState("");
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState<"save" | "delete" | null>(null);

  // A course just created: bring its card into view (its notice says what's next).
  useEffect(() => {
    if (isNew) card.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [isNew]);

  const d = draft ?? NO_DRAFT;
  const shownCourse = withDraft(course, draft);
  const dirty = !!draft && differs(course, shownCourse);
  const members = new Set(shownCourse.members);
  const title = (ex: ExerciseSummary) => (lang === "he" && ex.title_he) || ex.title_en;

  /** Keep only real changes; nothing left means no draft. */
  const update = (next: Draft) => {
    const n: Draft = {
      ...next,
      name: next.name === course.name ? undefined : next.name,
      def: next.def === course.default_exercise ? undefined : next.def,
    };
    onDraft(differs(course, withDraft(course, n)) ? n : undefined);
  };

  const toggleExercise = (id: string) => {
    const on = shownCourse.exercises.includes(id);
    const [exOn, exOff] = flip(course.exercises, d.exOn, d.exOff, id, !on);
    const list = merge(course.exercises, exOn, exOff);
    let def = shownCourse.default_exercise;
    if (on && def === id) def = list[0] ?? null;
    if (!on && !def) def = id;
    update({ ...d, exOn, exOff, def });
  };

  const toggleMember = (id: number) => {
    const [memOn, memOff] = flip(course.members, d.memOn, d.memOff, id, !members.has(id));
    update({ ...d, memOn, memOff });
  };

  // The filters show only when the lists are long. Exercises in the order
  // chosen in the Exercises tab (newest first unless changed there).
  const exQ = exercises.length > 8 ? exFilter.trim().toLowerCase() : "";
  const shownEx = sortExercises(exercises.filter(
    (ex) => !exQ || title(ex).toLowerCase().includes(exQ) || ex.exercise_id.toLowerCase().includes(exQ),
  ), exSort, lang);
  const q = students.length > 12 ? filter.trim().toLowerCase() : "";

  // Members (as saved) first, so they are visible without scrolling; ordered by
  // the saved course, not the draft, so rows don't jump while ticking boxes.
  const shown = useMemo(() => {
    const saved = new Set(course.members);
    return students
      .filter((s) => !q || s.username.toLowerCase().includes(q) || s.login_code.toLowerCase().includes(q))
      .sort((a, b) => Number(saved.has(b.id)) - Number(saved.has(a.id)));
  }, [students, q, course.members]);

  const setShown = (want: boolean) => {
    let on = d.memOn;
    let off = d.memOff;
    for (const s of shown) [on, off] = flip(course.members, on, off, s.id, want);
    update({ ...d, memOn: on, memOff: off });
  };

  const save = async () => {
    setBusy("save");
    try {
      const saved = await api.updateCourse(shownCourse);
      toast.success(t("coSaved"));
      onSaved(saved);
    } catch (err) {
      toast.error(t("coSaveFailed"), err);
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!(await confirm({
      title: t("coDeleteTitle", { name: course.name }), body: t("deleteCourseConfirm"),
      confirmLabel: t("coDeleteYes"), danger: true,
    }))) return;
    setBusy("delete");
    try {
      await api.deleteCourse(course.course_id);
      toast.success(t("coDeleted"));
      onDeleted();
    } catch (err) {
      toast.error(t("coDeleteFailed"), err);
      setBusy(null);
    }
  };

  const offered = shownCourse.exercises.length;
  const hint = offered === 0 ? t("courseHintNone") : offered === 1 ? t("courseHintOne") : t("courseHintMany");
  const nameMissing = !shownCourse.name.trim();

  return (
    <article ref={card} className="vc-card vc-courses-card" data-dirty={dirty} aria-label={shownCourse.name || course.course_id}>
      <header className="vc-courses-card__head">
        <div className="u-grow">
          <label htmlFor={nameId} className="u-sr">{t("courseName")}</label>
          <Input id={nameId} className="vc-courses-card__name" value={shownCourse.name} aria-invalid={nameMissing || undefined}
                 onChange={(e) => update({ ...d, name: e.target.value })} />
          <div className="vc-courses-card__meta">
            <span title={t("coIdTitle")}>{t("coId")} <span className="vc-mono" dir="ltr">{course.course_id}</span></span>
            <span aria-hidden="true">·</span>
            <span>{t("coMeta", { s: shownCourse.members.length, e: offered })}</span>
          </div>
        </div>
        {dirty && <span className="vc-badge vc-badge--warning">{t("coUnsaved")}</span>}
      </header>

      <div className="vc-courses-card__body">
        {isNew && (
          <Notice tone="info" title={t("coCreated")} className="u-mb-16"
                  action={<Button variant="quiet" size="sm" iconOnly icon={<X />} aria-label={t("close")} onClick={onDismissNew} />}>
            {t("coCreatedNext")}
          </Notice>
        )}

        <div className="vc-courses-card__cols">
          <section aria-labelledby={exHead}>
            <h3 id={exHead} className="vc-courses-sub">
              <BookOpen /> {t("courseExercises")} <span className="vc-badge vc-badge--count">{offered}</span>
            </h3>
            <p className="vc-hint">{hint}</p>
            {exercises.length > 8 && (
              <div className="vc-courses-tools">
                <SearchBox value={exFilter} onChange={setExFilter} label={t("coFilterExercises")} />
              </div>
            )}
            <div className="vc-courses-pick">
              {exercises.length === 0 && <div className="vc-courses-pick__empty">{t("coNoExercises")}</div>}
              {exercises.length > 0 && shownEx.length === 0 && <div className="vc-courses-pick__empty">{t("coNoExerciseMatch")}</div>}
              {shownEx.map((ex) => {
                const on = shownCourse.exercises.includes(ex.exercise_id);
                const isDefault = on && shownCourse.default_exercise === ex.exercise_id;
                return (
                  <div key={ex.exercise_id} className="vc-courses-pick__row" data-on={on}>
                    <label className="vc-courses-pick__main">
                      <input type="checkbox" checked={on} onChange={() => toggleExercise(ex.exercise_id)} />
                      <span className="vc-courses-pick__title" dir="auto" title={title(ex)}>{title(ex)}</span>
                      <span className="vc-courses-pick__id" dir="ltr">{ex.exercise_id}</span>
                    </label>
                    <label className="vc-courses-default" data-off={!on} data-default={isDefault} title={t("coDefaultTitle")}>
                      <input
                        type="radio" name={`default-${course.course_id}`} disabled={!on} checked={isDefault}
                        aria-label={`${t("defaultExercise")}: ${title(ex)}`}
                        onChange={() => update({ ...d, def: ex.exercise_id })}
                      />
                      {t("defaultExercise")}
                    </label>
                  </div>
                );
              })}
            </div>
          </section>

          <section aria-labelledby={stHead}>
            <h3 id={stHead} className="vc-courses-sub">
              <Users /> {t("coStudentsTitle")} <span className="vc-badge vc-badge--count">{shownCourse.members.length}</span>
            </h3>
            <p className="vc-hint">{t("coStudentsHint")}</p>
            {students.length === 0 ? (
              <Notice action={<Button size="sm" icon={<Upload />} onClick={onImport}>{t("importStudents")}</Button>}>
                {t("coNoStudentsCard")}
              </Notice>
            ) : (
              <>
                <div className="vc-courses-tools">
                  {students.length > 12 && <SearchBox value={filter} onChange={setFilter} label={t("searchStudents")} />}
                  <Button size="sm" onClick={() => setShown(true)}>{q ? t("selectShown") : t("coSelectAll")}</Button>
                  <Button size="sm" variant="quiet" onClick={() => setShown(false)}>{q ? t("clearShown") : t("coClearAll")}</Button>
                </div>
                <div className="vc-courses-pick">
                  {shown.length === 0 && <div className="vc-courses-pick__empty">{t("noStudentsFound")}</div>}
                  {shown.map((s) => {
                    const on = members.has(s.id);
                    const others = s.courses.filter((c) => c !== course.course_id);
                    return (
                      <label key={s.id} className="vc-courses-pick__row vc-courses-pick__main" data-on={on}>
                        <input type="checkbox" checked={on} onChange={() => toggleMember(s.id)} />
                        <span className="vc-courses-pick__title u-grow" dir="auto">{s.username}</span>
                        <MaskedUsername code={s.login_code} show={showCodes} />
                        {others.length > 0 && (
                          <span className="vc-courses-pick__badges">
                            {others.map((c) => (
                              <span key={c} className="vc-badge" dir="ltr" title={t("coAlsoIn", { name: courseNames.get(c) ?? c })}>{c}</span>
                            ))}
                          </span>
                        )}
                      </label>
                    );
                  })}
                </div>
              </>
            )}
          </section>
        </div>

        <MeetingsSection courseId={course.course_id} exercises={exercises} onChanged={onChanged} />
      </div>

      <footer className="vc-courses-card__foot" data-dirty={dirty}>
        <Button variant="primary" icon={<Save />} busy={busy === "save"} disabled={!dirty || nameMissing || busy !== null} onClick={save}>
          {t("saveCourse")}
        </Button>
        <Button variant="quiet" icon={<RotateCcw />} disabled={!dirty || busy !== null} onClick={() => onDraft(undefined)}>
          {t("revert")}
        </Button>
        {dirty && <span className="u-sm u-bold u-warning">{t("coUnsaved")}</span>}
        <span className="u-push" />
        <Button variant="danger-soft" icon={<Trash2 />} busy={busy === "delete"} disabled={busy !== null} onClick={remove}>
          {t("deleteCourse")}
        </Button>
      </footer>
    </article>
  );
}

/** Every account with what it signs in with and whether its password was set. */
function PasswordsSection({ users, hasStudents, showCodes, onShowCodes, onChanged, onImport }: {
  users: UserAccount[];
  hasStudents: boolean;
  showCodes: boolean;
  onShowCodes: (v: boolean) => void;
  onChanged: () => void;
  onImport: () => void;
}) {
  const { t } = useLang();
  const toast = useToast();
  const confirm = useConfirm();
  const head = useId();
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState<number | null>(null);

  // Both sides in lower case: usernames are stored in capitals.
  const q = filter.trim().toLowerCase();
  const shown = users.filter((u) => !q || u.username.toLowerCase().includes(q) || u.login_code.toLowerCase().includes(q));

  const apply = async (u: UserAccount, password: string | null) => {
    if (password === null && !(await confirm({
      title: t("coResetTitle", { name: u.username }), body: t("coResetBody"), confirmLabel: t("coResetYes"),
    }))) return;
    setBusy(u.id);
    try {
      await api.setPassword(u.id, password);
      setEditing(null);
      setValue("");
      toast.success(password === null ? t("coPasswordReset", { name: u.username }) : t("coPasswordSaved", { name: u.username }));
      onChanged();
    } catch (err) {
      toast.error(t("coPasswordFailed"), err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="vc-section u-mt-24" aria-labelledby={head}>
      <div className="vc-section__head u-mb-4">
        <h2 id={head} className="vc-section__title">
          <KeyRound /> {t("passwordsTitle")} <span className="vc-badge vc-badge--count">{users.length}</span>
        </h2>
      </div>
      <p className="vc-section__hint u-mb-12">{t("passwordsIntro")}</p>

      {!hasStudents && (
        <div className="vc-card u-mb-12">
          <EmptyState icon={<Users />} title={t("coNoStudentsTitle")}
                      actions={<Button icon={<Upload />} onClick={onImport}>{t("importStudents")}</Button>}>
            {t("coNoStudentsText")}
          </EmptyState>
        </div>
      )}

      {users.length > 0 && (
        <>
          <div className="vc-courses-pw-tools">
            <SearchBox value={filter} onChange={setFilter} label={t("searchStudents")} />
            {q && <span className="u-muted u-sm">{t("coShowing", { n: shown.length, m: users.length })}</span>}
            <span className="u-push" />
            <Switch checked={showCodes} onChange={onShowCodes}>{t("coShowUsernames")}</Switch>
          </div>
          <p className="vc-hint u-mb-8">{t("coMaskHint")}</p>

          <div className="vc-table-wrap">
            <table className="vc-table vc-courses-table">
              <thead>
                <tr>
                  <th scope="col">{t("colName")}</th>
                  <th scope="col">{t("colUsername")}</th>
                  <th scope="col">{t("colRole")}</th>
                  <th scope="col">{t("colPassword")}</th>
                  <th scope="col"><span className="u-sr">{t("coColActions")}</span></th>
                </tr>
              </thead>
              <tbody>
                {shown.length === 0 && (
                  <tr><td colSpan={5} className="u-muted">{t("noStudentsFound")}</td></tr>
                )}
                {shown.map((u) => (
                  <tr key={u.id}>
                    {/* Name: the person (data: username). Username: what they sign in with (data: login_code). */}
                    <td><span dir="auto">{u.username}</span></td>
                    <td><MaskedUsername code={u.login_code} show={showCodes} /></td>
                    <td>{u.role === "teacher" ? t("roleTeacher") : t("roleStudent")}</td>
                    <td>
                      {u.custom_password
                        ? <span className="vc-badge vc-badge--success">{t("passwordCustom")}</span>
                        : <span className="vc-badge vc-badge--warning">{t("passwordDefault")}</span>}
                    </td>
                    <td>
                      {editing === u.id ? (
                        <form className="vc-courses-pw-form" onSubmit={(e) => { e.preventDefault(); apply(u, value); }}>
                          <Input
                            small autoFocus type="password" dir="ltr" value={value} autoComplete="new-password"
                            onChange={(e) => setValue(e.target.value)}
                            onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); setEditing(null); } }}
                            placeholder={t("coPasswordHint")} aria-label={t("coPasswordFor", { name: u.username })}
                          />
                          <Button size="sm" variant="primary" type="submit" busy={busy === u.id} disabled={!value}>
                            {t("setPassword")}
                          </Button>
                          <Button size="sm" variant="quiet" onClick={() => setEditing(null)}>{t("cancel")}</Button>
                        </form>
                      ) : (
                        <span className="vc-courses-actions">
                          <Button size="sm" icon={<KeyRound />} onClick={() => { setEditing(u.id); setValue(""); }}>
                            {t("changePassword")}
                          </Button>
                          {u.custom_password && (
                            <Button size="sm" variant="quiet" icon={<RotateCcw />} busy={busy === u.id} onClick={() => apply(u, null)}>
                              {t("resetPassword")}
                            </Button>
                          )}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
