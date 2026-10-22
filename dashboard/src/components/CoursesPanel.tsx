import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Course, ExerciseSummary, UserAccount } from "../types";
import { useLang } from "../i18n";
import { Button } from "./ui/Button";
import { controlStyle } from "./ui/Field";

// The "Courses" tab: which students are in which course, which exercises each
// course offers, and the one preselected after login (backend/courses.py).
// Below the courses: each account's password (backend/passwords.py).
export function CoursesPanel() {
  const { t } = useLang();
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [exercises, setExercises] = useState<ExerciseSummary[]>([]);
  const [users, setUsers] = useState<UserAccount[]>([]);
  const [creating, setCreating] = useState(false);
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);

  const load = () =>
    Promise.all([api.courses(), api.exercises(), api.users()])
      .then(([c, e, u]) => {
        setCourses(c);
        setExercises(e);
        setUsers(u);
      })
      .catch(console.error);

  useEffect(() => {
    load();
  }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError(null);
    try {
      await api.createCourse(newId.trim(), newName.trim());
      setCreating(false);
      setNewId("");
      setNewName("");
      await load();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : String(err));
    }
  };

  const students = users.filter((u) => u.role === "student");

  return (
    <section>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>{t("coursesTitle")}</h2>
        {!creating && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            {t("newCourse")}
          </Button>
        )}
      </div>
      <p style={{ color: "#6b7280", fontSize: 13, marginTop: 0, maxWidth: 760 }}>{t("coursesIntro")}</p>

      {creating && (
        <form onSubmit={create} style={{ ...card, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input
            autoFocus
            value={newId}
            onChange={(e) => setNewId(e.target.value)}
            placeholder={t("courseIdPlaceholder")}
            aria-label={t("courseId")}
            dir="ltr"
            style={{ ...controlStyle, width: 200 }}
          />
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t("courseNamePlaceholder")}
            aria-label={t("courseName")}
            dir="auto"
            style={{ ...controlStyle, width: 260 }}
          />
          <Button variant="primary" type="submit" disabled={!newId.trim() || !newName.trim()}>
            {t("createCourse")}
          </Button>
          <Button type="button" onClick={() => setCreating(false)}>
            {t("cancel")}
          </Button>
          {createError && <span style={{ color: "#b91c1c", fontSize: 13, width: "100%" }}>{createError}</span>}
        </form>
      )}

      {courses === null && <p style={{ color: "#6b7280" }}>{t("loading")}</p>}
      {courses?.length === 0 && !creating && <p style={{ color: "#6b7280" }}>{t("noCourses")}</p>}

      <div style={{ display: "grid", gap: 16 }}>
        {courses?.map((c) => (
          <CourseCard key={c.course_id} course={c} exercises={exercises} students={students} onChanged={load} />
        ))}
      </div>

      <PasswordsSection users={users} onChanged={load} />
    </section>
  );
}

