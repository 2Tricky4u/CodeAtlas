// The explorer's tree, as pure data: forward-slash repo-relative paths in,
// nested directories out. Directories first, then files, both sorted — the
// shape every file explorer readers already know.

import type { RepoFile } from "../api";

export interface TreeDir {
  name: string;
  /** Repo-relative path of this directory ("" for the root). */
  path: string;
  dirs: TreeDir[];
  files: RepoFile[];
}

export function buildFileTree(files: RepoFile[]): TreeDir {
  const root: TreeDir = { name: "", path: "", dirs: [], files: [] };
  const dirsByPath = new Map<string, TreeDir>([["", root]]);

  const dirFor = (path: string): TreeDir => {
    const known = dirsByPath.get(path);
    if (known) return known;
    const cut = path.lastIndexOf("/");
    const parent = dirFor(cut === -1 ? "" : path.slice(0, cut));
    const created: TreeDir = {
      name: cut === -1 ? path : path.slice(cut + 1),
      path,
      dirs: [],
      files: [],
    };
    parent.dirs.push(created);
    dirsByPath.set(path, created);
    return created;
  };

  for (const file of files) {
    const cut = file.path.lastIndexOf("/");
    dirFor(cut === -1 ? "" : file.path.slice(0, cut)).files.push(file);
  }

  for (const dir of dirsByPath.values()) {
    dir.dirs.sort((a, b) => a.name.localeCompare(b.name));
    dir.files.sort((a, b) => a.path.localeCompare(b.path));
  }
  return root;
}

/** How many files the tree under this directory holds. */
export function fileCount(dir: TreeDir): number {
  return dir.files.length + dir.dirs.reduce((sum, child) => sum + fileCount(child), 0);
}
