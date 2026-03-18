import asyncio
import pytest
from atlas.control.emergency import EmergencyController


@pytest.fixture
def controller():
    return EmergencyController()


async def test_initial_state_is_not_paused(controller):
    assert controller.is_paused is False
    assert controller.active_task_id is None


async def test_pause_sets_paused_flag(controller):
    controller.pause()
    assert controller.is_paused is True


async def test_resume_clears_paused_flag(controller):
    controller.pause()
    controller.resume()
    assert controller.is_paused is False


async def test_wait_if_paused_blocks_when_paused(controller):
    controller.pause()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(controller.wait_if_paused(), timeout=0.1)


async def test_wait_if_paused_returns_immediately_when_not_paused(controller):
    await asyncio.wait_for(controller.wait_if_paused(), timeout=0.1)


async def test_wait_if_paused_unblocks_on_resume(controller):
    controller.pause()

    async def resume_soon():
        await asyncio.sleep(0.05)
        controller.resume()

    asyncio.create_task(resume_soon())
    await asyncio.wait_for(controller.wait_if_paused(), timeout=0.5)
    assert controller.is_paused is False


async def test_set_and_clear_active_task(controller):
    controller.set_active_task("task-123")
    assert controller.active_task_id == "task-123"
    controller.clear_active_task()
    assert controller.active_task_id is None


async def test_kill_task_marks_cancelled(controller):
    controller.set_active_task("task-abc")
    result = controller.kill_task("task-abc")
    assert result is True
    assert controller.is_task_cancelled("task-abc")


async def test_kill_task_wrong_id_returns_false(controller):
    controller.set_active_task("task-abc")
    result = controller.kill_task("task-xyz")
    assert result is False
