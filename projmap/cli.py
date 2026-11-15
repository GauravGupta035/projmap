"""projmap: a living onboarding map for any repository.

Joins three things into one HTML page:
  - content.json: short, hand-written records (words, components, rules,
    decisions, one line per issue). Every record has a word cap, so the page
    cannot grow into another long document.
  - live facts: issues and pull requests from gh, modules and their imports
    from the source tree, and the files each pull request changed.
  - a drift list: every ID in the repo that has no record on the map, and
    every record whose ID is gone.

Needs python3 and gh (signed in). Standard library only.
"""
import argparse
import datetime
import hashlib
import html
import http.server
import json
import pathlib
import re
import subprocess
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
CONFIG_PLACES = [".projmap", "docs/map", "docs/projmap"]
CODE_EXT = {".swift", ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".rb", ".c", ".h", ".cc",
            ".cpp", ".hpp", ".cs", ".php", ".scala", ".hs", ".ex", ".exs", ".m", ".mm", ".vue", ".svelte", ".sh",
            ".sql", ".lua", ".dart", ".zig"}
MODULE_GLOBS = ["src/*", "Sources/*", "Packages/*/Sources/*", "packages/*", "apps/*", "lib/*", "crates/*", "cmd/*",
                "internal/*", "services/*"]
SKIP_DIRS = {"node_modules", "dist", "build", "out", "target", "vendor", "docs", "doc", "tests", "test", "Tests",
             "scripts", "assets", "public", "coverage", "venv", "__pycache__"}
TEST_PATTERN = r"(?m)^\s*(?:def test_|func test|@Test\b|#\[test\]|(?:it|test)\s*\()"
IMPORT_LINE = r"(?m)^\s*(?:@testable\s+)?(?:import|from|use|using|include|#include|require)\b[^\n]*(?<![\w-]){name}(?![\w-])"
PR_ISSUE = r"(?im)\b(?:closes|fixes|resolves)\s+#(\d+)|^\[#(\d+)\]"
DEPENDS = r"(?im)^\s*(?:Depends on|Blocked by):?\s*(.*)$"

# Word caps: collection, field, most words allowed.
CAPS = [("terms", "plain", 20), ("components", "does", 25), ("links", "how", 20), ("knobs", "plain", 20),
        ("rules", "plain", 25), ("decisions", "what", 25), ("decisions", "why", 25), ("decisions", "cost", 25)]
ISSUE_CAP, REACH_CAP, STORY_CAP = 15, 25, 6

# Used when the config names no stages. The first stage whose "when" holds wins.
STAGES = [
    {"id": "done", "name": "Merged", "tone": "ok", "when": {"open": False, "merged": True}},
    {"id": "closed", "name": "Closed, no merge", "tone": "idle", "when": {"open": False}},
    {"id": "review", "name": "In review", "tone": "acc", "moving": True, "when": {"openPr": True}},
    {"id": "wait", "name": "Waiting on another issue", "tone": "idle", "when": {"depsMet": False}},
    {"id": "open", "name": "Open", "tone": "warn", "canStart": True, "when": {}},
]
PIPELINE = [
    {"name": "Open", "who": "Someone writes the issue", "stages": ["open", "wait"]},
    {"name": "In review", "who": "A pull request is open", "stages": ["review"]},
    {"name": "Merged", "who": "The change is on the main branch", "stages": ["done"], "countOnly": True},
]


class MapError(Exception):
    pass


# --- Finding the repo, the config and the content -------------------------


def git_root(start):
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True)
    if out.returncode:
        raise MapError("projmap: not inside a git repository")
    return pathlib.Path(out.stdout.strip())


def find_config(root, explicit):
    if explicit:
        return pathlib.Path(explicit).resolve()
    for place in CONFIG_PLACES:
        if (root / place / "projmap.json").is_file():
            return root / place / "projmap.json"
    raise MapError("projmap: no projmap.json found. Run `projmap init` first.")


def read_json(path):
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise MapError(f"projmap: {path} is not valid JSON: {error}")


def load(root, config_path):
    config = read_json(config_path)
    content_path = config_path.parent / config.get("content", "content.json")
    content = read_json(content_path) if content_path.is_file() else {}
    return config, content


