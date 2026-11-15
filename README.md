# projmap

A living onboarding map for any repository: one page that explains a project's
words, parts, rules, decisions and issues in short plain records, and shows
what each issue touches.

It joins three things:

- **Live facts** it gathers itself: issues and pull requests (through `gh`),
  modules and their imports, and the files each pull request changed.
- **Hand-written records** in `content.json`, each with a word cap so the page
  cannot grow into another long document.
- **A drift check** between the two, so the map says when it is behind.

## Use

    projmap init          # add a map to the repo you are in
    projmap serve         # http://localhost:4400, updates itself
    projmap build         # write one HTML file
    projmap check         # exits 1 when the map is behind the repo

A repo with no hand-written records still gets the Work view (stages,
dependency tree, what each issue touches) and a diagram of its modules.

Needs python3 (standard library only) and a signed-in `gh`.

## The pieces

- `projmap/`: the tool. `cli.py` gathers the facts, `template.html` is the page.
- `skill/project-map/`: the Claude skill that writes and refreshes the
  hand-written records and proposes them as a pull request. `schema.md`
  documents both files.
- `mod/projmap/`: a Claude Code mod that shows a summary pane beside the chat.
- `ci/project-map.yml`: a GitHub Actions template that rebuilds the page on
  every issue and pull request change.

## Licence

MIT. See `LICENSE`.
