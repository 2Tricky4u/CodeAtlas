// Syntax colour is presentation with three hard properties: language comes
// only from the extension, multi-line constructs survive tokenization, and
// the source text stays text — tokens carry content and colour, never markup.

import { describe, expect, it } from "vitest";
import { languageFor, tokenizeLines } from "./highlight";

describe("languageFor", () => {
  it("maps by extension, case-insensitively", () => {
    expect(languageFor("src/walk.rs")).toBe("rust");
    expect(languageFor("Cargo.toml")).toBe("toml");
    expect(languageFor("Cargo.lock")).toBe("toml");
    expect(languageFor("README.md")).toBe("markdown");
    expect(languageFor(".github/workflows/CICD.YML")).toBe("yaml");
  });

  it("never guesses: unknown or missing extensions are null", () => {
    expect(languageFor("LICENSE")).toBeNull();
    expect(languageFor("contrib/completion/_fd")).toBeNull();
    expect(languageFor("logo.png")).toBeNull();
  });
});

describe("tokenizeLines", () => {
  it("returns one token row per input line, coloured by the grammar", async () => {
    const lines = await tokenizeLines('pub fn job() {\n    let x = "hi";\n}', "rust");
    expect(lines).toHaveLength(3);
    // The keyword and the string carry theme colours; content round-trips.
    expect(lines![0]!.map((t) => t.content).join("")).toBe("pub fn job() {");
    const colours = new Set(lines!.flat().map((t) => t.color));
    expect(colours.size).toBeGreaterThan(1);
  });

  it("a block comment stays a comment on every line it covers", async () => {
    const lines = await tokenizeLines("/* first\nsecond */\nfn x() {}", "rust");
    const commentColour = lines![0]![0]!.color;
    expect(lines![1]!.some((t) => t.color === commentColour)).toBe(true);
    expect(lines![2]!.every((t) => t.color !== commentColour || !t.content.trim())).toBe(true);
  });

  it("source text stays text — a script tag is token content, not markup", async () => {
    const lines = await tokenizeLines('let a = "<script>alert(1)</script>";', "rust");
    const text = lines![0]!.map((t) => t.content).join("");
    expect(text).toBe('let a = "<script>alert(1)</script>";');
  });

  it("an unknown language is null — the caller renders plain text", async () => {
    expect(await tokenizeLines("anything", null)).toBeNull();
  });
});
