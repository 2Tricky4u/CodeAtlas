// Small shared primitives. Deliberately few: the design system lives in
// theme.css, and these are the handful of pieces that need behavior or
// repeated markup rather than a class name.

import type { ReactNode } from "react";

export function Panel({
  title,
  count,
  children,
  actions,
  style,
}: {
  title: string;
  count?: number | string;
  children: ReactNode;
  actions?: ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <section className="panel" style={style}>
      <header className="panel-title">
        <span>{title}</span>
        {count !== undefined && <span className="count mono-num">{count}</span>}
        {actions && <span style={{ marginLeft: "auto" }}>{actions}</span>}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export type Tone = "ok" | "warn" | "bad" | "info" | "accent" | "plain";

export function Badge({ tone = "plain", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge ${tone === "plain" ? "" : tone}`}>{children}</span>;
}

export const SEVERITY_TONE: Record<string, Tone> = {
  critical: "bad",
  high: "bad",
  medium: "warn",
  low: "info",
};

export const BUMP_TONE: Record<string, Tone> = {
  major: "bad",
  minor: "warn",
  none: "ok",
  unknown: "plain",
};

export const STATUS_TONE: Record<string, Tone> = {
  succeeded: "ok",
  succeeded_with_gaps: "warn",
  running: "info",
  failed: "bad",
  cancelled: "plain",
  created: "plain",
  paused_for_approval: "warn",
};

export function KindDot({ kind }: { kind: string }) {
  return (
    <span
      className="dot"
      style={{ background: `var(--kind-${kind}, var(--fg-2))` }}
      title={kind}
    />
  );
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <div role="alert" className="panel-body" style={{ color: "var(--bad)" }}>
      {error}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

export function Loading() {
  return (
    <div className="empty-state" aria-busy="true">
      loading…
    </div>
  );
}

export function shortSha(sha: string | null | undefined, length = 10): string {
  return sha ? sha.slice(0, length) : "—";
}
