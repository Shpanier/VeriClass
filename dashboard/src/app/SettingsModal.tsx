import { useEffect, useRef, useState } from "react";
import { api, type ChatLanguage, type Settings } from "../api";
import { useLang } from "../i18n";
import { Button, FormField, Modal, Notice, Select, useToast } from "../components/ui";
import { TutorForm } from "./TutorForm";
import { NotificationSettings } from "./Notifications";

/** The AI tutor's key, the student chat's language, and where this
 *  installation keeps its files. */
export function SettingsModal({ settings, onChanged, onClose, focus, onNotifyChanged }: {
  settings: Settings;
  onChanged: (s: Settings) => void;
  onClose: () => void;
  /** Open on this section (from the bell's "Settings"). */
  focus?: "notifications";
  onNotifyChanged?: () => void;
}) {
  const { t } = useLang();
  const notifyBox = useRef<HTMLElement>(null);
  useEffect(() => {
    if (focus !== "notifications") return;
    const id = window.requestAnimationFrame(() => notifyBox.current?.scrollIntoView({ block: "start" }));
    return () => window.cancelAnimationFrame(id);
  }, [focus]);
  const toast = useToast();
  const [lang, setLang] = useState<ChatLanguage>(settings.chat_language);
  const { llm } = settings;

  const saveLang = async (value: ChatLanguage) => {
    const before = lang;
    setLang(value);
    try {
      const r = await api.saveChatLanguage(value);
      onChanged({ ...settings, chat_language: r.chat_language });
      toast.success(t("setSaved"));
    } catch (e) {
      setLang(before);
      toast.error(e);
    }
  };

  return (
    <Modal title={t("setTitle")} size="md" onClose={onClose}
           footer={<><span className="u-push" /><Button onClick={onClose}>{t("close")}</Button></>}>
      <section className="vc-section">
        <h3 className="u-mb-8">{t("setTutor")}</h3>
        {!llm.ready && <Notice tone="warning" className="u-mb-12">{t("tuNoKey")}</Notice>}
        {llm.ready && llm.health.ok === false && (
          <Notice tone="danger" className="u-mb-12">{t("tuLastError", { error: llm.health.error })}</Notice>
        )}
        {llm.ready && llm.health.ok === true && <Notice tone="success" className="u-mb-12">{t("tuWorking")}</Notice>}
        <TutorForm
          llm={llm} saveLabel={t("tuSave")}
          onSaved={(next, check) => {
            onChanged({ ...settings, llm: next });
            if (check.ok) toast.success(t("tuSaved")); else toast.info(t("tuSavedUnchecked"));
          }}
        />
        {llm.ready && (
          <p className="vc-hint u-mt-12">
            {t("tuModels", { chat: llm.chat_model, agent: llm.agent_model })}. {t("tuModelsHint")}
          </p>
        )}
      </section>

      <hr className="vc-divider" />
      <section className="vc-section">
        <FormField label={t("setChatLang")} hint={t("setChatLangHint")}>
          <Select value={lang} onChange={(e) => saveLang(e.target.value as ChatLanguage)}>
            <option value="auto">{t("setLangAuto")}</option>
            <option value="he">{t("setLangHe")}</option>
            <option value="en">{t("setLangEn")}</option>
          </Select>
        </FormField>
      </section>

      <hr className="vc-divider" />
      <section className="vc-section" ref={notifyBox}>
        <NotificationSettings onChanged={() => onNotifyChanged?.()} />
      </section>

      <hr className="vc-divider" />
      <section>
        <h3 className="u-mb-8">{t("setAbout")}</h3>
        <dl className="vc-kv">
          <dt>{t("setVersion")}</dt><dd>VeriClass {settings.version}</dd>
          <dt>{t("setEnv")}</dt><dd className="vc-mono" dir="ltr">{settings.paths.env_file}</dd>
          <dt>{t("setData")}</dt><dd className="vc-mono" dir="ltr">{settings.paths.data_dir}</dd>
          <dt>{t("setDb")}</dt><dd className="vc-mono" dir="ltr">{settings.paths.database}</dd>
        </dl>
        <p className="vc-hint">{t("setBackupHint")}</p>
      </section>
    </Modal>
  );
}
