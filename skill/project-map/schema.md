# projmap files

Both files live in the map folder (`.projmap/` or `docs/map/`). Every collection in `content.json` is optional: a view appears on the page only when its records exist.

## content.json

| Key | Shape | Cap |
|---|---|---|
| `story` | list of sentences | 6 sentences |
| `terms` | `{id, group, word, plain, example, see?}`; `see` is a view: `fit`, `knobs`, `rules`, `work` | plain 20 words |
| `components` | `{id, name, module?, status, short, does, takes?, gives?, built?, next?: [issue numbers], pos?: [column, row]}`; `status` is `built`, `partial`, `stub` or `planned`; `module` is a name from `projmap facts` | does 25 |
| `flow` | list of `[from id, to id]`: the arrows of the parts diagram | |
| `links` | `{from, to, how}`: a change in `from` is felt by `to`, and how | how 20 |
| `knobs` | `{id, name, plain, default?, where?, reaches: [{to, how}]}`; `to` is a component id, a rule id, or `kind:name` | plain 20, how 25 |
| `rules` | `{id, name, plain, state, issue?, ok?, bad?}`; `state` is `ok`, `part` or `todo`; `ok` and `bad` are a short sentence each showing the rule kept and broken | plain 25 |
| `rulesIntro` | `{title, text, noun}`: explains what a rule is in this project | |
| `decisions` | `{id, group, what, why, cost}` | 25 each |
| `open` | `{what, why}`: decisions nobody has made yet | |
| `standing` | `{rule, means, from}`: rules for the whole repo | |
| `commands` | `{cmd, plain}` | |
| `issues` | object keyed by issue number: `{part, plain, label?}`; `part` is a component id; `label` is a short title for the diagram | plain 15 |
| `notes` | object keyed by issue number: what a person must decide on it | |
| `walk` | `{title, text, lit: [component ids], needs?: [issue numbers], show?: [lines]}`: one worked example, step by step | |
| `lists` | `{id, title, view, style?, lede?, columns?, caps?, rows: [{id, group?, plain, ...}]}`: the project's own ID lists, such as error codes; `view` is `words` or `rules`; `style: "table"` needs `columns: [{key, label}]` | per list, in `caps` |
| `text` | page wording: `storyTitle`, `walkTitle`, `walkLede`, `fitLede`, `decisionsLede`, `firstPart`, `rulesPart` | |

If `components` is empty, the page draws the modules and their imports instead.
If `pos` is missing from any component, the diagram lays itself out from `flow`.

## projmap.json

| Key | Meaning |
|---|---|
| `title`, `rebuild` | page title, and the command the footer names |
| `modules` | `{roots: [globs of module folders], tests?: "path/{name}Tests", testAlias?, testPattern?, extensions?}` or `{list: [{name, path, tests?}]}` |
| `issues` | `{records: "open" or "all", dependsPattern?, dependsStop?, sizePattern?, prIssuePattern?, limit?}` |
| `stages` | ordered list; the first whose `when` holds is the issue's stage. `{id, name, tone, when, attention?, moving?, canStart?, hint?}`. `tone` is `ok`, `acc`, `warn`, `stop` or `idle`. `when` keys: `open`, `merged`, `openPr`, `depsMet` (true or false), `label`, `anyLabel`, `prLabel` |
| `pipeline` | the steps drawn under "How an issue travels": `{name, label?, who, stages: [ids], countOnly?, side?}` |
| `gate` | `{name, marker, pass}`: a bot comment that checks an issue before work starts |
| `backlog` | which issues the dependency tree draws: `{from: number}`, `{label}` or `{numbers}`. Default: every issue linked to an open one |
| `ids` | drift tracking: `{kind, in, sources}`; `in` is a content collection or `lists.<id>`; each source is `{file, pattern}` or `{glob, name}` (regular expressions with one group) |
| `statusDoc` | `{path, datePattern, dateFormat}`: a hand-kept status file to flag when it falls behind |
| `caps` | overrides, such as `{"terms.plain": 25}` |

## Commands

- `projmap init [--dir <folder>]`: add a map to a repo
- `projmap facts`: everything the tool gathers itself, as JSON
- `projmap check [--json]`: drift and records over their cap; exits 1 if any
- `projmap build [--out <file>]`: write the page as one HTML file
- `projmap serve [--port 4400]`: serve the page and keep it up to date
