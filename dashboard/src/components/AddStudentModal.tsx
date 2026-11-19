import { useRef, useState, type FormEvent } from "react";
import { UserPlus } from "lucide-react";
import { api } from "../api";
import type { AddedStudent, Course } from "../types";
import { useLang } from "../i18n";
import { describeError } from "../lib/errors";
import { Button, CopyButton, FormField, Input, Modal, Notice, Select, Switch } from "./ui";
import { MaskedUsername } from "./ImportStudentsModal";
import "../styles/courses.css";
import { textDir } from "../lib/textDir";

/** One student added by hand (POST /api/students): a late joiner after the
 *  class list was imported. Shows the username and password to hand them. */
export function AddStudentModal({ courses, courseId: initialCourse, onClose, onAdded }: {
  courses: Course[];
  /** The course it was opened from (preselected). */
  courseId?: string | null;
  onClose: () => void;
  onAdded: () => void;
}) {
  const { t } = useLang();
  const [name, setName] = useState("");
  const [studentId, setStudentId] = useState("");
  const [email, setEmail] = useState("");
  const [group, setGroup] = useState("");
  const [courseId, setCourseId] = useState<string>(
    initialCourse ?? (courses.length === 1 ? courses[0].course_id : ""));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<AddedStudent | null>(null);
  const [show, setShow] = useState(false);
  const nameInput = useRef<HTMLInputElement>(null);

  const course = courses.find((c) => c.course_id === (added?.course ?? courseId));
  const dirty = !added && !!(name || studentId || email || group);

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const row = await api.addStudent({
        name: name.trim(), student_id: studentId.trim() || null, email: email.trim() || null,
        group: group.trim() || null, course_id: courseId || null,
      });
      setAdded(row);
      setShow(false);
      onAdded();
    } catch (err) {
      setError(describeError(err, t));
    } finally {
      setBusy(false);
    }
  };

  const another = () => {
    setAdded(null);
    setName("");
    setStudentId("");
    setEmail("");
    setGroup("");
    setError(null);
    window.setTimeout(() => nameInput.current?.focus(), 0);
  };

  const who = added ? added.username ?? added.name : "";
  const doneText = !added ? "" : added.status === "new"
    ? (course ? t("coAddDoneNewCourse", { name: who, course: course.name }) : t("coAddDoneNew", { name: who }))
    : (course ? t("coAddDoneExistingCourse", { name: who, course: course.name }) : t("coAddDoneExisting", { name: who }));
  const signIn = added?.code
    ? `${t("colUsername")}: ${added.code}\n${t("coAddPassword")}: ${added.password_set ? t("coAddPasswordSet") : added.code}`
    : "";

  const footer = added ? (
    <>
      <span className="u-push" />
      <Button onClick={onClose}>{t("close")}</Button>
      <Button variant="primary" icon={<UserPlus />} onClick={another}>{t("coAddAnother")}</Button>
    </>
  ) : (
    <>
      <span className="u-push" />
      <Button onClick={onClose}>{t("cancel")}</Button>
      <Button variant="primary" icon={<UserPlus />} busy={busy} disabled={!name.trim()} onClick={() => submit()}>
        {t("coAddDo")}
      </Button>
    </>
  );

  return (
    <Modal title={t("coAddTitle")} subtitle={t("coAddSub")} size="md" onClose={onClose} footer={footer} dirty={dirty}>
      {added ? (
        <div className="vc-courses-added">
          <Notice tone="success" title={doneText} className="u-mb-12">
            {added.status === "new" ? t("coAddHandOut") : t("coAddExistingNote")}
          </Notice>
          {added.code && (
            <>
              <div className="u-row u-mb-8">
                <Switch checked={show} onChange={setShow}>{t("coShowUsernames")}</Switch>
              </div>
              <dl className="vc-courses-signin">
                <dt>{t("colUsername")}</dt>
                <dd><MaskedUsername code={added.code} show={show} /></dd>
                <dt>{t("coAddPassword")}</dt>
                <dd>
                  {added.password_set
                    ? <span className="u-soft">{t("coAddPasswordSet")}</span>
                    : <><MaskedUsername code={added.code} show={show} /> <span className="u-muted u-xs">{t("coAddPasswordSame")}</span></>}
                </dd>
              </dl>
              <CopyButton size="sm" text={signIn}>{t("coAddCopy")}</CopyButton>
            </>
          )}
        </div>
      ) : (
        <form onSubmit={submit} className="vc-courses-addform">
          {error && <Notice tone="danger" title={t("coAddFailed")} className="u-mb-12">{error}</Notice>}
          <FormField label={t("coAddName")} required>
            <Input ref={nameInput} autoFocus value={name} maxLength={100} dir={textDir(name)}
                   onChange={(e) => setName(e.target.value)} />
          </FormField>
          <div className="vc-courses-addform__pair">
            <FormField label={t("coAddId")}>
              <Input value={studentId} maxLength={30} inputMode="numeric" dir="ltr"
                     onChange={(e) => setStudentId(e.target.value)} />
            </FormField>
            <FormField label={t("coAddEmail")}>
              <Input type="email" value={email} maxLength={200} dir="ltr" onChange={(e) => setEmail(e.target.value)} />
            </FormField>
          </div>
          <p className="vc-hint">{t("coAddIdHint")}</p>
          <div className="vc-courses-addform__pair">
            <FormField label={t("coAddCourse")}>
              <Select value={courseId} onChange={(e) => setCourseId(e.target.value)}>
                <option value="">{t("importNoCourse")}</option>
                {courses.map((c) => (
                  <option key={c.course_id} value={c.course_id}>{c.name} ({c.course_id})</option>
                ))}
              </Select>
            </FormField>
            <FormField label={t("coAddGroup")}>
              <Input value={group} maxLength={60} dir={textDir(group)} onChange={(e) => setGroup(e.target.value)} />
            </FormField>
          </div>
          {/* Enter in any field adds the student. */}
          <button type="submit" hidden aria-hidden="true" tabIndex={-1} />
        </form>
      )}
    </Modal>
  );
}
