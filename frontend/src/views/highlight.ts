// Syntax colour for the source viewer — presentation, not evidence.
//
// This is deterministic lexical tokenization: keywords, strings and comments
// coloured by the grammar the file's *extension* names. It claims nothing was
// measured — the measured channel stays what it was (the kind-coloured span
// border and the fan-in badge). The language is never guessed from content:
// an extension we do not know renders plain, which is the honest default.

import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import ini from "highlight.js/lib/languages/ini";
import json from "highlight.js/lib/languages/json";
import markdown from "highlight.js/lib/languages/markdown";
import python from "highlight.js/lib/languages/python";
import rust from "highlight.js/lib/languages/rust";
import typescript from "highlight.js/lib/languages/typescript";
import yaml from "highlight.js/lib/languages/yaml";

hljs.registerLanguage("rust", rust);
hljs.registerLanguage("ini", ini);
hljs.registerLanguage("json", json);
hljs.registerLanguage("markdown", markdown);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("python", python);
hljs.registerLanguage("typescript", typescript);

const BY_EXTENSION: Record<string, string> = {
  rs: "rust",
  toml: "ini",
  lock: "ini", // Cargo.lock is TOML
  json: "json",
  md: "markdown",
  markdown: "markdown",
  yml: "yaml",
  yaml: "yaml",
  sh: "bash",
  bash: "bash",
  py: "python",
  ts: "typescript",
  tsx: "typescript",
  js: "typescript",
  mjs: "typescript",
};

/** The grammar this path's extension names, or null — never content-guessed. */
export function languageFor(path: string): string | null {
  const name = path.split("/").pop() ?? path;
  const dot = name.lastIndexOf(".");
  if (dot === -1) return null;
  return BY_EXTENSION[name.slice(dot + 1).toLowerCase()] ?? null;
}

/**
 * Highlight a whole slice and return one HTML string per line.
 *
 * Highlighting line-by-line would break multi-line constructs (a block
 * comment's second line would render as code), so the slice is tokenized as
 * one text and then split, closing every open span at each newline and
 * reopening it on the next line — each line stays a self-contained, balanced
 * fragment. Returns null when the language is unknown so callers fall back to
 * plain text rendering rather than innerHTML.
 */
export function highlightToLines(code: string, language: string | null): string[] | null {
  if (!language) return null;
  const html = hljs.highlight(code, { language, ignoreIllegals: true }).value;
  return splitPreservingSpans(html);
}

function splitPreservingSpans(html: string): string[] {
  const lines: string[] = [];
  const open: string[] = [];
  let current = "";
  let i = 0;
  while (i < html.length) {
    const ch = html[i]!;
    if (ch === "\n") {
      lines.push(current + "</span>".repeat(open.length));
      current = open.join("");
      i += 1;
    } else if (html.startsWith("</span>", i)) {
      open.pop();
      current += "</span>";
      i += 7;
    } else if (ch === "<") {
      // hljs output contains only its own <span class="hljs-…"> tags; the
      // source text itself arrives entity-escaped.
      const end = html.indexOf(">", i);
      const tag = html.slice(i, end + 1);
      open.push(tag);
      current += tag;
      i = end + 1;
    } else {
      current += ch;
      i += 1;
    }
  }
  lines.push(current + "</span>".repeat(open.length));
  return lines;
}
