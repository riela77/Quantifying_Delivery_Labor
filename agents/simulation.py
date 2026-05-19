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
        allocations = CompanyAgent(daily_volume, n_drivers).allocate()
        stops = env.delivery_stops

        self.drivers: List[DriverAgent] = []
        for i in range(n_drivers):
            start = random.choice(stops)
            d = DriverAgent(
                agent_id=i+1,
                lat=start[0]+random.uniform(-0.0005,0.0005),
                lon=start[1]+random.uniform(-0.0005,0.0005),
                max_legal_hours=max_legal_hours,
                assigned_deliveries=allocations[i],
            )
            d.current_road = env.nearest_road(d.lat, d.lon)
            # 첫 경로 설정
            if stops:
                target = random.choice(stops)
                d.route = env.find_path(d.lat, d.lon, target[0], target[1])
            self.drivers.append(d)

    def step(self, n_ticks: int = 1):
        for _ in range(n_ticks):
            self.tick += 1
            for d in self.drivers:
                d.step(self.env.delivery_stops, self.env)

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
        return {"active":active,"over":over,"walking":walking,
                "done":done,"total":total,"remain":max(0,total-done),"tick":self.tick}