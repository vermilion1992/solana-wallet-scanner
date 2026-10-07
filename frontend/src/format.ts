export const shorten = (address: string, head = 6) =>
  address.length > head * 2 + 3
    ? `${address.slice(0, head)}…${address.slice(-head)}`
    : address;
export const date = (value?: string) =>
  value
    ? new Date(value).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC",
      })
    : "Not set";
export const dateTime = (value?: string) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        timeZone: "UTC",
      })
    : "Not set";
export const count = (value: number | undefined) =>
  (value ?? 0).toLocaleString();
export const label = (value: string) =>
  value.replace(/_/g, " ").replace(/\b\w/g, (x) => x.toUpperCase());
export function decimal(value: string | null | undefined, places = 2): string {
  if (
    value === null ||
    value === undefined ||
    !/^[+-]?\d+(?:\.\d+)?$/.test(value)
  )
    return value ?? "—";
  const negative = value.startsWith("-");
  const raw = value.replace(/^[+-]/, "");
  const [whole, fraction = ""] = raw.split(".");
  const precision = Math.max(0, Math.min(100, Math.trunc(places)));
  const scale = 10n ** BigInt(precision);
  let rounded = BigInt(
    whole + fraction.slice(0, precision).padEnd(precision, "0"),
  );
  // Round the absolute exact decimal half up, without floating-point conversion.
  if ((fraction[precision] ?? "0") >= "5") rounded += 1n;
  const integer = (rounded / scale).toString();
  const significant = precision
    ? (rounded % scale).toString().padStart(precision, "0").replace(/0+$/, "")
    : "";
  return `${negative && rounded !== 0n ? "-" : ""}${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${significant ? `.${significant}` : ""}`;
}
// Values stay decimal strings. This comparator never uses binary floating point.
export const WORKSHEET_LABEL =
  "worksheet total, partial coverage, not independently audited";

export function joinAmount(
  amount: string | null | undefined,
  unit?: string | null,
): string | null {
  if (amount == null || amount === "") return null;
  const trimmedUnit = (unit || "").trim();
  return trimmedUnit ? `${amount} ${trimmedUnit}` : String(amount);
}

export function formatWorksheetTotal(
  amount: string | null | undefined,
  unit?: string | null,
): string | null {
  const joined = joinAmount(amount, unit);
  return joined ? `${joined} (${WORKSHEET_LABEL})` : null;
}

function atomicScale(unit?: string | null): bigint {
  return unit === "USDC" ? 1_000_000n : 1_000_000_000n;
}

const CANONICAL_AMOUNT = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;

export function parseCanonicalAmount(value: unknown): string | null {
  if (typeof value !== "string" || !CANONICAL_AMOUNT.test(value)) return null;
  return value;
}

export function quantizeToAtomics(value: unknown, unit?: string | null): bigint | null {
  const canonical = parseCanonicalAmount(value);
  if (canonical == null) return null;
  const scale = atomicScale(unit);
  const fracPlaces = Number(scale.toString().length - 1);
  const negative = canonical.startsWith("-");
  const [whole, fraction = ""] = canonical.replace(/^-/, "").split(".");
  const kept = fraction.slice(0, fracPlaces).padEnd(fracPlaces, "0");
  const rest = fraction.slice(fracPlaces);
  let atomics = BigInt(`${whole || "0"}${kept}` || "0");
  if (rest) {
    const next = Number(rest[0] || "0");
    const tail = rest.slice(1);
    const tailNonZero = [...tail].some((digit) => digit !== "0");
    const exactHalf = next === 5 && !tailNonZero;
    const roundUp = next > 5 || (next === 5 && tailNonZero) || (exactHalf && atomics % 2n === 1n);
    if (roundUp) atomics += 1n;
  }
  return negative ? -atomics : atomics;
}

