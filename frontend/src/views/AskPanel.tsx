// Ask a question about the code on this page; get an answer you can check.
//
// Every sentence in an answer carries citations that were validated server-side
// against this revision — claims that failed are gone and the removal is
// disclosed. A refusal renders as an answer, because "this cannot be answered
// from this file" is one. When the server has asking disabled the panel says
// how to enable it rather than pretending the feature does not exist.

import { useState } from "react";
import { api, type CodeAnswer } from "../api";
import { Badge, Panel } from "../ui";

export function AskPanel({
  runId,
  scope,
  onOpenSource,
}: {
  runId: string;
  scope: string;
  onOpenSource: (path: string, startLine?: number) => void;
}) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<CodeAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    const trimmed = question.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    setAnswer(null);
    api
      .ask(runId, scope, trimmed)
      .then(setAnswer)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };

  return (
    <Panel title="ask about this module">
      <div style={{ display: "flex", gap: 8 }}>
        <input
          type="text"
          placeholder={`a question about ${scope.split("/").pop()}…`}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && submit()}
          data-testid="ask-input"
          disabled={busy}
          style={{
            flex: 1,
            padding: "7px 10px",
            background: "var(--bg-0)",
            border: "1px solid var(--border-strong)",
            borderRadius: 6,
            color: "var(--fg-0)",
            font: "inherit",
          }}
        />
        <button
          className="badge accent"
          style={{ cursor: "pointer" }}
          onClick={submit}
          disabled={busy}
          data-testid="ask-submit"
        >
          {busy ? "reading…" : "ask"}
        </button>
      </div>
      <p className="note" style={{ marginBottom: 0 }}>
        answered from this module's source and graph at this revision · every sentence is
        citation-checked, and what fails the check is removed and disclosed
      </p>

      {error && (
        <div className="caveat" style={{ marginTop: 8 }} data-testid="ask-error">
          {error}
        </div>
      )}

      {answer && (
        <div style={{ marginTop: 10 }} data-testid="ask-answer">
          <div style={{ display: "flex", gap: 6, alignItems: "baseline", flexWrap: "wrap" }}>
            <strong>{answer.question}</strong>
            {answer.cached && <Badge tone="info">cached</Badge>}
          </div>

          {answer.refused ? (
            <p data-testid="ask-refused" style={{ marginBottom: 0 }}>
              <Badge tone="warn">refused</Badge> {answer.refused}
            </p>
          ) : (
            <>
              {answer.answer && <p style={{ margin: "6px 0" }}>{answer.answer}</p>}
              <ul style={{ margin: 0, paddingLeft: "1.2em" }} data-testid="ask-claims">
                {answer.claims.map((claim, claimIndex) => (
                  <li key={claimIndex} style={{ marginBottom: 4 }}>
                    {claim.text}{" "}
                    {claim.citations.map((citation, citationIndex) =>
                      citation.kind === "source" ? (
                        <button
                          key={citationIndex}
                          className="badge accent"
                          style={{ cursor: "pointer", marginLeft: 4 }}
                          data-testid="ask-citation"
                          onClick={() => onOpenSource(citation.path, citation.startLine)}
                        >
                          {citation.path.split("/").pop()}
                          {citation.startLine ? `:${citation.startLine}` : ""}
                        </button>
                      ) : (
                        <span key={citationIndex} className="badge" style={{ marginLeft: 4 }}>
                          {citation.key}
                        </span>
                      ),
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}

          {(answer.droppedClaims?.length ?? 0) > 0 && (
            <div className="caveat" style={{ marginTop: 6 }} data-testid="ask-dropped">
              {answer.droppedClaims!.length} statement(s) were removed because their
              citations did not resolve against this revision
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
