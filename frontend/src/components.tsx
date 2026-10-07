import {
  ArrowUpRight,
  ChevronRight,
  LoaderCircle,
  Search,
  ShieldCheck,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Metric, Report } from "./types";
import {
  completedEpisodeFields,
  dateTime,
  decimal,
  formatCompletedEpisodeHeadline,
  formatWorksheetTotal,
  label,
  listRealisedProfit,
  shorten,
  WORKSHEET_LABEL,
} from "./format";
import { useNarrowViewport } from "./useNarrow";

export function Button({
  children,
  icon: Icon,
  busy,
  variant = "primary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  icon?: LucideIcon;
  busy?: boolean;
  variant?: "primary" | "secondary" | "ghost" | "danger";
}) {
  return (
    <button
      className={`button ${variant}`}
      {...props}
      disabled={props.disabled || busy}
    >
      {busy ? (
        <LoaderCircle size={16} className="spin" />
      ) : (
        Icon && <Icon size={16} />
      )}
      <span>{children}</span>
    </button>
  );
}
export function Badge({
  value,
  children,
}: {
  value: string;
  children?: ReactNode;
}) {
  return (
    <span className={`badge ${value.toLowerCase().replace(/[^a-z]/g, "-")}`}>
      <span className="badge-dot" />
      {children ?? label(value.toLowerCase())}
    </span>
  );
}
export function Empty({
  title,
  detail,
  icon: Icon = Search,
  action,
  kind,
}: {
  title: string;
  detail: string;
  icon?: LucideIcon;
  action?: ReactNode;
  kind?: string;
}) {
  return (
    <div className="empty" data-empty-kind={kind}>
      <div className="empty-icon">
        <Icon size={25} />
      </div>
      <h3>{title}</h3>
      <p>{detail}</p>
      {action}
    </div>
  );
}
export function SectionHeading({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-heading">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
export function MetricValue({
  metric,
  suffix,
}: {
  metric?: Metric;
  suffix?: string;
}) {
  const known = metric?.status === "known" && metric.value !== null;
  return (
    <span
      title={
        !known
          ? (metric?.reason ?? "Insufficient evidence for this metric")
          : (metric?.value ?? undefined)
      }
      className={!known ? "unknown-value" : undefined}
    >
      {known ? decimal(metric.value) : "—"}
      {known && suffix && <small> {suffix}</small>}
    </span>
  );
}
export const metricDefinitions: {
  key: string;
  name: string;
  suffix?: string;
  hint: string;
}[] = [
  {
    key: "profit_sol",
    name: "Realised profit",
    suffix: "SOL",
    hint: "Net FIFO profit on all evidenced disposals in the reporting window, including partial exits",
  },
  {
    key: "realised_roi_pct",
    name: "Realised ROI",
    suffix: "%",
    hint: "Net realised profit divided by the acquisition cost of disposed quantities",
  },
  {
    key: "median_roi_pct",
    name: "Median position ROI",
    suffix: "%",
    hint: "Median return across eligible completed positions",
  },
  {
    key: "win_rate_pct",
    name: "Win rate",
    suffix: "%",
    hint: "Positive completed positions / eligible completed positions",
  },
  {
    key: "median_hold_hours",
    name: "Median hold",
    suffix: "hours",
    hint: "Median duration from first acquisition to the final exit that returns the position to zero",
  },
  {
    key: "completed_positions",
    name: "Completed positions",
    hint: "Fully closed eligible positions in the reporting window",
  },
  {
    key: "completed_positions_90d",
    name: "90-day positions",
    hint: "Eligible completed positions in the verification window",
  },
  {
    key: "traded_mints",
    name: "Traded mints",
    hint: "Distinct eligible token mints",
  },
  {
    key: "rapid_sale_pct",
    name: "Rapid sales",
    suffix: "%",
    hint: "Share of eligible completed positions with their first positive economic sale within five minutes of first acquisition",
  },
  {
    key: "avg_buys",
    name: "Average buys",
    hint: "Mean entries per completed position",
  },
  {
    key: "avg_sells",
    name: "Average sells",
    hint: "Mean exits per completed position",
  },
  {
    key: "positive_weeks",
    name: "Positive weeks",
    hint: "Positive realised profit in four consecutive seven-day periods ending at the report end; this independent 28-day interval can extend beyond a shorter report window",
  },
  {
    key: "largest_contribution_pct",
    name: "Largest contribution",
    suffix: "%",
    hint: "Largest positive token contribution divided by total net realised profit",
  },
  {
    key: "economic_pnl_sol",
    name: "Economic P&L",
    suffix: "SOL",
    hint: "Equity change adjusted for external flows",
  },
];
export function ListRealisedProfitCell({
  report,
  hideLabel = false,
}: {
  report: Report;
  hideLabel?: boolean;
}) {
  void hideLabel;
  const listed = listRealisedProfit(report);
  if (listed.basis === "reconstructed-subset" && listed.value != null) {
    const episode = formatCompletedEpisodeHeadline(completedEpisodeFields(report));
    return (
      <span
        className="subset-list-profit"
        data-list-profit="reconstructed-subset"
        title={`${WORKSHEET_LABEL}. Not a wallet-wide MATCH.`}
      >
        {decimal(listed.value, 4)}
        <small> SOL</small>
        <small className="subset-list-label" data-worksheet-label="true">{formatWorksheetTotal(listed.value, "SOL")}</small>
        {episode ? <small className="subset-list-label" data-completed-episode-net="true">{episode}</small> : null}
      </span>
    );
  }
  return <MetricValue metric={report.metrics.profit_sol} suffix="SOL" />;
}
export function ReportTable({
  reports,
  onOpen,
  selected,
  onSelect,
}: {
  reports: Report[];
  onOpen: (report: Report) => void;
  selected?: string[];
  onSelect?: (id: string) => void;
}) {
  const narrow = useNarrowViewport();
  const rows = reports.slice(0, 200);
  return (
    <>
      {!narrow && (
        <div className="table-scroll">
          <table className="report-table">
            <thead>
              <tr>
                {onSelect && <th className="checkbox-cell">Compare</th>}
                <th>Wallet</th>
                <th>Realised profit</th>
                <th>Median hold</th>
                <th>Positions</th>
                <th>Policy fit</th>
                <th>Data status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((report) => (
                <tr key={report.id}>
                  {onSelect && (
                    <td className="checkbox-cell">
                      <input
                        type="checkbox"
                        aria-label={`Compare ${report.label || shorten(report.address)}`}
                        checked={selected?.includes(report.id) ?? false}
                        onChange={() => onSelect(report.id)}
                      />
                    </td>
                  )}
                  <td>
                    <button className="wallet-cell" onClick={() => onOpen(report)}>
                      <span
                        className={`wallet-avatar ${report.source === "demo" ? "demo-avatar" : ""}`}
                      >
                        {(report.label || report.address).slice(0, 2).toUpperCase()}
                      </span>
                      <span>
                        <strong>{report.label || shorten(report.address)}</strong>
                        <small className="mono">
                          {shorten(report.address, 5)}{" "}
                          {report.source === "demo" && (
                            <span className="demo-inline">SYNTHETIC</span>
                          )}
                          {report.source === "mass-search" && (
                            <span className="demo-inline">subset</span>
                          )}
                        </small>
                      </span>
                    </button>
                  </td>
                  <td className="numeric">
                    <ListRealisedProfitCell report={report} />
                  </td>
                  <td className="numeric">
                    <MetricValue
                      metric={report.metrics.median_hold_hours}
                      suffix="h"
                    />
                  </td>
                  <td className="numeric">
                    <MetricValue metric={report.metrics.completed_positions} />
                  </td>
                  <td>
                    <Badge value={report.policy} />
                  </td>
                  <td>
                    <Badge value={report.evidence_status} />
                  </td>
                  <td>
                    <button
                      className="icon-button"
                      aria-label={`Open ${report.label || report.address}`}
                      onClick={() => onOpen(report)}
                    >
                      <ChevronRight size={18} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ul className="report-cards">
        {rows.map((report) => (
          <li key={`card-${report.id}`}>
            {onSelect && (
              <label className="report-card-compare">
                <input
                  type="checkbox"
                  aria-label={`Compare ${report.label || shorten(report.address)}`}
                  checked={selected?.includes(report.id) ?? false}
                  onChange={() => onSelect(report.id)}
                />
                Compare
              </label>
            )}
            <strong>{report.label || shorten(report.address)}</strong>
            <small className="mono">
              {shorten(report.address, 5)}{" "}
              {report.source === "demo" && (
                <span className="demo-inline">SYNTHETIC</span>
              )}
              {report.source === "mass-search" && (
                <span className="demo-inline">subset</span>
              )}
            </small>
            <div className="report-card-profit">
              <span>Realised profit</span>
              <ListRealisedProfitCell report={report} />
            </div>
            <p>
              Hold <MetricValue metric={report.metrics.median_hold_hours} suffix="h" />
              {" · "}
              Positions <MetricValue metric={report.metrics.completed_positions} />
            </p>
            <p>
              <Badge value={report.policy} />{" "}
              <Badge value={report.evidence_status} />
            </p>
            <Button
              variant="secondary"
              onClick={() => onOpen(report)}
            >
              Open report
            </Button>
          </li>
        ))}
      </ul>
      {reports.length > 200 && (
        <p className="table-note">
          Showing the first 200 results. Refine your filters to inspect a
          smaller set.
        </p>
      )}
    </>
  );
}
export function WindowLabel({ report }: { report: Report }) {
  return (
    <span className="window-label">
      {dateTime(report.window.start)} <ArrowUpRight size={13} />{" "}
      {dateTime(report.window.end)} · UTC
    </span>
  );
}
export function EvidenceHint() {
  return (
    <div className="evidence-hint">
      <ShieldCheck size={18} />
      <span>
        Policy fit and evidence completeness are evaluated separately. Unknown
        costs stay unknown.
      </span>
    </div>
  );
}