export function amountsAgreeWithinTolerance(
  left?: unknown,
  right?: unknown,
  unit?: string | null,
  tolerance = 2n,
): boolean {
  if (parseCanonicalAmount(left) == null || parseCanonicalAmount(right) == null) return false;
  const a = quantizeToAtomics(left, unit);
  const b = quantizeToAtomics(right, unit);
  if (a == null || b == null) return false;
  const delta = a - b;
  return (delta < 0n ? -delta : delta) <= tolerance;
}

export function formatAuditorConfirmation(
  appNet?: string | null,
  auditorNet?: string | null,
  unit?: string | null,
): string | null {
  if (parseCanonicalAmount(appNet) == null || parseCanonicalAmount(auditorNet) == null) return null;
  const resolvedUnit = unit || "SOL";
  const auditor = joinAmount(auditorNet, resolvedUnit);
  if (amountsAgreeWithinTolerance(appNet, auditorNet, resolvedUnit)) {
    return resolvedUnit === "USDC"
      ? `auditor confirms within 2 USDC base units: ${auditor}`
      : `auditor confirms within 2 lamports: ${auditor}`;
  }
  const headline = joinAmount(appNet, resolvedUnit);
  return `aggregate rounding bridge (not within 2 ${resolvedUnit === "USDC" ? "USDC base units" : "lamports"}): app ${headline} vs auditor ${auditor}`;
}

export function formatCompletedEpisodeHeadline(input: {
  appNet?: string | null;
  appUnit?: string | null;
  independentlyAudited?: boolean | null;
  auditorNet?: string | null;
  auditorUnit?: string | null;
  auditorConfirmation?: string | null;
}): string | null {
  const headline = joinAmount(input.appNet, input.appUnit);
  if (!headline) return null;
  let text = `${headline} (completed-episode net)`;
  if (input.independentlyAudited && input.auditorNet != null && input.auditorNet !== "") {
    const derived = formatAuditorConfirmation(input.appNet, input.auditorNet, input.auditorUnit || input.appUnit);
    if (derived) text += `; ${derived}`;
  }
  return text;
}

export function formatWorksheetEpisodeBridge(input: {
  worksheet?: string | null;
  episode?: string | null;
  worksheet_total?: string | null;
  completed_episode_net?: string | null;
  bridge?: string | null;
  unit?: string | null;
} | null | undefined): string | null {
  if (!input || input.bridge == null || input.bridge === "") return null;
  const unit = input.unit || "";
  const worksheet = input.worksheet_total ?? input.worksheet;
  const episode = input.completed_episode_net ?? input.episode;
  return `worksheet-vs-completed-episode bridge ${input.bridge}${unit ? ` ${unit}` : ""} (worksheet ${worksheet || "—"} − episode ${episode || "—"}; worksheet is not the qualifying value)`;
}

type ComparisonBridge = {
  agree?: boolean;
  unit?: string | null;
  membership?: {
    one_to_one?: boolean;
    agree?: boolean;
    app?: { mint?: string | null; close_signature?: string | null; close?: string | null };
    auditor?: { mint?: string | null; close_signature?: string | null; close?: string | null };
  };
  components?: Record<string, { agree?: boolean; app?: string | null; auditor?: string | null }>;
};

function bridgeIdentity(side?: { mint?: string | null; close_signature?: string | null; close?: string | null } | null) {
  const mint = side?.mint;
  const close = side?.close_signature || side?.close;
  if (!mint || !close) return null;
  return `${mint}|${close}`;
}

function bridgeComponentKey(bridge: ComparisonBridge) {
  const amounts = ["acquisition", "proceeds", "costs", "net"].map((name) => {
    const row = bridge.components?.[name];
    return `${name}:${row?.app ?? ""}:${row?.auditor ?? ""}`;
  });
  return `${bridgeIdentity(bridge.membership?.app)}|${bridgeIdentity(bridge.membership?.auditor)}|${bridge.unit ?? ""}|${amounts.join("|")}`;
}

