from __future__ import annotations
import random
from typing import List

from agents.driver import DriverAgent
from agents.company import CompanyAgent
from agents.environment import EnvironmentAgent


class DeliveryModel:
    def __init__(self, daily_volume: int, n_drivers: int,
                 max_legal_hours: float, env: EnvironmentAgent):
        self.env = env
        self.tick = 0
        company = CompanyAgent(daily_volume, n_drivers)
        allocations = company.allocate()
        stops = env.delivery_stops

        self.drivers: List[DriverAgent] = []
        for i in range(n_drivers):
            start  = random.choice(stops)
            target = random.choice(stops)
            d = DriverAgent(
                agent_id=i + 1,
                lat=start[0] + random.uniform(-0.001, 0.001),
                lon=start[1] + random.uniform(-0.001, 0.001),
                max_legal_hours=max_legal_hours,
                assigned_deliveries=allocations[i],
                target_lat=target[0],
                target_lon=target[1],
            )
            d.current_road = env.nearest_road(d.lat, d.lon)
            self.drivers.append(d)

    def step(self, n_ticks: int = 1):
        for _ in range(n_ticks):
            self.tick += 1
            for d in self.drivers:
                d.step(self.env.delivery_stops, self.env.nearest_road)

    @property
    def is_done(self) -> bool:
        return all(d.over_limit or d.delivered >= d.assigned_deliveries
                   for d in self.drivers)

    def summary(self) -> dict:
        active  = sum(1 for d in self.drivers if not d.over_limit and d.delivered < d.assigned_deliveries)
        over    = sum(1 for d in self.drivers if d.over_limit)
        done    = sum(d.delivered for d in self.drivers)
        total   = sum(d.assigned_deliveries for d in self.drivers)
        walking = sum(1 for d in self.drivers if d.walking and not d.over_limit)
        return {"active": active, "over": over, "walking": walking,
                "done": done, "total": total,
                "remain": max(0, total - done), "tick": self.tick}
