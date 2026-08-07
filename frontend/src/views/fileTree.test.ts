// The explorer's tree shape: nesting, ordering, and counts.

import { describe, expect, it } from "vitest";
import { buildFileTree, fileCount } from "./fileTree";

const F = (path: string) => ({ path, language: null, isGenerated: false });

describe("buildFileTree", () => {
  it("nests directories and keeps files at their level", () => {
    const tree = buildFileTree([
      F("src/main.rs"),
      F("src/exec/job.rs"),
      F("Cargo.toml"),
      F("src/walk.rs"),
    ]);
    expect(tree.files.map((f) => f.path)).toEqual(["Cargo.toml"]);
    expect(tree.dirs.map((d) => d.name)).toEqual(["src"]);
    const src = tree.dirs[0]!;
    expect(src.path).toBe("src");
    expect(src.files.map((f) => f.path)).toEqual(["src/main.rs", "src/walk.rs"]);
    expect(src.dirs.map((d) => d.path)).toEqual(["src/exec"]);
    expect(src.dirs[0]!.files.map((f) => f.path)).toEqual(["src/exec/job.rs"]);
  });

  it("creates intermediate directories that hold no files of their own", () => {
    const tree = buildFileTree([F("a/b/c/deep.rs")]);
    expect(tree.dirs[0]!.name).toBe("a");
    expect(tree.dirs[0]!.dirs[0]!.name).toBe("b");
    expect(tree.dirs[0]!.dirs[0]!.files).toEqual([]);
  });

  it("sorts directories and files independently", () => {
    const tree = buildFileTree([F("z.rs"), F("a.rs"), F("m/x.rs"), F("b/y.rs")]);
    expect(tree.dirs.map((d) => d.name)).toEqual(["b", "m"]);
    expect(tree.files.map((f) => f.path)).toEqual(["a.rs", "z.rs"]);
  });

  it("counts every file under a directory", () => {
    const tree = buildFileTree([F("src/a.rs"), F("src/x/b.rs"), F("src/x/c.rs"), F("top.md")]);
    expect(fileCount(tree)).toBe(4);
    expect(fileCount(tree.dirs[0]!)).toBe(3);
  });

  it("an empty list is an empty root, not a crash", () => {
    const tree = buildFileTree([]);
    expect(tree.dirs).toEqual([]);
    expect(tree.files).toEqual([]);
    expect(fileCount(tree)).toBe(0);
  });
});