function CourseCard({
  course,
  exercises,
  students,
  onChanged,
}: {
  course: Course;
  exercises: ExerciseSummary[];
  students: UserAccount[];
  onChanged: () => void;
}) {
  const { t, lang } = useLang();
  const [draft, setDraft] = useState<Course>(course);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => setDraft(course), [course]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(course);
  const title = (ex: ExerciseSummary) => (lang === "he" ? ex.title_he ?? ex.title_en : ex.title_en);

  const toggleExercise = (id: string) =>
    setDraft((d) => {
      const on = d.exercises.includes(id);
      const list = on ? d.exercises.filter((x) => x !== id) : [...d.exercises, id];
      let def = d.default_exercise;
      if (on && def === id) def = list[0] ?? null;
      if (!on && !def) def = id;
      return { ...d, exercises: list, default_exercise: def };
    });

  const toggleMember = (id: number) =>
    setDraft((d) => ({
      ...d,
      members: d.members.includes(id) ? d.members.filter((m) => m !== id) : [...d.members, id],
    }));

  // Members (as saved) first, so they are visible without scrolling; ordered by
  // the saved course, not the draft, so rows don't jump while ticking boxes.
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const saved = new Set(course.members);
    return students
      .filter((s) => !q || s.username.toLowerCase().includes(q) || s.login_code.includes(q))
      .sort((a, b) => Number(saved.has(b.id)) - Number(saved.has(a.id)));
  }, [students, filter, course.members]);

  const setShown = (on: boolean) =>
    setDraft((d) => {
      const ids = new Set(d.members);
      shown.forEach((s) => (on ? ids.add(s.id) : ids.delete(s.id)));
      return { ...d, members: [...ids] };
    });

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.updateCourse(draft);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await api.deleteCourse(course.course_id);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  const offered = draft.exercises.length;
  const hint = offered === 0 ? t("courseHintNone") : offered === 1 ? t("courseHintOne") : t("courseHintMany");

  return (
    <div style={card}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
        <input
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          aria-label={t("courseName")}
          dir="auto"
          style={{ ...controlStyle, fontWeight: 600, fontSize: 15, width: 300 }}
        />
        <code style={{ fontSize: 12, color: "#6b7280" }}>{course.course_id}</code>
      </div>

      <div style={{ display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
        <div style={{ minWidth: 0 }}>
          <h4 style={h4}>{t("courseExercises")}</h4>
          <p style={{ color: "#6b7280", fontSize: 12, margin: "0 0 8px" }}>{hint}</p>
          <div style={{ display: "grid", gap: 4 }}>
            {exercises.map((ex) => {
              const on = draft.exercises.includes(ex.exercise_id);
              return (
                <div key={ex.exercise_id} style={row}>
                  <label style={{ display: "flex", gap: 8, alignItems: "center", flex: 1, minWidth: 0 }}>
                    <input type="checkbox" checked={on} onChange={() => toggleExercise(ex.exercise_id)} />
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{title(ex)}</span>
                    <code style={{ fontSize: 11, color: "#9ca3af" }}>{ex.exercise_id}</code>
                  </label>
                  <label style={{ fontSize: 12, color: on ? "#111827" : "#d1d5db", whiteSpace: "nowrap" }}>
                    <input
                      type="radio"
                      name={`default-${course.course_id}`}
                      disabled={!on}
                      checked={on && draft.default_exercise === ex.exercise_id}
                      onChange={() => setDraft({ ...draft, default_exercise: ex.exercise_id })}
                    />{" "}
                    {t("defaultExercise")}
                  </label>
                </div>
              );
            })}
          </div>
        </div>

        <div style={{ minWidth: 0 }}>
          <h4 style={h4}>{t("courseStudents", { n: draft.members.length })}</h4>
          <div style={{ display: "flex", gap: 6, marginBottom: 6, flexWrap: "wrap" }}>
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={t("searchStudents")}
              aria-label={t("searchStudents")}
              dir="auto"
              style={{ ...controlStyle, flex: 1, minWidth: 140 }}
            />
            <Button type="button" onClick={() => setShown(true)} style={{ padding: "6px 10px" }}>
              {t("selectShown")}
            </Button>
            <Button type="button" onClick={() => setShown(false)} style={{ padding: "6px 10px" }}>
              {t("clearShown")}
            </Button>
          </div>
          <div style={{ maxHeight: 240, overflowY: "auto", border: "1px solid #f3f4f6", borderRadius: 6 }}>
            {shown.map((s) => (
              <label key={s.id} style={{ ...row, cursor: "pointer" }}>
                <input type="checkbox" checked={draft.members.includes(s.id)} onChange={() => toggleMember(s.id)} />
                <span style={{ flex: 1 }}>{s.username}</span>
                <code style={{ fontSize: 11, color: "#6b7280" }} dir="ltr">
                  {s.login_code}
                </code>
                {s.courses
                  .filter((c) => c !== course.course_id)
                  .map((c) => (
                    <span key={c} style={chip}>
                      {c}
                    </span>
                  ))}
              </label>
            ))}
            {shown.length === 0 && <p style={{ color: "#9ca3af", fontSize: 13, padding: 8, margin: 0 }}>{t("noStudentsFound")}</p>}
          </div>
        </div>
      </div>

      {error && <p style={{ color: "#b91c1c", fontSize: 13 }}>{error}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <Button variant="primary" disabled={!dirty || busy} onClick={save}>
          {busy ? t("saving") : t("saveCourse")}
        </Button>
        <Button disabled={!dirty || busy} onClick={() => setDraft(course)}>
          {t("revert")}
        </Button>
        <span style={{ flex: 1 }} />
        {confirmDelete ? (
          <>
            <span style={{ fontSize: 13, alignSelf: "center" }}>{t("deleteCourseConfirm")}</span>
            <Button variant="danger" disabled={busy} onClick={remove}>
              {t("deleteCourseYes")}
            </Button>
            <Button onClick={() => setConfirmDelete(false)}>{t("cancel")}</Button>
          </>
        ) : (
          <Button onClick={() => setConfirmDelete(true)}>{t("deleteCourse")}</Button>
        )}
      </div>
    </div>
  );
}

function PasswordsSection({ users, onChanged }: { users: UserAccount[]; onChanged: () => void }) {
  const { t } = useLang();
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const shown = users.filter((u) => {
    const q = filter.trim().toLowerCase();
    return !q || u.username.toLowerCase().includes(q) || u.login_code.includes(q);
  });

  const apply = async (id: number, password: string | null) => {
    setBusy(true);
    setError(null);
    try {
      await api.setPassword(id, password);
      setEditing(null);
      setValue("");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: 32 }}>
      <h2 style={{ margin: "0 0 4px" }}>{t("passwordsTitle")}</h2>
      <p style={{ color: "#6b7280", fontSize: 13, marginTop: 0, maxWidth: 760 }}>{t("passwordsIntro")}</p>
      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder={t("searchStudents")}
        aria-label={t("searchStudents")}
        dir="auto"
        style={{ ...controlStyle, width: 260, marginBottom: 8 }}
      />
      {error && <p style={{ color: "#b91c1c", fontSize: 13 }}>{error}</p>}
      <div style={{ ...card, padding: 0, overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f9fafb", textAlign: "start" }}>
              <th style={th}>{t("colName")}</th>
              <th style={th}>{t("colUsername")}</th>
              <th style={th}>{t("colRole")}</th>
              <th style={th}>{t("colPassword")}</th>
              <th style={th} />
            </tr>
          </thead>
          <tbody>
            {shown.map((u) => (
              <tr key={u.id} style={{ borderTop: "1px solid #f3f4f6" }}>
                <td style={td}>{u.username}</td>
                <td style={td}>
                  <code dir="ltr">{u.login_code}</code>
                </td>
                <td style={td}>{u.role === "teacher" ? t("roleTeacher") : t("roleStudent")}</td>
                <td style={td}>
                  {u.custom_password ? (
                    <span style={{ ...chip, background: "#dcfce7", color: "#166534" }}>{t("passwordCustom")}</span>
                  ) : (
                    <span style={{ ...chip, background: "#fef3c7", color: "#92400e" }}>{t("passwordDefault")}</span>
                  )}
                </td>
                <td style={{ ...td, whiteSpace: "nowrap" }}>
                  {editing === u.id ? (
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        apply(u.id, value);
                      }}
                      style={{ display: "inline-flex", gap: 6 }}
                    >
                      <input
                        autoFocus
                        type="password"
                        value={value}
                        onChange={(e) => setValue(e.target.value)}
                        placeholder={t("newPassword")}
                        aria-label={t("newPassword")}
                        autoComplete="new-password"
                        style={{ ...controlStyle, width: 160 }}
                      />
                      <Button variant="primary" type="submit" disabled={busy || !value} style={{ padding: "4px 10px" }}>
                        {t("setPassword")}
                      </Button>
                      <Button type="button" onClick={() => setEditing(null)} style={{ padding: "4px 10px" }}>
                        {t("cancel")}
                      </Button>
                    </form>
                  ) : (
                    <span style={{ display: "inline-flex", gap: 6 }}>
                      <Button
                        onClick={() => {
                          setEditing(u.id);
                          setValue("");
                          setError(null);
                        }}
                        style={{ padding: "4px 10px" }}
                      >
                        {t("changePassword")}
                      </Button>
                      {u.custom_password && (
                        <Button disabled={busy} onClick={() => apply(u.id, null)} style={{ padding: "4px 10px" }}>
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
    </div>
  );
}

const card: React.CSSProperties = {
  border: "1px solid #e5e7eb",
  borderRadius: 10,
  padding: 16,
  background: "white",
  boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
  marginBottom: 12,
};
const row: React.CSSProperties = { display: "flex", gap: 8, alignItems: "center", padding: "4px 6px", fontSize: 13 };
const h4: React.CSSProperties = { margin: "0 0 4px", fontSize: 14 };
const chip: React.CSSProperties = {
  fontSize: 11,
  padding: "1px 6px",
  borderRadius: 999,
  background: "#f3f4f6",
  color: "#374151",
};
const th: React.CSSProperties = { padding: "8px 10px", fontWeight: 600, textAlign: "start" };
const td: React.CSSProperties = { padding: "6px 10px", verticalAlign: "middle" };
