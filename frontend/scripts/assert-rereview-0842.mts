import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import {
  amountsAgreeWithinTolerance,
  certificateComparisonProof,
  completedEpisodeFields,
  quantizeToAtomics,
} from "../src/format.ts";
import {
  CompareCertificationView,
  RankedDesktopRow,
  RankedPhoneCard,
  ReportCertificationView,
} from "../src/researchSurfaces.ts";

function assert(condition: unknown, message: string) {
  if (!condition) throw new Error(message);
}

const casesPath = process.argv[2];
const cases = casesPath ? JSON.parse(readFileSync(casesPath, "utf8")) : {};

assert(quantizeToAtomics("1.0000000015", "SOL") === 1_000_000_002n, "half-even");
assert(amountsAgreeWithinTolerance("1", "1.000000003", "SOL") === false, "3 lamports reject");

function denyStale(html: string, label: string) {
  assert(!/auditor confirms/i.test(html), `${label} must not show auditor confirmation`);
  assert(!/positive matched position evidence/i.test(html), `${label} must not show stale positive category`);
  assert(!/positive_matched_position_evidence/i.test(html), `${label} must not stamp stale positive category`);
  assert(!/>C MET</i.test(html) && !/ · C MET/i.test(html) && !/Funnel C MET/i.test(html) && !/left C MET/i.test(html) && !/right C MET/i.test(html), `${label} must not show stale C=MET`);
  assert(!/data-funnel-c="MET"/i.test(html), `${label} data-funnel-c must not be MET`);
}

for (const key of Object.keys(cases)) {
  const row = cases[key];
  if (!row) continue;
  const audit = row.independent_audit || row.research_profile?.independent_audit;
  const ledger = row.completed_episode_ledger || row.research_profile?.completed_episode_ledger;
  if (key !== "valid") {
    if (row.expectProof !== true && audit) {
      assert(certificateComparisonProof(audit, ledger) === false, `${key} proof rejects`);
    }
    const fields = completedEpisodeFields(row);
    assert(fields.independentlyAudited === false, `${key} does not certify`);
    assert(fields.auditorConfirmation == null, `${key} has no auditor confirmation`);
    if (typeof row.auditorConfirmationForbidden === "string") {
      assert(
        !String(fields.auditorConfirmation || "").includes(row.auditorConfirmationForbidden),
        `${key} must not display stored confirmation ${row.auditorConfirmationForbidden}`,
      );
    }
  }
  if (key === "valid") continue;
  const phone = renderToStaticMarkup(createElement(RankedPhoneCard, { row }));
  const desktop = renderToStaticMarkup(createElement(RankedDesktopRow, { row }));
  const report = renderToStaticMarkup(createElement(ReportCertificationView, { report: row }));
  denyStale(phone, `${key} phone`);
  denyStale(desktop, `${key} desktop`);
  denyStale(report, `${key} report`);
  if (row.compare) {
    const compare = renderToStaticMarkup(createElement(CompareCertificationView, { compare: row.compare }));
    denyStale(compare, `${key} compare`);
  }
}

if (cases.valid) {
  const fields = completedEpisodeFields(cases.valid);
  assert(fields.independentlyAudited === true, "valid certificate still certifies");
}

console.log(JSON.stringify({ ok: true, mounted: true, cases: Object.keys(cases) }));