function ledgerComponent(episode: Record<string, unknown> | undefined, name: string): string | null {
  const keys: Record<string, string[]> = {
    acquisition: ["acquisition", "basis", "basis_sol"],
    proceeds: ["proceeds", "proceeds_sol"],
    costs: ["costs", "verified_costs", "verified_costs_sol"],
    net: ["net", "pnl", "net_profit_sol"],
  };
  for (const key of keys[name] || []) {
    const value = episode?.[key];
    if (value != null && value !== "") return String(value);
  }
  return null;
}

function bridgeAppMatchesLedger(
  bridge: ComparisonBridge,
  episode: { mint?: string | null; close_signature?: string | null; close?: string | null; unit?: string | null; settlement_asset?: string | null } & Record<string, unknown>,
): boolean {
  const unit = bridge.unit;
  const ledgerUnit = episode.unit || episode.settlement_asset;
  if (!unit || !ledgerUnit || unit !== ledgerUnit) return false;
  return ["acquisition", "proceeds", "costs", "net"].every((name) => (
    amountsAgreeWithinTolerance(bridge.components?.[name]?.app, ledgerComponent(episode, name), ledgerUnit)
  ));
}

function canonicalComparisonBridges(audit: {
  component_bridges?: ComparisonBridge[];
  episodes?: Array<{ component_bridge?: ComparisonBridge }>;
} | null | undefined): ComparisonBridge[] | null {
  const listed = (audit?.component_bridges || []).filter(Boolean);
  const fromEpisodes = (audit?.episodes || [])
    .map((episode) => episode.component_bridge)
    .filter(Boolean) as ComparisonBridge[];
  if (listed.length && fromEpisodes.length) {
    const left = [...listed.map(bridgeComponentKey)].sort();
    const right = [...fromEpisodes.map(bridgeComponentKey)].sort();
    if (left.length !== right.length || left.some((key, index) => key !== right[index])) return null;
    return listed;
  }
  return listed.length ? listed : fromEpisodes;
}

function sumBridgeAuditorNets(bridges: ComparisonBridge[]): { total: string; unit: string } | null {
  let total = 0n;
  let unit: string | null = null;
  for (const bridge of bridges) {
    if (!bridge.unit) return null;
    if (unit == null) unit = bridge.unit;
    else if (unit !== bridge.unit) return null;
    const auditor = quantizeToAtomics(bridge.components?.net?.auditor, bridge.unit);
    if (auditor == null) return null;
    total += auditor;
  }
  if (!unit) return null;
  const scale = Number(atomicScale(unit).toString().length - 1);
  const negative = total < 0n;
  const abs = negative ? -total : total;
  const whole = abs / atomicScale(unit);
  const frac = (abs % atomicScale(unit)).toString().padStart(scale, "0").replace(/0+$/, "");
  const text = `${negative ? "-" : ""}${whole.toString()}${frac ? `.${frac}` : ""}`;
  return { total: text || "0", unit };
}

function ledgerNetAndUnit(
  ledger: Array<{ unit?: string | null; settlement_asset?: string | null; net?: unknown }>,
): { total: string; unit: string } | null {
  let total = 0n;
  let unit: string | null = null;
  for (const row of ledger) {
    const rowUnit = row.unit || row.settlement_asset;
    if (!rowUnit) return null;
    if (unit == null) unit = rowUnit;
    else if (unit !== rowUnit) return null;
    const net = quantizeToAtomics(row.net, rowUnit);
    if (net == null) return null;
    total += net;
  }
  if (!unit) return null;
  const scale = Number(atomicScale(unit).toString().length - 1);
  const negative = total < 0n;
  const abs = negative ? -total : total;
  const whole = abs / atomicScale(unit);
  const frac = (abs % atomicScale(unit)).toString().padStart(scale, "0").replace(/0+$/, "");
  return { total: `${negative ? "-" : ""}${whole.toString()}${frac ? `.${frac}` : ""}` || "0", unit };
}

