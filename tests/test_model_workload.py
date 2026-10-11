import pytest
from core.model_workload import model_slot, ModelBusyError


def test_competing_local_request_wait_is_bounded_and_release_allows_next(tmp_path):
    database = tmp_path / "slots.sqlite3"
    with model_slot("http://127.0.0.1:8080/v1", database=database):
        with pytest.raises(ModelBusyError):
            with model_slot("http://127.0.0.1:8081/v1", database=database, wait_seconds=0):
                pytest.fail("Competing local model requests ran together")
    with model_slot("http://127.0.0.1:8081/v1", database=database, wait_seconds=0):
        pass


def test_model_failure_releases_slot(tmp_path):
    database = tmp_path / "slots.sqlite3"
    with pytest.raises(ValueError):
        with model_slot("http://127.0.0.1", database=database):
            raise ValueError("model failed")
    with model_slot("http://127.0.0.1", database=database, wait_seconds=0):
        pass


def test_remote_request_does_not_acquire_local_slot(tmp_path):
    database = tmp_path / "unused.sqlite3"
    with model_slot("https://example.com", database=database):
        assert not database.exists()
