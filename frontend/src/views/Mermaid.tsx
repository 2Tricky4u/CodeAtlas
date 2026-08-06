// Mermaid, rendered client-side.
//
// The dependency has been in package.json since P5 and imported nowhere: the
// change explanation has carried a `sequenceDiagram` field that was produced,
// validated and discarded, and the protocol model had no producer at all. This
// is where both stop being dead.
//
// A diagram that will not parse is *not* shown as a broken image. Mermaid's own
// error output is a red box with a stack trace in it, which reads as "this
// project is broken" rather than "this diagram is". The source is shown instead,
// with the reason — it is text a person can still read.

import { useEffect, useId, useRef, useState } from "react";
import mermaid from "mermaid";

let initialised = false;

function init() {
  if (initialised) return;
  mermaid.initialize({
    startOnLoad: false,
    // `securityLevel: strict` is the default and matters here: diagram source
    // comes from an agent, and must never be able to inject markup or scripts.
    securityLevel: "strict",
    theme: "base",
    themeVariables: {
      background: "#0b0e14",
      primaryColor: "#1b2333",
      primaryTextColor: "#c5cad6",
      primaryBorderColor: "#7aa2f7",
      lineColor: "#4a5570",
      secondaryColor: "#1b2333",
      tertiaryColor: "#11151f",
      fontFamily: "ui-monospace, monospace",
      fontSize: "13px",
    },
  });
  initialised = true;
}

/** Past this, Mermaid's layout degrades into something no one can follow. */
const MAX_LINES = 120;

export function Mermaid({ source, caption }: { source: string; caption?: string }) {
  const id = useId().replace(/:/g, "");
  const hostRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  const lines = source.trim().split("\n").length;
  const tooBig = lines > MAX_LINES;

  useEffect(() => {
    if (!hostRef.current || tooBig) return;
    let cancelled = false;
    init();
    mermaid
      .render(`m${id}`, source)
      .then(({ svg }) => {
        if (cancelled || !hostRef.current) return;
        hostRef.current.innerHTML = svg;
        setError(null);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [source, id, tooBig]);

  if (tooBig) {
    return (
      <div className="caveat" data-testid="mermaid-refused">
        this diagram is {lines} lines; past about {MAX_LINES} Mermaid's layout stops being
        followable, so the source is shown instead
        <pre className="codeblock" style={{ marginTop: 8, maxHeight: 260, overflow: "auto" }}>
          {source}
        </pre>
      </div>
    );
  }

  return (
    <figure style={{ margin: 0 }}>
      {error ? (
        <div className="caveat" data-testid="mermaid-error">
          this diagram could not be drawn ({error}); its source is below, which is still
          readable
          <pre className="codeblock" style={{ marginTop: 8, maxHeight: 260, overflow: "auto" }}>
            {source}
          </pre>
        </div>
      ) : (
        <div
          ref={hostRef}
          data-testid="mermaid"
          style={{ overflowX: "auto", padding: 8, background: "var(--bg-1)", borderRadius: 6 }}
        />
      )}
      {caption && (
        <figcaption className="note" style={{ marginTop: 4 }}>
          {caption}
        </figcaption>
      )}
    </figure>
  );
}
