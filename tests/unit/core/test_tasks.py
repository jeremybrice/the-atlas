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
