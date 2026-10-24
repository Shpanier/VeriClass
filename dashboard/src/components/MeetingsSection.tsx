import { useEffect, useState } from "react";
import { api } from "../api";
import type { Attendance, ExerciseSummary, Meeting } from "../types";
import { useLang } from "../i18n";
import { Modal } from "./ui/Modal";
import { Button } from "./ui/Button";
import { controlStyle } from "./ui/Field";

const today = () => new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD, local

// A course's meetings (backend/courses.py): on a meeting's date the course's
// students open its exercise without choosing; attendance comes from the
// sessions of that day.
export function MeetingsSection({ courseId, exercises, onChanged }: {
  courseId: string;
  exercises: ExerciseSummary[];
  onChanged: () => void;
}) {
  const { t, lang } = useLang();
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [date, setDate] = useState(today());
  const [exerciseId, setExerciseId] = useState(exercises[0]?.exercise_id ?? "");
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [attendance, setAttendance] = useState<Attendance | null>(null);

  const load = () => api.meetings(courseId).then(setMeetings).catch(console.error);
  useEffect(() => { load(); }, [courseId]);

  const add = async () => {
    setError(null);
    try {
      await api.addMeeting(courseId, date, exerciseId, title.trim());
      setTitle("");
      await load();
      onChanged(); // the course may now offer the exercise
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const remove = async (id: number) => {
    try {
      await api.deleteMeeting(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const exTitle = (id: string) => {
    const ex = exercises.find((e) => e.exercise_id === id);
    return ex ? (lang === "he" ? ex.title_he ?? ex.title_en : ex.title_en) : id;
  };

  return (
    <div style={{ marginTop: 16 }}>
      <h4 style={{ margin: "0 0 4px", fontSize: 14 }}>{t("meetingsTitle")}</h4>
      <p style={{ color: "#6b7280", fontSize: 12, margin: "0 0 8px" }}>{t("meetingsHint")}</p>
      {meetings.length === 0 && <p style={{ color: "#9ca3af", fontSize: 13, margin: "0 0 8px" }}>{t("noMeetings")}</p>}
      {meetings.map((m) => (
        <div key={m.id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, padding: "3px 0", flexWrap: "wrap" }}>
          <code dir="ltr">{m.meeting_date}</code>
          {m.meeting_date === today() && (
            <span style={{ fontSize: 11, background: "#dcfce7", color: "#166534", padding: "1px 6px", borderRadius: 999 }}>
              {t("todayLabel")}
            </span>
          )}
          <span style={{ flex: 1, minWidth: 0 }} dir="auto">
            {m.title ? `${m.title} · ` : ""}{exTitle(m.exercise_id)}
          </span>
          <Button style={{ padding: "3px 8px" }} onClick={() => api.attendance(m.id).then(setAttendance).catch(console.error)}>
            {t("attendanceBtn", { a: m.attended, m: m.members })}
          </Button>
          <Button style={{ padding: "3px 8px" }} onClick={() => remove(m.id)}>{t("deleteMeeting")}</Button>
        </div>
      ))}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 6 }}>
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} style={{ ...controlStyle, width: 150 }} />
        <select value={exerciseId} onChange={(e) => setExerciseId(e.target.value)} style={{ ...controlStyle, width: 240 }}>
          {exercises.map((ex) => (
            <option key={ex.exercise_id} value={ex.exercise_id}>{exTitle(ex.exercise_id)}</option>
          ))}
        </select>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("meetingTitlePlaceholder")}
               dir="auto" style={{ ...controlStyle, width: 180 }} />
        <Button disabled={!date || !exerciseId} onClick={add}>{t("addMeeting")}</Button>
      </div>
      {error && <p style={{ color: "#b91c1c", fontSize: 13 }}>{error}</p>}

      {attendance && (
        <Modal onClose={() => setAttendance(null)} width={760}>
          <h3 style={{ marginTop: 0 }}>
            {t("attendanceTitle", { d: attendance.meeting.meeting_date })}
            <span style={{ color: "#6b7280", fontWeight: 400, fontSize: 14 }}>
              {" "}· {attendance.counts.attended}/{attendance.counts.members}
            </span>
          </h3>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f9fafb" }}>
                <th style={th}>{t("colName")}</th>
                <th style={th} />
                <th style={th}>{t("firstSeen")}</th>
                <th style={th}>{t("colMessages")}</th>
                <th style={th}>{t("colStepsApproved")}</th>
              </tr>
            </thead>
            <tbody>
              {attendance.rows.map((r) => (
                <tr key={r.user_id} style={{ borderTop: "1px solid #f3f4f6" }}>
                  <td style={td} dir="auto">{r.username}{r.group ? ` · ${r.group}` : ""}</td>
                  <td style={{ ...td, color: r.attended ? "#166534" : "#b91c1c", fontWeight: 600 }}>
                    {r.attended ? t("attendedYes") : t("attendedNo")}
                  </td>
                  <td style={td} dir="ltr">{r.first_seen ?? ""}</td>
                  <td style={td}>{r.messages}</td>
                  <td style={td}>{r.steps_approved}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
            <Button onClick={() => setAttendance(null)}>{t("close")}</Button>
          </div>
        </Modal>
      )}
    </div>
  );
}

const th: React.CSSProperties = { padding: "6px 8px", textAlign: "start", fontWeight: 600 };
const td: React.CSSProperties = { padding: "4px 8px" };