function storedHeadlineMatches(
  audit: {
    independently_audited_episode_net?: string | null;
    independently_audited_episode_net_unit?: string | null;
    app_completed_episode_net?: string | null;
    app_completed_episode_net_unit?: string | null;
  },
  ledger: Array<{ unit?: string | null; settlement_asset?: string | null; net?: unknown }>,
  bridges: ComparisonBridge[],
): boolean {
  const auditor = sumBridgeAuditorNets(bridges);
  const app = ledgerNetAndUnit(ledger);
  if (!auditor || !app || auditor.unit !== app.unit) return false;
  if (audit.independently_audited_episode_net_unit && audit.independently_audited_episode_net_unit !== auditor.unit) return false;
  if (audit.app_completed_episode_net_unit && audit.app_completed_episode_net_unit !== app.unit) return false;
  if (
    audit.independently_audited_episode_net != null
    && audit.independently_audited_episode_net !== ""
    && !amountsAgreeWithinTolerance(audit.independently_audited_episode_net, auditor.total, auditor.unit)
  ) return false;
  if (
    audit.app_completed_episode_net != null
    && audit.app_completed_episode_net !== ""
    && !amountsAgreeWithinTolerance(audit.app_completed_episode_net, app.total, app.unit)
  ) return false;
  return true;
}

export function certificateComparisonProof(
  audit: {
    one_to_one_membership?: boolean;
    independently_audited_episode_net?: string | null;
    independently_audited_episode_net_unit?: string | null;
    app_completed_episode_net?: string | null;
    app_completed_episode_net_unit?: string | null;
    component_bridges?: ComparisonBridge[];
    episodes?: Array<{ component_bridge?: ComparisonBridge }>;
  } | null | undefined,
  ledger?: Array<{ mint?: string | null; close_signature?: string | null; close?: string | null; unit?: string | null; settlement_asset?: string | null } & Record<string, unknown>> | null,
): boolean {
  if (!audit || audit.one_to_one_membership !== true) return false;
  if (!ledger || !ledger.length) return false;
  const bridges = canonicalComparisonBridges(audit);
  if (!bridges || !bridges.length || bridges.length !== ledger.length) return false;
  const byId = new Map<string, (typeof ledger)[number]>();
  for (const item of ledger) {
    const id = bridgeIdentity(item);
    if (!id || byId.has(id)) return false;
    byId.set(id, item);
  }
  const matched = new Set<string>();
  for (const bridge of bridges) {
    const appId = bridgeIdentity(bridge.membership?.app);
    const auditorId = bridgeIdentity(bridge.membership?.auditor);
    if (!appId || !auditorId || appId !== auditorId) return false;
    const episode = byId.get(appId);
    if (!episode || matched.has(appId)) return false;
    matched.add(appId);
    const unit = bridge.unit;
    if (!unit) return false;
    const amountsOk = ["acquisition", "proceeds", "costs", "net"].every((name) => {
      const row = bridge.components?.[name];
      return amountsAgreeWithinTolerance(row?.app, row?.auditor, unit);
    });
    if (!amountsOk || !bridgeAppMatchesLedger(bridge, episode)) return false;
  }
  if (matched.size !== byId.size) return false;
  return storedHeadlineMatches(audit, ledger, bridges);
}

function fingerprintId(value: unknown): string | null {
  if (!value) return null;
  if (typeof value === "string") return value;
  if (typeof value === "object" && value && "fingerprint" in value) {
    const id = (value as { fingerprint?: unknown }).fingerprint;
    return typeof id === "string" && id ? id : null;
  }
  return null;
}

export function coverageStatusDisplay(source?: {
  coverage_status_display?: string | null;
  coverage_status?: string | null;
  research_profile?: { coverage_status_display?: string | null; coverage_status?: string | null } | null;
} | null): string {
  return (
    source?.research_profile?.coverage_status_display
    || source?.coverage_status_display
    || source?.research_profile?.coverage_status
    || source?.coverage_status
    || "blocked_unknown_denominator"
  );
}

