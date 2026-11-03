"""SCENARIO TEAM: write your scenarios here.

1. Write a function that returns a ``Scenario`` (see the example below and
   SCENARIO_GUIDE.md).
2. Add it to ``STUDENT_SCENARIOS`` at the bottom of this file.
3. Run it:   python run_simulation.py --scenario my_crosswalk

You never need to change anything in the simulator/ folder.
"""

from __future__ import annotations

from scenarios.scenario_tools import (   # noqa: F401  (everything you may need)
    INTERSECTION_LANE, LEFT_LANE, ONCOMING_LANE, RIGHT_LANE, STRAIGHT_THROUGH, TURN_LEFT, TURN_RIGHT,
    MPH, Scenario, bicycle, car, crosswalk_road, curved_two_lane_road, intersection, intersection_signals,
    pedestrian, truck, two_lane_road,
)


def my_crosswalk() -> Scenario:
    """Example: a pedestrian waits at a crosswalk, then crosses in front of the car."""
    walker = pedestrian(1, s_m=150.0, offset_m=8.95, walk_toward="left", speed_mps=0.0,
                        speed_changes=[(7.0, 0.0), (7.5, 1.3)])   # waits 7 s, then walks at 1.3 m/s
    return Scenario(
        name="my_crosswalk",
        description="A pedestrian waits at the crosswalk and then crosses in front of the car",
        road=crosswalk_road(), route=("crosswalk_road:F2",),
        ego_start_s_m=60.0, ego_speed_mps=8.0, desired_speed_mps=8.0, speed_limit_mps=25 * MPH,
        goal_distance_m=200.0, time_limit_s=45.0,
        actors=(walker,))


# Add every scenario function you write here: "name used on the command line": function
STUDENT_SCENARIOS = {
    "my_crosswalk": my_crosswalk,
}
