import { useEffect, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Database,
  Download,
  FlaskConical,
  KeyRound,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  TestTubeDiagonal,
  TriangleAlert,
} from "lucide-react";
import type { Actions } from "./App";
import type { Preset, Report } from "./types";
import { Badge, Button, ReportTable, SectionHeading } from "./components";
import { count, date, label, validAddress } from "./format";
import { api } from "./api";

const fields: {
  key: string;
  name: string;
  hint?: string;
  integer?: boolean;
  simple?: boolean;
}[] = [
  { key: "window_days", name: "Reporting days", integer: true, simple: true },
  { key: "min_profit_sol", name: "Minimum profit (SOL)", simple: true },
  { key: "min_hold_hours", name: "Minimum median hold (hours)", simple: true },
  {
    key: "min_positions",
    name: "Minimum completed positions",
    integer: true,
    simple: true,
  },
  { key: "verification_days", name: "Verification days", integer: true },
  { key: "min_realised_roi_pct", name: "Minimum realised ROI (%)" },
  { key: "min_median_roi_pct", name: "Minimum median ROI (%)" },
  { key: "min_win_rate_pct", name: "Minimum win rate (%)" },
  { key: "max_win_rate_pct", name: "Maximum win rate (%)" },
  { key: "max_hold_hours", name: "Maximum median hold (hours)" },
  { key: "min_positions_90d", name: "Minimum 90-day positions", integer: true },
  { key: "min_mints", name: "Minimum traded mints", integer: true },
  { key: "max_mints", name: "Maximum traded mints", integer: true },
  { key: "max_rapid_sale_pct", name: "Maximum rapid sales (%)" },
  { key: "min_avg_buys", name: "Minimum average buys" },
  { key: "max_avg_buys", name: "Maximum average buys" },
  { key: "min_avg_sells", name: "Minimum average sells" },
  { key: "max_avg_sells", name: "Maximum average sells" },
  { key: "min_positive_weeks", name: "Minimum positive weeks", integer: true },
  { key: "max_contribution_pct", name: "Maximum profit contribution (%)" },
];
const limitNames: Record<string, string> = {
  candidate_cap: "Candidates per batch",
  deep_audit_cap: "Deep audits per batch",
  transaction_limit: "Transactions per wallet",
  wallet_credit_limit: "Credits per wallet",
  helius_cap: "Cycle credit ceiling",
  discovery_pause: "Discovery pause threshold",
  min_free_disk_mb: "Minimum free disk (MB)",
};
export function SettingsView({ state, busy, run, open }: Actions) {
  const [preset, setPreset] = useState<Preset>({ ...state.preset });
  const [limits, setLimits] = useState({ ...state.settings.limits });
  const [advanced, setAdvanced] = useState(false);
  const [key, setKey] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [tariffConfirmed, setTariffConfirmed] = useState(false);
  const [manifest, setManifest] = useState<{
    version: string;
    effective_date: string;
    methods: Record<string, number>;
    source: string;
  } | null>(null);
  const [manifestError, setManifestError] = useState("");
  const [refreshMinutes, setRefreshMinutes] = useState(
    state.settings.refresh_minutes,
  );
  const [cycleStart, setCycleStart] = useState(
    state.provider.cycle_start?.slice(0, 10) || "",
  );
  const [cycleEnd, setCycleEnd] = useState(
    state.provider.cycle_end?.slice(0, 10) || "",
  );
  const [testAddress, setTestAddress] = useState("");
  const [testResult, setTestResult] = useState<unknown>(null);
  const [preview, setPreview] = useState<Report[] | null>(null);
  const [previewDetail, setPreviewDetail] = useState<Report | null>(null);
  const [backup, setBackup] = useState<unknown>(null);
  const [validation, setValidation] = useState("");
  useEffect(() => {
    api<{
      version: string;
      effective_date: string;
      methods: Record<string, number>;
      source: string;
    }>("/provider/manifest")
      .then(setManifest)
      .catch((error) => setManifestError(error.message));
  }, []);
  const update = (field: string, value: string, integer?: boolean) => {
    setPreset((current) => ({
      ...current,
      [field]: integer ? (value === "" ? 0 : Number(value)) : value,
    }));
    setPreview(null);
    setPreviewDetail(null);
    setValidation("");
  };
  const validPreset = () => {
    if (!String(preset.name || "").trim()) {
      setValidation("Give this preset a name.");
      return false;
    }
    for (const field of fields) {
      const value = String(preset[field.key] ?? "");
      if (
        !/^\d+(?:\.\d+)?$/.test(value) ||
        (field.integer && !/^\d+$/.test(value))
      ) {
        setValidation(
          `${field.name} needs a non-negative ${field.integer ? "integer" : "decimal"}.`,
        );
        return false;
      }
    }
    return true;
  };
  const save = async () => {
    if (!validPreset()) return;
    const result = await run(
      "preset-save",
      "/settings",
      { preset },
      "PUT",
      "Preset saved. Use cached preview to inspect threshold changes.",
    );
    if (result) setPreview(null);
  };
  const previewPreset = async () => {
    if (!validPreset()) return;
    const result = (await run("preset-preview", "/presets/preview?view=summary", {
      preset,
    })) as { reports: Report[] } | undefined;
    if (result) setPreview(result.reports);
  };
  const saveProvider = async () => {
    const result = await run(
      "provider-save",
      "/provider",
      {
        api_key: key,
        free_plan_confirmed: confirmed,
        cycle_start: cycleStart,
        cycle_end: cycleEnd,
      },
      "POST",
      "Provider configured. Run the capability test before starting a live scan.",
    );
    if (result) {
      setKey("");
      setConfirmed(false);
      setTariffConfirmed(false);
      setTestResult(null);
    }
  };
  const capabilityTest = async () => {
    const result = await run(
      "provider-test",
      "/provider/test",
      testAddress.trim() ? { address: testAddress.trim() } : {},
      "POST",
      "Read-only capability test finished. Review its result below.",
    );
    if (result) setTestResult(result);
  };
  return (
    <div className="settings-layout">
      <div>
        <section className="panel preset-panel">
          <SectionHeading
            title="Your screening preset"
            subtitle="Thresholds are research questions, not a promise of performance."
            action={<Badge value="known">FIFO v1</Badge>}
          />
          <div className="form-field preset-name">
            <label htmlFor="preset-name">Preset name</label>
            <input
              id="preset-name"
              value={String(preset.name || "")}
              onChange={(e) => update("name", e.target.value)}
            />
          </div>
          <div className="form-grid two">
            {fields
              .filter((field) => field.simple || advanced)
              .map((field) => (
                <div className="form-field" key={field.key}>
                  <label htmlFor={`preset-${field.key}`}>{field.name}</label>
                  <input
                    id={`preset-${field.key}`}
                    inputMode={field.integer ? "numeric" : "decimal"}
                    value={String(preset[field.key] ?? "")}
                    onChange={(e) =>
                      update(field.key, e.target.value, field.integer)
                    }
                  />
                </div>
              ))}
          </div>
          <button
            className="advanced-toggle"
            onClick={() => setAdvanced((value) => !value)}
          >
            <SlidersHorizontal size={16} />
            {advanced ? "Hide advanced thresholds" : "Show advanced thresholds"}
            {advanced ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          </button>
          {advanced && (
            <label className="check-label">
              <input
                type="checkbox"
                checked={!!preset.require_positive_economic_pnl}
                onChange={(e) =>
                  setPreset((p) => ({
                    ...p,
                    require_positive_economic_pnl: e.target.checked,
                  }))
                }
              />
              <span>
                <strong>Require positive economic P&L</strong>
                <small>Unknown mark-to-market values remain unresolved.</small>
              </span>
            </label>
          )}
          {validation && (
            <div className="inline-alert">
              <TriangleAlert size={16} />
              {validation}
            </div>
          )}
          <div className="preset-note">
            <Database size={16} />
            <span>
              Preview uses your local cache. It never fetches new data or
              changes the accounting methodology.
            </span>
          </div>
          <div className="settings-actions">
            <Button
              variant="secondary"
              icon={FlaskConical}
              busy={busy === "preset-preview"}
              onClick={previewPreset}
            >
              Preview on cached reports
            </Button>
            <Button icon={Save} busy={busy === "preset-save"} onClick={save}>
              Save preset
            </Button>
          </div>
          {preview !== null && (
            <div className="preset-preview">
              <SectionHeading
                title="Cached preview"
                subtitle={`${preview.length} report${preview.length !== 1 ? "s" : ""} re-evaluated with these thresholds. Changes are not yet saved.`}
              />
              {preview.length ? (
                <ReportTable reports={preview} onOpen={setPreviewDetail} />
              ) : (
                <p className="quiet-message">
                  No cached reports are available. Create a scan or load the
                  offline demo first.
                </p>
              )}
              {previewDetail && (
                <div className="preview-detail">
                  <div className="section-heading">
                    <div>
                      <h2>
                        {previewDetail.label ||
                          previewDetail.address.slice(0, 10)}{" "}
                        · unsaved preview
                      </h2>
                      <p>
                        These decisions use the thresholds in this form. The
                        saved report remains unchanged.
                      </p>
                    </div>
                    <Badge value={previewDetail.policy} />
                  </div>
                  {previewDetail.checks.map((check) => (
                    <div className="preview-check" key={check.key}>
                      <span>
                        {check.label}
                        <small>
                          {`Expected ${String(check.expected)}`}
                          {check.reason ? ` · ${check.reason}` : ""}
                        </small>
                      </span>
                      <Badge value={check.state} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
        <section className="panel">
          <SectionHeading
            title="Workload & quota guardrails"
            subtitle="Limits stop research before the application exhausts its configured allowance."
          />
          <div className="form-grid two">
            {Object.entries(limits).map(([field, value]) => (
              <div className="form-field" key={field}>
                <label htmlFor={`limit-${field}`}>
                  {limitNames[field] || label(field)}
                </label>
                <input
                  id={`limit-${field}`}
                  type="number"
                  min="1"
                  step="1"
                  value={value}
                  onChange={(e) =>
                    setLimits((l) => ({
                      ...l,
                      [field]: Number(e.target.value),
                    }))
                  }
                />
              </div>
            ))}
          </div>
          <div className="settings-actions">
            <p className="small-note">
              Discovery also pauses at its threshold. Reserved credits count
              against the cap.
            </p>
            <Button
              icon={Save}
              busy={busy === "limits-save"}
              disabled={Object.values(limits).some(
                (value) => !Number.isSafeInteger(value) || value < 1,
              )}
              onClick={() =>
                run(
                  "limits-save",
                  "/settings",
                  { limits },
                  "PUT",
                  "Workload guardrails saved.",
                )
              }
            >
              Save limits
            </Button>
          </div>
        </section>
      </div>
      <div>
        <section className="panel provider-panel">
          <SectionHeading
            title="Free data access"
            subtitle="Helius native Solana RPC"
            action={
              <span className="small-icon">
                <KeyRound size={19} />
              </span>
            }
          />
          <div className="provider-status">
            <Badge value={state.provider.configured ? "configured" : "unknown"}>
              {state.provider.configured ? "Configured" : "Not configured"}
            </Badge>
            <Badge value={state.provider.capability_status}>
              {label(state.provider.capability_status)}
            </Badge>
          </div>
          <div className="provider-storage">
            <ShieldCheck size={15} />
            <span>
              Key storage:{" "}
              {state.provider.storage === "os-keyring"
                ? "OS keyring"
                : state.provider.storage === "session-only"
                  ? "memory for this session"
                  : state.provider.storage === "environment"
                    ? "environment"
                    : "not configured"}
            </span>
          </div>
          <div className="form-field">
            <label htmlFor="provider-key">Helius Free API key</label>
            <input
              id="provider-key"
              type="password"
              autoComplete="off"
              placeholder={
                state.provider.configured
                  ? "Enter a key to update configuration"
                  : "Paste your manually obtained key"
              }
              value={key}
              onChange={(e) => setKey(e.target.value)}
              data-lpignore="true"
            />
            <small>
              Your key is sent only to the local backend and never stored in
              this browser.
            </small>
          </div>
          <div className="form-grid two">
            <div className="form-field">
              <label htmlFor="cycle-start">Billing cycle starts</label>
              <input
                id="cycle-start"
                type="date"
                value={cycleStart}
                onChange={(e) => setCycleStart(e.target.value)}
              />
            </div>
            <div className="form-field">
              <label htmlFor="cycle-end">Billing cycle ends</label>
              <input
                id="cycle-end"
                type="date"
                value={cycleEnd}
                min={cycleStart}
                onChange={(e) => setCycleEnd(e.target.value)}
              />
            </div>
          </div>
          <label className="check-label free-confirm">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>
              <strong>I manually verified my Helius account is on Free.</strong>
              <small>
                I checked the billing cycle and free native-method allowance in
                the provider dashboard.
              </small>
            </span>
          </label>
          {manifest && (
            <div className="cost-manifest">
              <span className="eyebrow">DATED NATIVE-METHOD MANIFEST</span>
              <p>
                {manifest.version} · {date(manifest.effective_date)}
              </p>
              <dl>
                {Object.entries(manifest.methods).map(([method, cost]) => (
                  <div key={method}>
                    <dt className="mono">{method}</dt>
                    <dd>
                      {cost} credit{cost !== 1 ? "s" : ""}
                    </dd>
                  </div>
                ))}
              </dl>
              <a
                className="text-button"
                href={manifest.source}
                target="_blank"
                rel="noreferrer"
              >
                Provider credit reference <ArrowRight size={12} />
              </a>
            </div>
          )}
          {manifestError && <div className="inline-alert">{manifestError}</div>}
          <label className="check-label">
            <input
              type="checkbox"
              checked={tariffConfirmed}
              onChange={(e) => setTariffConfirmed(e.target.checked)}
            />
            <span>
              <strong>
                I verified the dated native-method costs apply to my free
                account.
              </strong>
              <small>
                Published documentation and the capability test are separate
                access checks.
              </small>
            </span>
          </label>
          <Button
            icon={ShieldCheck}
            busy={busy === "provider-save"}
            disabled={
              (!key && !state.provider.configured) ||
              !confirmed ||
              !tariffConfirmed ||
              !manifest ||
              !cycleStart ||
              !cycleEnd ||
              cycleEnd <= cycleStart
            }
            onClick={saveProvider}
          >
            Save free-plan configuration
          </Button>
          <div className="capability-block">
            <SectionHeading
              title="Verify access"
              subtitle="A small read-only test consumes native-method credits."
            />
            <div className="form-field">
              <label htmlFor="test-address">
                Calibration wallet{" "}
                <span className="muted">(required before live scanning)</span>
              </label>
              <input
                id="test-address"
                className="mono"
                value={testAddress}
                onChange={(e) => setTestAddress(e.target.value)}
                placeholder="Public wallet with a known transaction"
              />
            </div>
            <Button
              variant="secondary"
              icon={TestTubeDiagonal}
              busy={busy === "provider-test"}
              disabled={
                !state.provider.configured || !validAddress(testAddress.trim())
              }
              onClick={capabilityTest}
            >
              Run capability test
            </Button>
            {testResult !== null && (
              <div className="test-result">
                <strong>Capability test response</strong>
                <pre>{JSON.stringify(testResult, null, 2)}</pre>
              </div>
            )}
          </div>
        </section>
        <section className="panel usage-panel">
          <SectionHeading
            title="This billing cycle"
            subtitle={`${date(state.usage.cycle_start)} → ${date(state.usage.cycle_end)}`}
          />
          <dl className="scope-list">
            <div>
              <dt>Used</dt>
              <dd>{count(state.usage.used)} credits</dd>
            </div>
            <div>
              <dt>Reserved</dt>
              <dd>{count(state.usage.reserved)} credits</dd>
            </div>
            <div>
              <dt>Configured ceiling</dt>
              <dd>{count(state.usage.cap)} credits</dd>
            </div>
            <div>
              <dt>Remaining</dt>
              <dd>{count(state.usage.remaining)} credits</dd>
            </div>
          </dl>
          <p className="small-note">
            Cost manifest: {state.usage.manifest_version || "not available"}.
            External provider usage also needs to be checked in your dashboard.
          </p>
        </section>
        <section className="panel local-storage-panel">
          <SectionHeading
            title="Local data & backup"
            subtitle="SQLite records and compressed evidence archives."
          />
          <dl className="coverage-list">
            {Object.entries(state.storage)
              .slice(0, 8)
              .map(([key, value]) => (
                <div key={key}>
                  <dt>{label(key)}</dt>
                  <dd className={typeof value === "string" ? "mono" : ""}>
                    {typeof value === "object"
                      ? JSON.stringify(value)
                      : String(value)}
                  </dd>
                </div>
              ))}
          </dl>
          <div className="watch-refresh">
            <div className="form-field">
              <label htmlFor="refresh-minutes">
                Watchlist refresh interval (minutes)
              </label>
              <input
                id="refresh-minutes"
                type="number"
                min="0"
                max="1440"
                step="1"
                value={refreshMinutes}
                onChange={(e) => setRefreshMinutes(Number(e.target.value))}
              />
              <small>
                0 disables refresh. Use 15–1440 to refresh live watchlist
                wallets in bounded batches while this local app is running.
                Synthetic demo wallets are excluded.
              </small>
            </div>
            <Button
              variant="secondary"
              busy={busy === "refresh-save"}
              disabled={
                !Number.isSafeInteger(refreshMinutes) ||
                (refreshMinutes !== 0 &&
                  (refreshMinutes < 15 || refreshMinutes > 1440))
              }
              onClick={() =>
                run(
                  "refresh-save",
                  "/settings",
                  { refresh_minutes: refreshMinutes },
                  "PUT",
                  refreshMinutes
                    ? "Local watchlist refresh enabled. It uses your configured allowance."
                    : "Watchlist refresh disabled.",
                )
              }
            >
              Save refresh interval
            </Button>
          </div>
          <Button
            variant="secondary"
            icon={Download}
            busy={busy === "backup"}
            onClick={async () => {
              const result = await run(
                "backup",
                "/backup",
                {},
                "POST",
                "A consistent local backup has been created.",
              );
              if (result) setBackup(result);
            }}
          >
            Create local backup
          </Button>
          {backup !== null && (
            <pre className="backup-result">
              {JSON.stringify(backup, null, 2)}
            </pre>
          )}
        </section>
      </div>
    </div>
  );
}
