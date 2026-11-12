# Submission Guide: uploading your code to the leaderboard

Every team has its own **private GitHub repo**. You upload your code there. About every 30 minutes, the leaderboard downloads every team's latest code, scores it with the simulator and updates the website:

**Leaderboard: https://labid52.github.io/AutonomousDrivingChallenge/**

| Team | Group | Your repo | What you upload |
|---|---|---|---|
| 1–6 | LLM-based Traffic Scene Generation | `adc-team-N`, e.g. `adc-team-3` | One file: `scenes.py` |
| 7–12 | AV Trajectory Planning | `adc-team-N`, e.g. `adc-team-9` | Your planner folder's contents: `planner.py` + helpers + weights |

You don't need to know git. Everything works through the GitHub website.

---

## Step 1. Get access to your team repo (once)

1. Create a free account at [github.com](https://github.com) if you don't have one.
2. Send your **GitHub username** to the instructor, together with your team number.
3. You will get an invitation email from GitHub. Click **View invitation → Accept invitation**. You can also find it at [github.com/notifications](https://github.com/notifications).
4. Open your repo: `https://github.com/fantasybarry/adc-team-N` (put in your team number). Only your team and the instructor can see it.

---

## Step 2. Prepare your code

Get it working **on your own computer first**. The leaderboard runs exactly the same simulator and scoring as `evaluate.py`.

### Scene Generation teams (1–6)

Your upload is **one file named `scenes.py`**.

1. Write your scenes as the README and [SCENARIO_GUIDE.md](SCENARIO_GUIDE.md) describe. The easiest way is to write them in `scenarios/student_scenario.py`, and then upload that file renamed to `scenes.py`.
2. The file must:
   * import **only** from `scenarios.scenario_tools`, not from your other files, because only this one file is uploaded;
   * end with a `STUDENT_SCENARIOS` dictionary listing every scene;
   * use the same name in each dictionary key and in that scene's `name=`.

   ```python
   from scenarios.scenario_tools import MPH, Scenario, crosswalk_road, pedestrian   # only from scenario_tools

   def school_run() -> Scenario:
       return Scenario(name="school_run", ...)

   STUDENT_SCENARIOS = {
       "school_run": school_run,          # key == name=
   }
   ```
3. Test it. Every scene must be **solvable by the baseline**, which has to reach the goal with no collision and without leaving the road. Otherwise the scene is invalid and scores 0.

   ```bash
   python run_simulation.py --list                                       # your scenes are listed
   python evaluate.py --scenario school_run --planner baseline student   # baseline: goal = True
   ```

### Trajectory Planning teams (7–12)

Your upload is **the contents of your `planners/team_N/` folder**, where N is your team number.

1. Put your planner in `planners/team_N/`, as in the README's *Create your own planner* example. Use your own team number, not `team_a`:

   ```
   planners/team_9/
       __init__.py        (can be empty)
       planner.py         your planner class
       model.py           any helper files (optional)
       weights/model.pt   trained weights (optional)
   ```
2. Rules the leaderboard depends on:
   * `planner.py` must define **exactly one class with a `plan()` method**. Imported classes don't count.
   * Imports inside your own code must use your team folder name, e.g. `from planners.team_9.model import Net`.
   * Load files relative to your code, not the current folder: `Path(__file__).resolve().parent / "weights" / "model.pt"`. The `learned_example` planner shows how.
   * Only these libraries are available: **Python 3.12 standard library, numpy, opencv and PyTorch (CPU)**. Anything else fails to import.
3. To test it, register it in `planners/__init__.py` (see the README), then run:

   ```bash
   python evaluate.py --planner baseline team_9
   ```

   Check that it runs without errors and that **planner compute stays under about 50 ms**.

---

## Step 3. Upload

1. Open your repo on GitHub.
2. Click **Add file → Upload files**.
3. Drag your files into the page:
   * **Scene teams:** `scenes.py`.
   * **Planning teams:** everything *inside* `planners/team_N/`, including subfolders such as `weights/`. Dragging the `team_N` folder itself also works.
4. Write a short message in the box, such as `faster lane change`, and click **Commit changes**.

Your files must be at the **top level** of the repo, next to `README.md`, not inside another folder. The one exception is that the planner may sit inside a single folder.

**Updating:** upload again with the same file names; the new files replace the old ones. To remove a file you no longer need, open it and click **⋯ → Delete file**.

**Files larger than 25 MB**, such as big weights, can't be uploaded through the website. Make them smaller, or use git:
`git clone https://github.com/fantasybarry/adc-team-N`, copy your files in, then `git add -A && git commit -m "update" && git push`.

Only your team's **latest** upload counts.

---

## Step 4. Check your score

1. Wait up to about **30 minutes**. GitHub sometimes starts the update a few minutes late.
2. Open the [leaderboard](https://labid52.github.io/AutonomousDrivingChallenge/) and scroll to **Team status**:
   * **✓ scored** with a 7-character code means it worked. The code matches your latest commit, which appears on your repo page next to the commit message. If it shows an older code, the update hasn't run yet.
   * **Red text** means something went wrong. See the table below.
   * **waiting for the first upload** means no code was found yet.
3. Read your results:
   * **Trajectory Planning:** your total, plus one coloured cell per scene. ✕ means collision or leaving the road. Hover over a cell to see how the run ended.
   * **Scene Generation:** your team score, plus one tag per scene. Hover over an **invalid** tag to see how the baseline failed.

Both leaderboards change when the other group uploads. A new scene is run with every planner, and a new planner is run on every scene. Your score can move even when you change nothing.

---

## Common problems

| Message on the leaderboard | What to do |
|---|---|
| `scenes.py not found at the top of the repo` | Name the file exactly `scenes.py` and put it at the top level of the repo |
| `planner.py not found at the top of the repo` | Upload the *contents* of `planners/team_N/`, so `planner.py` sits at the top level, or inside one folder at most |
| `planner.py must define exactly one class with a plan() method, found 0` / `found 2` | Keep one planner class in `planner.py`, and move the other classes into a helper file |
| `ModuleNotFoundError: No module named 'planners.team_x'` | Your imports use the wrong folder name. Use your own team number: `planners.team_9...` |
| `ModuleNotFoundError: No module named '<something else>'` | That library isn't available. Use only numpy, opencv, PyTorch and the standard library |
| `ModuleNotFoundError` for one of your own scene helper files | Scene teams upload only `scenes.py`. Copy the helper code into it |
| `the uploaded file must define a non-empty STUDENT_SCENARIOS dict` | Add `STUDENT_SCENARIOS = {"name": function, ...}` at the end of `scenes.py` |
| `STUDENT_SCENARIOS key '...' must match the Scenario's name=` | Make each dictionary key the same as that scene's `name=` |
| A scene shows **invalid** | The baseline couldn't solve it. Hover to see why, then make it fairer |
| `timed out after 600 s` | Your code is far too slow, or stuck in a loop |
| **plan() ms** shown in red | Your planner takes over 50 ms per call. Make it faster; judges check this |
| `FileNotFoundError` for your weights | Load them relative to `__file__`, as shown in Step 2, and upload the weights too |
| Score didn't change after uploading | Wait for the next update, then check that the code in Team status matches your latest commit |

---

## Rules (summary)

The full rules are in [COMPETITION_RULES.md](COMPETITION_RULES.md).

* **Planners** may only use the `obs` they are given. They must not read files, use the network, check which scene is running, or interfere with the simulator or the scoring.
* **Scenes** must be solvable by a careful driver and use realistic speeds. If they use random numbers, the seed must be fixed.
* The leaderboard runs your code with no network and a read-only disk.
* Judges review the top teams' code and replays at the end, and may disqualify results that break the rules.
