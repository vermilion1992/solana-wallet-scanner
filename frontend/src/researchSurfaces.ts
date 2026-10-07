import { createElement, type ReactNode } from "react";
import {
  authoritativeCategory,
  authoritativeFunnel,
  completedEpisodeFields,
  coverageStatusDisplay,
  formatCompletedEpisodeHeadline,
  formatCompareSidePnl,
  rankedDesktopPnlText,
  rankedPhonePnlText,
  shorten,
} from "./format.ts";
import type { RankedWorkflowRow, ResearchCompare } from "./types.ts";

type ReportLike = {
  address?: string;
  funnel?: RankedWorkflowRow["funnel"];
  qualification_category?: RankedWorkflowRow["qualification_category"];
  completed_episode_ledger?: RankedWorkflowRow["completed_episode_ledger"];
  independent_audit?: RankedWorkflowRow["independent_audit"];
  research_profile?: Record<string, unknown> | null;
};

export function RankedPhoneCard({
  row,
  shortlist,
  action,
}: {
  row: RankedWorkflowRow;
  shortlist?: ReactNode;
  action?: ReactNode;
}) {
  const coverage = coverageStatusDisplay(row);
  const fields = completedEpisodeFields(row);
  const funnel = authoritativeFunnel(row);
  const category = authoritativeCategory(row);
  const level = (row.qualification_level as { level?: string } | undefined)?.level
    || (row.research_profile?.qualification_level as { level?: string } | undefined)?.level
    || "insufficient_evidence";
  const inWindow = row.in_window_span?.hours != null ? ` · in-window ${String(row.in_window_span.hours)} h` : "";
  return createElement(
    "li",
    {
      "data-ranked-phone-card": "true",
      "data-history-required": row.history_required ? "true" : "false",
    },
    shortlist,
    createElement("strong", { className: "mono" }, shorten(row.address)),
    createElement(
      "p",
      { "data-funnel": "true", "data-funnel-c": funnel.C?.state || "—" },
      `Provider rank ${row.provider_rank ?? "—"} · A ${funnel.A?.state || "—"} · B ${funnel.B?.state || "—"} · C ${funnel.C?.state || "—"}`,
    ),
    createElement(
      "p",
      null,
      `Provider trades ${row.trade_count ?? "unknown"} · ${row.capture_available ? "cached capture" : row.report_id ? "analysed" : "History required — not analysed"}${inWindow}`,
    ),
    createElement(
      "p",
      { "data-qualification-category": category.category || "not_evaluated" },
      `Qualification ${String(category.category || "not_evaluated").replaceAll("_", " ")} · screening separate`,
    ),
    createElement(
      "p",
      { "data-qualification-level": level },
      `qualification_level ${level}`,
    ),
    createElement(
      "p",
      { "data-coverage-status": coverage },
      `coverage_status ${coverage}`,
    ),
    createElement(
      "p",
      {
        "data-ranked-pnl": "true",
        "data-independently-audited": fields.independentlyAudited ? "true" : "false",
      },
      rankedPhonePnlText(row),
    ),
    (row.blocking_reason || row.research_profile?.blocking_reason)
      ? createElement("p", { "data-blocking-reason": "true" }, `blocking_reason ${row.blocking_reason || row.research_profile?.blocking_reason}`)
      : null,
    createElement("p", null, row.funnel?.next_action?.detail || "Browse cached row only."),
    fields.auditorConfirmation
      ? createElement("p", { "data-auditor-confirmation": "true" }, fields.auditorConfirmation)
      : null,
    action,
  );
}

export function RankedDesktopRow({
  row,
  shortlist,
  action,
}: {
  row: RankedWorkflowRow;
  shortlist?: ReactNode;
  action?: ReactNode;
}) {
  const fields = completedEpisodeFields(row);
  const funnel = authoritativeFunnel(row);
  const category = authoritativeCategory(row);
  return createElement(
    "tr",
    {
      "data-ranked-desktop-row": "true",
      "data-history-required": row.history_required ? "true" : "false",
      "data-qualification-category": category.category || "not_evaluated",
      "data-funnel-c": funnel.C?.state || "—",
      "data-independently-audited": fields.independentlyAudited ? "true" : "false",
    },
    createElement("td", null, shortlist),
    createElement("td", null, row.provider_rank ?? "—"),
    createElement("td", { className: "mono" }, shorten(row.address)),
    createElement("td", { "data-funnel": "true" }, `${funnel.A?.state || "—"} / ${funnel.B?.state || "—"} / ${funnel.C?.state || "—"}`),
    createElement("td", null, row.trade_count ?? "unknown"),
    createElement("td", { "data-ranked-pnl": "true" }, rankedDesktopPnlText(row)),
    createElement("td", null, action),
  );
}

