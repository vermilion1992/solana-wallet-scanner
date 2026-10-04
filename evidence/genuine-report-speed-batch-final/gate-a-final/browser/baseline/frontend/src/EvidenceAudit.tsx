import { useRef, useState } from "react";
import { ArrowLeft, ArrowUpRight, CircleHelp, Download, FileJson, FlaskConical, Search, Upload } from "lucide-react";
import type { Actions } from "./App";
import type { EvidenceAudit } from "./types";
import { api } from "./api";
import { Badge, Button, Empty, SectionHeading } from "./components";
import { count, dateTime, decimal, label, shorten } from "./format";

export function parseRawEvidenceBundle(text: string) {
  if (new TextEncoder().encode(text).length > 4 * 1024 * 1024)
    throw new Error("Transaction record files must be no larger than 4 MiB.");
  const bundle = JSON.parse(text) as Record<string, unknown>;
  if (!bundle || typeof bundle !== "object" || Array.isArray(bundle) || bundle.version !== "raw-evidence-v1")
    throw new Error("Choose a raw-evidence-v1 transaction record bundle. The reviewed example shows the supported format.");
  if (!Array.isArray(bundle.transactions) || !bundle.transactions.length || bundle.transactions.length > 20)
    throw new Error("A record audit accepts 1–20 supplied transactions.");
  return bundle;
}

const metricNames: Record<string, string> = {
  transaction_count: "Supplied transactions",
  decoded_swap_count: "Reconstructed swaps",
  gross_buy_consideration_sol: "Gross buy consideration",
  gross_sell_proceeds_sol: "Gross sell proceeds",
  wallet_network_fees_sol: "Wallet-paid network fees",
  native_wallet_delta_sol: "Native wallet balance change",
  outside_native_delta_sol: "Other native balance change",
};
const checkNames: Record<string, string> = {
  identity: "Signer in supplied records",
  chain_provenance: "Record provenance",
  account_ownership: "Ownership in supplied records",
  account_boundary: "Recorded account boundary",
  transaction_set: "Enumerated transaction set",
  fee_allocation: "Fee allocation",
  wallet_profit: "Complete wallet profit",
  copy_safety: "Copy-trading risk evidence",
};

