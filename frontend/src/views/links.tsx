// The two links that turn nine silos into one tool.
//
// Every view that names a module or a symbol renders one of these instead of an
// inert label or a dead-end source popup, so a reader can always walk from a
// mention to the thing itself: narrative chips, findings rows, matrix labels,
// cycle members, architecture containers, diff entries.

import type { CSSProperties, ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";

/** Route to a module page. Paths contain slashes, so the route is a splat. */
export function modulePath(runId: string, path: string): string {
  return `/runs/${runId}/module/${path}`;
}

export function ModuleLink({
  path,
  children,
  className = "badge accent",
  style,
  title,
}: {
  path: string;
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  title?: string;
}) {
  const { runId } = useParams();
  const navigate = useNavigate();
  if (!runId) return <span className={className}>{children ?? path}</span>;
  return (
    <button
      className={className}
      style={{ cursor: "pointer", ...style }}
      title={title ?? path}
      data-testid="module-link"
      onClick={() => navigate(modulePath(runId, path))}
    >
      {children ?? path.split("/").pop()}
    </button>
  );
}

/**
 * A symbol resolves to its defining module's page, anchored on the symbol —
 * the page is where its usages, importers and source live.
 */
export function SymbolLink({
  id,
  path,
  children,
  className = "badge accent",
  title,
}: {
  id: string;
  /** The defining file, when the caller already knows it. */
  path?: string;
  children?: ReactNode;
  className?: string;
  title?: string;
}) {
  const { runId } = useParams();
  const navigate = useNavigate();
  if (!runId || !path) {
    // Without a defining file there is nowhere to land; stay a plain label
    // rather than a link that goes somewhere wrong.
    return (
      <span className="badge" title={title ?? id} data-testid="symbol-label">
        {children ?? id}
      </span>
    );
  }
  return (
    <button
      className={className}
      style={{ cursor: "pointer" }}
      title={title ?? id}
      data-testid="symbol-link"
      onClick={() =>
        navigate(`${modulePath(runId, path)}?symbol=${encodeURIComponent(id)}`)
      }
    >
      {children}
    </button>
  );
}
