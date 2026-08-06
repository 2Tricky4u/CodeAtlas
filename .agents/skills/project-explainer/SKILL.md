# project-explainer

Explain what a project is and how to find your way around it: what it does, how
it is organised, where to start reading, what everything leans on, and what will
surprise someone opening it for the first time.

You are not reviewing this project. You are not judging its design. You are
orienting a competent engineer who has never seen it, so that they can open the
repository already knowing what they are looking at.

## Inputs

The structure has already been measured, without a model, and is supplied to you
as content:

- **the project overview** (`project-overview.v1`): every package and module,
  each module's fan-in, fan-out and dependency level, the dependency cycles, the
  modules nothing references, the entry points, and a ranked "start here" list
  with the reason each entry earned its place.

You are also in a read-only checkout at that same revision, so you can read the
source to find out what a module actually does — the overview tells you the
shape of the project, not its purpose. Read the files that matter and say what
they are for.

## Method

1. Read the overview first. It tells you things reading files cannot: which
   module the most others depend on, which ones form a cycle, which level a
   module sits at.
2. Read the entry points and the top of the "start here" list in the source.
   That is where the project's purpose is usually legible.
3. Write the `summary`: one paragraph, what this project is and what it does.
   This is the only prose most readers will certainly read. Say what it is *for*,
   not how many modules it has — the counts are already on the page.
4. Fill the sections in order. Skip any section you have nothing supported to
   say in — an empty section is better than a padded one.
   - **what** — what the project is and what problem it solves.
   - **structure** — how it is organised: what the packages are for, what the
     levels mean here, which parts are independent of which.
   - **entry** — where to start reading, and why that is the right place.
   - **hotspots** — what everything leans on, and what that implies for someone
     about to change it.
   - **caution** — what will surprise a newcomer. Cycles that make two modules
     unreadable apart. Modules nothing references. A name that means something
     different here than elsewhere.

## Hard rules

- **Every claim carries at least one citation.** A sentence you cannot point at
  is not publishable, however true it feels.
- **Citations are checked afterwards, and unsupported claims are deleted.** Not
  softened, not hedged — deleted, and listed as dropped. A newcomer has no
  independent picture of this project to catch you with; a plausible invention
  is indistinguishable from a fact to the only reader who needs this.
- **Cite only what you were given**, using exactly these four shapes:

  | kind | fields | must come from |
  |---|---|---|
  | `source` | `path`, optional `startLine`, `endLine` | a path that exists at this revision |
  | `module` | `key` | a `key` in the overview's `modules` |
  | `package` | `name` | a `name` in the overview's `packages` |
  | `cycle` | `members` | the **exact** member list of one entry in the overview's `cycles` |

  There is no `revision` field on a source citation: a project graph describes
  one revision, so there is no other side to point at. A `cycle` citation must
  name every member of that cycle and no others — a subset or a superset is a
  claim about a cycle that was not found.
- **Do not invent line numbers.** If you know the file but not the line, cite the
  path alone.
- **Do not restate the overview.** The reader can see the counts, the levels and
  the cycle list rendered next to your text. Tell them what those mean.
- **Do not speculate about history or intent** ("this was probably split out
  when…"). Say what is there. If the purpose is stated — a doc comment, a README
  line, a crate description — cite it.
- **Do not recommend changes.** "storage and api should be separated" is a
  review, and this is not one. Say that they depend on each other and what that
  costs a reader.
- No network access.

## Output

Exactly one fenced ```json block validating against `project-explanation.v1`:

```json
{
  "schemaVersion": "1.0.0",
  "summary": "kvstore is a single-crate in-process key-value store with an HTTP front end. Requests arrive in api.rs, are served from an in-memory map in storage.rs, and are bounded by an LRU cache in cache.rs.",
  "sections": [
    {
      "id": "what",
      "title": "What this project is",
      "claims": [
        {
          "text": "One crate, four modules: an HTTP surface over an in-memory store with a bounded cache.",
          "citations": [
            { "kind": "package", "name": "kvstore" }
          ]
        }
      ]
    },
    {
      "id": "entry",
      "title": "Where to start reading",
      "claims": [
        {
          "text": "main.rs binds the listener and constructs the store the rest of the code shares.",
          "citations": [
            { "kind": "module", "key": "kvstore/src/main.rs" },
            { "kind": "source", "path": "kvstore/src/main.rs", "startLine": 1, "endLine": 24 }
          ]
        }
      ]
    },
    {
      "id": "hotspots",
      "title": "What everything leans on",
      "claims": [
        {
          "text": "cache.rs is reached by every read path, so a change to its eviction rule is felt everywhere.",
          "citations": [
            { "kind": "module", "key": "kvstore/src/cache.rs" }
          ]
        }
      ]
    },
    {
      "id": "caution",
      "title": "What will surprise you",
      "claims": [
        {
          "text": "api.rs and storage.rs depend on each other, so neither can be read on its own.",
          "citations": [
            { "kind": "cycle", "members": ["kvstore/src/api.rs", "kvstore/src/storage.rs"] }
          ]
        }
      ]
    }
  ],
  "notes": []
}
```
