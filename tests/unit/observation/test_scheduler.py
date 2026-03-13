import asyncio
from atlas.observation.scheduler import ScheduledTrigger
from atlas.contracts.types import ObservationEvent, EventType


async def test_scheduled_trigger_fires_on_interval():
    events: list[ObservationEvent] = []

    async def on_event(event: ObservationEvent):
        events.append(event)

    trigger = ScheduledTrigger(
        name="test-trigger",
        interval_seconds=0.2,
        goal_template="do the thing",
        callback=on_event,
    )
    await trigger.start()
    await asyncio.sleep(0.5)
    await trigger.stop()

    assert len(events) >= 2
    assert events[0].event_type == EventType.SCHEDULED
    assert events[0].source == "schedule:test-trigger"
    assert events[0].payload["goal"] == "do the thing"


async def test_scheduled_trigger_stop():
    events: list[ObservationEvent] = []

    async def on_event(event: ObservationEvent):
        events.append(event)

    trigger = ScheduledTrigger(
        name="stop-test", interval_seconds=0.1, goal_template="x", callback=on_event,
    )
    await trigger.start()
    await asyncio.sleep(0.25)
    await trigger.stop()
    count_at_stop = len(events)
    await asyncio.sleep(0.3)
    assert len(events) == count_at_stop  # no more events after stop
