"""Runs ONE job inside the sandbox and prints its result as JSON on the last line.
Called by server.py, never by students.

    python leaderboard/runner.py list <scene_module>                       # names of the scenes in a module
    python leaderboard/runner.py run <planner> <scene_module> <scene_name>  # one evaluation

<planner> is "baseline" or a team id (code in planners/<team>/planner.py).
<scene_module> is "example" or "upload_<team>" (file scenarios/upload_<team>.py).
"""

import importlib
import inspect
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_scenes(module: str) -> dict:
    if module == "example":
        from scenarios.example_scenarios import EXAMPLE_SCENARIOS
        return EXAMPLE_SCENARIOS
    scenes = getattr(importlib.import_module(f"scenarios.{module}"), "STUDENT_SCENARIOS", None)
    if not isinstance(scenes, dict) or not scenes:
        raise SystemExit("the uploaded file must define a non-empty STUDENT_SCENARIOS dict")
    return scenes


def load_planner(name: str):
    if name == "baseline":
        from planners.baseline_planner import BaselinePlanner
        return BaselinePlanner()
    module = importlib.import_module(f"planners.{name}.planner")
    classes = [c for _, c in inspect.getmembers(module, inspect.isclass)
               if c.__module__ == module.__name__ and callable(getattr(c, "plan", None))]
    if len(classes) != 1:
        raise SystemExit(f"planner.py must define exactly one class with a plan() method, found {len(classes)}")
    return classes[0]()


def main() -> None:
    if sys.argv[1] == "list":
        scenes = load_scenes(sys.argv[2])
        for name, build in scenes.items():
            if build().name != name:
                raise SystemExit(f"STUDENT_SCENARIOS key '{name}' must match the Scenario's name=")
        result = list(scenes)
    else:
        from simulator.simulation import Simulation
        planner_name, module, scene = sys.argv[2:5]
        scenario = load_scenes(module)[scene]()
        planner = load_planner(planner_name)
        times, plan = [], planner.plan

        def timed_plan(obs):                       # measures the 50 ms fairness rule
            start = time.perf_counter()
            try:
                return plan(obs)
            finally:
                times.append(time.perf_counter() - start)

        planner.plan = timed_plan
        result = Simulation(scenario, planner, planner_name, verbose_errors=False).run().as_dict()
        result["plan_ms_avg"] = 1000 * sum(times) / max(1, len(times))
    print("\n" + json.dumps(result))


if __name__ == "__main__":
    main()
