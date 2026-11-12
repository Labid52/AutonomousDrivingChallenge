"""Scores every team's latest code and writes the leaderboard website into <site_dir>.
Run by .github/workflows/leaderboard.yml; see leaderboard/README.md.

    python leaderboard/score.py <site_dir>

Env: TEAM_REPOS_TOKEN      read access to the private team repos
     PREVIOUS_RESULTS_URL  the last published results.json, so only new (planner, scene) pairs are run
     LEADERBOARD_UNSAFE_NO_DOCKER=1   local testing only: student code runs unsandboxed
"""

import functools
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "leaderboard"
TEAMS = json.loads((HERE / "teams.json").read_text())   # {"team_1": {"kind": "scenes"|"planner", "repo": "owner/name"}}
UNSAFE = os.environ.get("LEADERBOARD_UNSAFE_NO_DOCKER") == "1"
IMAGE = "adc-leaderboard"
RUN_TIMEOUT_S = 600
IGNORE = shutil.ignore_patterns(".git", ".github", "training", "results", "frames", "venv", "__pycache__",
                                "tutorial_images", "*.md")


# ---------------------------------------------------------------------------
# Team code
# ---------------------------------------------------------------------------
def fetch(team: str, info: dict, dest: Path):
    """Clone the team's repo into dest. Returns its commit id, or None if there is nothing to score."""
    token = os.environ.get("TEAM_REPOS_TOKEN")
    auth = f"x-access-token:{token}@" if token else ""
    p = subprocess.run(["git", "clone", "--quiet", "--depth", "1", f"https://{auth}github.com/{info['repo']}.git",
                        str(dest)], capture_output=True)
    sha = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True)
    if p.returncode or sha.returncode:                   # no access, or an empty repo
        print(f"{team}: nothing to score in {info['repo']}")
        return None
    shutil.rmtree(dest / ".git")                         # the clone URL holds the token
    return sha.stdout.strip()


def prepare(kind: str, d: Path):
    """Check the layout of a team's code; returns an error message or None."""
    if kind == "scenes":
        return None if (d / "scenes.py").exists() else "scenes.py not found at the top of the repo"
    if not (d / "planner.py").exists():
        inner = [p for p in d.iterdir() if p.is_dir() and (p / "planner.py").exists()]
        if len(inner) != 1:
            return "planner.py not found at the top of the repo"
        for p in inner[0].iterdir():                     # the team uploaded the folder, not its contents
            p.rename(d / p.name)
    (d / "__init__.py").touch()
    return None


# ---------------------------------------------------------------------------
# Running student code in the sandbox
# ---------------------------------------------------------------------------
@functools.cache
def build_image():
    subprocess.run(["docker", "build", "-q", "-t", IMAGE, str(HERE)], check=True)


