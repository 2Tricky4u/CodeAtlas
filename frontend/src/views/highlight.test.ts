// Syntax colour is presentation with three hard properties: language comes
// only from the extension, multi-line constructs survive the line split, and
// source text can never inject markup.

import { describe, expect, it } from "vitest";
import { highlightToLines, languageFor } from "./highlight";

describe("languageFor", () => {
  it("maps by extension, case-insensitively", () => {
    expect(languageFor("src/walk.rs")).toBe("rust");
    expect(languageFor("Cargo.toml")).toBe("ini");
    expect(languageFor("Cargo.lock")).toBe("ini");
    expect(languageFor("README.md")).toBe("markdown");
    expect(languageFor(".github/workflows/CICD.YML")).toBe("yaml");
  });

  it("never guesses: unknown or missing extensions are null", () => {
    expect(languageFor("LICENSE")).toBeNull();
    expect(languageFor("contrib/completion/_fd")).toBeNull();
    expect(languageFor("logo.png")).toBeNull();
  });
});

describe("highlightToLines", () => {
  it("returns one balanced HTML fragment per input line", () => {
    const lines = highlightToLines('pub fn job() {\n    let x = "hi";\n}', "rust");
    expect(lines).toHaveLength(3);
    expect(lines![0]).toContain("hljs-keyword");
    expect(lines![1]).toContain("hljs-string");
    for (const line of lines!) {
      const opens = (line.match(/<span/g) ?? []).length;
      const closes = (line.match(/<\/span>/g) ?? []).length;
      expect(opens).toBe(closes);
    }
  });

  it("a block comment stays a comment on every line it covers", () => {
    // The reason the slice is tokenized whole and then split: per-line
    // highlighting would render the comment's second line as code.
    const lines = highlightToLines("/* first\nsecond */\nfn x() {}", "rust");
    expect(lines![0]).toContain("hljs-comment");
    expect(lines![1]).toContain("hljs-comment");
    expect(lines![2]).not.toContain("hljs-comment");
  });

  it("source text cannot inject markup", () => {
    const lines = highlightToLines('let a = "<script>alert(1)</script>";', "rust");
    expect(lines![0]).not.toContain("<script>");
    expect(lines![0]).toContain("&lt;script&gt;");
  });

  it("an unknown language is null — the caller renders plain text", () => {
    expect(highlightToLines("anything", null)).toBeNull();
  });
});