# --- Word caps -------------------------------------------------------------


def words(text):
    return len(str(text).split())


def check_caps(content, config):
    caps = {(c, f): n for c, f, n in CAPS}
    caps.update({tuple(key.split(".")): n for key, n in config.get("caps", {}).items()})
    over = []
    for (collection, field), cap in caps.items():
        for record in content.get(collection, []):
            if words(record.get(field, "")) > cap:
                name = record.get("id", record.get("from", "?"))
                over.append(f"{collection} {name}.{field}: {words(record[field])} words, cap {cap}")
    for knob in content.get("knobs", []):
        for reach in knob.get("reaches", []):
            if words(reach["how"]) > REACH_CAP:
                over.append(f"knobs {knob['id']} -> {reach['to']}: {words(reach['how'])} words, cap {REACH_CAP}")
    for number, issue in content.get("issues", {}).items():
        if words(issue.get("plain", "")) > ISSUE_CAP:
            over.append(f"issues {number}.plain: {words(issue['plain'])} words, cap {ISSUE_CAP}")
    if len(content.get("story", [])) > STORY_CAP:
        over.append(f"story: {len(content['story'])} sentences, cap {STORY_CAP}")
    for extra in content.get("lists", []):
        for field, cap in extra.get("caps", {}).items():
            for row in extra.get("rows", []):
                if words(row.get(field, "")) > cap:
                    over.append(f"lists.{extra['id']} {row.get('id', '?')}.{field}: {words(row[field])} words, cap {cap}")
    return over


# --- Modules, from the source tree ----------------------------------------


def module_dirs(root, config):
    """Returns {name: (folder, tests folder or None)}."""
    spec = config.get("modules") or {}
    found = {}
    for entry in spec.get("list", []):
        tests = root / entry["tests"] if entry.get("tests") else None
        found[entry["name"]] = (root / entry["path"], tests)
    globs = spec.get("roots")
    if globs is None and not found:
        globs = [g for g in MODULE_GLOBS if any(p.is_dir() for p in root.glob(g))]
        if not globs:
            globs = ["*"]
    for pattern in globs or []:
        for folder in sorted(p for p in root.glob(pattern) if p.is_dir()):
            if folder.name.startswith(".") or (pattern == "*" and folder.name in SKIP_DIRS):
                continue
            alias = spec.get("testAlias", {}).get(folder.name, folder.name)
            tests = root / spec["tests"].format(name=alias) if spec.get("tests") else None
            found.setdefault(folder.name, (folder, tests))
    return found


def code_files(folder, extensions):
    return sorted(f for f in folder.rglob("*") if f.is_file() and f.suffix in extensions
                  and not any(part in SKIP_DIRS - {"tests", "test", "Tests"} or part.startswith(".")
                              for part in f.relative_to(folder).parts[:-1]))


def read(path):
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def scan_modules(root, config):
    spec = config.get("modules") or {}
    extensions = set(spec.get("extensions", CODE_EXT))
    test_pattern = spec.get("testPattern", TEST_PATTERN)
    dirs = module_dirs(root, config)
    modules, sources = {}, {}
    for name, (folder, tests) in dirs.items():
        files = code_files(folder, extensions)
        if not files:
            continue
        texts = [read(f) for f in files]
        sources[name] = "\n".join(texts)
        test_texts = [read(f) for f in code_files(tests, extensions)] if tests and tests.is_dir() else texts
        modules[name] = {
            "path": str(folder.relative_to(root)),
            "tests_path": str(tests.relative_to(root)) if tests and tests.is_dir() else None,
            "files": len(files),
            "lines": sum(len(t.splitlines()) for t in texts),
            "tests": sum(len(re.findall(test_pattern, t)) for t in test_texts),
            "uses": [],
        }
    for name, source in sources.items():
        modules[name]["uses"] = [other for other in modules if other != name
                                 and re.search(IMPORT_LINE.format(name=re.escape(other)), source)]
    return modules


def owner_of(path, modules):
    """The module a file belongs to, by its longest matching folder."""
    best = None
    for name, module in modules.items():
        for folder in (module["path"], module["tests_path"]):
            if folder and path.startswith(folder + "/") and (best is None or len(folder) > best[1]):
                best = (name, len(folder))
    return best[0] if best else None


