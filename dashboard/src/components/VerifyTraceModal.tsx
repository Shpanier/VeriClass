import { useId, useState } from "react";
import { api } from "../api";
import type { TraceVerifyResult } from "../types";
import { useLang, type StringKey } from "../i18n";
import { describeError } from "../lib/errors";
import { Button, Loading, Modal, Notice, Time } from "./ui";

/**
 * A student's "Export my log" CSV (IDE plugin), checked by the server: was any
 * row edited, removed or reordered (signed chain), was the file cut short, and
 * which rows never reached the server. Those can be imported; they're then
 * marked as coming from the export everywhere they show.
 */
export function VerifyTraceModal({ onClose }: { onClose: () => void }) {
  const { t } = useLang();
  const fileId = useId();
  const hintId = useId();
  const [csv, setCsv] = useState<string | null>(null);
  const [result, setResult] = useState<TraceVerifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"check" | "import" | null>(null);

  const run = async (text: string, importMissing: boolean) => {
    setBusy(importMissing ? "import" : "check");
    setError(null);
    try {
      setResult(await api.verifyTrace(text, importMissing));
    } catch (e) {
      setError(describeError(e, t));
    } finally {
      setBusy(null);
    }
  };

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    setError(null);
    let text: string;
    try {
      text = await f.text();
    } catch (e) {
      setError(describeError(e, t));
      return;
    }
    setCsv(text);
    setResult(null);
    void run(text, false);
  };

  const missing = result?.missing_on_server ?? 0;
  const imported = result?.imported ?? 0;
  const canImport = !!result && imported === 0 && missing > 0;

  return (
    <Modal
      size="lg"
      onClose={onClose}
      title={t("verifyTitle")}
      subtitle={t("vtLead")}
      footer={<>
        <span className="u-push" />
        <Button onClick={onClose}>{t("close")}</Button>
        {canImport && (
          <Button variant="primary" busy={busy === "import"} disabled={busy !== null || !csv}
                  onClick={() => csv && run(csv, true)}>
            {t("verifyImport", { n: missing })}
          </Button>
        )}
      </>}
    >
      <div className="vc-field">
        <label className="vc-label" htmlFor={fileId}>{t("vtFile")}</label>
        <input id={fileId} type="file" accept=".csv,text/csv" className="vc-students-file" aria-describedby={hintId}
               onChange={(e) => onFile(e.target.files?.[0])} />
        <span className="vc-hint" id={hintId}>{t("verifyHint")}</span>
      </div>

      {busy === "check" && <Loading>{t("vtChecking")}</Loading>}
      {error && <Notice tone="danger" title={t("vtReadFailed")} className="u-mb-12">{error}</Notice>}

      {result && (
        <>
          {result.ok ? (
            <Notice tone="success">
              {t("verifyOk", { n: result.valid_rows ?? 0, student: result.student ?? t("vtUnknownStudent") })}
            </Notice>
          ) : (
            <Notice tone="danger" title={t("vtBadTitle")}>
              <span dir="auto">{result.error ?? ""}</span>
              {result.student && <> · <bdi>{result.student}</bdi></>}
            </Notice>
          )}

          <div className="u-mt-8 u-mb-12">
            {imported > 0 ? (
              <Notice tone="info">{t("verifyImported", { n: imported })}</Notice>
            ) : missing > 0 ? (
              <Notice tone="warning">{t("verifyMissing", { n: missing })}</Notice>
            ) : (
              result.rows.length > 0 && <p className="u-sm u-success">{t("verifyNothingMissing")}</p>
            )}
          </div>

          {result.rows.length > 0 && (
            <div className="vc-table-wrap vc-students-trace">
              <table className="vc-table">
                <thead>
                  <tr>
                    {(["colRow", "colTime", "colKind", "colWhat", "colSigned", "colOnServer"] as StringKey[]).map((k) => (
                      <th key={k} scope="col">{t(k)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((r, i) => (
                    <tr key={i} data-bad={r.valid ? undefined : "true"}>
                      <td>{r.seq ?? "?"}</td>
                      <td className="u-nowrap"><Time value={r.at_utc} mode="clock" /></td>
                      <td>{TRACE_KINDS.has(r.kind) ? t(`traceKind_${r.kind}` as StringKey) : r.kind}</td>
                      <td className="vc-mono" dir="auto">{r.summary}</td>
                      <td>
                        {r.valid
                          ? <span className="vc-badge vc-badge--success">{t("vtYes")}</span>
                          : <span className="vc-badge vc-badge--danger">{t("vtNo")}</span>}
                      </td>
                      <td>
                        {r.imported ? <span className="vc-badge vc-badge--brand">{t("vtImported")}</span>
                          : r.on_server === true ? t("vtYes")
                            : r.on_server === false ? <span className="vc-badge vc-badge--warning">{t("vtMissing")}</span>
                              : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

const TRACE_KINDS = new Set(["terminal", "proctor", "paste", "chat_user", "chat_tutor", "export_end"]);