export function completedEpisodeFields(source?: {
  corpus_kind?: string | null;
  coverage_status_display?: string | null;
  coverage_status?: string | null;
  completed_episode_ledger?: Array<{ mint?: string | null; close_signature?: string | null; close?: string | null; unit?: string | null; settlement_asset?: string | null; net?: unknown }>;
  research_profile?: Record<string, unknown> | null;
  independent_audit?: {
    independently_audited?: boolean;
    independently_audited_episode_net?: string | null;
    independently_audited_episode_net_unit?: string | null;
    app_completed_episode_net?: string | null;
    app_completed_episode_net_unit?: string | null;
    content_fingerprint?: unknown;
    fingerprint?: unknown;
    fingerprintless_not_certifying?: boolean;
    auditor_confirmation?: string | null;
    one_to_one_membership?: boolean;
    component_bridges?: Array<Record<string, unknown>>;
    episodes?: Array<Record<string, unknown>>;
  } | null;
} | null) {
  const profile = source?.research_profile || {};
  const topLevelMissing = !source || !("independent_audit" in source);
  const audit = ((topLevelMissing ? (profile.independent_audit as Record<string, unknown> | undefined) : source?.independent_audit) || {}) as {
    independently_audited?: boolean;
    independently_audited_episode_net?: string | null;
    independently_audited_episode_net_unit?: string | null;
    app_completed_episode_net?: string | null;
    app_completed_episode_net_unit?: string | null;
    content_fingerprint?: unknown;
    fingerprint?: unknown;
    fingerprintless_not_certifying?: boolean;
    auditor_confirmation?: string | null;
    not_a_genuine_research_wallet?: boolean;
    one_to_one_membership?: boolean;
    component_bridges?: ComparisonBridge[];
    episodes?: Array<{ component_bridge?: ComparisonBridge }>;
  };
  const typedAudit = audit as typeof audit & {
    independently_audited_episode_net?: string | null;
    independently_audited_episode_net_unit?: string | null;
    app_completed_episode_net?: string | null;
    app_completed_episode_net_unit?: string | null;
    component_bridges?: ComparisonBridge[];
    episodes?: Array<{ component_bridge?: ComparisonBridge }>;
  };
  const ledger = (
    source?.completed_episode_ledger
    ?? (profile.completed_episode_ledger as Array<{ mint?: string | null; close_signature?: string | null; close?: string | null; unit?: string | null; settlement_asset?: string | null; net?: unknown }> | undefined)
    ?? null
  );
  const contradiction = profile.ledger_summary_contradiction === true;
  const currentFingerprint = fingerprintId(profile.audit_fingerprint) || fingerprintId((source as { audit_fingerprint?: unknown } | null)?.audit_fingerprint);
  const certificateFingerprint = fingerprintId(audit.content_fingerprint) || fingerprintId(audit.fingerprint);
  const fingerprintMatches = Boolean(currentFingerprint && certificateFingerprint && currentFingerprint === certificateFingerprint);
  const proof = certificateComparisonProof(audit, ledger);
  const bridges = canonicalComparisonBridges(audit);
  const derivedAuditor = bridges ? sumBridgeAuditorNets(bridges) : null;
  const derivedApp = Array.isArray(ledger) ? ledgerNetAndUnit(ledger) : null;
  const appUnit = derivedApp?.unit
    ?? (profile.completed_episode_net_unit as string | null | undefined)
    ?? audit.app_completed_episode_net_unit;
  const auditorUnit = derivedAuditor?.unit ?? audit.independently_audited_episode_net_unit;
  const profileUnit = profile.completed_episode_net_unit as string | null | undefined;
  const unitsMatch = (
    (!auditorUnit || !appUnit || auditorUnit === appUnit)
    && (!profileUnit || !auditorUnit || profileUnit === auditorUnit)
    && (!audit.independently_audited_episode_net_unit || !appUnit || audit.independently_audited_episode_net_unit === appUnit)
    && (!audit.app_completed_episode_net_unit || !auditorUnit || audit.app_completed_episode_net_unit === auditorUnit)
  );
  const certifying = fingerprintMatches
    && audit.fingerprintless_not_certifying !== true
    && !contradiction
    && unitsMatch
    && proof;
  const derivedConfirmation = certifying && derivedApp && derivedAuditor
    ? formatAuditorConfirmation(derivedApp.total, derivedAuditor.total, derivedApp.unit)
    : null;
  return {
    appNet: derivedApp?.total
      ?? (profile.completed_episode_net as string | null | undefined)
      ?? (certifying ? audit.app_completed_episode_net : null),
    appUnit: appUnit ?? null,
    independentlyAudited: Boolean(audit.independently_audited) && certifying,
    auditorNet: certifying ? (derivedAuditor?.total ?? null) : null,
    auditorUnit: certifying ? (derivedAuditor?.unit ?? null) : null,
    auditorConfirmation: derivedConfirmation,
  };
}