export function EvidenceAuditResult({ audit, currentMethodology, showEvidence }: {
  audit: EvidenceAudit;
  currentMethodology?: string;
  showEvidence?: (hash: string) => void;
}) {
  const reviewed = audit.source === "raw-mainnet-records";
  const reconciled = audit.certificate.status === "SCOPED_RECONSTRUCTION";
  const current = !!currentMethodology && audit.certificate.version === currentMethodology;
  return (
    <>
      <section className="panel record-audit-summary">
        <SectionHeading
          title={!current ? (currentMethodology ? "Saved audit uses a previous method" : "Current record-audit method unavailable") : reconciled ? "Supplied records reconcile" : "Supplied records need more evidence"}
          subtitle={`${count(audit.scope.signatures.length)} enumerated transactions · ${count(audit.scope.accounts.length)} involved accounts · saved ${dateTime(audit.created_at)}`}
          action={<Badge value={current && reconciled ? "known" : "unresolved"}>{!current ? "Rebuild needed" : reconciled ? "Scoped reconstruction" : "Incomplete records"}</Badge>}
        />
        {!current && <div className="record-provenance record-method-warning">
          <CircleHelp size={18} />
          <p><strong>{currentMethodology ? "Older saved assessment." : "Saved assessment only."}</strong>{" "}
            Saved method: {audit.certificate.version}. {currentMethodology ? `Current method: ${currentMethodology}.` : "The server has not supplied its current record-audit method."}{" "}
            Rebuild with the record bundle or reviewed example above before using these saved figures and fee checks as a current assessment. The original result and export remain unchanged.
          </p>
        </div>}
        <div className={`record-provenance ${reviewed ? "reviewed" : ""}`}>
          <CircleHelp size={18} />
          <p>
            <strong>{reviewed ? "Reviewed mainnet record." : "Unverified import."}</strong>{" "}
            {reviewed
              ? "The supplied content matches the bundled reviewed fixture. This audit covers its explicit transaction set."
              : "Internal agreement between supplied records does not establish that an arbitrary import came from the Solana chain."}
          </p>
        </div>
        <p className="record-scope">{audit.scope.description}</p>
        <p className="record-address mono">{audit.address}</p>
        <div className="record-boundary-stats">
          <div><span>Wallet-wide history</span><strong>Not established</strong></div>
          <div><span>Wallet profit</span><strong>Unknown</strong></div>
          <div><span>Financial qualification</span><strong>Unresolved</strong></div>
        </div>
      </section>
      <section className="panel">
        <SectionHeading title={current ? "Amounts within the supplied records" : "Archived amounts within the supplied records"} subtitle={current ? "These measures describe this transaction set. Gross proceeds and balance changes are not wallet profit." : "Saved figures from the previous assessment; rebuild for the current method. Gross proceeds and balance changes are not wallet profit."} />
        <div className="record-audit-metrics">
          {Object.entries(metricNames).map(([key, name]) => {
            const metric = audit.metrics[key];
            const known = metric?.status === "known" && typeof metric.value === "string";
            return <div key={key}>
              <span>{name}</span>
              <strong>{known ? decimal(metric.value as string, metric.unit === "SOL" ? 9 : 0) : "—"}{known && metric.unit === "SOL" && <small> SOL</small>}</strong>
              <p>{known ? (current ? "Explicit supplied transaction set only" : "Archived figure · rebuild for current assessment") : metric?.reason ?? "Required record evidence is missing"}</p>
            </div>;
          })}
        </div>
      </section>
      <section className="panel record-checks-panel">
        <SectionHeading title={current ? "Record checks and missing prerequisites" : "Archived record checks and missing prerequisites"} subtitle={current ? "A passing record check has only the scope stated beside it. Complete history, opening costs, classification, and wallet profit need their own evidence." : "These are saved assessments from a previous method. Rebuild to assess fees and record consistency with the current method. Complete wallet profit remains unknown."} />
        <div className="checks-list">
          {Object.entries(audit.certificate.checks).map(([key, check]) => <div className="check-row" key={key} data-record-check={key}>
            <span className={`check-icon ${current ? check.state.toLowerCase() : "unknown"}`}><CircleHelp size={16} /></span>
            <div><strong>{checkNames[key] ?? label(key)}</strong><small>{!current && `Saved assessment: ${label(check.state.toLowerCase())}. `}{check.detail}{!current && key === "fee_allocation" && " Rebuild required for the current fee assessment."}</small></div>
            {current ? <Badge value={check.state} /> : <Badge value="unresolved">{key === "fee_allocation" ? "Rebuild needed" : "Archived"}</Badge>}
          </div>)}
        </div>
        {audit.notes.map((note, index) => <p className="report-note" key={index}>{note}</p>)}
      </section>
      <section className="panel record-certificate-panel">
        <SectionHeading title="Saved evidence certificate" subtitle="Download the immutable result to inspect amounts, exact account boundaries, source paths, and unresolved checks." action={
          <a className="button secondary" href={`/api/evidence/audits/${encodeURIComponent(audit.id)}/export`} download><Download size={15} /> Export JSON</a>
        } />
        <p className="record-content-hash">Saved method · {audit.certificate.version}</p>
        <p className="record-content-hash mono">Content hash · {audit.certificate.content_hash}</p>
        {showEvidence && <div className="record-source-links">{audit.evidence.map((record) => <button className="text-button mono" key={record.hash} onClick={() => showEvidence(record.hash)}>
          Source {shorten(record.hash, 7)} <ArrowUpRight size={12} />
        </button>)}</div>}
        <details className="record-token-quantities"><summary>Inspect token quantities in this set</summary><pre>{JSON.stringify(audit.metrics.asset_net_quantities_raw ?? { status: "unknown" }, null, 2)}</pre></details>
      </section>
    </>
  );
}

