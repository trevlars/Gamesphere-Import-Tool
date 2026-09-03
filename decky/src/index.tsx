import {
  definePlugin,
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Field,
  ToggleField,
} from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useState } from "react";

const runImport = callable<
  [boolean],
  { ok: boolean; output: string; banner?: string }
>("run_import");

const runRemove = callable<[], { ok: boolean; output: string; banner?: string }>(
  "run_remove"
);

const getStatus = callable<[], { installed: boolean; paths?: Record<string, string> }>(
  "get_status"
);

function Content() {
  const [dryRun, setDryRun] = useState(true);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState("");
  const [installed, setInstalled] = useState<boolean | null>(null);

  const refreshStatus = async () => {
    const status = await getStatus();
    setInstalled(status.installed);
  };

  const doImport = async () => {
    setBusy(true);
    try {
      const result = await runImport(dryRun);
      setLog(result.output || (result.ok ? "Done." : "Failed."));
      if (result.banner) setLog((prev) => `${result.banner}\n\n${prev}`);
    } finally {
      setBusy(false);
    }
  };

  const doRemove = async () => {
    setBusy(true);
    try {
      const result = await runRemove();
      setLog(result.output || (result.ok ? "Removed." : "Failed."));
      if (result.banner) setLog((prev) => `${result.banner}\n\n${prev}`);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    refreshStatus();
  }, []);

  return (
    <PanelSection title="GameSphere Import">
      <PanelSectionRow>
        <Field label="CLI installed">
          {installed === null ? "…" : installed ? "Yes" : "No — run install-linux.sh on host"}
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Dry run (preview only)"
          checked={dryRun}
          onChange={setDryRun}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={doImport} disabled={busy || !installed}>
          {busy ? "Running…" : dryRun ? "Preview import" : "Import Steam games"}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={doRemove} disabled={busy || !installed}>
          Remove all games (stock apps only)
        </ButtonItem>
      </PanelSectionRow>
      {log ? (
        <PanelSectionRow>
          <Field label="Log">
            <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.85em" }}>{log}</pre>
          </Field>
        </PanelSectionRow>
      ) : null}
    </PanelSection>
  );
}

export default definePlugin(() => ({
  title: <div className="gamesphere-import-title">GameSphere Import</div>,
  content: <Content />,
  icon: "https://raw.githubusercontent.com/trevlars/Gamesphere-Import-Tool/main/assets/readme-screenshot.png",
  onDismount() {},
}));
