from atlas.memory.working import WorkingMemoryStore


def test_set_and_get():
    store = WorkingMemoryStore()
    store.set("key1", "value1")
    assert store.get("key1") == "value1"


def test_get_missing_key_returns_none():
    store = WorkingMemoryStore()
    assert store.get("nonexistent") is None


def test_clear():
    store = WorkingMemoryStore()
    store.set("a", 1)
    store.set("b", 2)
    store.clear()
    assert store.get("a") is None
    assert store.get("b") is None


def test_overwrite():
    store = WorkingMemoryStore()
    store.set("key", "old")
    store.set("key", "new")
    assert store.get("key") == "new"


def test_max_keys_eviction():
    store = WorkingMemoryStore(max_keys=3)
    store.set("a", 1)
    store.set("b", 2)
    store.set("c", 3)
    store.set("d", 4)  # should evict "a"
    assert store.get("a") is None
    assert store.get("d") == 4


def test_get_all():
    store = WorkingMemoryStore()
    store.set("x", 10)
    store.set("y", 20)
    all_items = store.get_all()
    assert all_items == {"x": 10, "y": 20}