# --- Issues and pull requests, from gh ------------------------------------


def gh(root, *arguments):
    try:
        out = subprocess.run(["gh", *arguments], cwd=root, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise MapError("projmap: gh is not installed. See https://cli.github.com")
    except subprocess.TimeoutExpired:
        raise MapError("projmap: gh took too long to answer")
    if out.returncode:
        raise MapError("projmap: gh failed: " + (out.stderr.strip().splitlines() or ["no message"])[-1])
    return json.loads(out.stdout)


def first(pattern, text):
    found = re.search(pattern, text or "")
    return found.group(1).strip() if found else None


def fetch_github(root, config):
    spec = config.get("issues") or {}
    gate = config.get("gate")
    limit = str(spec.get("limit", 300))
    issues = []
    for raw in gh(root, "issue", "list", "--state", "all", "--limit", limit, "--json",
                  "number,title,state,stateReason,labels,body,closedAt,url,comments"):
        body = raw.get("body") or ""
        depends = first(spec.get("dependsPattern", DEPENDS), body) or ""
        if spec.get("dependsStop"):
            depends = depends.split(spec["dependsStop"])[0]
        passed = None
        if gate:
            for comment in raw.get("comments", []):
                text = comment.get("body") or ""
                if gate["marker"] in text:
                    passed = "ready" if gate["pass"] in text else "needs"
        size = first(spec["sizePattern"], body) if spec.get("sizePattern") else None
        issues.append({
            "n": raw["number"], "title": raw["title"], "open": raw["state"] == "OPEN",
            "reason": raw.get("stateReason") or "", "labels": [label["name"] for label in raw["labels"]],
            "deps": sorted(set(int(n) for n in re.findall(r"#(\d+)", depends)) - {raw["number"]}),
            "size": int(size.replace(",", "")) if size else None,
            "criteria": len(re.findall(r"(?m)^\s*- \[[ xX]\]", body)),
            "gate": passed, "closedAt": raw.get("closedAt"), "url": raw["url"], "text": raw["title"] + "\n" + body,
        })
    prs = []
    for raw in gh(root, "pr", "list", "--state", "all", "--limit", limit, "--json",
                  "number,title,body,state,mergedAt,labels,closingIssuesReferences,url,reviews,comments,"
                  "statusCheckRollup,files"):
        texts = [c.get("body") or "" for c in raw.get("comments", []) + raw.get("reviews", [])]
        rounds = [int(n) for text in texts for n in re.findall(r"(?i)\bround\s*:?\s*(\d)\b", text)]
        checks = [c.get("conclusion") or c.get("state") or "PENDING" for c in raw.get("statusCheckRollup") or []]
        failing = [c for c in checks if c not in ("SUCCESS", "SKIPPED", "NEUTRAL")]
        named = re.findall(spec.get("prIssuePattern", PR_ISSUE), raw["title"] + "\n" + (raw.get("body") or ""))
        closes = set(ref["number"] for ref in raw.get("closingIssuesReferences") or [])
        closes |= set(int(n) for groups in named for n in (groups if isinstance(groups, tuple) else (groups,)) if n)
        prs.append({
            "n": raw["number"], "title": raw["title"], "state": raw["state"], "mergedAt": raw.get("mergedAt"),
            "labels": [label["name"] for label in raw["labels"]], "closes": sorted(closes),
            "rounds": max(rounds) if rounds else 0,
            "checks": "none" if not checks else ("passed" if not failing else "failing"),
            "url": raw["url"], "paths": [f["path"] for f in raw.get("files") or []],
        })
    return {"issues": sorted(issues, key=lambda i: i["n"]), "prs": sorted(prs, key=lambda p: -p["n"]),
            "at": datetime.datetime.now().astimezone().strftime("%d %B %Y, %H:%M")}


# --- Stages, and what each issue touches ----------------------------------


def stage_of(issue, prs, by_number, stages):
    open_pr = next((p for p in prs if p["state"] == "OPEN"), None)
    facts = {
        "open": issue["open"],
        "merged": any(p["mergedAt"] for p in prs) or (issue["reason"] == "COMPLETED" and not prs),
        "openPr": bool(open_pr),
        "depsMet": all(d in by_number and not by_number[d]["open"] for d in issue["deps"]),
    }
    for stage in stages:
        when = stage.get("when", {})
        holds = all(facts[key] == value for key, value in when.items() if key in facts)
        if "label" in when:
            holds = holds and when["label"] in issue["labels"]
        if "anyLabel" in when:
            holds = holds and any(label in issue["labels"] for label in when["anyLabel"])
        if "prLabel" in when:
            holds = holds and bool(open_pr) and when["prLabel"] in open_pr["labels"]
        if holds:
            return stage["id"]
    return stages[-1]["id"]


def downstream(names, modules):
    """Every module that imports one of these, directly or through another."""
    reached, frontier = set(), set(names)
    while frontier:
        frontier = {m for m, module in modules.items() if set(module["uses"]) & frontier} - reached - set(names)
        reached |= frontier
    return sorted(reached)


def derive(config, content, modules, github):
    """Adds the stage, the touched modules and the affected modules to each issue."""
    issues, prs = github["issues"], github["prs"]
    by_number = {i["n"]: i for i in issues}
    stages = config.get("stages", STAGES)
    part_module = {c["id"]: c.get("module") for c in content.get("components", [])}
    for pr in prs:
        owners = [owner_of(path, modules) for path in pr["paths"]]
        pr["touches"] = sorted(set(o for o in owners if o))
        pr["other"] = sum(1 for o in owners if not o)
    for issue in issues:
        linked = [p for p in prs if issue["n"] in p["closes"]]
        issue["stage"] = stage_of(issue, linked, by_number, stages)
        merged = [p for p in linked if p["mergedAt"]]
        live = [p for p in linked if p["state"] == "OPEN"]
        if merged or live:
            source = merged or live
            touched = set(m for p in source for m in p["touches"])
            other = sum(p["other"] for p in source)
            basis = "merged" if merged else "open"
        else:
            text = issue["text"]
            touched = set(name for name, module in modules.items()
                          if re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", text) or module["path"] + "/" in text)
            authored = part_module.get((content.get("issues", {}).get(str(issue["n"])) or {}).get("part"))
            if authored in modules:
                touched.add(authored)
            other, basis = 0, "predicted" if touched else "none"
        issue["touches"] = {"modules": sorted(touched), "other": other, "basis": basis,
                            "affects": downstream(touched, modules)}
    return issues, prs


def pick_backlog(config, issues):
    """The issues drawn as a dependency tree."""
    spec = config.get("backlog") or {}
    if "numbers" in spec:
        return [n for n in spec["numbers"]]
    if "from" in spec:
        return [i["n"] for i in issues if i["n"] >= spec["from"] and (i["deps"] or i["open"] or any(i["n"] in o["deps"] for o in issues))]
    if "label" in spec:
        return [i["n"] for i in issues if spec["label"] in i["labels"]]
    by_number = {i["n"]: i for i in issues}
    near = {n: set(i["deps"]) & set(by_number) for n, i in by_number.items()}
    for n, deps in list(near.items()):
        for d in deps:
            near[d].add(n)
    keep, frontier = set(), {n for n, i in by_number.items() if i["open"]}
    while frontier:
        keep |= frontier
        frontier = {m for n in frontier for m in near[n]} - keep
    return sorted(keep)[-60:]


# --- Drift -----------------------------------------------------------------


def ids_in_repo(root, source):
    found = set()
    paths = [root / source["file"]] if "file" in source else sorted(root.glob(source["glob"]))
    for path in paths:
        if not path.is_file():
            continue
        if "name" in source:
            found |= set(re.findall(source["name"], path.name))
        if "pattern" in source:
            found |= set(re.findall(source["pattern"], read(path)))
    return found


def records(content, where):
    if where.startswith("lists."):
        rows = next((l.get("rows", []) for l in content.get("lists", []) if l["id"] == where[6:]), [])
    else:
        rows = content.get(where, [])
    return set(str(r["id"]) for r in rows if "id" in r)


def find_drift(root, config, content, modules, issues):
    pairs = []
    for kind in config.get("ids", []):
        in_repo = set()
        for source in kind["sources"]:
            in_repo |= ids_in_repo(root, source)
        pairs.append((kind["kind"], in_repo, records(content, kind["in"])))
    want = (config.get("issues") or {}).get("records", "open")
    written = set(content.get("issues", {}))
    numbers = set(str(i["n"]) for i in issues)
    expected = numbers if want == "all" else set(str(i["n"]) for i in issues if i["open"])
    drift = [{"kind": "issue", "id": n, "problem": "has no line on the map"} for n in sorted(expected - written, key=int)]
    drift += [{"kind": "issue", "id": n, "problem": "is on the map but not on GitHub"} for n in sorted(written - numbers)]
    if content.get("components"):
        pairs.append(("module", set(modules), set(c["module"] for c in content["components"] if c.get("module"))))
    for kind, in_repo, on_map in pairs:
        drift += [{"kind": kind, "id": i, "problem": "has no record on the map"} for i in sorted(in_repo - on_map)]
        drift += [{"kind": kind, "id": i, "problem": "is on the map but no longer in the repo"} for i in sorted(on_map - in_repo)]
    return drift


# --- Putting the page together --------------------------------------------


def status_doc(root, config, prs):
    spec = config.get("statusDoc")
    if not spec or not (root / spec["path"]).is_file():
        return None
    date = first(spec["datePattern"], read(root / spec["path"]))
    merges = sorted(p["mergedAt"] for p in prs if p["mergedAt"])
    try:
        said = datetime.datetime.strptime(date, spec.get("dateFormat", "%d %B %Y")).date()
        stale = bool(merges) and datetime.date.fromisoformat(merges[-1][:10]) > said
    except (TypeError, ValueError):
        stale = False
    return {"path": spec["path"], "date": date, "stale": stale}


def auto_components(content, modules):
    """With no hand-written components, the modules and their imports stand in."""
    if content.get("components"):
        return
    content["components"] = [{"id": name, "name": name, "module": name, "status": "built", "auto": True,
                              "short": f"{m['files']} files, {m['lines']} lines", "does": ""} for name, m in modules.items()]
    content["flow"] = [[used, name] for name, m in modules.items() for used in m["uses"]]
    content["links"] = [{"from": used, "to": name, "how": f"{name} imports {used}, so a change to {used} can break it."}
                        for name, m in modules.items() for used in m["uses"]]


def gather(root, config_path, github=None):
    """Returns (data for the page, caps problems). Fetches GitHub unless given."""
    config, content = load(root, config_path)
    over = check_caps(content, config)
    modules = scan_modules(root, config)
    github = github or fetch_github(root, config)
    issues, prs = derive(config, content, modules, github)
    drift = find_drift(root, config, content, modules, issues)
    auto_components(content, modules)
    data = {
        "title": config.get("title", root.name + " project map"),
        "rebuild": config.get("rebuild", "projmap build"),
        "contentPath": str(shown(root, config_path.parent / config.get("content", "content.json"))),
        "issues": [{k: v for k, v in i.items() if k != "text"} for i in issues],
        "prs": [{k: v for k, v in p.items() if k != "paths"} for p in prs],
        "modules": modules, "stages": config.get("stages", STAGES), "pipeline": config.get("pipeline", PIPELINE),
        "gate": (config.get("gate") or {}).get("name"), "backlog": pick_backlog(config, issues),
        "statusDoc": status_doc(root, config, prs), "drift": drift, "content": content,
    }
    data["version"] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
    data["generated"] = github["at"]
    return data, over


def render(data, live=False):
    data = dict(data, live=live)
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    page = (HERE / "template.html").read_text()
    return page.replace("__TITLE__", html.escape(data["title"])).replace("__DATA__", payload)


def out_path(root, config_path, explicit):
    if explicit:
        return pathlib.Path(explicit).resolve()
    return config_path.parent / "out" / "index.html"


def shown(root, path):
    return path.relative_to(root) if path.is_relative_to(root) else path


# --- Commands --------------------------------------------------------------


def cmd_build(args):
    root = git_root(pathlib.Path.cwd())
    config_path = find_config(root, args.config)
    data, over = gather(root, config_path)
    if over:
        raise MapError("projmap: these records are over their word cap:\n  " + "\n  ".join(over))
    out = out_path(root, config_path, args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data))
    print(f"projmap: wrote {shown(root, out)}")
    print(f"projmap: {len(data['issues'])} issues, {len(data['prs'])} pull requests, {len(data['modules'])} modules, {len(data['drift'])} drift item(s)")
    for item in data["drift"]:
        print(f"  drift: {item['kind']} {item['id']} {item['problem']}")


def cmd_check(args):
    root = git_root(pathlib.Path.cwd())
    data, over = gather(root, find_config(root, args.config))
    if args.json:
        print(json.dumps({"caps": over, "drift": data["drift"]}, indent=2))
    else:
        for line in over:
            print("over cap: " + line)
        for item in data["drift"]:
            print(f"drift: {item['kind']} {item['id']} {item['problem']}")
        if not over and not data["drift"]:
            print("projmap: the map matches the repo")
    sys.exit(1 if over or data["drift"] else 0)


def cmd_facts(args):
    """Everything the map knows that nobody wrote by hand, for whoever writes the content."""
    root = git_root(pathlib.Path.cwd())
    config_path = find_config(root, args.config)
    config, content = load(root, config_path)
    modules = scan_modules(root, config)
    github = fetch_github(root, config)
    issues, prs = derive(config, content, modules, github)
    ids = {kind["kind"]: sorted(set().union(*[ids_in_repo(root, s) for s in kind["sources"]])) for kind in config.get("ids", [])}
    print(json.dumps({
        "modules": modules, "ids": ids,
        "issues": [{k: i[k] for k in ("n", "title", "open", "labels", "deps", "stage", "touches")} for i in issues],
        "prs": [{k: p[k] for k in ("n", "title", "state", "closes", "touches")} for p in prs],
        "caps": {f"{c}.{f}": n for c, f, n in CAPS} | {"issues.plain": ISSUE_CAP, "knobs.reaches.how": REACH_CAP, "story": STORY_CAP},
        "drift": find_drift(root, config, content, modules, issues),
    }, indent=2))


def cmd_summary(args):
    """The few facts a small panel needs: what waits, what moves, what each open issue touches."""
    root = git_root(pathlib.Path.cwd())
    data, over = gather(root, find_config(root, args.config))
    stages = {s["id"]: s for s in data["stages"]}
    written, notes = data["content"].get("issues", {}), data["content"].get("notes", {})
    rows = []
    for issue in data["issues"]:
        if not issue["open"]:
            continue
        stage, record = stages.get(issue["stage"], {}), written.get(str(issue["n"]), {})
        kind = "attention" if stage.get("attention") else "moving" if stage.get("moving") else "start" if stage.get("canStart") else "wait"
        rows.append({"n": issue["n"], "plain": record.get("plain") or issue["title"], "stage": stage.get("name", issue["stage"]),
                     "kind": kind, "note": notes.get(str(issue["n"]), ""), "hint": stage.get("hint", ""),
                     "touches": issue["touches"]["modules"], "basis": issue["touches"]["basis"],
                     "affects": issue["touches"]["affects"], "url": issue["url"]})
    print(json.dumps({"title": data["title"], "generated": data["generated"], "issues": rows[::-1],
                      "merged": sum(1 for p in data["prs"] if p["mergedAt"]),
                      "drift": [f"{d['kind']} {d['id']} {d['problem']}" for d in data["drift"]], "caps": over}))


def cmd_init(args):
    root = git_root(pathlib.Path.cwd())
    folder = root / args.dir
    if (folder / "projmap.json").exists():
        raise MapError(f"projmap: {shown(root, folder / 'projmap.json')} already exists")
    folder.mkdir(parents=True, exist_ok=True)
    globs = [g for g in MODULE_GLOBS if any(p.is_dir() for p in root.glob(g))] or ["*"]
    config = {"title": root.name + " project map", "modules": {"roots": globs}, "ids": []}
    (folder / "projmap.json").write_text(json.dumps(config, indent=2) + "\n")
    content = {"story": [], "terms": [], "components": [], "links": [], "decisions": [], "issues": {}}
    (folder / "content.json").write_text(json.dumps(content, indent=2) + "\n")
    (folder / ".gitignore").write_text("out/\n")
    print(f"projmap: wrote {shown(root, folder)}/projmap.json and content.json")
    print("projmap: modules found: " + ", ".join(scan_modules(root, config)) or "none")
    print("projmap: run `projmap serve` to see it. The map already shows the work and the modules;")
    print("         the words, rules and decisions appear as content.json is filled in.")


class Live:
    """Rebuilds the page when a local file or GitHub changes, and serves the latest."""

    def __init__(self, root, config_path, interval):
        self.root, self.config_path, self.interval = root, config_path, interval
        self.page, self.version, self.github, self.note = b"", "", None, ""
        self.lock = threading.Lock()

    def stamp(self):
        """Changes whenever the map's own files or the checked-out commit change."""
        paths = list(self.config_path.parent.glob("*.json")) + [HERE / "template.html", HERE / "cli.py"]
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True).stdout
        return head + "".join(str(p.stat().st_mtime_ns) for p in paths if p.exists())

    def rebuild(self, refetch):
        note = ""
        if refetch or self.github is None:
            try:
                self.github = fetch_github(self.root, load(self.root, self.config_path)[0])
            except MapError as error:
                if self.github is None:
                    raise
                note = f"GitHub could not be reached, so issues and pull requests are from {self.github['at']}. ({error})"
        try:
            data, over = gather(self.root, self.config_path, self.github)
        except (MapError, KeyError, TypeError) as error:
            print(f"projmap: kept the last good page: {error}", flush=True)
            return
        data["note"] = note or ("Over the word cap: " + "; ".join(over) if over else "")
        page = render(data, live=True).encode()
        with self.lock:
            changed = data["version"] + data["note"] != self.version
            self.page, self.version = page, data["version"] + data["note"]
        if changed:
            print(f"projmap: rebuilt at {time.strftime('%H:%M:%S')}, {len(data['drift'])} drift item(s)", flush=True)

    def watch(self):
        last_stamp, last_fetch = self.stamp(), time.monotonic()
        while True:
            time.sleep(2)
            due = time.monotonic() - last_fetch >= self.interval
            stamp = self.stamp()
            if due or stamp != last_stamp:
                self.rebuild(refetch=due)
                last_stamp = stamp
                if due:
                    last_fetch = time.monotonic()