export function rankedPhonePnlText(row: {
  funnel?: { B?: { scoped_pnl?: string | null; scoped_pnl_unit?: string | null; completed_known_cost_positions?: number } } | null;
  research_profile?: Record<string, unknown> | null;
  completed_episode_ledger?: Array<{ mint?: string | null; close_signature?: string | null; close?: string | null }>;
  independent_audit?: Record<string, unknown> | null;
} | null | undefined): string {
  const fields = completedEpisodeFields(row);
  const profile = row?.research_profile || {};
  const positions = Number(profile.completed_known_cost_positions ?? row?.funnel?.B?.completed_known_cost_positions ?? 0);
  if (positions >= 1 && (row?.funnel?.B?.scoped_pnl || profile.scoped_pnl)) {
    return formatCompareSidePnl({
      completedNet: fields.appNet ?? (profile.completed_episode_net as string | null | undefined),
      completedUnit: fields.appUnit ?? (profile.completed_episode_net_unit as string | null | undefined),
      independentlyAudited: fields.independentlyAudited,
      auditorNet: fields.auditorNet,
      auditorUnit: fields.auditorUnit,
      worksheet: row?.funnel?.B?.scoped_pnl || (profile.scoped_pnl as string | null | undefined),
      worksheetUnit: row?.funnel?.B?.scoped_pnl_unit || (profile.scoped_pnl_unit as string | null | undefined),
    });
  }
  if (profile.matched_fragment_pnl) {
    return `matched-fragment ${profile.matched_fragment_pnl} ${profile.matched_fragment_unit || ""}`;
  }
  return "no completed-episode net";
}

export function rankedDesktopPnlText(row: {
  funnel?: { B?: { scoped_pnl?: string | null; scoped_pnl_unit?: string | null; completed_known_cost_positions?: number } } | null;
  research_profile?: Record<string, unknown> | null;
  completed_episode_ledger?: Array<{ mint?: string | null; close_signature?: string | null; close?: string | null }>;
  independent_audit?: Record<string, unknown> | null;
} | null | undefined): string {
  const fields = completedEpisodeFields(row);
  const profile = row?.research_profile || {};
  const positions = Number(profile.completed_known_cost_positions ?? row?.funnel?.B?.completed_known_cost_positions ?? 0);
  if (positions >= 1 && row?.funnel?.B?.scoped_pnl) {
    return formatCompareSidePnl({
      completedNet: fields.appNet ?? (profile.completed_episode_net as string | null | undefined),
      completedUnit: fields.appUnit ?? (profile.completed_episode_net_unit as string | null | undefined),
      independentlyAudited: fields.independentlyAudited,
      auditorNet: fields.auditorNet,
      auditorUnit: fields.auditorUnit,
      worksheet: row.funnel.B.scoped_pnl,
      worksheetUnit: row.funnel.B.scoped_pnl_unit,
    });
  }
  if (profile.matched_fragment_pnl) {
    return `matched-fragment ${profile.matched_fragment_pnl} ${profile.matched_fragment_unit || ""}`;
  }
  return "unverified";
}

