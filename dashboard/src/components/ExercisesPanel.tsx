import { useEffect, useState } from "react";
import { api } from "../api";
import type { ExerciseSummary, FullExercise } from "../types";
import { useLang } from "../i18n";
import { Button } from "./ui/Button";
import { ExerciseFormModal } from "./ExerciseFormModal";

type FormState =
  | { mode: "create"; initial?: undefined }
  | { mode: "edit" | "duplicate"; initial: FullExercise };

// The "Exercises" tab: lists every exercise (built-in YAML + console-authored),
// lets the teacher pick which one is active, and create / edit / duplicate.
export function ExercisesPanel({ onActiveChanged }: { onActiveChanged: () => void }) {
  const { t, lang } = useLang();
  const [exercises, setExercises] = useState<ExerciseSummary[] | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = () => api.exercises().then(setExercises).catch(console.error);

  useEffect(() => {
    refresh();
  }, []);

  const setActive = async (id: string) => {
    setBusyId(id);
    try {
      await api.setActiveExercise(id);
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
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>{t("exercisesTitle")}</h2>
        <Button variant="primary" onClick={() => setForm({ mode: "create" })}>
          {t("newExercise")}
        </Button>
      </div>

      {exercises === null && <p style={{ color: "#6b7280" }}>{t("loading")}</p>}
      {exercises?.length === 0 && <p style={{ color: "#6b7280" }}>{t("noExercises")}</p>}

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
                <Pill bg={ex.source === "console" ? "#3b82f6" : "#6b7280"}>
                  {ex.source === "console" ? t("sourceConsole") : ex.edited ? t("sourceYamlEdited") : t("sourceYaml")}
                </Pill>
              </div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
              <div style={{ color: "#6b7280", fontSize: 13, marginBottom: 12 }}>
                {t("variantsCount", { n: ex.variant_count })} · {modeLabel(ex.default_mode, t)}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {!ex.is_active && (
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