export function ReportCertificationView({ report }: { report: ReportLike }) {
  const profile = report.research_profile || {};
  const fields = completedEpisodeFields(report);
  const funnel = authoritativeFunnel(report);
  const category = authoritativeCategory(report);
  const headline = formatCompletedEpisodeHeadline(fields);
  return createElement(
    "section",
    {
      "data-report-certification": "true",
      "data-independently-audited": fields.independentlyAudited ? "true" : "false",
      "data-qualification-category": category.category || "not_evaluated",
      "data-funnel-c": funnel.C?.state || "unknown",
    },
    createElement("p", { "data-funnel-a": "true" }, `Funnel A ${funnel.A?.state || "unknown"}`),
    createElement("p", { "data-funnel-b": "true" }, `Funnel B ${funnel.B?.state || "unknown"}`),
    createElement("p", { "data-funnel-c": "true" }, `Funnel C ${funnel.C?.state || "unknown"}`),
    createElement(
      "p",
      { "data-qualification-category-label": "true" },
      `Qualification ${String(category.category || "not_evaluated").replaceAll("_", " ")} (evidence quality, not a screen pass).`,
    ),
    headline
      ? createElement("p", { "data-completed-episode-net": "true" }, headline)
      : createElement("p", { "data-completed-episode-net": "true" }, "no completed-episode net"),
    fields.auditorConfirmation
      ? createElement("p", { "data-auditor-confirmation": "true" }, fields.auditorConfirmation)
      : null,
    profile.criteria_met === true
      ? createElement("p", { "data-criteria-met": "true" }, "criteria_met")
      : null,
  );
}

export function CompareCertificationView({ compare }: { compare: ResearchCompare }) {
  const leftFunnel = authoritativeFunnel({
    funnel: compare.left_funnel,
    research_profile: {
      qualification_category: compare.left_qualification_category,
      completed_known_cost_positions: compare.window_policy?.left_sample_size,
      criteria_met: (compare.left_funnel as { C?: { criteria_met?: boolean } } | null | undefined)?.C?.criteria_met === true,
      funnel: compare.left_funnel,
    },
  });
  const rightFunnel = authoritativeFunnel({
    funnel: compare.right_funnel,
    research_profile: {
      qualification_category: compare.right_qualification_category,
      completed_known_cost_positions: compare.window_policy?.right_sample_size,
      criteria_met: (compare.right_funnel as { C?: { criteria_met?: boolean } } | null | undefined)?.C?.criteria_met === true,
      funnel: compare.right_funnel,
    },
  });
  const leftCategory = authoritativeCategory({
    qualification_category: compare.left_qualification_category,
    research_profile: {
      qualification_category: compare.left_qualification_category,
      completed_known_cost_positions: compare.window_policy?.left_sample_size,
    },
  });
  const rightCategory = authoritativeCategory({
    qualification_category: compare.right_qualification_category,
    research_profile: {
      qualification_category: compare.right_qualification_category,
      completed_known_cost_positions: compare.window_policy?.right_sample_size,
    },
  });
  const policy = compare.window_policy || {};
  const leftPnl = formatCompareSidePnl({
    completedNet: policy.left_completed_episode_net,
    completedUnit: policy.left_completed_episode_net_unit,
    independentlyAudited: policy.left_independently_audited,
    auditorNet: policy.left_independently_audited_episode_net,
    auditorUnit: policy.left_independently_audited_episode_net_unit,
    worksheet: policy.left_scoped_pnl,
    worksheetUnit: policy.left_scoped_pnl_unit,
  });
  const rightPnl = formatCompareSidePnl({
    completedNet: policy.right_completed_episode_net,
    completedUnit: policy.right_completed_episode_net_unit,
    independentlyAudited: policy.right_independently_audited,
    auditorNet: policy.right_independently_audited_episode_net,
    auditorUnit: policy.right_independently_audited_episode_net_unit,
    worksheet: policy.right_scoped_pnl,
    worksheetUnit: policy.right_scoped_pnl_unit,
  });
  return createElement(
    "div",
    { "data-research-compare": "true" },
    createElement("p", { "data-compare-left-funnel-c": leftFunnel.C?.state || "—" }, `left C ${leftFunnel.C?.state || "—"}`),
    createElement("p", { "data-compare-right-funnel-c": rightFunnel.C?.state || "—" }, `right C ${rightFunnel.C?.state || "—"}`),
    createElement("p", { "data-compare-left-category": leftCategory.category || "not_evaluated" }, `left ${leftCategory.category || "not_evaluated"}`),
    createElement("p", { "data-compare-right-category": rightCategory.category || "not_evaluated" }, `right ${rightCategory.category || "not_evaluated"}`),
    createElement("p", { "data-compare-left-pnl": "true" }, leftPnl),
    createElement("p", { "data-compare-right-pnl": "true" }, rightPnl),
  );
}
