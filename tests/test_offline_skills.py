from core.approval_manager import BoodaApprovalManager
from core.artifact_manager import BoodaArtifactManager
from core.audit_log import BoodaAuditLog
from core.capability_registry import BoodaCapabilityRegistry
from core.goal_manager import BoodaGoalManager
from core.main import run_ai_agent
from core.offline_skills import (
    BoodaOfflineAdPlanner,
    BoodaOfflineMarketingPlanner,
)
from core.planning import BoodaGoal
from core.permission_manager import BoodaPermissionManager
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry
from core.agent_session import BoodaAgentSessionStore


def test_offline_ad_skill_supports_ad_copy_but_not_strategy_goals():
    assert BoodaOfflineAdPlanner.supports_goal("اكتبي إعلان ميكب واحفظيه كمسودة")
    assert not BoodaOfflineAdPlanner.supports_goal("اعملي خطة لحملة إعلانية")
    assert not BoodaOfflineAdPlanner.supports_goal("اكتبي وصف منتج")


def test_offline_ad_skill_creates_labeled_arabic_draft_with_placeholders():
    permission_manager = BoodaPermissionManager()
    permission_manager.add_permission("save_file", allowed=False)
    registry = BoodaToolRegistry()
    registry.register("save_task_content", lambda task: task.description)
    planner = BoodaOfflineAdPlanner(permission_name="save_file")
    planner.configure_agent(registry=registry, permission_manager=permission_manager)

    plan = planner.create_plan(
        BoodaGoal("goal-1", "إعلان جذاب لبيع مستحضرات ميكب"), memory=None
    )

    step = plan.steps[0]
    assert step.capability == "save_task_content"
    assert step.permission_name == "save_file"
    assert step.metadata["provider"] == "offline_ad_skill"
    assert "ليست ناتج نموذج AI" in step.description
    assert "مستحضرات الميكب" in step.description
    assert "أضيفي السعر" in step.description


def test_offline_ad_skill_refuses_unconfigured_or_mismatched_permission(tmp_path):
    planner = BoodaOfflineAdPlanner(permission_name="save_file")
    goal = BoodaGoal("goal-1", "إعلان ميكب")
    try:
        planner.create_plan(goal, memory=None)
    except RuntimeError as error:
        assert "Configure" in str(error)
    else:
        raise AssertionError("Unconfigured offline skill must not plan.")

    permission_manager = BoodaPermissionManager()
    permission_manager.add_permission("save_file", allowed=False)
    registry = BoodaToolRegistry()
    registry.register("save_task_content", lambda task: task.description)
    from core.capability_registry import BoodaCapabilityRegistry

    capabilities = BoodaCapabilityRegistry(tmp_path / "capabilities.json")
    capabilities.register("save_task_content", permission_name="other_permission")
    restricted_registry = BoodaToolRegistry(capabilities)
    restricted_registry.register("save_task_content", lambda task: task.description)
    try:
        planner.configure_agent(registry=restricted_registry, permission_manager=permission_manager)
    except ValueError as error:
        assert "does not match" in str(error)
    else:
        raise AssertionError("Mismatched capability permission must be rejected.")


