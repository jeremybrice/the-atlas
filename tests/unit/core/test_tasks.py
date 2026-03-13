# tests/unit/core/test_tasks.py
from atlas.contracts.types import TaskStatus
from atlas.core.tasks import Task, TaskQueue


def test_task_creation():
    task = Task(description="read a file", skill_id="file.read", input_params={"path": "test.py"})
    assert task.status == TaskStatus.PENDING
    assert task.skill_id == "file.read"


def test_task_queue_enqueue_and_dequeue():
    queue = TaskQueue()
    t1 = Task(description="first")
    t2 = Task(description="second")
    queue.enqueue(t1)
    queue.enqueue(t2)
    assert queue.size() == 2
    next_task = queue.get_next()
    assert next_task.description == "first"
    assert next_task.status == TaskStatus.EXECUTING


def test_task_queue_empty():
    queue = TaskQueue()
    assert queue.get_next() is None


def test_task_complete():
    queue = TaskQueue()
    task = Task(description="do something")
    queue.enqueue(task)
    pulled = queue.get_next()
    queue.complete(pulled.task_id, result={"done": True})
    assert pulled.status == TaskStatus.COMPLETED
    assert pulled.result == {"done": True}


def test_task_fail():
    queue = TaskQueue()
    task = Task(description="do something")
    queue.enqueue(task)
    pulled = queue.get_next()
    queue.fail(pulled.task_id, error="something broke")
    assert pulled.status == TaskStatus.FAILED


def test_task_queue_all_tasks():
    queue = TaskQueue()
    queue.enqueue(Task(description="a"))
    queue.enqueue(Task(description="b"))
    assert len(queue.all_tasks()) == 2


def test_priority_queue_ordering():
    q = TaskQueue()
    low = Task(description="low priority", priority=10)
    high = Task(description="high priority", priority=1)
    q.enqueue(low)
    q.enqueue(high)
    next_task = q.get_next()
    assert next_task.description == "high priority"


def test_task_deduplication():
    q = TaskQueue()
    q.enqueue(Task(description="run tests", dedup_key="tests"))
    q.enqueue(Task(description="run tests again", dedup_key="tests"))
    assert q.size() == 1  # second one was dropped


def test_task_dedup_different_keys():
    q = TaskQueue()
    q.enqueue(Task(description="run tests", dedup_key="tests"))
    q.enqueue(Task(description="run lint", dedup_key="lint"))
    assert q.size() == 2


def test_dedup_key_cleared_on_complete():
    """After completing a task, the same dedup_key can be enqueued again."""
    q = TaskQueue()
    q.enqueue(Task(description="run tests", dedup_key="tests"))
    task = q.get_next()
    q.complete(task.task_id)
    q.enqueue(Task(description="run tests again", dedup_key="tests"))
    assert q.pending_count() == 1


def test_dedup_key_cleared_on_fail():
    """After a task fails, the same dedup_key can be enqueued again."""
    q = TaskQueue()
    q.enqueue(Task(description="run tests", dedup_key="tests"))
    task = q.get_next()
    q.fail(task.task_id, error="broke")
    q.enqueue(Task(description="run tests retry", dedup_key="tests"))
    assert q.pending_count() == 1
