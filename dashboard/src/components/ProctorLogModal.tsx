import { useEffect, useState } from "react";
import { AppWindow, Ban, Circle, ClipboardPaste, MonitorCheck, MonitorX, Video } from "lucide-react";
import { api } from "../api";
import type { Paste, ProctorEvent, Student } from "../types";
import { arrivedLate, eventTime, isIdeAlertKind, isLeaveKind, isTerminalAlertKind } from "../proctor";
import { useLang, type StringKey } from "../i18n";
import { formatDateTime, parseServerTime } from "../lib/time";
import { Button, EmptyState, Loading, Modal, Notice, Time } from "./ui";
import { awayText, examKindLabel, ExamStatePill } from "./StudentGrid";

/**
 * One student's exam log (IDE plugin), newest first: leaving and returning to
 * the IDE, panels and windows that aren't allowed (with how they were opened),
 * editor tabs, and pastes with the pasted text. Polls every 2s like the chat viewer.
 */
export function ProctorLogModal({ student, onClose }: { student: Student; onClose: () => void }) {
  const { t } = useLang();
  const [events, setEvents] = useState<ProctorEvent[] | null>(null);
  const [pastes, setPastes] = useState<Paste[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    // A background poll: a failure stays quiet (the page reports a lost
    // server); only a log that never arrived says so, below.
    const tick = () => {
      api.proctorEvents(student.session_id)
        .then((list) => { if (alive) { setEvents(list); setFailed(false); } })
        .catch(() => { if (alive) setFailed(true); });
      api.pastes(student.session_id)
        .then((list) => { if (alive) setPastes(list); })
        .catch(() => { /* the events above say whether the server answers */ });
    };
    tick();
    const id = window.setInterval(tick, 2000);
    return () => { alive = false; window.clearInterval(id); };
  }, [student.session_id]);

  const leaves = (events ?? []).filter((e) => isLeaveKind(e.kind)).length;
  const state = student.exam_state && student.exam_state !== "ok" ? student.exam_state : null;

  return (
    <Modal
      onClose={onClose}
      title={<><bdi>{student.username}</bdi> · {t("proctorLog")}</>}
      subtitle={(events || state) && (
        <span className="u-row u-wrap u-gap-8">
          {events && <span>{t("leaveEventsRecorded", { n: leaves })}</span>}
          {state && <ExamStatePill state={state} detail={student.exam_state_detail} flash />}
        </span>
      )}
      footer={<><span className="u-push" /><Button onClick={onClose}>{t("close")}</Button></>}
    >
      {events === null ? (
        failed ? <Notice tone="danger">{t("plLoadFailed")}</Notice> : <Loading />
      ) : events.length === 0 ? (
        <EmptyState icon={<Video />} title={t("plEmptyTitle")}>{t("noProctorEvents")}</EmptyState>
      ) : (
        <>
          <div className="vc-students-list__title">{t("plEventsTitle")}</div>
          <div className="vc-students-list">
            {events.map((e) => <EventRow key={e.id} e={e} />)}
          </div>
        </>
      )}

      <details className="vc-students-details" open={!!pastes?.some((p) => p.source === "outside")}>
        <summary><ClipboardPaste aria-hidden="true" />{t("pastesTitle", { n: pastes?.length ?? 0 })}</summary>
        {pastes === null ? (
          <Loading />
        ) : pastes.length === 0 ? (
          <p className="u-muted u-sm">{t("noPastes")}</p>
        ) : (
          <div className="vc-students-list">
            {pastes.map((p) => <PasteRow key={p.id} p={p} />)}
          </div>
        )}
      </details>
    </Modal>
  );
}

const RETURN_KINDS = new Set(["focus_regained", "window_restored", "fullscreen_restored", "other_window_closed"]);

function EventRow({ e }: { e: ProctorEvent }) {
  const { t, lang } = useLang();
  const terminal = isTerminalAlertKind(e.kind);
  const ide = isIdeAlertKind(e.kind);
  // Terminal and in-IDE violations get the same red treatment as leaving the IDE.
  const leave = isLeaveKind(e.kind) || terminal || ide;
  const icon = terminal ? <Ban className="vc-students-row__icon u-danger" aria-hidden="true" />
    : e.kind === "paste_external" ? <ClipboardPaste className="vc-students-row__icon u-danger" aria-hidden="true" />
      : ide ? <AppWindow className="vc-students-row__icon u-warning" aria-hidden="true" />
        : leave ? <MonitorX className="vc-students-row__icon u-danger" aria-hidden="true" />
          : RETURN_KINDS.has(e.kind) ? <MonitorCheck className="vc-students-row__icon u-success" aria-hidden="true" />
            : <Circle className="vc-students-row__icon u-muted" aria-hidden="true" />;
  const received = parseServerTime(e.created_at);
  return (
    <div className={leave ? "vc-students-row vc-students-row--alert" : "vc-students-row"}>
      <div className="vc-students-row__line">
        {icon}
        <div className="vc-students-row__body">
          <div className="vc-students-row__title">
            {examKindLabel(e.kind, t)}
            {e.away_ms != null && (
              <span className="u-normal u-soft"> · {t("awayFor", { d: awayText(e.away_ms, t) })}</span>
            )}
          </div>
          {e.detail && (
            <div className={terminal ? "vc-students-row__detail vc-mono" : "vc-students-row__detail"} dir={terminal ? "ltr" : "auto"}>
              {e.detail}
            </div>
          )}
        </div>
        <div className="vc-students-row__when">
          <Time value={eventTime(e)} mode="clock" />
          {arrivedLate(e) && (
            <span className="u-warning" title={received ? t("plArrivedAt", { time: formatDateTime(received, lang) }) : undefined}>
              {t("arrivedLate")}
            </span>
          )}
          {e.via === "export" && <span className="u-brand">{t("fromExport")}</span>}
        </div>
      </div>
    </div>
  );
}

function PasteRow({ p }: { p: Paste }) {
  const { t } = useLang();
  const outside = p.source === "outside";
  return (
    <div className={outside ? "vc-students-row vc-students-row--alert" : "vc-students-row"}>
      <div className="vc-students-row__line">
        <div className="vc-students-row__body">
          <div className="vc-students-row__title">
            {t(`pasteFrom_${p.source}` as StringKey)} · {t(`pasteInto_${p.target}` as StringKey)}
          </div>
          <div className="vc-students-row__detail u-row u-wrap u-gap-8">
            {p.file && <code dir="ltr">{p.file}</code>}
            <span>{t("pasteSize", { chars: p.chars, lines: p.lines })}</span>
          </div>
        </div>
        <div className="vc-students-row__when">
          <Time value={eventTime(p)} mode="clock" />
          {p.via === "export" && <span className="u-brand">{t("fromExport")}</span>}
        </div>
      </div>
      <pre className="vc-pre" dir="ltr">{p.text}</pre>
    </div>
  );
}
