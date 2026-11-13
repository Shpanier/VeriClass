import { useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, Globe, Laptop } from "lucide-react";
import qrcode from "qrcode-generator";
import { api, type ShareInfo } from "../api";
import { useLang } from "../i18n";
import { describeError } from "../lib/errors";
import { Button, CopyButton, Loading, Modal, Notice, useConfirm } from "../components/ui";

function QrCode({ text }: { text: string }) {
  const svg = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(text);
    qr.make();
    return qr.createSvgTag({ cellSize: 4, margin: 0, scalable: true });
  }, [text]);
  // The markup comes from the QR library, built from the address alone.
  return <div className="vc-qr" dangerouslySetInnerHTML={{ __html: svg }} />;
}

function LinkBox({ url }: { url: string }) {
  const { t } = useLang();
  return (
    <div className="vc-link-box">
      <span className="vc-link-box__url">{url}</span>
      <CopyButton text={url} variant="primary" size="sm">{t("shCopyLink")}</CopyButton>
      <a className="vc-btn vc-btn--sm" href={url} target="_blank" rel="noreferrer"><ExternalLink /> {t("open")}</a>
    </div>
  );
}

/** The link students open, as text and as a QR code, and the public tunnel
 *  behind it: create it, see it, turn it off. */
export function ShareModal({ onClose, onShared }: { onClose: () => void; onShared: () => void }) {
  const { t } = useLang();
  const confirm = useConfirm();
  const [info, setInfo] = useState<ShareInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"start" | "stop" | "download" | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    const load = () => api.share().then((s) => { if (alive.current) setInfo(s); })
      .catch((e) => { if (alive.current) setError(describeError(e, t)); });
    load();
    const id = window.setInterval(load, 2000);
    return () => { alive.current = false; window.clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { if (info?.public_url) onShared(); }, [info?.public_url, onShared]);

  const act = async (action: "start" | "stop" | "download") => {
    if (action === "stop" && !(await confirm({
      title: t("shStopTitle"), body: t("shStopBody"), confirmLabel: t("shStop"), danger: true,
    }))) return;
    setBusy(action);
    setError(null);
    try {
      let next = await api.tunnel(action);
      if (action === "download") next = await api.tunnel("start");
      if (alive.current) setInfo(next);
    } catch (e) {
      if (alive.current) setError(describeError(e, t));
    } finally {
      if (alive.current) setBusy(null);
    }
  };

  const tunnel = info?.tunnel;
  const canStart = !!info && (info.available.cloudflared || (info.available.ngrok && !!info.ngrok_domain));
  const starting = tunnel?.state === "starting" || busy === "start";

  return (
    <Modal title={t("shTitle")} subtitle={t("shLead")} size="md" onClose={onClose}
           footer={<><span className="u-push" /><Button onClick={onClose}>{t("close")}</Button></>}>
      {!info && !error && <Loading />}
      {error && <Notice tone="danger" className="u-mb-12">{error}</Notice>}

      {info && !info.chat_mounted && <Notice tone="warning" className="u-mb-12">{t("shNoChat")}</Notice>}

      {info && info.public_url && (
        <section className="vc-section">
          <h3 className="u-row u-mb-8"><Globe size={18} /> {t("shPublic")}</h3>
          <LinkBox url={info.public_url} />
          <div className="u-row u-row--top u-gap-16 u-mt-12 u-wrap">
            <div>
              <QrCode text={info.public_url} />
              <div className="vc-hint" style={{ textAlign: "center" }}>{t("shScan")}</div>
            </div>
            <div className="u-grow u-col">
              <p className="u-soft u-sm">
                {tunnel?.external ? t("shExternalNote") : tunnel?.provider === "ngrok" ? t("shFixedNote") : t("shQuickNote")}
              </p>
              <p className="u-muted u-sm">{t("shCodes")}</p>
              {!tunnel?.external && (
                <div><Button variant="danger-soft" size="sm" busy={busy === "stop"} onClick={() => act("stop")}>{t("shStop")}</Button></div>
              )}
            </div>
          </div>
        </section>
      )}

      {info && !info.public_url && info.chat_mounted && (
        <section className="vc-section">
          {tunnel?.state === "error" && tunnel.error && (
            <Notice tone="danger" className="u-mb-12">{t("shStopped", { error: tunnel.error })}</Notice>
          )}
          {starting ? (
            <Notice tone="info"><span className="u-row"><span className="vc-spinner" /> {t("shStarting")}</span></Notice>
          ) : canStart ? (
            <Notice tone="warning" title={t("shLocalOnlyTitle")}
                    action={<Button variant="primary" onClick={() => act("start")}>{t("shCreate")}</Button>}>
              {t("shLocalOnlyBody")}
            </Notice>
          ) : (
            <Notice tone="info" title={t("shNeedTitle")}
                    action={<Button variant="primary" busy={busy === "download"} onClick={() => act("download")}>
                      {busy === "download" ? t("shDownloading") : t("shDownload")}
                    </Button>}>
              {t("shNeedBody")}
              <div className="u-mt-8 u-muted">{t("shOrInstall")} <code dir="ltr">{info.install_hint}</code></div>
            </Notice>
          )}
        </section>
      )}

      {info && (
        <section>
          <h3 className="u-row u-mb-8"><Laptop size={18} /> {t("shLocal")}</h3>
          <LinkBox url={info.local_url} />
          {info.lan_urls.length > 0 && (
            <p className="vc-hint">{t("shLan")} {info.lan_urls.map((u) => <code key={u} dir="ltr">{u}</code>)}</p>
          )}
          {!info.public_url && <p className="vc-hint">{t("shCodes")}</p>}
        </section>
      )}
    </Modal>
  );
}
