import { useEffect, useState, type ReactNode } from "react";
import { Ban, Check as CheckIcon, SquareTerminal, TriangleAlert, X } from "lucide-react";
import { api } from "../api";
import type { Student, TerminalCommand, TerminalFullOutput } from "../types";
import { arrivedLate, eventTime } from "../proctor";
import { useLang } from "../i18n";
import { formatDateTime, parseServerTime } from "../lib/time";
import { Button, Check, EmptyState, Loading, Modal, Notice, Time, useToast } from "./ui";

/**
 * One student's VeriClass-terminal log (IDE plugin): every line they entered,
 * newest first: what ran (exit code, output) and what the plugin refused (and
 * why). Polls every 2s like the other live viewers. "Only refused commands"
 * narrows the list to the alerts.
 */
export function TerminalLogModal({ student, onClose }: { student: Student; onClose: () => void }) {
  const { t } = useLang();
  const [rows, setRows] = useState<TerminalCommand[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [refusedOnly, setRefusedOnly] = useState(false);

  useEffect(() => {
    let alive = true;
    // A background poll: a failure stays quiet (the page reports a lost
    // server); only a log that never arrived says so, below.
    const tick = () => api.terminalCommands(student.session_id)
      .then((list) => { if (alive) { setRows(list); setFailed(false); } })
      .catch(() => { if (alive) setFailed(true); });
    tick();
    const id = window.setInterval(tick, 2000);
    return () => { alive = false; window.clearInterval(id); };
  }, [student.session_id]);

  const all = rows ?? [];
  const refused = all.filter((r) => !r.allowed && !r.syntax_error);
  const shown = refusedOnly ? refused : all;

  return (
    <Modal
      size="lg"
      onClose={onClose}
      title={<><bdi>{student.username}</bdi> · {t("terminalLog")}</>}
      subtitle={rows ? t("terminalSummary", { n: all.length, refused: refused.length }) : undefined}
      footer={<><span className="u-push" /><Button onClick={onClose}>{t("close")}</Button></>}
    >
      {rows === null ? (
        failed ? <Notice tone="danger">{t("tlLoadFailed")}</Notice> : <Loading />
      ) : rows.length === 0 ? (
        <EmptyState icon={<SquareTerminal />} title={t("noTerminalCommands")}>{t("tlEmptyText")}</EmptyState>
      ) : (
        <>
          <div className="u-mb-12">
            <Check checked={refusedOnly} onChange={setRefusedOnly}>{t("terminalRefusedOnly")}</Check>
          </div>
          {shown.length === 0 ? (
            <p className="u-muted u-sm">{t("tlNoRefused")}</p>
          ) : (
            <div className="vc-students-list">
              {shown.map((r) => <CommandRow key={r.id} r={r} />)}
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

function CommandRow({ r }: { r: TerminalCommand }) {
  const { t, lang } = useLang();
  const toast = useToast();
  const [full, setFull] = useState<TerminalFullOutput | null>(null);
  const [loading, setLoading] = useState(false);
  const loadFull = () => {
    setLoading(true);
    api.terminalOutput(r.id)
      .then(setFull)
      .catch((e) => toast.error(t("tlOutputFailed"), e))
      .finally(() => setLoading(false));
  };
  // Only the tail is in the row; the rest came in pieces.
  const hasMore = (r.output_chunks ?? 0) > 0 && (r.output_chars ?? 0) > (r.output_tail?.length ?? 0);
  const blocked = !r.allowed && !r.syntax_error;
  const failedRun = r.allowed && r.exit_code != null && r.exit_code !== 0;
  const status: { tone: "danger" | "warning" | "success"; icon: ReactNode; text: string } = blocked
    ? { tone: "danger", icon: <Ban aria-hidden="true" />, text: t("terminalRefused") }
    : r.syntax_error
      ? { tone: "warning", icon: <TriangleAlert aria-hidden="true" />, text: t("terminalSyntax") }
      : failedRun
        ? { tone: "warning", icon: <X aria-hidden="true" />, text: t("terminalExit", { n: r.exit_code ?? "" }) }
        : { tone: "success", icon: <CheckIcon aria-hidden="true" />, text: t("terminalExit", { n: r.exit_code ?? 0 }) };
  const received = parseServerTime(r.created_at);

  return (
    <div className={blocked ? "vc-students-row vc-students-row--alert" : "vc-students-row"}>
      <div className="vc-students-row__line">
        <span className={`vc-badge vc-badge--${status.tone}`}>{status.icon}{status.text}</span>
        <code className="vc-students-cmd" dir="ltr">
          <span className="vc-students-cmd__prompt">{r.cwd ? `${r.cwd}$ ` : "$ "}</span>
          {r.line}
        </code>
        <div className="vc-students-row__when">
          <span>
            {r.duration_ms != null && r.allowed && <>{t("tlDuration", { s: (r.duration_ms / 1000).toFixed(1) })} · </>}
            <Time value={eventTime(r)} mode="clock" />
          </span>
          {arrivedLate(r) && (
            <span className="u-warning" title={received ? t("plArrivedAt", { time: formatDateTime(received, lang) }) : undefined}>
              {t("arrivedLate")}
            </span>
          )}
          {r.via === "export" && <span className="u-brand">{t("fromExport")}</span>}
          {r.client_os && <span title={r.shell ?? undefined}>{r.client_os.split(" ")[0]}</span>}
        </div>
      </div>
      {r.reason && (
        <div className={`vc-students-row__detail ${status.tone === "danger" ? "u-danger" : status.tone === "warning" ? "u-warning" : ""}`}
             dir="ltr">
          {r.reason}
        </div>
      )}
      {r.output_tail && (
        <details>
          <summary>{t("terminalOutput")}</summary>
          <pre className="vc-pre" dir="ltr">{full ? full.output : r.output_tail}</pre>
          {hasMore && !full && (
            <Button variant="link" size="sm" className="u-mt-4" busy={loading} onClick={loadFull}>
              {loading ? t("loading") : t("showFullOutput", { n: r.output_chars ?? 0 })}
            </Button>
          )}
          {full && !full.complete && <div className="u-xs u-warning u-mt-4">{t("outputIncomplete")}</div>}
        </details>
      )}
    </div>
  );
}
