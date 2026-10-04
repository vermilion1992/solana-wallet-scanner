import type { Report } from "./types";
import { Badge, SectionHeading } from "./components";
import { shorten } from "./format";

type Facts = Record<string, unknown>;

function facts(value: unknown): Facts | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Facts)
    : undefined;
}

function sources(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((hash): hash is string => typeof hash === "string" && /^[a-f0-9]{64}$/.test(hash))
    : [];
}

function nativeAmount(value: unknown): string | undefined {
  if (typeof value !== "string" || !/^\d{1,20}$/.test(value)) return undefined;
  const amount = BigInt(value);
  if (amount > 18446744073709551615n) return undefined;
  const digits = amount.toString().padStart(10, "0");
  const fraction = digits.slice(-9).replace(/0+$/, "");
  return `${digits.slice(0, -9)}${fraction ? `.${fraction}` : ""} SOL`;
}

export function InventoryObservations({ report, currentWalletMethod, historyCurrent, showEvidence }: {
  report: Report;
  currentWalletMethod?: string;
  historyCurrent: boolean;
  showEvidence: (hash: string) => void;
}) {
  const wallet = facts(report.coverage.wallet_evidence);
  const inventory = facts(wallet?.inventory_observations);
  if (!inventory || sources(inventory.source_dependencies).length === 0) return null;
  const components = facts(inventory.components);
  const programs = facts(components?.token_programs);
  const current = historyCurrent && report.source === "live" && !report.preview &&
    wallet?.version === currentWalletMethod && inventory.version === "current-inventory-evidence-v1";
  const rows = [
    ["Native SOL", facts(components?.native_lamports)],
    ["Legacy token accounts", facts(programs?.TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA)],
    ["Token2022 accounts", facts(programs?.TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb)],
  ] as const;
  const combined = current && facts(components?.same_slot_inventory)?.state === "PASS";
  return <section className="panel" data-inventory-observations={current ? "current" : "rebuild_required"}>
    <SectionHeading title="Archived balance snapshots"
      subtitle="Balances recorded in supplied evidence. Reporting-period balances and profit need separate evidence."
      action={<Badge value="partial">Archived observations</Badge>} />
    {!current && <p className="small-note">Rebuild from saved records to use the current interpretation.</p>}
    <div className="checks-list">
      {rows.map(([title, check]) => {
        const known = current && check?.state === "PASS";
        const observations = Array.isArray(check?.observations)
          ? check.observations.flatMap((value) => facts(value) ? [facts(value)!] : []) : [];
        return <div className="check-row" key={title} data-inventory-component={title}>
          <div>
            <strong>{title}</strong>
            {known && observations.length > 0 ? observations.map((point, index) => {
              const slot = typeof point.slot === "number" && Number.isSafeInteger(point.slot) && point.slot >= 0
                ? point.slot.toLocaleString() : undefined;
              const amount = title === "Native SOL" ? nativeAmount(point.lamports)
                : typeof point.account_count === "number" && Number.isSafeInteger(point.account_count) && point.account_count >= 0
                  ? `${point.account_count.toLocaleString()} ${point.account_count === 1 ? "account" : "accounts"}` : undefined;
              return <p key={index}>{amount && slot ? `${amount} · Slot ${slot}` : "Unknown"}</p>;
            }) : <p>Unknown</p>}
            {sources(check?.evidence).slice(0, 3).map((hash) => <button className="text-button mono"
              onClick={() => showEvidence(hash)} key={hash}>Source {shorten(hash, 5)}</button>)}
          </div>
          <Badge value={known ? "partial" : "unknown"}>{known ? "Observed" : "Unknown"}</Badge>
        </div>;
      })}
    </div>
    <p className="small-note">{combined
      ? "These observations share an exact slot. Historical evidence is still required for reporting-period balances."
      : "These observations do not establish one combined wallet balance. Their slots differ or a required source is missing."}</p>
    <p className="small-note">Token-account lamports are separate from token units and market value. These snapshots do not establish complete wallet history or profit.</p>
  </section>;
}