const POSITIVE_CATEGORIES = new Set([
  "positive_matched_position_evidence",
  "positive_net_realised_over_window",
  "profitable_account_performance",
]);

function displayedLedger(
  source?: {
    completed_episode_ledger?: unknown;
    research_profile?: Record<string, unknown> | null;
  } | null,
): unknown[] | null {
  const profile = source?.research_profile || {};
  const ledger = source?.completed_episode_ledger ?? profile.completed_episode_ledger ?? null;
  return Array.isArray(ledger) ? ledger : null;
}

export function authoritativeFunnel(source?: {
  funnel?: { A?: { state?: string }; B?: { state?: string }; C?: { state?: string; criteria_met?: boolean } } | null;
  completed_episode_ledger?: unknown;
  research_profile?: Record<string, unknown> | null;
} | null) {
  const profile = source?.research_profile || {};
  const profileFunnel = (profile.funnel as {
    A?: { state?: string };
    B?: { state?: string };
    C?: { state?: string; criteria_met?: boolean };
  } | undefined) || null;
  const funnel = profileFunnel || source?.funnel || {};
  const ledger = displayedLedger(source);
  const completed = ledger ? ledger.length : Number(profile.completed_known_cost_positions ?? 0);
  const criteriaMet = profile.criteria_met === true;
  const stalePositive = completed < 1 || !ledger || ledger.length < 1 || !criteriaMet;
  if (funnel.C?.state === "MET" && stalePositive) {
    return {
      ...funnel,
      B: funnel.B?.state === "ESTABLISHED" && (!ledger || ledger.length < 1)
        ? { ...(funnel.B || {}), state: "NOT_ESTABLISHED" }
        : funnel.B,
      C: { ...(funnel.C || {}), state: "NOT_MET", criteria_met: false },
    };
  }
  return funnel;
}

export function authoritativeCategory(source?: {
  qualification_category?: { category?: string; evidence_class?: number } | null;
  completed_episode_ledger?: unknown;
  research_profile?: Record<string, unknown> | null;
} | null) {
  const profile = source?.research_profile || {};
  const category = (
    source?.qualification_category
    || (profile.qualification_category as { category?: string; evidence_class?: number } | undefined)
    || {}
  );
  const ledger = displayedLedger(source);
  const completed = ledger ? ledger.length : Number(profile.completed_known_cost_positions ?? 0);
  if ((completed < 1 || !ledger || ledger.length < 1) && category.category && POSITIVE_CATEGORIES.has(category.category)) {
    return { ...category, category: "analysed_incomplete" };
  }
  return category;
}

export function reportHeadlineText(report: Parameters<typeof completedEpisodeFields>[0]): string | null {
  return formatCompletedEpisodeHeadline(completedEpisodeFields(report));
}

export function compareSideText(policy: {
  completedNet?: string | null;
  completedUnit?: string | null;
  independentlyAudited?: boolean | null;
  auditorNet?: string | null;
  auditorUnit?: string | null;
  worksheet?: string | null;
  worksheetUnit?: string | null;
}): string {
  return formatCompareSidePnl(policy);
}

export function formatCompareSidePnl(input: {
  completedNet?: string | null;
  completedUnit?: string | null;
  independentlyAudited?: boolean | null;
  auditorNet?: string | null;
  auditorUnit?: string | null;
  worksheet?: string | null;
  worksheetUnit?: string | null;
}): string {
  const episode = formatCompletedEpisodeHeadline({
    appNet: input.completedNet,
    appUnit: input.completedUnit,
    independentlyAudited: input.independentlyAudited,
    auditorNet: input.auditorNet,
    auditorUnit: input.auditorUnit,
  });
  const worksheet = formatWorksheetTotal(input.worksheet, input.worksheetUnit);
  return [episode, worksheet].filter(Boolean).join("; ") || "—";
}

