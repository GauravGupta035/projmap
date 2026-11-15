---
name: project-map
description: Create or refresh a repository's projmap onboarding map, the living page that explains a project's words, parts, rules, decisions and issues in short plain records. Use when asked to "map this repo", "set up the project map", "refresh the map", "the map is behind", when `projmap check` reports drift, or after issues or pull requests are opened or merged in a repo that has a projmap.json.
---

# project-map

projmap builds one page per repository from three things: live facts it gathers itself (issues, pull requests, modules, imports, the files each pull request changed), short hand-written records in `content.json`, and a drift check between the two. This skill is the hand-written half. The tool never writes knowledge; you do, and a person approves it.

The CLI is `projmap` (on the PATH, or `python3 -m projmap` from its checkout). Read `schema.md` beside this file before writing any record.

## Rules that always hold

1. **Short, plain records.** Every field has a word cap and `projmap check` enforces it. Write for a new developer who has read nothing. One idea per record. Say what a thing is before what it is called.
2. **Only what the repo says.** Every record traces to a file, an issue or a pull request you read. Never invent a decision, a reason or a cost. If the repo does not say why, leave the record out and list it under "could not find" in your report.
3. **Propose, never apply silently.** Work on a branch, show the diff, and open a pull request or leave the change for the person to review. Never push to the default branch and never merge.
4. **Follow the repo's own rules** for language, commit format and attribution (read its CLAUDE.md or AGENTS.md first).
5. **Do not touch live facts.** Stages, touched modules, counts and dates come from the tool. If one looks wrong, fix the config pattern in `projmap.json`, not the content.

## Mode 1: set up a map in a repo that has none

1. Run `projmap init` (add `--dir docs/map` if the repo keeps documents under `docs/`). Run `projmap facts` and read the modules it found. If they are wrong, fix `modules` in `projmap.json` first.
2. Read the repo in this order: README and contributor guides, architecture decisions, specs, then the entry points of each module. Read the open issues from `projmap facts`.
3. Find the repo's own IDs (decision records, numbered rules, error codes) and add an `ids` entry for each kind, so drift is tracked from the first day.
4. If the repo moves issues through labels, write `stages` and `pipeline` in `projmap.json` to match. Otherwise leave the defaults.
5. Write `content.json` in this order, running `projmap check` after each part:
   - `story`: at most six sentences on what the project is and how it works.
   - `components`, `flow`, `links`: the parts, how data moves, and what feels a change to what.
   - `terms`: the project's own words, each with an example from the repo.
   - `rules` and `decisions`: only those the repo records.
   - `issues`: one line for every open issue (or every issue, if the config says `"records": "all"`).
   - `walk`, `knobs`, `lists`: only when the repo has a worked example, steering inputs, or its own ID lists.
6. Run `projmap serve`, open the page, and look at every view. Fix anything that reads like a document instead of a card.
7. Report what you wrote, what you could not find, and what a person should check.

## Mode 2: refresh a map that is behind

1. Run `projmap check --json`. It lists `drift` (IDs with no record, records whose ID is gone) and `caps` (records too long).
2. For each drift item, read the source it points to (the issue, the decision file, the code) and write or remove the one record. For a new issue, write its one-line `plain` and its `part`. Do not rewrite records that have not drifted.
3. Then check for silent staleness, which the tool cannot see: for each pull request merged since the map's last content change (`git log -1 --format=%cI -- <content.json>`), read its title and touched modules from `projmap facts` and update any component `status`, `built`, `next`, or rule `state` it changed.
4. Run `projmap check` until it exits 0, then `projmap build`.
5. Propose the change: a branch and a pull request titled for the map refresh, listing each record added, changed or removed with its source.

## When something is unclear

Ask the person once, with the specific record and the two readings. Carry on with the rest meanwhile. A map with an honest gap is better than a map with a guess.
