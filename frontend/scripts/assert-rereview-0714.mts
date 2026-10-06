import {
  amountsAgreeWithinTolerance,
  certificateComparisonProof,
  compareSideText,
  completedEpisodeFields,
  quantizeToAtomics,
  rankedDesktopPnlText,
  rankedPhonePnlText,
  reportHeadlineText,
} from "../src/format.ts";

function assert(condition: unknown, message: string) {
  if (!condition) throw new Error(message);
}

import { readFileSync } from "node:fs";

const casesPath = process.argv[2];
const cases = casesPath ? JSON.parse(readFileSync(casesPath, "utf8")) : {};

assert(quantizeToAtomics("1", "SOL") === 1_000_000_000n, "SOL 1 quantize");
assert(quantizeToAtomics("1.0000000029", "SOL") === 1_000_000_003n, "SOL 1.0000000029 half-even away from even");
assert(amountsAgreeWithinTolerance("1", "1.0000000029", "SOL") === false, "SOL 1 vs 1.0000000029 outside 2 lamports");
assert(quantizeToAtomics("1.0000000015", "SOL") === 1_000_000_002n, "positive exact-half rounds to even 2");
assert(quantizeToAtomics("1.0000000005", "SOL") === 1_000_000_000n, "positive exact-half stays even 0");
assert(quantizeToAtomics("-1.0000000015", "SOL") === -1_000_000_002n, "negative exact-half rounds to even 2");
assert(quantizeToAtomics("-1.0000000005", "SOL") === -1_000_000_000n, "negative exact-half stays even 0");
assert(amountsAgreeWithinTolerance("1", "1.000000002", "SOL") === true, "2-lamport boundary agrees");
assert(amountsAgreeWithinTolerance("1", "1.000000003", "SOL") === false, "3-lamport boundary rejects");

if (cases.valid) {
  const fields = completedEpisodeFields(cases.valid);
  assert(fields.independentlyAudited === true, "valid certificate certifies");
  const phone = rankedPhonePnlText(cases.valid);
  const desktop = rankedDesktopPnlText(cases.valid);
  const report = reportHeadlineText(cases.valid) || "";
  const compare = compareSideText({
    completedNet: fields.appNet,
    completedUnit: fields.appUnit,
    independentlyAudited: fields.independentlyAudited,
    auditorNet: fields.auditorNet,
    auditorUnit: fields.auditorUnit,
    worksheet: cases.valid.research_profile?.scoped_pnl,
    worksheetUnit: cases.valid.research_profile?.scoped_pnl_unit,
  });
  for (const [name, text] of [
    ["phone", phone],
    ["desktop", desktop],
    ["report", report],
    ["compare", compare],
  ] as const) {
    assert(!/auditor confirms/.test(text) || fields.independentlyAudited, `${name} auditor text only when certifying`);
  }
}

if (cases.an9s) {
  const fields = completedEpisodeFields(cases.an9s);
  const phone = rankedPhonePnlText(cases.an9s);
  const desktop = rankedDesktopPnlText(cases.an9s);
  const report = reportHeadlineText(cases.an9s) || "";
  const compare = compareSideText({
    completedNet: fields.appNet,
    completedUnit: fields.appUnit,
    independentlyAudited: fields.independentlyAudited,
    auditorNet: fields.auditorNet,
    auditorUnit: fields.auditorUnit,
    worksheet: cases.an9s.research_profile?.scoped_pnl,
    worksheetUnit: cases.an9s.research_profile?.scoped_pnl_unit,
  });
  for (const text of [phone, desktop, report, compare]) {
    assert(!/provisional research lead/i.test(text), "An9s surfaces are not a lead badge");
  }
  const coverage = cases.an9s.research_profile?.coverage_status_display || "";
  assert(coverage === "Coverage gate eligible; not a research lead.", "An9s coverage wording");
}

for (const key of ["duplicate", "removedAmounts", "alteredClose"]) {
  const row = cases[key];
  if (!row) continue;
  assert(certificateComparisonProof(row.independent_audit || row.research_profile?.independent_audit, row.completed_episode_ledger || row.research_profile?.completed_episode_ledger) === false, `${key} proof rejects`);
  const fields = completedEpisodeFields(row);
  assert(fields.independentlyAudited === false, `${key} does not certify`);
  assert(fields.auditorConfirmation == null, `${key} has no auditor confirmation`);
  const phone = rankedPhonePnlText(row);
  const desktop = rankedDesktopPnlText(row);
  const report = reportHeadlineText(row) || "";
  const compare = compareSideText({
    completedNet: fields.appNet,
    completedUnit: fields.appUnit,
    independentlyAudited: fields.independentlyAudited,
    auditorNet: fields.auditorNet,
    auditorUnit: fields.auditorUnit,
    worksheet: row.research_profile?.scoped_pnl,
    worksheetUnit: row.research_profile?.scoped_pnl_unit,
  });
  for (const [name, text] of [
    ["phone", phone],
    ["desktop", desktop],
    ["report", report],
    ["compare", compare],
  ] as const) {
    assert(!/auditor confirms/i.test(text), `${key} ${name} must not show auditor confirmation`);
  }
}

console.log(JSON.stringify({ ok: true, half_even: true, surfaces: true }));