def run_job(args, subs=()):
    """Copy the project + the given team code into a temp dir, run runner.py there, return its JSON."""
    ws = Path(tempfile.mkdtemp(prefix="adc_"))
    try:
        shutil.copytree(ROOT, ws, dirs_exist_ok=True, ignore=IGNORE)
        ws.chmod(0o755)                                  # readable by the sandbox user
        for s in subs:
            if s["kind"] == "planner":
                shutil.copytree(s["dir"], ws / "planners" / s["team"])
            else:
                shutil.copy(s["dir"] / "scenes.py", ws / "scenarios" / f"upload_{s['team']}.py")
        cmd = ["python", "leaderboard/runner.py", *args]
        if UNSAFE:
            cmd[0] = sys.executable
        else:
            cmd = ["docker", "run", "--rm", "--network", "none", "--memory", "2g", "--cpus", "1",
                   "--pids-limit", "256", "--user", "65534", "--read-only", "--tmpfs", "/tmp",
                   "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", "-v", f"{ws}:/work:ro", "-w", "/work",
                   IMAGE, "timeout", str(RUN_TIMEOUT_S), *cmd]
        env = {k: v for k, v in os.environ.items() if k != "TEAM_REPOS_TOKEN"}
        try:
            p = subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True, timeout=RUN_TIMEOUT_S + 60)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"timed out after {RUN_TIMEOUT_S} s")
        if p.returncode:
            raise RuntimeError("\n".join((p.stderr or p.stdout or f"exit code {p.returncode}").strip().splitlines()[-3:]))
        return json.loads(p.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def safe_run(args, subs=()):
    try:
        return run_job(args, subs)
    except Exception as e:
        return {"score": 0.0, "error": str(e)}


def core_version() -> str:
    """Changes whenever the simulator or the scoring changes, which invalidates every old result."""
    h = hashlib.sha256()
    for p in sorted([*ROOT.glob("simulator/*.py"), *ROOT.glob("scenarios/*.py"), *ROOT.glob("planners/*.py"),
                     HERE / "runner.py", HERE / "Dockerfile"]):
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def previous_results(core: str) -> dict:
    url = os.environ.get("PREVIOUS_RESULTS_URL")
    try:
        old = json.load(urllib.request.urlopen(url, timeout=30)) if url else {}
    except Exception as e:
        print(f"no previous results ({e}); scoring everything")
        old = {}
    return old if old.get("core") == core else {"core": core, "lists": {}, "runs": {}}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def score(site: Path) -> int:
    """Updates the site; returns how many simulations were run."""
    core = core_version()
    cache = previous_results(core)
    lists, runs = {}, {}                                 # only what is still current is kept
    work = Path(tempfile.mkdtemp(prefix="adc_teams_"))

    subs = {}
    for team, info in TEAMS.items():
        d = work / team
        sha = fetch(team, info, d)
        if sha:
            subs[team] = dict(team=team, kind=info["kind"], dir=d, sha=sha, key=f"{team}@{sha[:7]}",
                              error=prepare(info["kind"], d))

    def scene_list(key, args, sub_list):
        if key not in cache["lists"]:
            if not UNSAFE:
                build_image()
            cache["lists"][key] = safe_run(args, sub_list)
        lists[key] = cache["lists"][key]
        return lists[key]

    examples = scene_list("example", ["list", "example"], [])
    if isinstance(examples, dict):
        raise SystemExit(f"cannot list the example scenes: {examples['error']}")
    scenes = [("example", None, n) for n in examples]
    for s in subs.values():
        if s["kind"] == "scenes" and not s["error"]:
            names = scene_list(s["key"], ["list", f"upload_{s['team']}"], [s])
            if isinstance(names, dict):
                s["error"] = names["error"]
            else:
                scenes += [(s["key"], s, n) for n in names]
    planners = [("baseline", None)] + [(s["key"], s) for s in subs.values() if s["kind"] == "planner" and not s["error"]]

    def run_all(pairs):
        todo = [(p, s) for p, s in pairs if f"{p[0]}|{s[0]}/{s[2]}" not in cache["runs"]]
        if todo and not UNSAFE:
            build_image()
        with ThreadPoolExecutor(os.cpu_count()) as pool:
            done = pool.map(lambda job: safe_run(
                ["run", job[0][1]["team"] if job[0][1] else "baseline",
                 f"upload_{job[1][1]['team']}" if job[1][1] else "example", job[1][2]],
                [x for x in (job[0][1], job[1][1]) if x]), todo)
            for (p, s), result in zip(todo, done):
                cache["runs"][f"{p[0]}|{s[0]}/{s[2]}"] = result
        for p, s in pairs:
            runs[f"{p[0]}|{s[0]}/{s[2]}"] = cache["runs"][f"{p[0]}|{s[0]}/{s[2]}"]
        return len(todo)

    count = run_all([(planners[0], s) for s in scenes])             # baseline first: which scenes are valid
    valid = [s for s in scenes if is_valid(runs.get(f"baseline|{s[0]}/{s[2]}"))]
    count += run_all([(p, s) for p in planners[1:] for s in valid])
    shutil.rmtree(work, ignore_errors=True)

    site.mkdir(parents=True, exist_ok=True)
    (site / "results.json").write_text(json.dumps({"core": core, "lists": lists, "runs": runs}))
    (site / "index.html").write_text(render(subs, scenes, valid, planners, runs))
    print(f"ran {count} simulations; {len(valid)} valid scenes, {len(planners) - 1} planner teams")
    return count


def is_valid(r) -> bool:
    """A scene counts only if the baseline reaches the goal without collision or leaving the road."""
    return bool(r and r.get("completed") and not r.get("collision") and not r.get("road_departure"))


def render(subs, scenes, valid, planners, runs) -> str:
    def name(sub):
        return f"{sub['team']} ({sub['sha'][:7]})" if sub else "baseline (reference)"

    planner_rows = []
    for pkey, psub in planners:
        cells = [runs[f"{pkey}|{s[0]}/{s[2]}"] for s in valid]
        ms = [c["plan_ms_avg"] for c in cells if "plan_ms_avg" in c]
        planner_rows.append(dict(name=name(psub), reference=not psub, cells=cells,
                                 total=sum(c["score"] for c in cells), ms=max(ms) if ms else None))
    planner_rows.sort(key=lambda r: -r["total"])

    scene_rows = {}
    for skey, ssub, n in scenes:
        if not ssub:
            continue
        baseline = runs[f"baseline|{skey}/{n}"]
        scores = [runs[f"{p}|{skey}/{n}"]["score"] for p, _ in planners[1:]] if is_valid(baseline) else []
        if not is_valid(baseline):
            score = 0.0
        else:
            score = 100 - sum(scores) / len(scores) if scores else None   # None: no planner teams yet
        row = scene_rows.setdefault(skey, dict(name=name(ssub), scenes=[]))
        row["scenes"].append(dict(name=n, valid=is_valid(baseline), score=score,
                                  why=baseline.get("error") or baseline.get("end_reason")))
    for row in scene_rows.values():
        known = [i["score"] for i in row["scenes"] if i["score"] is not None]
        row["total"] = sum(known) / len(known) if known else None
    scene_rows = sorted(scene_rows.values(), key=lambda r: -(r["total"] or 0))

    status = [dict(team=t, kind=i["kind"], repo=i["repo"], sha=subs[t]["sha"][:7] if t in subs else "",
                   error=subs[t]["error"] if t in subs else "no code uploaded yet") for t, i in TEAMS.items()]
    return jinja2.Environment(autoescape=True).from_string(PAGE).render(
        valid=valid, planner_rows=planner_rows, scene_rows=scene_rows, status=status,
        updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Driving Challenge Leaderboard</title>
<style>
 body{font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:16px;color:#1d1d1f;background:#fafafa}
 table{border-collapse:collapse;width:100%;margin:8px 0 24px;background:#fff}
 th,td{border:1px solid #ddd;padding:5px 8px;text-align:right;white-space:nowrap}
 th:first-child,td:first-child,td.l{text-align:left} .wrap{overflow-x:auto}
 .ref{color:#777;font-style:italic} .bad{color:#b00020} .muted{color:#777}
</style></head><body>
<h1>Autonomous Driving Challenge</h1>
<p class="muted">Last updated {{ updated }}. Scores update about every 30 minutes after you upload new code.</p>

<h2>AV Trajectory Planning leaderboard</h2>
<p>Total score over every valid scene (100 points each). Hover over a cell to see why the run ended.</p>
<div class="wrap"><table>
<tr><th>#</th><th>Team</th><th>Total / {{ 100 * valid|length }}</th><th>Max avg plan() ms</th>
{% for s in valid %}<th>{{ s[2] }}</th>{% endfor %}</tr>
{% for r in planner_rows %}<tr class="{{ 'ref' if r.reference }}"><td>{{ '' if r.reference else loop.index }}</td>
<td>{{ r.name }}</td><td><b>{{ '%.1f'|format(r.total) }}</b></td>
<td class="{{ 'bad' if r.ms and r.ms > 50 }}">{{ '%.1f'|format(r.ms) if r.ms is not none else '' }}</td>
{% for c in r.cells %}<td title="{{ c.error or c.end_reason }}" class="{{ 'bad' if c.error or c.collision or c.road_departure }}">
{{ '%.1f'|format(c.score) }}</td>{% endfor %}</tr>{% endfor %}
</table></div>

<h2>LLM-based Traffic Scene Generation leaderboard</h2>
<p>Scene score = 100 − average score of the planning teams on it; 0 if the baseline cannot solve it. Team score = average of its scenes.</p>
<div class="wrap"><table>
<tr><th>#</th><th>Team</th><th>Team score</th><th class="l">Scenes</th></tr>
{% for r in scene_rows %}<tr><td>{{ loop.index }}</td><td>{{ r.name }}</td>
<td><b>{{ '%.1f'|format(r.total) if r.total is not none else '—' }}</b></td><td class="l">
{% for i in r.scenes %}<span class="{{ '' if i.valid else 'bad' }}" title="baseline: {{ i.why }}">{{ i.name }}:
{{ '%.1f'|format(i.score) if i.score is not none else '—' }}{{ '' if i.valid else ' (invalid)' }}</span>{{ ', ' if not loop.last }}{% endfor %}
</td></tr>{% endfor %}
</table></div>

<h2>Team status</h2>
<p>Planning teams: put <code>planner.py</code> (and the rest of your <code>planners/&lt;team&gt;/</code> folder) at the top of your team repo.
Scene teams: put <code>scenes.py</code>, which defines <code>STUDENT_SCENARIOS</code>, at the top of your team repo.</p>
<table><tr><th>Team</th><th>Kind</th><th>Version</th><th class="l">Problem</th></tr>
{% for s in status %}<tr><td>{{ s.team }}</td><td>{{ s.kind }}</td><td>{{ s.sha }}</td>
<td class="l {{ 'bad' if s.error }}"><pre style="margin:0;white-space:pre-wrap">{{ s.error or '' }}</pre></td></tr>{% endfor %}
</table>
</body></html>"""


if __name__ == "__main__":
    score(Path(sys.argv[1]))
