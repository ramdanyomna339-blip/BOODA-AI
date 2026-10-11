from contextlib import contextmanager
import json
from pathlib import Path
from threading import Event, Lock, Thread

import pytest

import core.main as main_module
import core.local_model as local_model
from core.llm_planner import OpenAICompatiblePlanner
from core.approval_manager import BoodaApprovalManager
from core.artifact_manager import BoodaArtifactManager
from core.audit_log import BoodaAuditLog
from core.capability_registry import BoodaCapabilityRegistry
from core.goal_manager import BoodaGoalManager
from core.planning import BoodaGoal, BoodaPlan, PlanStep
from core.permission_manager import BoodaPermissionManager
from core.task_manager import BoodaTaskManager
from core.agent_session import BoodaAgentSessionStore
from core.risk import RiskLevel


def test_ai_provider_defaults_to_gemini_unless_another_provider_is_selected():
    assert main_module._resolve_ai_provider("") == "gemini"
    assert main_module._resolve_ai_provider("local") == "local"
    assert main_module._resolve_ai_provider("", "https://example.test/v1") == "openai"


def _create_server_files(root):
    runtime = root / ".local-ai-runtime"
    binary = runtime / "bin" / "llama-server.exe"
    model = root / local_model.DEFAULT_MODEL_RELATIVE_PATH
    smaller_model = runtime / "models" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
    binary.parent.mkdir(parents=True)
    model.parent.mkdir(parents=True)
    binary.write_bytes(b"server placeholder")
    model.write_bytes(b"model placeholder")
    smaller_model.write_bytes(b"smaller model placeholder")
    return binary, model


class _FakeProcess:
    pid = 12345

    def __init__(self, return_code=None):
        self.return_code = return_code
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.return_code

    def terminate(self):
        self.terminated = True
        self.return_code = 0

    def wait(self, timeout=None):
        return self.return_code

    def kill(self):
        self.killed = True
        self.return_code = -9


def test_local_server_reports_exact_missing_files(tmp_path, monkeypatch):
    monkeypatch.setattr(local_model, "_is_healthy", lambda: False)

    with pytest.raises(RuntimeError) as error:
        with local_model.ensure_local_model_server(root=tmp_path):
            pytest.fail("Server must not start when local assets are missing.")

    assert str(
        tmp_path / ".local-ai-runtime" / "models"
        / "Qwen3-4B-Q2_K.gguf"
    ) in str(error.value)
    assert "GGUF models present" in str(error.value)


def test_local_model_defaults_to_qwen3_4b_and_ignores_smaller_model(
    tmp_path, monkeypatch
):
    _, model = _create_server_files(tmp_path)
    monkeypatch.delenv("BOODA_LOCAL_MODEL_PATH", raising=False)

    project_root, selected = local_model.resolve_local_model_path(root=tmp_path)

    assert project_root == tmp_path.resolve()
    assert selected == model.resolve()
    assert selected.name == "Qwen3-4B-Q2_K.gguf"
    assert selected.name != "qwen2.5-0.5b-instruct-q4_k_m.gguf"


def test_relative_configured_model_path_is_resolved_from_project_root(
    tmp_path, monkeypatch
):
    _, model = _create_server_files(tmp_path)
    relative = str(model.relative_to(tmp_path))
    monkeypatch.setenv("BOODA_LOCAL_MODEL_PATH", relative)

    project_root, selected = local_model.resolve_local_model_path(root=tmp_path)

    assert project_root == tmp_path.resolve()
    assert selected == model.resolve()


def test_missing_configured_model_lists_available_models_without_fallback(
    tmp_path, monkeypatch
):
    _, default_model = _create_server_files(tmp_path)
    missing = tmp_path / "custom-model.gguf"
    monkeypatch.setenv("BOODA_LOCAL_MODEL_PATH", str(missing))
    monkeypatch.setattr(local_model, "_is_healthy", lambda: False)
    launches = []
    monkeypatch.setattr(
        local_model.subprocess, "Popen",
        lambda *args, **kwargs: launches.append(args),
    )

    with pytest.raises(RuntimeError) as error:
        with local_model.ensure_local_model_server(root=tmp_path):
            pytest.fail("A missing configured model must not be replaced.")

    message = str(error.value)
    assert str(missing) in message
    assert default_model.name in message
    assert "Qwen3-4B-Q2_K.gguf" in message
    assert "no model was selected automatically" in message
    assert launches == []


def test_local_readiness_check_reports_health_state(monkeypatch):
    monkeypatch.setattr(local_model, "_is_healthy", lambda: False)
    with pytest.raises(RuntimeError, match="127.0.0.1:8080/health"):
        local_model.check_local_model_readiness()

    monkeypatch.setattr(local_model, "_is_healthy", lambda: True)
    assert local_model.check_local_model_readiness() == local_model.BASE_URL