export function EvidenceAuditView({ state, busy, run, navigate, showEvidence }: Actions & { showEvidence: (hash: string) => void }) {
  const [selectedId, setSelectedId] = useState("");
  const [bundle, setBundle] = useState<Record<string, unknown> | null>(null);
  const [filename, setFilename] = useState("");
  const [error, setError] = useState("");
  const [loadingExample, setLoadingExample] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const audits = state.evidence_audits ?? [];
  const audit = audits.find((item) => item.id === selectedId) ?? audits[0];
  const perform = async (records: Record<string, unknown>) => {
    const result = await run("record-audit", "/evidence/audit", records, "POST", "Record audit saved. Its scope remains separate from complete wallet qualification.") as EvidenceAudit | undefined;
    if (result?.id || result?.audit_id) setSelectedId(result.id ?? result.audit_id ?? "");
  };
  const example = async () => {
    setError("");
    setLoadingExample(true);
    try { await perform(await api<Record<string, unknown>>("/evidence/example")); }
    catch (issue) { setError(issue instanceof Error ? issue.message : "The reviewed example could not be read."); }
    finally { setLoadingExample(false); }
  };
  return <>
    <div className="report-navigation"><button className="text-button" onClick={() => navigate("scan")}><ArrowLeft size={15} /> Back to advanced manual audit</button></div>
    <section className="panel record-import-panel">
      <SectionHeading title="Audit saved raw transaction records" subtitle="Read-only checks on a supplied JSON record bundle. No provider reads or credits are used." />
      <div className="record-import-content">
        <p>Choose up to 20 raw transaction records in a bundle no larger than 4 MiB. The audit checks the enumerated records, fees, owned-account quantities, and native balance equations. It does not turn a transaction sample into complete wallet history.</p>
        <div className="record-import-actions">
          <Button variant="secondary" icon={Upload} disabled={!!busy || loadingExample} onClick={() => fileRef.current?.click()}>Choose record bundle</Button>
          <Button variant="secondary" icon={FlaskConical} disabled={!!busy} busy={loadingExample} onClick={example}>Audit reviewed example</Button>
          <a className="text-button" href="/api/evidence/example" download><Download size={14} /> Download example bundle</a>
          <input ref={fileRef} type="file" accept=".json,application/json" className="visually-hidden" aria-label="Saved transaction record bundle" onChange={async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            setError(""); setBundle(null); setFilename("");
            try {
              if (file.size > 4 * 1024 * 1024) throw new Error("Transaction record files must be no larger than 4 MiB.");
              const records = parseRawEvidenceBundle(await file.text());
              setBundle(records); setFilename(file.name);
            } catch (issue) { setError(issue instanceof Error ? issue.message : "This transaction record file could not be read."); }
          }} />
        </div>
        {error && <div className="inline-alert" role="alert"><CircleHelp size={16} />{error}</div>}
        {bundle && <div className="record-selected-file"><span><FileJson size={17} />{filename} · {count((bundle.transactions as unknown[]).length)} supplied transactions</span><Button icon={Search} busy={busy === "record-audit"} disabled={!!busy || loadingExample} onClick={() => perform(bundle)}>Audit these records</Button></div>}
      </div>
    </section>
    {audits.length > 1 && <div className="record-audit-picker"><label htmlFor="saved-record-audit">Saved record audit</label><select id="saved-record-audit" value={audit?.id ?? ""} onChange={(event) => setSelectedId(event.target.value)}>{audits.map((item) => <option key={item.id} value={item.id}>{dateTime(item.created_at)} · {shorten(item.address, 5)}</option>)}</select></div>}
    {audit ? <EvidenceAuditResult audit={audit} currentMethodology={state.evidence_audit_methodology} showEvidence={showEvidence} /> : <section className="panel"><Empty title="Keep record checks separate from wallet conclusions" detail="The reviewed example demonstrates what can be reconstructed from raw records and which wallet-wide claims remain unknown." icon={FileJson} /></section>}
  </>;
}
