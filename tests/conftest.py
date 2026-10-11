"""Tests must not acquire the user's live model request lock."""
import pytest


@pytest.fixture(autouse=True)
def isolated_model_request_database(monkeypatch, tmp_path):
    import core.model_workload as workload
    monkeypatch.setattr(workload, "DEFAULT_DATABASE", tmp_path / "model-workload.sqlite3")
    import core.cost_policy as cost_policy
    monkeypatch.setattr(cost_policy, "COST_POLICY_PATH", tmp_path / "ai-cost-policy.json")