@pytest.mark.parametrize("matching", [True, False])
def test_existing_server_must_match_selected_model(tmp_path, monkeypatch, matching):
    from io import BytesIO
    _, selected = _create_server_files(tmp_path)
    monkeypatch.setattr(local_model, "_is_healthy", lambda: True)
    class Opener:
        def open(self, url, timeout):
            assert url.endswith("/props")
            return BytesIO(json.dumps({"model_path": str(selected if matching else tmp_path / "other.gguf")}).encode())
    monkeypatch.setattr(local_model, "build_opener", lambda *args: Opener())
    launches = []
    monkeypatch.setattr(local_model.subprocess, "Popen", lambda *args, **kwargs: launches.append(args))
    if matching:
        with local_model.ensure_local_model_server(root=tmp_path) as url:
            assert url == local_model.BASE_URL
    else:
        with pytest.raises(RuntimeError, match="not stopped or silently reused"):
            with local_model.ensure_local_model_server(root=tmp_path):
                pytest.fail("Mismatched server must not be used")
    assert launches == []


def test_local_server_reports_startup_failure_and_log_details(tmp_path, monkeypatch):
    _create_server_files(tmp_path)
    monkeypatch.setattr(local_model, "_is_healthy", lambda: False)
    fake_process = _FakeProcess(return_code=2)
    monkeypatch.setattr(local_model.subprocess, "Popen", lambda *args, **kwargs: fake_process)
    log_path = tmp_path / ".local-ai-runtime" / "server.log"
    log_path.write_text("unable to allocate model buffer", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unable to allocate model buffer"):
        with local_model.ensure_local_model_server(root=tmp_path):
            pytest.fail("Failed server must not be treated as ready.")


def test_local_server_timeout_stops_the_owned_process(tmp_path, monkeypatch):
    _create_server_files(tmp_path)
    monkeypatch.setattr(local_model, "_is_healthy", lambda: False)
    fake_process = _FakeProcess()
    monkeypatch.setattr(local_model.subprocess, "Popen", lambda *args, **kwargs: fake_process)

    with pytest.raises(RuntimeError, match="Timed out waiting"):
        with local_model.ensure_local_model_server(root=tmp_path, startup_timeout=0):
            pytest.fail("A server without a readiness response must time out.")

    assert fake_process.terminated
    assert not fake_process.killed


def test_local_server_stops_only_a_process_started_by_its_context(
    tmp_path, monkeypatch
):
    _create_server_files(tmp_path)
    fake_process = _FakeProcess()
    launch = {}

    def fake_popen(command, **kwargs):
        launch["command"] = command
        launch["kwargs"] = kwargs
        return fake_process

    monkeypatch.setattr(local_model.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(local_model.time, "sleep", lambda _seconds: None)
    health = iter([False, True, True])
    monkeypatch.setattr(local_model, "_is_healthy", lambda: next(health))

    with local_model.ensure_local_model_server(root=tmp_path) as url:
        assert url == local_model.BASE_URL
        assert not fake_process.terminated

    assert fake_process.terminated
    command = launch["command"]
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "8080"
    assert command[command.index("--model") + 1] == str(
        (tmp_path / ".local-ai-runtime" / "models"
         / "Qwen3-4B-Q2_K.gguf").resolve()
    )
    assert command[command.index("--model") + 1] == str(
        (tmp_path / ".local-ai-runtime" / "models" / "Qwen3-4B-Q2_K.gguf").resolve()
    )


def test_concurrent_server_contexts_never_start_two_servers(tmp_path, monkeypatch):
    _create_server_files(tmp_path)
    state_lock = Lock()
    active_servers = 0
    max_active_servers = 0
    launch_count = 0
    first_ready = Event()
    second_ready = Event()
    release_first = Event()
    release_second = Event()
    second_started = Event()
    failures = []

    class TrackedProcess(_FakeProcess):
        def terminate(self):
            nonlocal active_servers
            with state_lock:
                if not self.terminated:
                    active_servers -= 1
                self.terminated = True
                self.return_code = 0

    def fake_popen(_command, **_kwargs):
        nonlocal active_servers, max_active_servers, launch_count
        with state_lock:
            launch_count += 1
            active_servers += 1
            max_active_servers = max(max_active_servers, active_servers)
        return TrackedProcess()

    def healthy():
        with state_lock:
            return active_servers > 0

    monkeypatch.setattr(local_model.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(local_model, "_is_healthy", healthy)
    monkeypatch.setattr(local_model.time, "sleep", lambda _seconds: None)

    def use_server(ready, release, announce_start=False):
        try:
            if announce_start:
                second_started.set()
            with local_model.ensure_local_model_server(root=tmp_path):
                ready.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("Timed out waiting to release test server.")
        except Exception as error:
            failures.append(error)

    first = Thread(target=use_server, args=(first_ready, release_first))
    second = Thread(
        target=use_server,
        args=(second_ready, release_second, True),
    )
    first.start()
    assert first_ready.wait(timeout=5)
    second.start()
    assert second_started.wait(timeout=5)

    with state_lock:
        assert active_servers == 1
    release_first.set()
    assert second_ready.wait(timeout=5)
    with state_lock:
        assert active_servers == 1
    release_second.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert failures == []
    assert launch_count == 2
    assert max_active_servers == 1
    assert active_servers == 0


@pytest.mark.parametrize("provider", ["local"])
def test_local_provider_selection_does_not_read_keys_or_remote_settings(
    tmp_path, monkeypatch, capsys, provider
):
    monkeypatch.chdir(tmp_path)
    if provider is None:
        monkeypatch.delenv("BOODA_AI_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("BOODA_AI_PROVIDER", provider)
    audit_log = BoodaAuditLog(tmp_path / "audit.jsonl")
    permissions = BoodaPermissionManager(audit_log=audit_log)
    permissions.add_permission("save_file", allowed=False)
    approvals = BoodaApprovalManager(audit_log=audit_log)
    tasks = BoodaTaskManager(tmp_path / "tasks.json")
    goals = BoodaGoalManager(tmp_path / "goals.json")
    capabilities = BoodaCapabilityRegistry(tmp_path / "capabilities.json")
    capabilities.register("save_task_content", permission_name="save_file")
    sessions = BoodaAgentSessionStore(tmp_path / "sessions.json")
    server_lifecycle = []

    @contextmanager
    def fake_local_server():
        server_lifecycle.append("start")
        yield local_model.BASE_URL
        server_lifecycle.append("stop")

    class LocalOnlyEnvironment:
        def getenv(self, name, default=None):
            if name in {"BOODA_PROJECT_ID", "BOODA_CLIENT_ID"}:
                return default
            if name == "BOODA_AI_PROVIDER":
                return provider or ""
            if provider is None and name == "BOODA_LLM_BASE_URL":
                return default
            raise AssertionError(f"Local mode must not read {name}.")

    class FakePlanner:
        requires_explicit_permissions = True

        def __init__(self, **kwargs):
            assert kwargs["base_url"] == local_model.BASE_URL
            assert kwargs["model"] == local_model.MODEL_NAME
            assert kwargs["api_key"] is None

        def configure_agent(self, **_kwargs):
            return None

        def create_plan(self, goal, _memory):
            return BoodaPlan(goal.goal_id, (
                PlanStep(
                    "local-draft", "Local draft", "Demo draft",
                    capability="save_task_content", permission_name="save_file",
                ),
            ))

        def respond(self, _message, *, context=None, memory=None):
            return "رد محلي"

    answers = iter(["اكتب خطة تدريبية", "لا"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(main_module, "os", LocalOnlyEnvironment())
    monkeypatch.setattr(main_module, "ensure_local_model_server", fake_local_server)
    monkeypatch.setattr(main_module, "OpenAICompatiblePlanner", FakePlanner)

    main_module.run_ai_agent(
        audit_log=audit_log,
        permission_manager=permissions,
        approval_manager=approvals,
        task_manager=tasks,
        goal_manager=goals,
        capability_registry=capabilities,
        session_store=sessions,
    )

    assert server_lifecycle == ["start", "stop"]
    assert not (tmp_path / "outputs").exists()
    assert "نموذج Booda المحلي" in capsys.readouterr().out


def test_ollama_provider_uses_local_endpoint_and_never_reads_api_key(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOODA_AI_PROVIDER", "ollama")
    monkeypatch.delenv("BOODA_OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("BOODA_OLLAMA_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    audit_log = BoodaAuditLog(tmp_path / "audit.jsonl")
    permissions = BoodaPermissionManager(audit_log=audit_log)
    permissions.add_permission("save_file", allowed=False)
    approvals = BoodaApprovalManager(audit_log=audit_log)
    tasks = BoodaTaskManager(tmp_path / "tasks.json")
    goals = BoodaGoalManager(tmp_path / "goals.json")
    capabilities = BoodaCapabilityRegistry(tmp_path / "capabilities.json")
    sessions = BoodaAgentSessionStore(tmp_path / "sessions.json")
    captured = {}

    def capture_session(planner, *args, **kwargs):
        captured["planner"] = planner

    monkeypatch.setattr(main_module, "_run_ai_agent_session", capture_session)
    monkeypatch.setattr(
        main_module,
        "ensure_local_model_server",
        lambda: pytest.fail("Ollama mode must not start the bundled llama.cpp server."),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "اكتبي خطة محلية")

    main_module.run_ai_agent(
        audit_log=audit_log,
        permission_manager=permissions,
        approval_manager=approvals,
        task_manager=tasks,
        goal_manager=goals,
        capability_registry=capabilities,
        session_store=sessions,
    )

    planner = captured["planner"]
    assert planner.base_url == "http://127.0.0.1:11434/v1"
    assert planner.model == "qwen3.5:4b"
    assert planner.api_key is None
    assert planner.local_planning is False
    assert planner.capability_permissions == {
        "save_task_content": ("save_file",)
    }
    assert "نموذج Ollama المحلي: qwen3.5:4b" in capsys.readouterr().out


def test_ollama_provider_rejects_nonlocal_endpoints(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOODA_AI_PROVIDER", "ollama")
    monkeypatch.setenv("BOODA_OLLAMA_BASE_URL", "https://example.test/v1")
    monkeypatch.setattr("builtins.input", lambda _prompt: "اكتبي خطة محلية")

    audit_log = BoodaAuditLog(tmp_path / "audit.jsonl")
    permissions = BoodaPermissionManager(audit_log=audit_log)
    permissions.add_permission("save_file", allowed=False)
    main_module.run_ai_agent(
        audit_log=audit_log,
        permission_manager=permissions,
        approval_manager=BoodaApprovalManager(audit_log=audit_log),
        task_manager=BoodaTaskManager(tmp_path / "tasks.json"),
        goal_manager=BoodaGoalManager(tmp_path / "goals.json"),
    )

    assert "only accepts a model server on this computer" in capsys.readouterr().out


def _run_local_cli(
    tmp_path, monkeypatch, answers, *, permission_allowed=True,
    permission_risk=RiskLevel.LOW, include_permission=True,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOODA_AI_PROVIDER", "local")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-read-or-shown")
    monkeypatch.setenv("BOODA_LLM_API_KEY", "must-not-be-read-or-shown")

    audit_log = BoodaAuditLog(tmp_path / "memory" / "audit.jsonl")
    permissions = BoodaPermissionManager(audit_log=audit_log)
    if include_permission:
        permissions.add_permission(
            "save_file",
            risk_level=permission_risk,
            allowed=permission_allowed,
        )
    approvals = BoodaApprovalManager(
        audit_log=audit_log, file_path=tmp_path / "memory" / "approvals.json"
    )
    tasks = BoodaTaskManager(tmp_path / "memory" / "tasks.json")
    goals = BoodaGoalManager(tmp_path / "memory" / "goals.json")
    capabilities = BoodaCapabilityRegistry(tmp_path / "security" / "capabilities.json")
    capabilities.register("save_task_content", permission_name="save_file")
    artifacts = BoodaArtifactManager(tmp_path / "memory" / "artifacts.json")
    sessions = BoodaAgentSessionStore(tmp_path / "memory" / "sessions.json")

    def transport(endpoint, payload):
        assert endpoint == f"{local_model.BASE_URL}/chat/completions"
        return _local_model_response()

    def planner_factory(**kwargs):
        assert kwargs["api_key"] is None
        assert kwargs["local_planning"] is True
        assert kwargs["min_plan_steps"] == 3
        assert kwargs["max_plan_steps"] == 7
        assert kwargs["capability_permissions"] == {
            "create_plan_artifact": ("save_file",)
        }
        return OpenAICompatiblePlanner(**kwargs, transport=transport)

    @contextmanager
    def fake_local_server():
        yield local_model.BASE_URL

    monkeypatch.setattr(main_module, "ensure_local_model_server", fake_local_server)
    monkeypatch.setattr(main_module, "OpenAICompatiblePlanner", planner_factory)
    monkeypatch.setattr(
        "core.llm_planner.urlopen",
        lambda *args, **kwargs: pytest.fail("Local CLI must not send HTTP requests."),
    )
    answer_iter = iter(answers)
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return next(answer_iter)

    monkeypatch.setattr("builtins.input", answer)

    managers = {
        "audit_log": audit_log,
        "permission_manager": permissions,
        "approval_manager": approvals,
        "task_manager": tasks,
        "goal_manager": goals,
        "artifact_manager": artifacts,
        "capability_registry": capabilities,
        "session_store": sessions,
        "prompts": prompts,
    }
    main_module.run_ai_agent(**{
        name: value for name, value in managers.items() if name != "prompts"
    })
    return managers


def test_local_cli_reviews_plan_then_saves_and_audits_local_artifact(
    tmp_path, monkeypatch, capsys
):
    managers = _run_local_cli(
        tmp_path,
        monkeypatch,
        [
            "عايزة أتعلم البرمجة وأعمل خطة دراسة",
            "نعم",  # Review the complete plan before execution.
            "نعم", "نعم", "نعم", "نعم",  # Approve each high-risk file write.
            "",
        ],
        permission_allowed=True,
        permission_risk=RiskLevel.HIGH,
    )

    tasks = list(managers["task_manager"].tasks.values())
    assert len(tasks) == 4
    assert all(task.status == "completed" for task in tasks)
    artifacts = managers["artifact_manager"].list(kind="plan")
    assert len(artifacts) == 1
    artifact_path = Path(artifacts[0]["path"])
    assert artifact_path.is_file()
    artifact_text = artifact_path.read_text(encoding="utf-8")
    assert "عايزة أتعلم البرمجة وأعمل خطة دراسة" in artifact_text
    assert "تحديد المستوى والمتطلبات" in artifact_text
    assert "تطبيق عملي وتمارين" in artifact_text
    assert "متابعة التقدم والتقييم" in artifact_text
    assert artifacts[0]["metadata"]["provider"] == "local"
    assert artifacts[0]["metadata"]["scope"] == "local-only"
    assert artifacts[0]["metadata"]["plan_id"]
    for task in tasks:
        events = managers["audit_log"].get_events(task_id=task.task_id)
        assert any(event.outcome == "completed" for event in events)
    output = capsys.readouterr().out
    assert "خطة Booda للمراجعة:" in output
    assert any("تنفذي الخطة؟" in prompt for prompt in managers["prompts"])
    assert "توقّف التنفيذ" not in output
    assert "must-not-be-read-or-shown" not in output


def test_local_cli_permission_refusal_prevents_plan_artifact(
    tmp_path, monkeypatch, capsys
):
    managers = _run_local_cli(
        tmp_path,
        monkeypatch,
        ["عايزة أتعلم البرمجة وأعمل خطة دراسة", "نعم", "لا", ""],
        permission_allowed=False,
    )

    assert managers["artifact_manager"].list(kind="plan") == []
    assert not (tmp_path / "outputs").exists()
    assert all(task.status == "pending" for task in managers["task_manager"].tasks.values())
    assert "توقّف التنفيذ بانتظار الصلاحية." in capsys.readouterr().out


def test_local_cli_missing_permission_prevents_plan_artifact(
    tmp_path, monkeypatch, capsys
):
    managers = _run_local_cli(
        tmp_path,
        monkeypatch,
        ["عايزة أتعلم البرمجة وأعمل خطة دراسة"],
        include_permission=False,
    )

    assert managers["artifact_manager"].list(kind="plan") == []
    assert not (tmp_path / "outputs").exists()
    assert "Model plan step requires a known permission" in capsys.readouterr().out


def _local_study_steps():
    return [
        {
            "task_id": "level",
            "title": "تحديد المستوى والمتطلبات",
            "description": "قيّمي مستواك الحالي وجهّزي أساسيات استخدام الحاسوب.",
            "capability": "create_plan_artifact",
            "depends_on": [],
            "permission_name": "save_file",
            "metadata": {},
        },
        {
            "task_id": "foundations",
            "title": "المرحلة الأولى: أساسيات البرمجة",
            "description": "تعلّمي المتغيرات والشروط والحلقات والدوال بالترتيب مع أمثلة بسيطة.",
            "capability": "create_plan_artifact",
            "depends_on": ["level"],
            "permission_name": "save_file",
            "metadata": {},
        },
        {
            "task_id": "practice",
            "title": "تطبيق عملي وتمارين",
            "description": "حلّي تمارين قصيرة ثم أنجزي مشروعًا بسيطًا.",
            "capability": "create_plan_artifact",
            "depends_on": ["foundations"],
            "permission_name": "save_file",
            "metadata": {},
        },
        {
            "task_id": "progress",
            "title": "متابعة التقدم والتقييم",
            "description": "سجّلي إنجازك أسبوعيًا واختبري ما تعلمتِه.",
            "capability": "create_plan_artifact",
            "depends_on": ["practice"],
            "permission_name": "save_file",
            "metadata": {},
        },
    ]


def _local_model_response(steps=None):
    return {
        "choices": [{
            "message": {
                "content": json.dumps(
                    {"plan_id": "local-study", "steps": steps or _local_study_steps()},
                    ensure_ascii=False,
                )
            }
        }]
    }


def test_local_planner_creates_arabic_educational_plan_without_network(monkeypatch):
    requests = []

    def transport(endpoint, payload):
        requests.append((endpoint, payload))
        return _local_model_response()

    planner = OpenAICompatiblePlanner(
        base_url=local_model.BASE_URL,
        model=local_model.MODEL_NAME,
        api_key=None,
        transport=transport,
        max_plan_steps=7,
        min_plan_steps=3,
        local_planning=True,
        capability_permissions={"create_plan_artifact": ("save_file",)},
    )
    registry = main_module.BoodaToolRegistry()
    registry.register("create_plan_artifact", lambda task: task.description)
    permissions = BoodaPermissionManager()
    permissions.add_permission("save_file", allowed=True)
    planner.configure_agent(registry=registry, permission_manager=permissions)
    monkeypatch.setattr(
        "core.llm_planner.urlopen",
        lambda *args, **kwargs: pytest.fail("Injected local transport must not use HTTP."),
    )

    goal = BoodaGoal("study-ar", "عايزة أتعلم البرمجة وأعمل خطة دراسة")
    plan = planner.create_plan(goal, None)

    assert len(requests) == 1
    assert requests[0][0] == f"{local_model.BASE_URL}/chat/completions"
    assert goal.intent in requests[0][1]["messages"][1]["content"]
    assert "لا تترجم هدفًا عربيًا" in requests[0][1]["messages"][0]["content"]
    assert "خطوة لمتابعة التقدم" in requests[0][1]["messages"][1]["content"]
    assert requests[0][1]["response_format"]["type"] == "json_schema"
    assert len(plan.steps) == 4
    assert all(any("\u0600" <= char <= "\u06ff" for char in step.title) for step in plan.steps)
    assert len({step.task_id for step in plan.steps}) == len(plan.steps)
    assert all(step.capability == "create_plan_artifact" for step in plan.steps)
    assert all(len(step.description.split()) >= 6 for step in plan.steps)
    plan_text = " ".join(
        f"{step.title} {step.description}" for step in plan.steps
    )
    assert "المتطلبات" in plan_text
    assert "المرحلة" in plan_text
    assert "تمارين" in plan_text
    assert "متابعة" in plan_text
    assert planner.api_key is None
    assert plan.goal_id == goal.goal_id


def test_local_planner_rejects_fewer_than_three_steps():
    calls = []

    def transport(endpoint, payload):
        calls.append(payload)
        return _local_model_response(_local_study_steps()[:2])

    planner = OpenAICompatiblePlanner(
        base_url=local_model.BASE_URL,
        model=local_model.MODEL_NAME,
        api_key=None,
        transport=transport,
        max_plan_steps=7,
        min_plan_steps=3,
        local_planning=True,
        capability_permissions={"create_plan_artifact": ("save_file",)},
    )
    registry = main_module.BoodaToolRegistry()
    registry.register("create_plan_artifact", lambda task: task.description)
    permissions = BoodaPermissionManager()
    permissions.add_permission("save_file", allowed=True)
    planner.configure_agent(registry=registry, permission_manager=permissions)

    with pytest.raises(ValueError, match="at least 3 steps"):
        planner.create_plan(
            BoodaGoal("study-ar", "عايزة أتعلم البرمجة وأعمل خطة دراسة"), None
        )
    assert len(calls) == 2
    assert "رُفضت المحاولة السابقة" in calls[1]["messages"][1]["content"]


def test_local_planner_corrects_invalid_response_with_same_model():
    calls = []
    responses = [
        _local_model_response(_local_study_steps()[:2]),
        _local_model_response(),
    ]

    def transport(endpoint, payload):
        calls.append(payload)
        return responses.pop(0)

    planner = OpenAICompatiblePlanner(
        base_url=local_model.BASE_URL,
        model=local_model.MODEL_NAME,
        api_key=None,
        transport=transport,
        max_plan_steps=7,
        min_plan_steps=3,
        local_planning=True,
        capability_permissions={"create_plan_artifact": ("save_file",)},
    )
    registry = main_module.BoodaToolRegistry()
    registry.register("create_plan_artifact", lambda task: task.description)
    permissions = BoodaPermissionManager()
    permissions.add_permission("save_file", allowed=True)
    planner.configure_agent(registry=registry, permission_manager=permissions)

    plan = planner.create_plan(
        BoodaGoal("study-ar", "عايزة أتعلم البرمجة وأعمل خطة دراسة"), None
    )

    assert len(calls) == 2
    assert len(plan.steps) == 4
    assert "رُفضت المحاولة السابقة" in calls[1]["messages"][1]["content"]


def test_local_planner_retries_repetitive_generic_ad_plan():
    calls = []
    repeated = [
        {
            "task_id": f"generic-{index}",
            "title": "الخطة التخطيطية",
            "description": (
                "الخطة التخطيطية تحدد الأهداف والخطوات الأساسية للاعتماد على "
                "الإجراءات والتأكد من أنها تتوافق مع المتطلبات."
            ),
            "capability": "create_plan_artifact",
            "depends_on": [],
            "permission_name": "save_file",
        }
        for index in range(4)
    ]
    specific = [
        (
            "مراجعة الجمهور والعرض",
            "حددي جمهور الإعلان والعرض والهدف ومعلومة المنتج الموجودة في brief قبل كتابة النسخ.",
        ),
        (
            "كتابة نسخ الإعلان",
            "اكتبي نسختين للإعلان برسالتين مختلفتين، واجعلي الدعوة للشراء واضحة للجمهور المحدد.",
        ),
        (
            "مراجعة جودة الإعلان",
            "راجعي وضوح الإعلان وصدق ادعاءاته وملاءمته للمنصة، ثم صححي أي عبارة غير مدعومة.",
        ),
        (
            "إعداد اختبار الأداء",
            "قارني النسختين باختبار صغير، وسجلي النقرات والتحويلات وتكلفة النتيجة لتحديد الأفضل.",
        ),
    ]
    useful_steps = [
        {
            "task_id": f"ad-{index}",
            "title": title,
            "description": description,
            "capability": "create_plan_artifact",
            "depends_on": [],
            "permission_name": "save_file",
        }
        for index, (title, description) in enumerate(specific)
    ]
    responses = [
        _local_model_response(repeated),
        _local_model_response(useful_steps),
    ]

    def transport(_endpoint, payload):
        calls.append(payload)
        return responses.pop(0)

    planner = OpenAICompatiblePlanner(
        base_url=local_model.BASE_URL,
        model=local_model.MODEL_NAME,
        api_key=None,
        transport=transport,
        max_plan_steps=7,
        min_plan_steps=3,
        local_planning=True,
        capability_permissions={"create_plan_artifact": ("save_file",)},
    )
    registry = main_module.BoodaToolRegistry()
    registry.register("create_plan_artifact", lambda task: task.description)
    permissions = BoodaPermissionManager()
    permissions.add_permission("save_file", allowed=True)
    planner.configure_agent(registry=registry, permission_manager=permissions)

    plan = planner.create_plan(
        BoodaGoal("ad-plan", "حسني إعلانًا واجعليه يحقق مبيعات أكثر"), None
    )

    assert len(calls) == 2
    assert "repeats the same idea" in calls[1]["messages"][1]["content"]
    assert "مراجعة الـbrief" in calls[0]["messages"][1]["content"]
    assert [step.title for step in plan.steps] == [title for title, _ in specific]


def test_local_planner_uses_marked_ad_fallback_after_quality_retry_fails():
    calls = []
    generic_steps = [
        {
            "task_id": f"generic-{index}",
            "title": "الخطة النهائية",
            "description": (
                "تأكدي من أن الإجراءات والخطوات تتوافق مع المتطلبات "
                "والأهداف المحددة بشكل واضح وعملي."
            ),
            "capability": "create_plan_artifact",
            "depends_on": [],
            "permission_name": "save_file",
        }
        for index in range(4)
    ]

    def transport(_endpoint, payload):
        calls.append(payload)
        if len(calls) > 1:
            raise TimeoutError("Local model correction took too long.")
        return _local_model_response(generic_steps)

    planner = OpenAICompatiblePlanner(
        base_url=local_model.BASE_URL,
        model=local_model.MODEL_NAME,
        api_key=None,
        transport=transport,
        max_plan_steps=7,
        min_plan_steps=3,
        local_planning=True,
        capability_permissions={"create_plan_artifact": ("save_file",)},
    )
    registry = main_module.BoodaToolRegistry()
    registry.register("create_plan_artifact", lambda task: task.description)
    permissions = BoodaPermissionManager()
    permissions.add_permission("save_file", allowed=True)
    planner.configure_agent(registry=registry, permission_manager=permissions)

    plan = planner.create_plan(
        BoodaGoal("ad-fallback", "حسني إعلانًا واختبري نتائجه"), None
    )

    assert len(calls) == 2
    assert plan.plan_id == "ad-fallback-local-ad-fallback-v1"
    assert len(plan.steps) == 4
    assert all(
        step.metadata["planner_origin"] == "deterministic_local_quality_fallback"
        for step in plan.steps
    )
    assert len({step.description for step in plan.steps}) == 4
    assert "brief" in plan.steps[0].description
    assert "التحويلات" in plan.steps[3].description


def test_local_ad_plan_falls_back_when_local_model_times_out():
    calls = []

    def transport(_endpoint, payload):
        calls.append(payload)
        raise TimeoutError("The local model took too long.")

    planner = OpenAICompatiblePlanner(
        base_url=local_model.BASE_URL,
        model=local_model.MODEL_NAME,
        api_key=None,
        transport=transport,
        local_planning=True,
        capability_permissions={"create_plan_artifact": ("save_file",)},
    )
    registry = main_module.BoodaToolRegistry()
    registry.register("create_plan_artifact", lambda task: task.description)
    permissions = BoodaPermissionManager()
    permissions.add_permission("save_file", allowed=True)
    planner.configure_agent(registry=registry, permission_manager=permissions)

    plan = planner.create_plan(
        BoodaGoal("ad-timeout", "حسني إعلانًا محليًا"), None
    )

    assert len(calls) == 1
    assert plan.plan_id == "ad-timeout-local-ad-fallback-v1"
    assert plan.steps[0].metadata["planner_origin"] == (
        "deterministic_local_quality_fallback"
    )


def test_local_educational_plan_rejects_missing_required_sections():
    steps = _local_study_steps()
    steps[-1]["title"] = "المهمة الختامية"
    steps[-1]["description"] = "أنجزي تحديًا أخيرًا حول أساسيات البرمجة."
    planner = OpenAICompatiblePlanner(
        base_url=local_model.BASE_URL,
        model=local_model.MODEL_NAME,
        api_key=None,
        transport=lambda _endpoint, _payload: _local_model_response(steps),
        max_plan_steps=7,
        min_plan_steps=3,
        local_planning=True,
        capability_permissions={"create_plan_artifact": ("save_file",)},
    )
    registry = main_module.BoodaToolRegistry()
    registry.register("create_plan_artifact", lambda task: task.description)
    permissions = BoodaPermissionManager()
    permissions.add_permission("save_file", allowed=True)
    planner.configure_agent(registry=registry, permission_manager=permissions)

    with pytest.raises(ValueError, match="progress tracking"):
        planner.create_plan(
            BoodaGoal("study-ar", "عايزة أتعلم البرمجة وأعمل خطة دراسة"), None
        )


def test_local_educational_plan_requires_a_real_level_or_prerequisites_step():
    steps = _local_study_steps()
    steps[0]["title"] = "مقدمة إلى أساسيات البرمجة"
    steps[0]["description"] = "تعرفي على أساسيات البرمجة من خلال أمثلة بسيطة."
    planner = OpenAICompatiblePlanner(
        base_url=local_model.BASE_URL,
        model=local_model.MODEL_NAME,
        api_key=None,
        transport=lambda _endpoint, _payload: _local_model_response(steps),
        max_plan_steps=7,
        min_plan_steps=3,
        local_planning=True,
        capability_permissions={"create_plan_artifact": ("save_file",)},
    )
    registry = main_module.BoodaToolRegistry()
    registry.register("create_plan_artifact", lambda task: task.description)
    permissions = BoodaPermissionManager()
    permissions.add_permission("save_file", allowed=True)
    planner.configure_agent(registry=registry, permission_manager=permissions)

    with pytest.raises(ValueError, match="level or prerequisites"):
        planner.create_plan(
            BoodaGoal("study-ar", "عايزة أتعلم البرمجة وأعمل خطة دراسة"), None
        )


def test_local_smoke_test_sends_arabic_and_displays_response(
    monkeypatch, capsys
):
    lifecycle = []
    received = {}

    @contextmanager
    def fake_local_server():
        lifecycle.append("start")
        yield local_model.BASE_URL
        lifecycle.append("stop")

    class FakePlanner:
        def __init__(self, **kwargs):
            received.update(kwargs)

        def configure_agent(self, *, registry, permission_manager):
            received["capability"] = registry.names()
            received["permissions"] = tuple(permission_manager.permissions)

        def create_plan(self, goal, memory):
            received["goal"] = goal.intent
            received["memory"] = memory
            return BoodaPlan(goal.goal_id, (
                PlanStep(
                    "study-level", "تحديد المستوى والمتطلبات",
                    "حددي مستواك الحالي ومتطلبات البداية.",
                    capability="create_plan_artifact", permission_name="save_file",
                ),
                PlanStep(
                    "study-practice", "تطبيق عملي",
                    "تدرّبي على المفاهيم بمشروع صغير.",
                    capability="create_plan_artifact", permission_name="save_file",
                ),
                PlanStep(
                    "study-progress", "متابعة التقدم",
                    "راجعي تقدمك واختبري ما تعلمتِه.",
                    capability="create_plan_artifact", permission_name="save_file",
                ),
            ))

    monkeypatch.setattr(local_model, "ensure_local_model_server", fake_local_server)
    monkeypatch.setattr("core.llm_planner.OpenAICompatiblePlanner", FakePlanner)

    plan = local_model.run_local_model_smoke_test()

    assert len(plan.steps) == 3
    assert plan.steps[0].title == "تحديد المستوى والمتطلبات"
    assert received["goal"] == "اكتبي خطة عربية لتحسين إعلان محلي وقياس نتائجه"
    assert received["memory"] is None
    assert received["capability"] == ("create_plan_artifact",)
    assert received["permissions"] == ("save_file",)
    assert received["api_key"] is None
    assert received["local_planning"] is True
    assert received["min_plan_steps"] == 3
    assert received["max_plan_steps"] == 7
    assert lifecycle == ["start", "stop"]
    assert "خطة النموذج المحلي:" in capsys.readouterr().out


def test_local_http_transport_bypasses_proxies_and_uses_only_loopback(
    monkeypatch,
):
    planner = OpenAICompatiblePlanner(
        base_url=local_model.BASE_URL,
        model=local_model.MODEL_NAME,
        api_key=None,
    )
    requested = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok": true}'

    class FakeOpener:
        def open(self, request, timeout):
            requested["url"] = request.full_url
            requested["timeout"] = timeout
            return FakeResponse()

    def local_opener(proxy_handler):
        assert proxy_handler.proxies == {}
        return FakeOpener()

    monkeypatch.setattr("core.llm_planner.build_opener", local_opener)
    monkeypatch.setattr(
        "core.llm_planner.urlopen",
        lambda *_args, **_kwargs: pytest.fail("Local model attempted external HTTP."),
    )

    assert planner._send_request(
        planner._endpoint(), {"messages": [{"content": "اختبار"}]}
    ) == {"ok": True}
    assert requested["url"] == f"{local_model.BASE_URL}/chat/completions"
    assert requested["url"].startswith("http://127.0.0.1:")