export function listRealisedProfit(report: {
  source?: string;
  metrics?: { profit_sol?: { status?: string; value?: string | null } | null };
  worksheet?: { total_profit_sol?: string | null } | null;
}): { value: string | null; basis: "wallet" | "reconstructed-subset" } {
  const subset = report.worksheet?.total_profit_sol;
  if (report.source === "mass-search" && subset) {
    return { value: subset, basis: "reconstructed-subset" };
  }
  const metric = report.metrics?.profit_sol;
  if (metric?.status === "known" && metric.value != null && metric.value !== "") {
    return { value: metric.value, basis: "wallet" };
  }
  return { value: null, basis: "wallet" };
}
export function compareDecimal(a?: string | null, b?: string | null): number {
  if (a === null || a === undefined)
    return b === null || b === undefined ? 0 : 1;
  if (b === null || b === undefined) return -1;
  if (!/^-?\d+(?:\.\d+)?$/.test(a) || !/^-?\d+(?:\.\d+)?$/.test(b))
    return a.localeCompare(b);
  const parts = (s: string) => {
    const [integer, fractional = ""] = s.replace(/^-/, "").split(".");
    return { negative: s.startsWith("-"), integer, fractional };
  };
  const x = parts(a),
    y = parts(b),
    places = Math.max(x.fractional.length, y.fractional.length);
  const left =
    BigInt(x.integer + x.fractional.padEnd(places, "0")) *
    (x.negative ? -1n : 1n);
  const right =
    BigInt(y.integer + y.fractional.padEnd(places, "0")) *
    (y.negative ? -1n : 1n);
  return left < right ? -1 : left > right ? 1 : 0;
}
const alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
export function validAddress(address: string): boolean {
  if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(address)) return false;
  let value = 0n;
  for (const char of address)
    value = value * 58n + BigInt(alphabet.indexOf(char));
  let bytes = 0;
  while (value > 0n) {
    bytes++;
    value >>= 8n;
  }
  return bytes + (address.match(/^1*/)?.[0].length ?? 0) === 32;
}
export function parseAddresses(input: string): {
  addresses: string[];
  invalid: string[];
} {
  let tokens: string[] = [];
  if (/^[\[{]/.test(input.trim())) {
    try {
      const data = JSON.parse(input);
      const entries = Array.isArray(data)
        ? data
        : (data.addresses ?? data.wallets ?? []);
      if (!Array.isArray(entries))
        return {
          addresses: [],
          invalid: ["JSON must contain an array of addresses."],
        };
      tokens = entries
        .map((item) =>
          typeof item === "string"
            ? item
            : (item?.address ?? item?.wallet ?? ""),
        )
        .filter(Boolean);
    } catch {
      return {
        addresses: [],
        invalid: [
          "Invalid JSON. Use an address array or an object with an addresses array.",
        ],
      };
    }
  } else {
    const rows = input.split(/\r?\n/).filter((x) => x.trim());
    const csvRows = rows.map((row) =>
      (row.match(/(?:"(?:[^"]|"")*"|[^,;]+)(?:[,;]|$)/g) ?? [row]).map((cell) =>
        cell
          .replace(/[,;]$/, "")
          .trim()
          .replace(/^"|"$/g, "")
          .replace(/""/g, '"'),
      ),
    );
    const headerIndex = csvRows[0]?.findIndex((cell) =>
      /^(address|wallet|wallet_address)$/i.test(cell),
    );
    if (headerIndex !== undefined && headerIndex >= 0)
      tokens = csvRows
        .slice(1)
        .map((row) => row[headerIndex] ?? "")
        .filter(Boolean);
    else
      tokens = rows
        .flatMap((row) => row.split(/[\s,;]+/))
        .map((x) => x.replace(/^"|"$/g, ""))
        .filter(Boolean);
  }
  tokens = tokens.map((token) => String(token).trim()).filter(Boolean);
  const addresses = [...new Set(tokens.filter(validAddress))];
  const invalid = [...new Set(tokens.filter((token) => !validAddress(token)))];
  return { addresses, invalid };
}
