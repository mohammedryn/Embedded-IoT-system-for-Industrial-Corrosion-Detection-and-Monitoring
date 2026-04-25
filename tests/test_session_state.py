from concurrent.futures import ThreadPoolExecutor

from edge.session_state import SessionStateManager


def test_new_session_resets_state():
    store = SessionStateManager(max_readings=10)
    first_session = store.session_id

    store.add_photo("/tmp/photo-a.jpg")
    store.add_reading({"seq": 1, "rp_ohm": 9000.0})

    next_session = store.new_session()

    assert next_session != first_session
    assert store.list_photos() == []
    assert store.readings_snapshot() == []


def test_readings_maxlen_enforced():
    store = SessionStateManager(max_readings=3)
    for i in range(6):
        store.add_reading({"seq": i, "rp_ohm": float(i)})

    snapshot = store.readings_snapshot()
    assert len(snapshot) == 3
    assert [row["seq"] for row in snapshot] == [3, 4, 5]


def test_add_reading_threadsafe():
    store = SessionStateManager(max_readings=3000)

    def write_one(i: int) -> None:
        store.add_reading({"seq": i, "rp_ohm": float(i)})

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(write_one, range(1000)))

    snapshot = store.readings_snapshot()
    assert len(snapshot) == 1000
    assert store.latest_reading() is not None