def test_local_ad_goal_uses_offline_skill_and_existing_permission_flow(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOODA_AI_PROVIDER", "local")
    audit = BoodaAuditLog(tmp_path / "audit.jsonl")
    permissions = BoodaPermissionManager(audit_log=audit)
    permissions.add_permission("save_file", allowed=False)
    approvals = BoodaApprovalManager(audit_log=audit)
    tasks = BoodaTaskManager(tmp_path / "tasks.json")
    capabilities = BoodaCapabilityRegistry(tmp_path / "capabilities.json")
    capabilities.register("save_task_content", permission_name="save_file")
    answers = iter((
        "اكتبي إعلانًا جذابًا لمستحضرات ميكب واحفظيه كمسودة",
        "نعم",  # Review the draft plan.
        "نعم",  # Grant the existing save_file permission.
        "",  # Leave the optional conversation prompt.
    ))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(
        "core.main.ensure_local_model_server",
        lambda: (_ for _ in ()).throw(AssertionError("Model should not start.")),
    )

    run_ai_agent(
        audit_log=audit,
        permission_manager=permissions,
        approval_manager=approvals,
        task_manager=tasks,
        goal_manager=BoodaGoalManager(tmp_path / "goals.json"),
        capability_registry=capabilities,
        session_store=BoodaAgentSessionStore(tmp_path / "sessions.json"),
    )

    saved_files = list((tmp_path / "outputs").glob("announcement-*.txt"))
    assert len(saved_files) == 1
    saved_copy = saved_files[0].read_text(encoding="utf-8")
    assert "مستحضرات الميكب" in saved_copy
    assert "أضيفي السعر" in saved_copy
    assert "بدون نموذج" in capsys.readouterr().out
    assert tasks.list_tasks()[0].status == "completed"


def test_offline_campaign_plan_is_specific_and_labels_its_limits(tmp_path):
    permissions = BoodaPermissionManager()
    permissions.add_permission("save_file", allowed=False)
    capabilities = BoodaCapabilityRegistry(tmp_path / "capabilities.json")
    capabilities.register("create_plan_artifact", permission_name="save_file")
    registry = BoodaToolRegistry(capabilities)
    registry.register("create_plan_artifact", lambda task: task.description)
    planner = BoodaOfflineMarketingPlanner(permission_name="save_file")
    planner.configure_agent(registry=registry, permission_manager=permissions)

    assert planner.supports_goal("اعملي خطة حملة تسويقية لمحل ميكب")
    assert not planner.supports_goal("عايزة أتعلم التسويق")
    plan = planner.create_plan(
        BoodaGoal("campaign-1", "اعملي خطة حملة تسويقية لمحل ميكب"),
        memory=None,
    )

    assert len(plan.steps) == 4
    assert all(step.capability == "create_plan_artifact" for step in plan.steps)
    assert all(step.permission_name == "save_file" for step in plan.steps)
    assert "بيانات سوق" in plan.steps[0].description
    assert "لا تفترضي أرقامًا" in plan.steps[-1].description


def test_local_campaign_goal_saves_reviewed_plan_without_starting_model(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOODA_AI_PROVIDER", "local")
    audit = BoodaAuditLog(tmp_path / "audit.jsonl")
    permissions = BoodaPermissionManager(audit_log=audit)
    permissions.add_permission("save_file", allowed=False)
    approvals = BoodaApprovalManager(audit_log=audit)
    tasks = BoodaTaskManager(tmp_path / "tasks.json")
    capabilities = BoodaCapabilityRegistry(tmp_path / "capabilities.json")
    capabilities.register("save_task_content", permission_name="save_file")
    capabilities.register("create_plan_artifact", permission_name="save_file")
    artifacts = BoodaArtifactManager(tmp_path / "artifacts.json")
    answers = iter((
        "اعملي خطة حملة تسويقية لمحل ميكب",
        "نعم",  # Review the campaign plan.
        "نعم",  # Grant the existing save_file permission.
        "",  # Leave the optional conversation prompt.
    ))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(
        "core.main.ensure_local_model_server",
        lambda: (_ for _ in ()).throw(AssertionError("Model should not start.")),
    )

    run_ai_agent(
        audit_log=audit,
        permission_manager=permissions,
        approval_manager=approvals,
        task_manager=tasks,
        goal_manager=BoodaGoalManager(tmp_path / "goals.json"),
        artifact_manager=artifacts,
        capability_registry=capabilities,
        session_store=BoodaAgentSessionStore(tmp_path / "sessions.json"),
    )

    plans = artifacts.list(kind="plan")
    assert len(plans) == 1
    content = open(plans[0]["path"], encoding="utf-8").read()
    assert "تحديد هدف الحملة والجمهور" in content
    assert "تشغيل اختبار وقياس النتيجة" in content
    assert all(task.status == "completed" for task in tasks.list_tasks())
    assert "بدون نموذج" in capsys.readouterr().out


def test_voice_mode_confirms_transcript_and_speaks_local_ad_result(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOODA_AI_PROVIDER", "local")
    audit = BoodaAuditLog(tmp_path / "audit.jsonl")
    permissions = BoodaPermissionManager(audit_log=audit)
    permissions.add_permission("save_file", allowed=False)
    approvals = BoodaApprovalManager(audit_log=audit)
    tasks = BoodaTaskManager(tmp_path / "tasks.json")
    capabilities = BoodaCapabilityRegistry(tmp_path / "capabilities.json")
    capabilities.register("save_task_content", permission_name="save_file")
    spoken = []
    answers = iter(("نعم", "نعم", "نعم", "x"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(
        "core.voice.transcribe_microphone",
        lambda **_kwargs: {"text": "اكتبي إعلان ميكب واحفظيه كمسودة"},
    )
    monkeypatch.setattr(
        "core.voice.speak_arabic", lambda text, **kwargs: spoken.append(text) or True
    )

    run_ai_agent(
        audit_log=audit,
        permission_manager=permissions,
        approval_manager=approvals,
        task_manager=tasks,
        goal_manager=BoodaGoalManager(tmp_path / "goals.json"),
        capability_registry=capabilities,
        session_store=BoodaAgentSessionStore(tmp_path / "sessions.json"),
        voice_mode=True,
    )

    assert len(list((tmp_path / "outputs").glob("announcement-*.txt"))) == 1
    assert any("خطة" in line and "للمراجعة" in line and "مسودة إعلان" in line for line in spoken)
    assert any("الخطوات المسجلة" in line for line in spoken)
    assert "النص اللي سمعته Booda" in capsys.readouterr().out
