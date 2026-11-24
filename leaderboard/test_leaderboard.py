"""End-to-end check without Docker or GitHub: score one planner team and one scene team, then
check that a second run reuses every result.

    python leaderboard/test_leaderboard.py      (needs jinja2 + the project requirements; ~30 s)
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["LEADERBOARD_UNSAFE_NO_DOCKER"] = "1"
sys.path.insert(0, str(ROOT / "leaderboard"))
import score  # noqa: E402

tmp = Path(tempfile.mkdtemp())
(tmp / "team_7" / "team_7").mkdir(parents=True)             # uploaded as a folder, not its contents
shutil.copy(ROOT / "planners/student_planner.py", tmp / "team_7/team_7/planner.py")
(tmp / "team_1").mkdir()
shutil.copy(ROOT / "scenarios/student_scenario.py", tmp / "team_1/scenes.py")
(tmp / "team_2").mkdir()
(tmp / "team_2/scenes.py").write_text("STUDENT_SCENARIOS = {}\n")   # broken upload
(tmp / "team_3").mkdir()
(tmp / "team_3/README.md").write_text("upload here")          # repo with only our README: not uploaded yet

score.TEAMS = {"team_1": {"kind": "scenes", "repo": "x/1"}, "team_2": {"kind": "scenes", "repo": "x/2"},
               "team_3": {"kind": "scenes", "repo": "x/3"}, "team_7": {"kind": "planner", "repo": "x/7"}}


def fake_fetch(team, info, dest):
    if not (tmp / team).exists():
        return None
    shutil.copytree(tmp / team, dest)
    return "abcdef1234" + team


score.fetch = fake_fetch
site = tmp / "site"
assert score.score(site) == 5 + 5                           # 3 examples + practice + team_1's scene, baseline + team_7

results = json.loads((site / "results.json").read_text())
crosswalk = results["runs"]["team_7@abcdef1|team_1@abcdef1/my_crosswalk"]["score"]
page = (site / "index.html").read_text()
assert "team_7<small>abcdef1</small>" in page and "team_1<small>abcdef1</small>" in page
assert f">{100 - crosswalk:.1f}</b>" in page                # my_crosswalk's scene score
assert "practice, not counted" in page and "/ 400<" in page  # the practice scene is shown but not in the total
counted = sum(v["score"] for k, v in results["runs"].items() if k.startswith("team_7@") and "student_scenario/" not in k)
assert f"<b>{counted:.1f}</b> <span>/ 400" in page
scene_table = page.split('id="scenes"')[1]
assert "baseline<small>reference</small>" in scene_table and 'class="rank r1">1<' in scene_table and "rank r2" not in scene_table
assert "non-empty STUDENT_SCENARIOS" in page and "waiting for the first upload" in page

os.environ["PREVIOUS_RESULTS_URL"] = (site / "results.json").as_uri()
os.environ["GITHUB_OUTPUT"] = str(site / "out.txt")
assert score.score(site) == 0                               # nothing changed: nothing re-run
assert (site / "out.txt").read_text() == "changed=false\n"   # ... and nothing to deploy
print(f"OK: team_7 on my_crosswalk = {crosswalk:.1f}")
