# Leaderboard (for the instructor)

Each team has its own private GitHub repo and uploads its code there. Every 5 minutes (the shortest interval GitHub allows), a GitHub Action scores every team's latest code with the simulator and publishes the leaderboard as a GitHub Pages website. There is no server to run.

| File | What it does |
|---|---|
| `teams.json` | The 12 teams: `kind` (`scenes` or `planner`) and `repo` (the team's GitHub repo) |
| `score.py` | Downloads the team repos, runs everything that is new, writes `index.html` and `results.json` |
| `runner.py` | Runs one simulation inside the sandbox |
| `Dockerfile` | The sandbox: student code runs here with no network, 2 GB of memory and 1 CPU |
| `../.github/workflows/leaderboard.yml` | Runs `score.py` every 5 minutes and publishes the site |

## One-time setup

1. **Create the 12 private team repos**, for example `adc-team-1` … `adc-team-12`, and add each team's students as collaborators.
   Each team can only see its own repo.
2. **Write the repo names into `teams.json`**, replacing `OWNER` with the account that owns them.
3. **Create a read-only access key** on GitHub: *Settings → Developer settings → Fine-grained tokens → Generate new token*.
   * Resource owner: the account that owns the team repos.
   * Repository access: only the 12 team repos.
   * Permissions: *Contents → Read-only*.
   * Expiration: after your final grading.
4. **Store the key** in the repo that holds this leaderboard: *Settings → Secrets and variables → Actions → New repository secret*. Name it `final` (the workflow reads `secrets.FINAL`).
5. **Turn on the website:** *Settings → Pages → Source: GitHub Actions*.
6. **Run it once:** *Actions → Leaderboard → Run workflow*. The site appears at `https://<owner>.github.io/<repo>/`.

## What students do

Open their team repo on GitHub, click **Add file → Upload files**, drag in their files and click **Commit changes**. No git commands are needed.

| Team | What goes at the top of the repo |
|---|---|
| Scene Generation (1–6) | `scenes.py`, which defines `STUDENT_SCENARIOS` and imports only from `scenarios.scenario_tools` |
| Trajectory Planning (7–12) | The contents of their `planners/team_N/` folder, at least `planner.py` with exactly one planner class. Imports inside their own code must use `planners.team_N...` |

The leaderboard updates within about 5–10 minutes. If something is wrong with an upload, the **Team status** table on the site says what.

## How scores are computed

* **Test set:** the three example scenes, plus every scene from the scene teams that the baseline solves. The baseline must reach the goal with no collision or road departure.
* **Trajectory Planning:** each team's latest code is run on every scene in the test set, and the team is ranked by its total score. The baseline appears as a reference. The page also shows each team's average `plan()` time and marks it in red above 50 ms.
* **Scene Generation:** scene score = 100 − the average of the planning teams' scores on that scene, or 0 if the baseline can't solve it. A team's score is the average of its scenes.

Results are reused between runs. A run only simulates the (planner, scene) pairs where either side has new code. If anything in `simulator/`, `scenarios/`, `planners/*.py` or the sandbox changes, everything is scored again.

**Limitation:** planner code runs in the same program as the simulator, so a determined team could fake its score. Reviewing the top teams' code at the end catches this. The rules already forbid it.

## Test

`python leaderboard/test_leaderboard.py` scores a sample planner team and a sample scene team on your own computer, without Docker or GitHub. It takes about 30 seconds and needs `pip install jinja2`.
