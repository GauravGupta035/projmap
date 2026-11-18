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

## Install

projmap has four pieces. Only the first is required; add the others as you
need them.

**1. The command-line tool.** Needs python3 3.9 or later, and a `gh` that is
installed and signed in (`gh auth login`).

    pipx install git+https://github.com/GauravGupta035/projmap

`pip install git+https://github.com/GauravGupta035/projmap` works too. To run
it from a checkout instead, put `bin/projmap` on your PATH.

**2. The Claude skill**, which writes and refreshes the hand-written records.
Copy or link its folder into your Claude skills folder:

    git clone https://github.com/GauravGupta035/projmap
    ln -s "$PWD/projmap/skill/project-map" ~/.claude/skills/project-map

Then ask Claude to "map this repo" or "refresh the project map".

**3. The Claude Code pane.** At the prompt of a Claude Code terminal session:

    /plugin install projmap --marketplace GauravGupta035/projmap

Answer `y` to add the marketplace, then pick a scope. From a shell, use
`claude plugin install projmap --marketplace GauravGupta035/projmap`. In the
desktop app, click + next to the prompt box, then Plugins, add the marketplace
`GauravGupta035/projmap`, then add the plugin. The pane runs `projmap
summary`, so the tool from step 1 must be on your PATH. Type `/map` to open it.

**4. The CI template**, which publishes the page whenever an issue or pull
request changes. Copy `ci/project-map.yml` into your repo's
`.github/workflows/` and follow the setup steps at the top of the file.

## Use

    projmap init          # add a map to the repo you are in
    projmap serve         # http://localhost:4400, updates itself
    projmap build         # write one HTML file
    projmap check         # exits 1 when the map is behind the repo

A repo with no hand-written records still gets the Work view (stages,
dependency tree, what each issue touches) and a diagram of its modules.

## The pieces

- `projmap/`: the tool. `cli.py` gathers the facts, `template.html` is the page.
- `skill/project-map/`: the Claude skill that writes and refreshes the
  hand-written records and proposes them as a pull request. `schema.md`
  documents both files.
- `mod/projmap/`: a Claude Code mod that shows a summary pane beside the chat.
- `ci/project-map.yml`: a GitHub Actions template that rebuilds the page on
  every issue and pull request change.
- `.projmap/`: this repo's own map, as a worked example. Run `projmap serve`
  in a checkout to see it.

## Develop

The tests use only the standard library and stub out GitHub, so they need no
network and no `gh`:

    python3 -m unittest discover -s tests

CI runs them on Python 3.9, 3.11 and 3.13, and builds and checks this repo's
own map, on every pull request.

## Licence

MIT. See `LICENSE`.
