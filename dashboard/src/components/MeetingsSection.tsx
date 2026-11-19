import { useEffect, useId, useState } from "react";
import { CalendarDays, CalendarPlus, RefreshCw, Trash2, UserCheck } from "lucide-react";
import { api } from "../api";
import type { Attendance, ExerciseSummary, Lang, Meeting } from "../types";
import { useLang } from "../i18n";
import { describeError } from "../lib/errors";
import { sortExercises, useExerciseSort } from "../lib/exerciseOrder";
import { Button, FormField, Input, Modal, Notice, Select, Spinner, Time, useConfirm, useToast } from "./ui";
import { textDir } from "../lib/textDir";

// YYYY-MM-DD, local. Not toLocaleDateString: it builds an Intl formatter on every
// call, and this runs on every render of every course card.
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// One formatter per language, made once.
const dayFormats = new Map<Lang, Intl.DateTimeFormat>();

/** "Fri, 13 Nov 2026" for a YYYY-MM-DD date, in the dashboard's language. */
function formatDay(iso: string, lang: Lang): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  let f = dayFormats.get(lang);
  if (!f) {
    f = new Intl.DateTimeFormat(lang === "he" ? "he-IL" : "en-GB",
                                { weekday: "short", day: "numeric", month: "short", year: "numeric" });
    dayFormats.set(lang, f);
  }
  return f.format(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
}

