import asyncio
import json

from spider_common.link import InMemoryHub
from spider_common.protocol import Topics

from spider_gateway.button import HOLD_S, HoldDetector, run_loop

ROBOT = "spider-01"
T = Topics(ROBOT)


def test_a_full_hold_fires_exactly_once():
    d = HoldDetector()
    assert not d.update(True, 0.0)
    assert not d.update(True, HOLD_S - 0.01)
    assert d.update(True, HOLD_S)
    assert not d.update(True, HOLD_S + 5.0)


def test_a_short_press_does_not_fire():
    d = HoldDetector()
    d.update(True, 0.0)
    d.update(False, 2.9)
    assert not d.update(True, 3.0)  # the count restarted when the button was let go


def test_it_can_fire_again_after_being_let_go():
    d = HoldDetector()
    d.update(True, 0.0)
    assert d.update(True, HOLD_S)
    d.update(False, HOLD_S + 1)
    d.update(True, HOLD_S + 2)
    assert d.update(True, 2 * HOLD_S + 2)


class HeldButton:
    def __init__(self):
        self.held = False

    def pressed(self):
        return self.held


async def test_holding_publishes_one_release_on_its_own_source():
    link = InMemoryHub().endpoint([])
    await link.start()
    button = HeldButton()
    now = [0.0]
    task = asyncio.create_task(run_loop(button, link, ROBOT, clock=lambda: now[0], poll_s=0.001))
    button.held = True
    await asyncio.sleep(0.01)
    now[0] = HOLD_S + 0.1
    await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert [m.topic for m in link.published] == [T.request("button")]
    assert json.loads(link.published[0].payload)["type"] == "estop_release"
