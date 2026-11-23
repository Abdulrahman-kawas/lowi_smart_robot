from spider_common.protocol import Protection
from test_gateway_moves import replies, rig_for, sent


def protection(clock, seq, enabled=False, session="r"):
    return Protection(enabled=enabled, ttl_s=2.0, seq=seq, session=session,
                      ts=1000.0 + clock.now).model_dump_json()


async def test_only_the_app_can_change_lidar_protection():
    gw, link, clock = await rig_for(bench=True)

    for source in ("voice", "bench", "planner"):
        gw.on_request(source, protection(clock, 1, session=source))
    assert sent(link) == []
    for source in ("voice", "bench", "planner"):
        assert replies(link, source)[-1]["detail"] == f"{source} may not change LiDAR protection"

    gw.on_request("button", protection(clock, 1, session="button"))
    assert sent(link) == []
    assert replies(link, "button")[-1]["detail"] == "the button may only release an E-stop"

    gw.on_request("console", protection(clock, 1, session="console"))
    assert sent(link) == [] and replies(link, "console") == []


async def test_app_turns_protection_off_and_on_without_motion_ownership():
    gw, link, clock = await rig_for()

    gw.on_request("remote", protection(clock, 1))
    gw.on_request("voice", protection(clock, 2, enabled=True, session="v"))
    gw.on_request("remote", protection(clock, 3, enabled=True))

    forwarded = [c for c in sent(link) if c["type"] == "protection"]
    assert [(c["enabled"], c["ttl_s"]) for c in forwarded] == [(False, 2.0), (True, 2.0)]
    assert gw._owner is None
