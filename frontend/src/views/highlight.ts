// Syntax colour for the source viewer — presentation, not evidence.
//
// Shiki runs the same TextMate grammars VS Code does (the closest web
// equivalent to nvim's tree-sitter fidelity), themed Tokyo Night — the
// palette this app already speaks. Tokenization is deterministic and the
// grammar comes only from the file's *extension*, never content-guessed: an
// unknown extension renders plain, which is the honest default. The output
// is tokens, not HTML, so the source text is rendered as React text nodes —
// nothing the file contains can become markup.
//
// The measured channel is untouched: only the kind-coloured span border and
// the fan-in badge claim anything was measured.

import { createHighlighterCore, type HighlighterCore, type ThemedToken } from "shiki/core";
import { createJavaScriptRegexEngine } from "shiki/engine/javascript";

const BY_EXTENSION: Record<string, string> = {
  rs: "rust",
  toml: "toml",
  lock: "toml", // Cargo.lock is TOML
  json: "json",
  md: "markdown",
  markdown: "markdown",
  yml: "yaml",
  yaml: "yaml",
  sh: "bash",
  bash: "bash",
  py: "python",
  ts: "typescript",
  tsx: "tsx",
  js: "javascript",
  mjs: "javascript",
};

/** The grammar this path's extension names, or null — never content-guessed. */
export function languageFor(path: string): string | null {
  const name = path.split("/").pop() ?? path;
  const dot = name.lastIndexOf(".");
  if (dot === -1) return null;
  return BY_EXTENSION[name.slice(dot + 1).toLowerCase()] ?? null;
}

// One highlighter per page session, created on first use — the same memoise-
// and-evict-on-failure shape graphIndex uses, for the same reason.
let highlighterPromise: Promise<HighlighterCore> | null = null;

function highlighter(): Promise<HighlighterCore> {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighterCore({
      themes: [import("shiki/themes/tokyo-night.mjs")],
      langs: [
        import("shiki/langs/rust.mjs"),
        import("shiki/langs/toml.mjs"),
        import("shiki/langs/json.mjs"),
        import("shiki/langs/markdown.mjs"),
        import("shiki/langs/yaml.mjs"),
        import("shiki/langs/bash.mjs"),
        import("shiki/langs/python.mjs"),
        import("shiki/langs/typescript.mjs"),
        import("shiki/langs/tsx.mjs"),
        import("shiki/langs/javascript.mjs"),
      ],
      engine: createJavaScriptRegexEngine({ forgiving: true }),
    });
    highlighterPromise.catch(() => {
      highlighterPromise = null;
    });
  }
  return highlighterPromise;
}

export type { ThemedToken };

/**
 * Tokenize a whole slice: one array of themed tokens per input line.
 *
 * The slice is tokenized as one text, so multi-line constructs keep their
 * meaning — a block comment's second line is still a comment. Shiki already
 * returns tokens grouped by line, so the line count matches the input and no
 * HTML splitting is involved. Null when the language is unknown; callers
 * render plain text.
 */
export async function tokenizeLines(
  code: string,
  language: string | null,
): Promise<ThemedToken[][] | null> {
  if (!language) return null;
  const shiki = await highlighter();
  return shiki.codeToTokensBase(code, { lang: language, theme: "tokyo-night" });
}
