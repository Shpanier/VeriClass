import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ExerciseSummary, FullExercise, PackageResult } from "../types";
import { useLang } from "../i18n";
import { Button } from "./ui/Button";
import { ExerciseFormModal } from "./ExerciseFormModal";

type FormState =
  | { mode: "create"; initial?: undefined }
  | { mode: "edit" | "duplicate"; initial: FullExercise };

/** The file's bytes as base64. */
async function fileBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

// The "Exercises" tab: lists every exercise (built-in YAML, dashboard-made, and
// packages from the private data folder), lets the teacher pick which one is
// active, create / edit / duplicate, upload a package zip, export, and reload
// the packages from disk. New labs are written in Claude Code (the exercise
// skill) and installed with the MCP tool push_exercise, or uploaded here.
export function ExercisesPanel({ onActiveChanged }: { onActiveChanged: () => void }) {
  const { t, lang } = useLang();
  const [exercises, setExercises] = useState<ExerciseSummary[] | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [loadErrors, setLoadErrors] = useState<{ folder: string; error: string }[]>([]);
  const [upload, setUpload] = useState<PackageResult | { error: string } | null>(null);
  const [working, setWorking] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = () => {
    api.exercises().then(setExercises).catch(console.error);
    api.exercisesStatus().then((s) => setLoadErrors(s.load_errors)).catch(console.error);
  };

  useEffect(() => {
    refresh();
  }, []);

  const uploadZip = async (file: File) => {
    setWorking(true);
    setUpload(null);
    try {
      setUpload(await api.importExercise(await fileBase64(file)));
      refresh();
      onActiveChanged();
    } catch (e) {
      setUpload({ error: e instanceof Error ? e.message : String(e) });
    } finally {
      setWorking(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const reload = async () => {
    setWorking(true);
    try {
      const r = await api.reloadExercises();
      setExercises(r.exercises);
      setLoadErrors(r.load_errors);
      onActiveChanged();
    } catch (e) {
      console.error(e);
    } finally {
      setWorking(false);
    }
  };

  const exportZip = async (id: string) => {
    setBusyId(id);
    try {
      const url = URL.createObjectURL(await api.exportExercise(id));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${id}.zip`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      console.error(e);
    } finally {
      setBusyId(null);
    }
  };

  // makeActive=false switches the active exercise off (no exercise is active).
  const setActive = async (id: string, makeActive = true) => {
    setBusyId(id);
    try {
      await (makeActive ? api.setActiveExercise(id) : api.disableActiveExercise());
      await refresh();
      onActiveChanged(); // keep the monitor tab's header in sync
    } catch (e) {
      console.error(e);
    } finally {
      setBusyId(null);
    }
  };

  // Edit and Duplicate both need the FULL exercise (variants, params, tests),
  // which the list endpoint doesn't carry — fetch it, then open the form.
  const openWith = async (id: string, mode: "edit" | "duplicate") => {
    setBusyId(id);
    try {
      const full = await api.exercise(id);
      setForm({ mode, initial: full });
    } catch (e) {
      console.error(e);
    } finally {
      setBusyId(null);
    }
  };

  const afterSave = () => {
    setForm(null);
    refresh();
    onActiveChanged(); // an edit may have touched the active exercise
  };

  return (
    <section>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16, gap: 8, flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>{t("exercisesTitle")}</h2>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            ref={fileInput}
            type="file"
            accept=".zip,application/zip"
            style={{ display: "none" }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadZip(f); }}
          />
          <Button disabled={working} title={t("uploadHint")} onClick={() => fileInput.current?.click()}>
            {t("uploadExercise")}
          </Button>
          <Button disabled={working} onClick={reload}>{t("reloadExercises")}</Button>
          <Button variant="primary" onClick={() => setForm({ mode: "create" })}>
            {t("newExercise")}
          </Button>
        </div>
      </div>

      {upload && (
        <div style={{
          border: `1px solid ${"error" in upload || !upload.ok ? "#fecaca" : "#bbf7d0"}`,
          background: "error" in upload || !upload.ok ? "#fef2f2" : "#f0fdf4",
          borderRadius: 8, padding: 10, marginBottom: 12, fontSize: 13,
        }} dir="auto">
          {"error" in upload ? (
            <span style={{ color: "#b91c1c" }}>{upload.error}</span>
          ) : (
            <>
              <strong>{upload.ok ? t("uploadOk", { id: upload.summary.exercise_id ?? "" }) : t("uploadFailed")}</strong>
              {upload.errors.map((e, i) => <div key={i} style={{ color: "#b91c1c" }}>✗ {e}</div>)}
              {upload.warnings.length > 0 && (
                <details style={{ marginTop: 4 }}>
                  <summary style={{ cursor: "pointer" }}>{t("warningsLabel")} ({upload.warnings.length})</summary>
                  {upload.warnings.map((w, i) => <div key={i} style={{ color: "#92400e" }}>• {w}</div>)}
                </details>
              )}
            </>
          )}
        </div>
      )}
      {loadErrors.length > 0 && (
        <div style={{ border: "1px solid #fecaca", background: "#fef2f2", borderRadius: 8, padding: 10, marginBottom: 12, fontSize: 13 }}>
          <strong>{t("loadErrors")}</strong>
          {loadErrors.map((e) => <div key={e.folder} style={{ color: "#b91c1c" }} dir="auto">✗ {e.error}</div>)}
        </div>
      )}

      {exercises === null && <p style={{ color: "#6b7280" }}>{t("loading")}</p>}
      {exercises?.length === 0 && <p style={{ color: "#6b7280" }}>{t("noExercises")}</p>}
      {!!exercises?.length && !exercises.some((ex) => ex.is_active) && (
        <p style={{ color: "#b45309", marginTop: 0 }}>{t("noActiveExercise")}</p>
      )}

      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}>
        {exercises?.map((ex) => {
          const title = lang === "he" ? ex.title_he ?? ex.title_en : ex.title_en;
          const busy = busyId === ex.exercise_id;
          return (
            <div
              key={ex.exercise_id}
              style={{
                border: `1px solid ${ex.is_active ? "#10b981" : "#e5e7eb"}`,
                borderRadius: 10,
                padding: 16,
                background: "white",
                boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
                <code style={{ fontSize: 13 }}>{ex.exercise_id}</code>
                {ex.is_active && <Pill bg="#10b981">{t("activeBadge")}</Pill>}
                {!!ex.os_errors && <Pill bg="#b45309">{t("osErrorsBadge", { n: ex.os_errors })}</Pill>}
                <Pill bg={ex.source === "console" ? "#3b82f6" : ex.source === "package" ? "#0f766e" : "#6b7280"}>
                  {ex.source === "console" ? t("sourceConsole") : ex.source === "package" ? t("sourcePackage")
                    : ex.edited ? t("sourceYamlEdited") : t("sourceYaml")}
                </Pill>
              </div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
              <div style={{ color: "#6b7280", fontSize: 13, marginBottom: 12 }} title={ex.folder ?? undefined}>
                {ex.steps ? t("stepsCount", { n: ex.steps }) : t("variantsCount", { n: ex.variant_count })}
                {ex.bank_questions ? ` · ${t("bankCount", { n: ex.bank_questions })}` : ""}
                {" · "}{modeLabel(ex.default_mode, t)}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {ex.is_active ? (
                  <Button variant="neutral" disabled={busy} onClick={() => setActive(ex.exercise_id, false)}>
                    {busy ? t("saving") : t("disableActive")}
                  </Button>
                ) : (
                  <Button variant="neutral" disabled={busy} onClick={() => setActive(ex.exercise_id)}>
                    {busy ? t("saving") : t("setActive")}
                  </Button>
                )}
                <Button disabled={busy} onClick={() => openWith(ex.exercise_id, "edit")}>
                  {t("edit")}
                </Button>
                <Button disabled={busy} onClick={() => openWith(ex.exercise_id, "duplicate")}>
                  {t("duplicate")}
                </Button>
                <Button disabled={busy} onClick={() => exportZip(ex.exercise_id)}>
                  {t("exportExercise")}
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      {form && (
        <ExerciseFormModal
          mode={form.mode}
          initial={form.initial}
          onClose={() => setForm(null)}
          onSaved={afterSave}
        />
      )}
    </section>
  );
}

function modeLabel(mode: string, t: ReturnType<typeof useLang>["t"]) {
  return mode === "coding_partner" ? t("codingPartner") : t("mentor");
}

function Pill({ bg, children }: { bg: string; children: React.ReactNode }) {
  return (
    <span
      style={{
        background: bg,
        color: "white",
        fontSize: 11,
        fontWeight: 600,
        padding: "2px 8px",
        borderRadius: 999,
      }}
    >
      {children}
    </span>
  );
}