def cmd_serve(args):
    root = git_root(pathlib.Path.cwd())
    live = Live(root, find_config(root, args.config), args.interval)
    live.rebuild(refetch=True)
    threading.Thread(target=live.watch, daemon=True).start()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            with live.lock:
                page, version = live.page, live.version
            if self.path.split("?")[0] == "/version":
                body, kind = version.encode(), "text/plain"
            elif self.path.split("?")[0] in ("/", "/index.html"):
                body, kind = page, "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        raise MapError(f"projmap: port {args.port} is in use. Pick another with --port.")
    print(f"projmap: serving http://localhost:{args.port} (GitHub every {args.interval}s, local changes at once)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(prog="projmap", description="A living onboarding map for any repository.")
    parser.add_argument("--config", help="path to projmap.json (found automatically by default)")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="add a map to this repo")
    init.add_argument("--dir", default=".projmap", help="where the map's files live (default .projmap)")
    init.set_defaults(run=cmd_init)
    build = commands.add_parser("build", help="write the map as one HTML file")
    build.add_argument("--out", help="where to write it (default <map folder>/out/index.html)")
    build.set_defaults(run=cmd_build)
    serve = commands.add_parser("serve", help="serve the map and keep it up to date")
    serve.add_argument("--port", type=int, default=4400)
    serve.add_argument("--interval", type=int, default=120, help="seconds between GitHub checks (default 120)")
    serve.set_defaults(run=cmd_serve)
    check = commands.add_parser("check", help="list drift and records over their word cap; exits 1 if any")
    check.add_argument("--json", action="store_true")
    check.set_defaults(run=cmd_check)
    facts = commands.add_parser("facts", help="print the live facts as JSON, for writing content")
    facts.set_defaults(run=cmd_facts)
    summary = commands.add_parser("summary", help="print a short JSON summary, for panels and scripts")
    summary.set_defaults(run=cmd_summary)
    args = parser.parse_args()
    try:
        args.run(args)
    except MapError as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
