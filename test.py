from dataclasses import dataclass

from snitchvis import SnitchvisApp

@dataclass
class Snitch:
    x: int
    y: int

@dataclass
class Ping:
    snitch: Snitch
    # in ms
    t: int

s = Snitch(0, 0)
s2 = Snitch(10, 10)
s3 = Snitch(10, -10)
snitches = [s, s2, s3]
pings = [Ping(s, 0), Ping(s2, 1200), Ping(s3, 1400)]

vis = SnitchvisApp(snitches, pings)
vis.exec()
