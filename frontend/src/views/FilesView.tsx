// The explorer: every file at the revision, as a tree.
//
// The tree comes from the git tree (the same rows the /source allowlist
// reads), so it can browse files the graph has no node for. A file the graph
// measured opens its module page — definitions, usages, the ask box; anything
// else opens as pinned source. Symbol counts on files are measured, never
// inferred, and a file without one simply shows none.

import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type RepoFile } from "../api";
import { graphIndex, type GraphIndex } from "../graph";
import { Badge, ErrorBox, Loading, Panel } from "../ui";
import { buildFileTree, fileCount, type TreeDir } from "./fileTree";
import { kindColor } from "./layout";
import { modulePath } from "./links";
import { SourcePanel, type SourceRequest } from "./SourcePanel";

export function FilesView() {
  const { runId } = useParams();
  const [files, setFiles] = useState<RepoFile[] | null>(null);
  const [index, setIndex] = useState<GraphIndex | null>(null);
  const [revision, setRevision] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<SourceRequest | null>(null);

  useEffect(() => {
    if (!runId) return;
    setFiles(null);
    setError(null);
    setSource(null);
    api
      .files(runId)
      .then(setFiles)
      .catch((e: Error) => setError(e.message));
    api
      .runDetail(runId)
      .then((detail) => setRevision(detail.headSha))
      .catch((e: Error) => setError(e.message));
    graphIndex(runId)
      .then(setIndex)
      .catch((e: Error) => setError(e.message));
  }, [runId]);

  const tree = useMemo(() => (files ? buildFileTree(files) : null), [files]);

  if (error) return <ErrorBox error={error} />;
  if (!tree || !files) return <Loading />;

  return (
    <div data-testid="files-view">
      <Panel title="files at this revision" count={files.length}>
        <p className="note" style={{ marginTop: 0 }}>
          from the git tree, not the graph — everything is openable as pinned source; a
          file with a symbol count also has a module page with definitions, usages and
          the ask box
        </p>
        <div data-testid="file-tree">
          <Directory
            dir={tree}
            depth={0}
            index={index}
            onOpenSource={(path) => revision && setSource({ revision, path })}
          />
        </div>
      </Panel>
      <SourcePanel request={source} onClose={() => setSource(null)} />
    </div>
  );
}

function Directory({
  dir,
  depth,
  index,
  onOpenSource,
}: {
  dir: TreeDir;
  depth: number;
  index: GraphIndex | null;
  onOpenSource: (path: string) => void;
}) {
  // Top levels open, deeper ones folded — a 700-file repository must not
  // render as a wall on first paint.
  const [open, setOpen] = useState(depth < 2);
  const indent = { paddingLeft: depth * 14 };

  return (
    <div>
      {dir.path !== "" && (
        <button
          className="note"
          style={{ ...indent, cursor: "pointer", display: "block", padding: "2px 0 2px" }}
          data-testid="tree-dir"
          onClick={() => setOpen(!open)}
        >
          <span style={{ paddingLeft: depth * 14 }}>
            {open ? "▾" : "▸"} <strong style={{ color: "var(--fg-1)" }}>{dir.name}/</strong>{" "}
            <span className="mono-num">{fileCount(dir)}</span>
          </span>
        </button>
      )}
      {(open || dir.path === "") && (
        <>
          {dir.dirs.map((child) => (
            <Directory
              key={child.path}
              dir={child}
              depth={dir.path === "" ? depth : depth + 1}
              index={index}
              onOpenSource={onOpenSource}
            />
          ))}
          {dir.files.map((file) => (
            <FileRowEntry
              key={file.path}
              file={file}
              depth={dir.path === "" ? depth : depth + 1}
              index={index}
              onOpenSource={onOpenSource}
            />
          ))}
        </>
      )}
    </div>
  );
}

function FileRowEntry({
  file,
  depth,
  index,
  onOpenSource,
}: {
  file: RepoFile;
  depth: number;
  index: GraphIndex | null;
  onOpenSource: (path: string) => void;
}) {
  const navigate = useNavigate();
  const { runId } = useParams();
  const name = file.path.split("/").pop() ?? file.path;
  const measured = index?.fileByPath(file.path);
  const definitions = measured && index ? index.definitionsOf(measured.id) : [];

  return (
    <div style={{ paddingLeft: depth * 14 + 14, padding: "1px 0 1px" }}>
      <button
        className="note"
        style={{
          cursor: "pointer",
          color: measured ? "var(--fg-0)" : "var(--fg-2)",
          paddingLeft: depth * 14 + 14,
        }}
        data-testid="tree-file"
        title={file.path}
        onClick={() =>
          measured && runId ? navigate(modulePath(runId, file.path)) : onOpenSource(file.path)
        }
      >
        <span
          className="dot"
          style={{
            background: measured ? kindColor("file") : "var(--border-strong)",
            marginRight: 6,
          }}
        />
        {name}
      </button>{" "}
      {definitions.length > 0 && (
        <span className="note mono-num">{definitions.length} symbol(s)</span>
      )}
      {file.isGenerated && <Badge tone="info">generated</Badge>}
    </div>
  );
}
