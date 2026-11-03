"""PLANNER TEAM: your planner lives here.

The simulator calls ``StudentPlanner().plan(observation)`` 20 times per
second.  You must return a ``Trajectory`` (see PLANNER_GUIDE.md):

    Trajectory(t_s=..., x_m=..., y_m=..., speed_mps=...)

    t_s       times, starting at 0 (e.g. 0, 0.1, ..., 4.0)
    x_m, y_m  where the car's REAR AXLE should be at those times, in the
              ego frame (x forward, y RIGHT, the car is at (0, 0) now)
    speed_mps the speed the car should have there

This starter planner works but is simple: it keeps its lane, follows the
car ahead and stops for red lights.  It does NOT change lanes and does NOT
yield at junctions -- that is your job.  Ideas:
  * check your plan against predicted road users (planner_tools.first_collision)
  * try a lane change when the car ahead is slow (obs.lanes["left"])
  * stop at yield lines when crossing traffic is coming
  * or start from a copy of planners/baseline_planner.py and improve it

Rules: use only the observation you are given (see COMPETITION_RULES.md).
"""

from __future__ import annotations

import math

from planners.planner_tools import (
    EGO_REAR_AXLE_TO_FRONT_M, build_trajectory, find_lead, lateral_profile, speed_profile, time_grid,
)
from simulator.geometry import reference_state
from simulator.trajectory import Trajectory


class StudentPlanner:
    def __init__(self) -> None:
        self.t = time_grid(horizon_s=4.0, dt_s=0.1)

    def plan(self, obs) -> Trajectory:
        lane = obs.lanes["current"]                 # the lane we are driving in

        # 1) Is there a vehicle ahead of us in this lane?
        lead = find_lead(lane, obs.actors)

        # 2) Do we have to stop for a red / yellow traffic light?
        stop_distance = None                        # where our REAR AXLE must stop (metres ahead)
        for line in obs.stop_lines:
            front_distance = line.distance_m - EGO_REAR_AXLE_TO_FRONT_M
            if line.control == "signal" and line.signal_state in ("RED", "YELLOW") and front_distance > 0.0:
                stop_distance = front_distance - 1.0
                break

        # 3) Speed over the next 4 s: cruise, follow the lead, stop if needed
        s, v, a = speed_profile(self.t, obs.ego.speed_mps, obs.ego.acceleration_mps2, obs.desired_speed_mps,
                                lane=lane, stop_s_m=None if stop_distance is None else max(stop_distance, 0.0),
                                lead=lead)

        # 4) Sideways: steer smoothly back to the lane centre
        heading_error = -float(reference_state(lane.centerline, lane.ego_s_m)[2])
        d = lateral_profile(lane.ego_d_m, math.tan(heading_error), 0.0, max(8.0, 1.5 * obs.ego.speed_mps), s)

        # 5) Turn (distance along the lane, offset) into x/y points
        behavior = "FOLLOW_LEAD" if lead is not None and lead.gap_m < 40.0 else "KEEP_LANE"
        if stop_distance is not None:
            behavior = "STOP_SIGNAL"
        notes = ["student planner (starter version)"]
        if lead is not None:
            notes = [f"lead #{lead.actor_id}  {lead.gap_m:.0f} m  {lead.speed_mps:.1f} m/s"]
        return build_trajectory(lane, self.t, s, d, v, a, behavior=behavior, notes=notes)