// A course's meetings (backend/courses.py): on a meeting's date the course's
// students open its exercise without choosing; attendance comes from the
// sessions of that day. Unlike the rest of the course card, a meeting is saved
// as soon as it is added or deleted.
export function MeetingsSection({ courseId, exercises, onChanged }: {
  courseId: string;
  exercises: ExerciseSummary[];
  onChanged: () => void;
}) {
  const { t, lang } = useLang();
  const toast = useToast();
  const confirm = useConfirm();
  const headId = useId();
  // The exercises in the order chosen in the Exercises tab; the first is preselected.
  const [exSort] = useExerciseSort();
  const ordered = sortExercises(exercises, exSort, lang);
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [date, setDate] = useState(today);
  const [exerciseId, setExerciseId] = useState(ordered[0]?.exercise_id ?? "");
  const [title, setTitle] = useState("");
  const [adding, setAdding] = useState(false);
  const [opening, setOpening] = useState<number | null>(null);
  const [attendance, setAttendance] = useState<Attendance | null>(null);

  const load = () =>
    api.meetings(courseId)
      .then((m) => { setMeetings(m); setLoadError(null); })
      .catch((e) => setLoadError(describeError(e, t)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [courseId]);

  const add = async () => {
    setAdding(true);
    try {
      await api.addMeeting(courseId, date, exerciseId, title.trim());
      setTitle("");
      await load();
      onChanged(); // the course may now offer the exercise
    } catch (e) {
      toast.error(t("coMeetingAddFailed"), e);
    } finally {
      setAdding(false);
    }
  };

  const remove = async (m: Meeting) => {
    const day = formatDay(m.meeting_date, lang);
    if (!(await confirm({
      title: t("coMeetingDeleteTitle", { date: day }), body: t("coMeetingDeleteBody"),
      confirmLabel: t("coMeetingDeleteYes"), danger: true,
    }))) return;
    try {
      await api.deleteMeeting(m.id);
      await load();
    } catch (e) {
      toast.error(t("coMeetingDeleteFailed"), e);
    }
  };

  const openAttendance = async (id: number) => {
    setOpening(id);
    try {
      setAttendance(await api.attendance(id));
    } catch (e) {
      toast.error(t("coAttendanceFailed"), e);
    } finally {
      setOpening(null);
    }
  };

  const now = today();
  const titleOf = (ex: ExerciseSummary) => (lang === "he" && ex.title_he) || ex.title_en;
  // Titles that more than one exercise has: those also show the exercise's id.
  const seen = new Map<string, number>();
  exercises.forEach((ex) => seen.set(titleOf(ex), (seen.get(titleOf(ex)) ?? 0) + 1));
  const repeated = (ex: ExerciseSummary) => (seen.get(titleOf(ex)) ?? 0) > 1;
  const exerciseName = (id: string, fallback?: string | null) => {
    const ex = exercises.find((e) => e.exercise_id === id);
    return { name: ex ? titleOf(ex) : fallback ?? id, showId: !ex || repeated(ex) };
  };

  return (
    <section className="vc-courses-meetings" aria-labelledby={headId}>
      <div className="u-row u-wrap u-gap-8">
        <h3 id={headId} className="vc-courses-sub">
          <CalendarDays /> {t("meetingsTitle")}
          {meetings && <span className="vc-badge vc-badge--count">{meetings.length}</span>}
        </h3>
        <span className="vc-badge vc-badge--info">{t("coMeetingsSavedBadge")}</span>
      </div>
      <p className="vc-hint u-mb-8">{t("meetingsHint")} {t("coMeetingsSaved")}</p>

      {loadError && (
        <Notice tone="danger" className="u-mb-8"
                action={<Button size="sm" icon={<RefreshCw />} onClick={load}>{t("retry")}</Button>}>
          {t("coMeetingsLoadFailed")} {loadError}
        </Notice>
      )}
      {meetings === null && !loadError && <div className="u-row u-muted u-sm"><Spinner /> {t("loading")}</div>}
      {meetings?.length === 0 && <p className="u-muted u-sm">{t("noMeetings")}</p>}
      {meetings && meetings.length > 0 && (
        <div className="vc-courses-meetings__list">
          {meetings.map((m) => {
            const day = formatDay(m.meeting_date, lang);
            const ex = exerciseName(m.exercise_id, m.exercise_title);
            return (
              <div key={m.id} className="vc-courses-meeting" data-past={m.meeting_date < now}>
                <span className="vc-courses-meeting__date">
                  <span>{day}</span>
                  {m.meeting_date === now && <span className="vc-badge vc-badge--success">{t("todayLabel")}</span>}
                </span>
                <span className="vc-courses-meeting__what">
                  {m.title && <><span className="u-bold" dir={textDir(m.title)}>{m.title}</span><span className="u-muted"> · </span></>}
                  <span dir={textDir(ex.name)}>{ex.name}</span>
                  {ex.showId && <> <span className="u-muted u-xs vc-mono" dir="ltr">({m.exercise_id})</span></>}
                </span>
                <Button size="sm" icon={<UserCheck />} busy={opening === m.id} onClick={() => openAttendance(m.id)}>
                  {t("attendanceBtn", { a: m.attended, m: m.members })}
                </Button>
                <Button
                  size="sm" variant="quiet" iconOnly icon={<Trash2 />} onClick={() => remove(m)}
                  aria-label={t("coMeetingDeleteAria", { date: day })} title={t("coMeetingDeleteAria", { date: day })}
                />
              </div>
            );
          })}
        </div>
      )}

      <div className="vc-courses-meeting-add">
        <FormField label={t("coMeetingDate")}>
          <Input type="date" dir="ltr" value={date} onChange={(e) => setDate(e.target.value)} />
        </FormField>
        <FormField label={t("coMeetingExercise")}>
          <Select value={exerciseId} onChange={(e) => setExerciseId(e.target.value)}>
            {ordered.map((ex) => (
              <option key={ex.exercise_id} value={ex.exercise_id}>
                {repeated(ex) ? `${titleOf(ex)} (${ex.exercise_id})` : titleOf(ex)}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label={t("coMeetingTitle")}>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("coMeetingTitlePh")} />
        </FormField>
        <Button icon={<CalendarPlus />} busy={adding} disabled={!date || !exerciseId} onClick={add}>{t("addMeeting")}</Button>
      </div>

      {attendance && (
        <Modal
          size="lg" onClose={() => setAttendance(null)}
          title={t("attendanceTitle", { d: formatDay(attendance.meeting.meeting_date, lang) })}
          subtitle={t("coAttendanceSub", {
            a: attendance.counts.attended, m: attendance.counts.members,
            exercise: exerciseName(attendance.meeting.exercise_id, attendance.meeting.exercise_title).name,
          })}
          footer={<><span className="u-push" /><Button onClick={() => setAttendance(null)}>{t("close")}</Button></>}
        >
          {attendance.rows.length === 0 ? (
            <p className="u-muted">{t("coAttendanceEmpty")}</p>
          ) : (
            <div className="vc-table-wrap">
              <table className="vc-table">
                <thead>
                  <tr>
                    <th scope="col">{t("colName")}</th>
                    <th scope="col">{t("coColAttended")}</th>
                    <th scope="col">{t("firstSeen")}</th>
                    <th scope="col">{t("colMessages")}</th>
                    <th scope="col">{t("colStepsApproved")}</th>
                  </tr>
                </thead>
                <tbody>
                  {attendance.rows.map((r) => (
                    <tr key={r.user_id}>
                      <td>
                        <span dir={textDir(r.username)}>{r.username}</span>
                        {r.group && <span className="u-muted"> · <span dir={textDir(r.group)}>{r.group}</span></span>}
                      </td>
                      <td>
                        {r.attended
                          ? <span className="vc-badge vc-badge--success">{t("attendedYes")}</span>
                          : <span className="vc-badge">{t("attendedNo")}</span>}
                      </td>
                      <td>{r.first_seen ? <Time value={r.first_seen} mode="full" /> : <span className="u-muted">–</span>}</td>
                      <td>{r.messages}</td>
                      <td>{r.steps_approved}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Modal>
      )}
    </section>
  );
}
