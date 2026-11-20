import { useEffect, useRef, useState } from "react";
import { BookOpen, ChevronDown, FileCheck2, LogOut, MonitorPlay, Settings as SettingsIcon, Share2, UserRound, Users, WifiOff } from "lucide-react";
import type { Settings } from "../api";
import { LanguageToggle, useLang } from "../i18n";
import { connection } from "../lib/connection";
import { Button } from "../components/ui";
import { Brand } from "./FirstRun";
import { textDir } from "../lib/textDir";

export type Tab = "monitor" | "exercises" | "courses";

/** The red strip at the very top while the server isn't answering. */
export function ConnectionBanner() {
  const { t } = useLang();
  const [lost, setLost] = useState(connection.isLost());
  useEffect(() => connection.subscribe(setLost), []);
  if (!lost) return null;
  return <div className="vc-banner" role="alert"><WifiOff /> {t("connLost")}</div>;
}

function TutorStatus({ settings, onClick }: { settings: Settings | null; onClick: () => void }) {
  const { t } = useLang();
  if (!settings) return null;
  const { llm } = settings;
  const failing = llm.ready && llm.health.ok === false;
  const tone = !llm.ready ? "warning" : failing ? "danger" : "success";
  const label = !llm.ready ? t("statusNoKey") : failing ? t("statusError") : t("statusReady");
  return (
    <button type="button" className={`vc-status ${tone === "success" ? "" : `vc-status--${tone}`}`}
            title={failing ? llm.health.error : t("statusTitle")} onClick={onClick}>
      <span className={`vc-dot vc-dot--${tone}`} /> {label}
    </button>
  );
}

function AccountMenu({ settings, plugin, onSettings, onVerify, onSignOut }: {
  settings: Settings | null;
  plugin: boolean;
  onSettings: () => void;
  onVerify: () => void;
  onSignOut: () => void;
}) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const pick = (fn: () => void) => () => { setOpen(false); fn(); };
  return (
    <div className="vc-menu" ref={box}>
      <Button variant="quiet" size="sm" icon={<UserRound />} aria-haspopup="menu" aria-expanded={open}
              aria-label={t("menuAccount")} onClick={() => setOpen((v) => !v)}>
        <ChevronDown />
      </Button>
      {open && (
        <div className="vc-menu__list" role="menu">
          {settings && (
            <div className="vc-menu__label">{t("menuSignedIn")}<strong dir={textDir(settings.user.name)}>{settings.user.name}</strong></div>
          )}
          <button role="menuitem" className="vc-menu__item" onClick={pick(onSettings)}><SettingsIcon /> {t("menuSettings")}</button>
          {plugin && <button role="menuitem" className="vc-menu__item" onClick={pick(onVerify)}><FileCheck2 /> {t("menuVerify")}</button>}
          <button role="menuitem" className="vc-menu__item" onClick={pick(onSignOut)}><LogOut /> {t("signOut")}</button>
        </div>
      )}
    </div>
  );
}

export function Topbar({ tab, onTab, settings, plugin, bell, onShare, onSettings, onVerify, onSignOut }: {
  tab: Tab;
  onTab: (t: Tab) => void;
  settings: Settings | null;
  plugin: boolean;
  /** The notifications' bell (app/Notifications.tsx). */
  bell?: React.ReactNode;
  onShare: () => void;
  onSettings: () => void;
  onVerify: () => void;
  onSignOut: () => void;
}) {
  const { t } = useLang();
  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "monitor", label: t("navClass"), icon: <MonitorPlay /> },
    { key: "exercises", label: t("navExercises"), icon: <BookOpen /> },
    { key: "courses", label: t("navCourses"), icon: <Users /> },
  ];
  return (
    <header className="vc-topbar">
      <div className="vc-topbar__inner">
        <Brand />
        <nav className="vc-nav" aria-label="VeriClass">
          {tabs.map(({ key, label, icon }) => (
            <button key={key} type="button" className="vc-nav__item" aria-current={tab === key ? "page" : undefined}
                    onClick={() => onTab(key)}>
              {icon} {label}
            </button>
          ))}
        </nav>
        <div className="vc-topbar__actions">
          {bell}
          <TutorStatus settings={settings} onClick={onSettings} />
          <Button variant="primary" size="sm" icon={<Share2 />} onClick={onShare}>{t("shareBtn")}</Button>
          <LanguageToggle />
          <AccountMenu settings={settings} plugin={plugin} onSettings={onSettings} onVerify={onVerify} onSignOut={onSignOut} />
        </div>
      </div>
    </header>
  );
}
