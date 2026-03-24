from cogos.db.sqlite_repository import SqliteRepository


def test_creates_db_file(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    assert (tmp_path / "cogos.db").exists()


def test_tables_created(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    tables = repo.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    table_names = [t["name"] for t in tables]
    assert "cogos_process" in table_names
    assert "cogos_file" in table_names
    assert "cogos_run" in table_names


def test_epoch_starts_at_zero(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    assert repo.reboot_epoch == 0


def test_increment_epoch(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    assert repo.increment_epoch() == 1
    assert repo.increment_epoch() == 2
    assert repo.reboot_epoch == 2


def test_batch_is_transactional(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    repo.set_meta("key1", "val1")
    try:
        with repo.batch():
            repo.set_meta("key2", "val2")
            raise ValueError("rollback")
    except ValueError:
        pass
    assert repo.get_meta("key1") is not None
    assert repo.get_meta("key2") is None


def test_meta_set_and_get(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    repo.set_meta("foo", "bar")
    result = repo.get_meta("foo")
    assert result == {"key": "foo", "value": "bar"}


def test_clear_all(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    repo.set_meta("key", "val")
    repo.clear_all()
    assert repo.get_meta("key") is None


def test_upsert_and_get_process(tmp_path):
    from cogos.db.models import Process, ProcessMode, ProcessStatus
    repo = SqliteRepository(str(tmp_path))
    p = Process(name="test", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    pid = repo.upsert_process(p)
    result = repo.get_process(pid)
    assert result is not None
    assert result.name == "test"


def test_get_process_by_name(tmp_path):
    from cogos.db.models import Process, ProcessMode, ProcessStatus
    repo = SqliteRepository(str(tmp_path))
    p = Process(name="named", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.WAITING)
    repo.upsert_process(p)
    result = repo.get_process_by_name("named")
    assert result is not None


def test_process_cascade_disable(tmp_path):
    from cogos.db.models import Process, ProcessMode, ProcessStatus
    repo = SqliteRepository(str(tmp_path))
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING, parent_process=parent.id)
    repo.upsert_process(child)
    repo.update_process_status(parent.id, ProcessStatus.DISABLED)
    assert repo.get_process(child.id).status == ProcessStatus.DISABLED


def test_process_round_trip_json_fields(tmp_path):
    from cogos.db.models import Process, ProcessMode, ProcessStatus
    repo = SqliteRepository(str(tmp_path))
    p = Process(name="rt", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING,
                metadata={"key": "val"}, required_tags=["gpu"])
    repo.upsert_process(p)
    got = repo.get_process(p.id)
    assert got.metadata == {"key": "val"}
    assert got.required_tags == ["gpu"]
