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
    subprocess.run(["docker", "build", "-t", IMAGE, str(HERE)], check=True)


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
        if sha and any(not p.name.lower().startswith("readme") for p in d.iterdir()):   # not just our README
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
                                 total=sum(c["score"] for c in cells), ms=max(ms) if ms else None,
                                 goals=sum(bool(c.get("completed")) for c in cells),
                                 crashes=sum(bool(c.get("collision") or c.get("road_departure")) for c in cells)))
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
        repo=os.environ.get("GITHUB_REPOSITORY"), updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60"><title>Driving Challenge Leaderboard</title>
<style>
:root{--bg:#f4f6fa;--card:#fff;--ink:#14181f;--muted:#5d6675;--line:#e3e7ee;--accent:#2f6fed;--bad:#c62828;
 --hero1:#14213d;--hero2:#2f6fed;--heat-l:88%;--heat-s:75%;--gold:#e9b824;--silver:#a7b0bc;--bronze:#c98a52}
@media (prefers-color-scheme:dark){:root{--bg:#0f131a;--card:#171c25;--ink:#e8ecf2;--muted:#98a2b3;--line:#273041;
 --accent:#6b9bff;--bad:#ff6b6b;--hero1:#0b1220;--hero2:#1d3c8a;--heat-l:30%;--heat-s:55%}}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:var(--bg)}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px}
a{color:var(--accent)}
header{background:linear-gradient(120deg,var(--hero1),var(--hero2));color:#fff;padding:36px 0 28px}
header h1{margin:4px 0 6px;font-size:clamp(26px,4vw,38px);letter-spacing:-.02em}
.eyebrow{margin:0;text-transform:uppercase;letter-spacing:.12em;font-size:12px;opacity:.75}
.sub{margin:0;opacity:.8}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0 18px}
.stats div{background:rgba(255,255,255,.12);border-radius:12px;padding:10px 16px;min-width:130px}
.stats b{display:block;font-size:26px;line-height:1.1}.stats span{font-size:13px;opacity:.8}
nav{display:flex;gap:6px;flex-wrap:wrap}
nav a{color:#fff;text-decoration:none;font-size:14px;padding:6px 12px;border-radius:999px;background:rgba(255,255,255,.14)}
nav a:hover{background:rgba(255,255,255,.26)}
section{margin:28px 0}
h2{margin:0 0 4px;font-size:22px}
.lead{margin:0 0 14px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.scroll{overflow-x:auto}
table{border-collapse:separate;border-spacing:0;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:center;white-space:nowrap}
tr:last-child td{border-bottom:0}
th{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;vertical-align:bottom}
th.scene{text-transform:none;letter-spacing:0;white-space:normal;min-width:84px;max-width:110px;font-size:12px}
th.scene small{display:block;font-weight:400;opacity:.8}
.l{text-align:left}
.sticky{position:sticky;left:0;background:var(--card);z-index:1}
.rank{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:50%;font-weight:700;font-size:13px;background:var(--line)}
.r1{background:var(--gold);color:#3a2a00}.r2{background:var(--silver);color:#1e2329}.r3{background:var(--bronze);color:#2e1a07}
.team{font-weight:600}.team small{display:block;font-weight:400;color:var(--muted);font-family:ui-monospace,monospace;font-size:12px}
.ref td{color:var(--muted);background:repeating-linear-gradient(135deg,transparent 0 8px,rgba(127,127,127,.05) 8px 16px)}
.ref .sticky{background:var(--card)}
.total{min-width:150px;text-align:left}.total b{font-size:17px}.total span{color:var(--muted);font-size:12px}
.bar{height:6px;border-radius:3px;background:var(--line);margin-top:4px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent);border-radius:3px}
.heat{background:hsl(calc(var(--s) * 1.2) var(--heat-s) var(--heat-l));font-weight:600;border-left:2px solid var(--card)}
.x{color:var(--bad);font-weight:700}
.bad{color:var(--bad)}
.legend{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px;margin:10px 2px 0}
.legend i{width:120px;height:8px;border-radius:4px;background:linear-gradient(90deg,hsl(0 var(--heat-s) var(--heat-l)),hsl(60 var(--heat-s) var(--heat-l)),hsl(120 var(--heat-s) var(--heat-l)))}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{display:inline-flex;gap:8px;align-items:center;border-radius:999px;padding:3px 4px 3px 12px;font-size:13px;border:1px solid var(--line);background:var(--bg)}
.chip b{border-radius:999px;padding:1px 9px;min-width:44px;text-align:center}
.chip.invalid{border-color:var(--bad);color:var(--bad)}.chip.invalid b{background:transparent}
.empty{padding:22px;text-align:center;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}
.st{padding:12px 14px}.st .top{display:flex;justify-content:space-between;align-items:center;gap:8px}
.tag{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;border-radius:6px;padding:2px 7px;background:var(--line);color:var(--muted)}
.ok{color:#1f8a4c;font-size:13px}.st pre{margin:6px 0 0;white-space:pre-wrap;font-size:12px;color:var(--bad);max-height:7.5em;overflow:auto}
.st code{font-size:12px;color:var(--muted)}.wait{color:var(--muted);font-size:13px}
footer{color:var(--muted);font-size:13px;padding:10px 0 40px}
@media (max-width:600px){header{padding:24px 0 20px}.stats div{min-width:0;flex:1}th,td{padding:7px 6px}}
</style></head><body>
<header><div class="wrap">
  <p class="eyebrow">Final project leaderboard</p>
  <h1>Autonomous Driving Challenge</h1>
  <p class="sub">Updated {{ updated }} · scores update every 5 minutes; this page reloads every minute</p>
  <div class="stats">
    <div><b>{{ valid|length }}</b><span>scenes in the test set</span></div>
    <div><b>{{ planner_rows|length - 1 }}</b><span>planning teams scored</span></div>
    <div><b>{{ scene_rows|length }}</b><span>scene teams scored</span></div>
  </div>
  <nav><a href="#planning">Trajectory Planning</a><a href="#scenes">Scene Generation</a><a href="#status">Team status</a>
  {% if repo %}<a href="https://github.com/{{ repo }}#7-submitting-your-code-and-the-leaderboard">Rules &amp; how to submit</a>{% endif %}</nav>
</div></header>

<main class="wrap">
<section id="planning">
  <h2>AV Trajectory Planning</h2>
  <p class="lead">Total score over every scene in the test set, 100 points each. ✕ = collision or left the road. Hover over a score to see how the run ended.</p>
  <div class="card scroll"><table>
    <tr><th class="sticky">#</th><th class="l sticky" style="left:48px">Team</th><th class="l">Total</th><th>Goals</th><th>Crashes</th><th title="Average time per plan() call; must stay under about 50 ms">plan() ms</th>
    {% for s in valid %}<th class="scene">{{ s[2]|replace('_', ' ') }}<small>{{ s[1].team if s[1] else 'example' }}</small></th>{% endfor %}</tr>
    {% set ns = namespace(rank=0) %}
    {% for r in planner_rows %}{% if not r.reference %}{% set ns.rank = ns.rank + 1 %}{% endif %}
    <tr class="{{ 'ref' if r.reference }}">
      <td class="sticky">{% if r.reference %}–{% else %}<span class="rank r{{ ns.rank }}">{{ ns.rank }}</span>{% endif %}</td>
      <td class="l sticky team" style="left:48px">{{ r.name.split(' ')[0] }}<small>{{ 'reference' if r.reference else r.name.split(' ')[1][1:-1] }}</small></td>
      <td class="total"><b>{{ '%.1f'|format(r.total) }}</b> <span>/ {{ 100 * valid|length }}</span>
        <div class="bar"><i style="width:{{ (100 * r.total / (100 * valid|length)) if valid else 0 }}%"></i></div></td>
      <td>{{ r.goals }}/{{ r.cells|length }}</td>
      <td class="{{ 'bad' if r.crashes }}">{{ r.crashes }}</td>
      <td class="{{ 'bad' if r.ms and r.ms > 50 }}">{{ '%.1f'|format(r.ms) if r.ms is not none else '–' }}</td>
      {% for c in r.cells %}<td class="heat" style="--s:{{ c.score }}" title="{{ c.error or c.end_reason }}">{% if c.error or c.collision or c.road_departure %}<span class="x">✕</span> {% endif %}{{ '%.0f'|format(c.score) }}</td>{% endfor %}
    </tr>{% endfor %}
  </table>
  {% if planner_rows|length == 1 %}<p class="empty">No planning team has uploaded code yet. The baseline is shown for reference.</p>{% endif %}
  </div>
  <div class="legend">0 <i></i> 100 points</div>
</section>

<section id="scenes">
  <h2>LLM-based Traffic Scene Generation</h2>
  <p class="lead">Scene score = 100 − the planning teams' average on it, so harder scenes score higher. A scene the baseline can't solve is invalid and scores 0. Team score = average of its scenes.</p>
  <div class="card scroll"><table>
    <tr><th>#</th><th class="l">Team</th><th class="l">Team score</th><th class="l">Scenes</th></tr>
    {% for r in scene_rows %}<tr>
      <td><span class="rank r{{ loop.index }}">{{ loop.index }}</span></td>
      <td class="l team">{{ r.name.split(' ')[0] }}<small>{{ r.name.split(' ')[1][1:-1] }}</small></td>
      <td class="total">{% if r.total is not none %}<b>{{ '%.1f'|format(r.total) }}</b> <span>/ 100</span>
        <div class="bar"><i style="width:{{ r.total }}%"></i></div>{% else %}<span>waiting for planning teams</span>{% endif %}</td>
      <td class="l"><div class="chips">{% for i in r.scenes %}
        <span class="chip {{ '' if i.valid else 'invalid' }}" title="{{ 'baseline: ' ~ i.why }}">{{ i.name }}
        {% if not i.valid %}<b>invalid</b>{% elif i.score is none %}<b>–</b>{% else %}<b class="heat" style="--s:{{ i.score }}">{{ '%.1f'|format(i.score) }}</b>{% endif %}</span>{% endfor %}
      </div></td>
    </tr>{% endfor %}
  </table>
  {% if not scene_rows %}<p class="empty">No scene team has uploaded scenes yet.</p>{% endif %}
  </div>
</section>

<section id="status">
  <h2>Team status</h2>
  <p class="lead">Planning teams: put <code>planner.py</code> and the rest of your <code>planners/team_N/</code> folder at the top of your team repo.
  Scene teams: put <code>scenes.py</code>, which defines <code>STUDENT_SCENARIOS</code>, at the top of your team repo.</p>
  <div class="grid">{% for s in status %}
    <div class="card st"><div class="top"><span class="team">{{ s.team }}</span><span class="tag">{{ 'planning' if s.kind == 'planner' else 'scenes' }}</span></div>
    {% if s.sha == '' %}<span class="wait">waiting for the first upload</span>{% elif s.error %}<pre>{{ s.error }}</pre>{% else %}<span class="ok">✓ scored</span> <code>{{ s.sha }}</code>{% endif %}</div>{% endfor %}
  </div>
</section>
</main>
<footer class="wrap">Scores come from the simulator only, using what the car actually did. Only each team's latest upload counts.</footer>
</body></html>"""


if __name__ == "__main__":
    score(Path(sys.argv[1]))
