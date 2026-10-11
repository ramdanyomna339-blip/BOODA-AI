"""Local experience and user-approved evolution workflow.

This manager stores proposals and learning records only. It never executes code,
registers capabilities, installs integrations, or performs network access.
"""

from copy import deepcopy
import math
import re
from dataclasses import asdict
from uuid import uuid4

from core.evolution import (
    CapabilityGap,
    ChangeLogRecord,
    EvaluationRecord,
    ExperienceRecord,
    ImprovementProposal,
    KnowledgeRecord,
    utc_now,
)
from core.executor import BoodaExecutor
from core.persistence import JsonObjectStore
from core.permission_policy import BoodaPermissionPolicy
from core.task import BoodaTask


EVOLUTION_PERMISSION = "evolution_change"


def _experience_terms(text):
    terms = set()
    for token in re.findall(r"\w+", text.casefold()):
        normalized = token.translate(str.maketrans({
            "أ": "ا",
            "إ": "ا",
            "آ": "ا",
        }))
        for _ in range(2):
            prefix = next((
                candidate
                for candidate in ("وال", "بال", "كال", "فال", "لل", "ال", "و", "ف", "ب", "ل", "ك")
                if normalized.startswith(candidate)
                and len(normalized) > len(candidate) + 1
            ), None)
            if prefix is None:
                break
            normalized = normalized[len(prefix):]
        if len(normalized) >= 2:
            terms.add(normalized)
    return terms


class BoodaEvolutionManager:
    def __init__(
        self,
        file_path="memory/evolution.json",
        *,
        audit_log,
        event_log=None,
        version_store=None,
        executor=None,
        permission_policy=None,
    ):
        if audit_log is None:
            raise ValueError("Evolution requires an audit log.")
        self.store = JsonObjectStore(file_path)
        self.audit_log = audit_log
        self.event_log = event_log
        self.version_store = version_store
        self.executor = executor or BoodaExecutor()
        self.permission_policy = permission_policy or BoodaPermissionPolicy()
        self.data = self.store.load()
        for key in (
            "experiences", "evaluations", "capability_gaps", "proposals",
            "knowledge", "change_log", "versions", "snapshots",
        ):
            self.data.setdefault(key, {})

    @staticmethod
    def _require_text(value, field_name):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must not be empty.")
        return value.strip()

    def _save(self):
        self.store.save(self.data)

    def _record(self, action, entity_type, entity_id, *, title, details=None,
                requested_by="user", outcome="completed", reason=None):
        self.audit_log.record(
            action=action,
            task_id=entity_id,
            task_title=title,
            requested_by=requested_by,
            outcome=outcome,
            rejection_reason=reason,
        )
        if self.event_log is not None:
            self.event_log.record(
                action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details,
            )

    def _reject_operation(self, action, entity_type, entity_id, *, title,
                          reason, requested_by="user"):
        self._record(
            action,
            entity_type,
            entity_id,
            title=title,
            details={"reason": reason},
            requested_by=requested_by,
            outcome="rejected",
            reason=reason,
        )
        raise ValueError(reason)

    def _record_change(self, component, entity_id, reason, approval_status,
                       *, changed_by="user"):
        old_version = self.data["versions"].get(component, 0)
        new_version = old_version + 1
        self.data["versions"][component] = new_version
        component_history = self.data["snapshots"].setdefault(
            f"{component}:{entity_id}", []
        )
        snapshot = deepcopy(self.data[component].get(entity_id, {"deleted": True}))
        component_history.append({
            "version": new_version,
            "snapshot": snapshot,
            "reason": reason,
            "approval_status": approval_status,
            "recorded_at": utc_now(),
        })
        change = asdict(ChangeLogRecord(
            component=component,
            old_version=old_version,
            new_version=new_version,
            reason=reason,
            approval_status=approval_status,
            change_id=f"change-{uuid4().hex}",
        ))
        self.data["change_log"][change["change_id"]] = change
        if self.version_store is not None:
            self.version_store.record(
                component,
                entity_id,
                self.data[component].get(entity_id, {"deleted": True}),
                changed_by=changed_by,
                reason=reason,
            )
        return change

    @staticmethod
    def _valid_metric(name, value):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a number or None.")
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite non-negative number.")
        if name in {"quality", "reliability", "privacy"} and value > 1:
            raise ValueError(f"{name} must be between 0 and 1.")
        return float(value)

    def record_task_result(self, task, *, goal, inputs_summary=None,
                           result_summary=None, metrics=None,
                           recorded_by="agent"):
        if task.status not in {"completed", "failed", "blocked"}:
            raise ValueError("Only completed, failed, or blocked tasks are experience.")
        existing = next(
            (item for item in self.data["experiences"].values()
             if item["task_id"] == task.task_id),
            None,
        )
        if existing is not None:
            return deepcopy(existing)
        outcome = "success" if task.status == "completed" else "failure"
        experience_id = f"experience-{uuid4().hex}"
        result_text = task.result or "No result details recorded."
        arabic_goal = any("\u0600" <= char <= "\u06ff" for char in goal)
        if arabic_goal:
            lesson = (
                f"ملاحظة موثقة: {'نجحت' if outcome == 'success' else 'فشلت'} "
                f"المهمة «{task.title}». النتيجة: {result_text}"
            )
        else:
            lesson = (
                f"Observed {outcome} for task '{task.title}'. Result: {result_text}"
            )
        record = asdict(ExperienceRecord(
            experience_id=experience_id,
            task_id=task.task_id,
            goal=self._require_text(goal, "goal"),
            inputs_summary=inputs_summary if inputs_summary is not None else task.description,
            result_summary=(
                result_summary if result_summary is not None
                else str(task.result or "")
            ),
            outcome=outcome,
            metrics=dict(metrics or {}),
            lessons=(lesson,),
        ))
        record["lessons"] = list(record["lessons"])
        self.data["experiences"][experience_id] = record
        evaluation = self._new_evaluation(
            experience_id,
            quality=None,
            reliability=None,
            speed=None,
            cost=None,
            privacy=None,
            notes=f"Task outcome: {outcome}; scores not supplied.",
        )
        self.data["evaluations"][evaluation["evaluation_id"]] = evaluation
        self._record_change(
            "experiences", experience_id, "Task result recorded", "not_required",
            changed_by=recorded_by,
        )
        self._save()
        self._record(
            "experience_recorded", "experience", experience_id,
            title=f"{task.task_id}: {task.title}",
            details={"task_id": task.task_id, "outcome": outcome},
            requested_by=recorded_by,
        )
        self._record(
            "evaluation_recorded", "evaluation", evaluation["evaluation_id"],
            title=f"Evaluation for {task.task_id}",
            details={"experience_id": experience_id, "scores": "not supplied"},
            requested_by=recorded_by,
        )
        self.add_knowledge(
            lesson,
            source=f"task://{task.task_id}",
            metadata={
                "kind": "experience_lesson",
                "experience_id": experience_id,
                "outcome": outcome,
            },
            changed_by=recorded_by,
        )
        if outcome == "failure":
            self.create_proposal(
                title=f"Review failed task: {task.title}",
                problem=(
                    f"Task '{task.title}' failed. Observed result: {result_text}"
                ),
                proposed_solution=(
                    "Review the failure evidence and validate a local corrective "
                    "workflow in the sandbox before proposing adoption."
                ),
                expected_benefit="Reduce recurrence of the observed task failure.",
                risks="The proposed cause or remediation may be incorrect.",
                cost="User review and local sandbox effort; no paid service.",
                changed_by=recorded_by,
            )
        return deepcopy(record)

    def _new_evaluation(self, experience_id, *, quality, reliability, speed,
                        cost, privacy, notes):
        if experience_id not in self.data["experiences"]:
            raise ValueError(f"Unknown experience: {experience_id}")
        values = {
            name: self._valid_metric(name, value)
            for name, value in {
                "quality": quality,
                "reliability": reliability,
                "speed": speed,
                "cost": cost,
                "privacy": privacy,
            }.items()
        }
        return asdict(EvaluationRecord(
            experience_id=experience_id,
            notes=notes,
            evaluation_id=f"evaluation-{uuid4().hex}",
            **values,
        ))

    def add_evaluation(self, experience_id, *, quality=None, reliability=None,
                       speed=None, cost=None, privacy=None, notes="",
                       changed_by="user"):
        evaluation = self._new_evaluation(
            experience_id,
            quality=quality,
            reliability=reliability,
            speed=speed,
            cost=cost,
            privacy=privacy,
            notes=notes,
        )
        self.data["evaluations"][evaluation["evaluation_id"]] = evaluation
        self._record_change(
            "evaluations", evaluation["evaluation_id"],
            "Evaluation added", "not_required", changed_by=changed_by,
        )
        self._save()
        self._record(
            "evaluation_recorded", "evaluation", evaluation["evaluation_id"],
            title=f"Evaluation for {experience_id}",
            details={"experience_id": experience_id},
            requested_by=changed_by,
        )
        return deepcopy(evaluation)

    def add_lesson(self, experience_id, lesson, *, changed_by="user"):
        lesson = self._require_text(lesson, "lesson")
        experience = self.data["experiences"].get(experience_id)
        if experience is None:
            raise ValueError(f"Unknown experience: {experience_id}")
        if lesson in experience["lessons"]:
            return deepcopy(experience)
        experience["lessons"].append(lesson)
        self._record_change(
            "experiences", experience_id, "Lesson added", "not_required",
            changed_by=changed_by,
        )
        self._save()
        self._record(
            "lesson_recorded", "experience", experience_id,
            title="Experience lesson added",
            details={"lesson": lesson},
            requested_by=changed_by,
        )
        return deepcopy(experience)

    def create_capability_gap(self, name, description, *, detected_from,
                              required_tools=(), changed_by="user"):
        name = self._require_text(name, "name")
        description = self._require_text(description, "description")
        detected_from = self._require_text(detected_from, "detected_from")
        tools = tuple(self._require_text(item, "required_tool") for item in required_tools)
        gap_id = f"gap-{uuid4().hex}"
        gap = asdict(CapabilityGap(
            gap_id=gap_id,
            name=name,
            description=description,
            detected_from=detected_from,
            required_tools=tools,
        ))
        self.data["capability_gaps"][gap_id] = gap
        self._record_change(
            "capability_gaps", gap_id, "Capability gap detected",
            "not_required", changed_by=changed_by,
        )
        self._save()
        self._record(
            "capability_gap_detected", "capability_gap", gap_id,
            title=name,
            details={"detected_from": detected_from, "required_tools": tools},
            requested_by=changed_by,
        )
        return deepcopy(gap)

    def create_proposal(self, *, title, problem, proposed_solution,
                        expected_benefit, risks, cost, changed_by="user"):
        values = {
            name: self._require_text(value, name)
            for name, value in {
                "title": title,
                "problem": problem,
                "proposed_solution": proposed_solution,
                "expected_benefit": expected_benefit,
                "risks": risks,
                "cost": cost,
            }.items()
        }
        proposal_id = f"proposal-{uuid4().hex}"
        proposal = asdict(ImprovementProposal(
            proposal_id=proposal_id, **values
        ))
        self.data["proposals"][proposal_id] = proposal
        self._record_change(
            "proposals", proposal_id, "Improvement proposed",
            "not_required", changed_by=changed_by,
        )
        self._save()
        self._record(
            "improvement_proposed", "improvement_proposal", proposal_id,
            title=title,
            details={"status": "proposed"},
            requested_by=changed_by,
        )
        return deepcopy(proposal)

    def sandbox_proposal(self, proposal_id, *, report, changed_by="user"):
        proposal = self._get_proposal(proposal_id)
        if proposal["status"] != "proposed":
            self._reject_operation(
                "improvement_sandbox_rejected",
                "improvement_proposal",
                proposal_id,
                title=proposal["title"],
                reason="Only a proposed improvement can enter sandbox.",
                requested_by=changed_by,
            )
        proposal["status"] = "sandbox"
        proposal["sandbox_report"] = self._require_text(report, "report")
        self._record_change(
            "proposals", proposal_id, "Local sandbox validation recorded",
            "not_required", changed_by=changed_by,
        )
        self._save()
        self._record(
            "improvement_sandboxed", "improvement_proposal", proposal_id,
            title=proposal["title"],
            details={"report": report, "code_executed": False},
            requested_by=changed_by,
        )
        return deepcopy(proposal)

    def _request_transition_approval(
        self, proposal_id, *, target, approval_manager, approved_by,
        created_by, reason,
    ):
        proposal = self._get_proposal(proposal_id)
        expected = "sandbox" if target == "adopted" else "adopted"
        if proposal["status"] != expected:
            self._reject_operation(
                "improvement_approval_request_rejected",
                "improvement_proposal",
                proposal_id,
                title=proposal["title"],
                reason=(
                    f"Proposal must be {expected} before requesting "
                    f"{target} approval."
                ),
                requested_by=created_by,
            )
        if approval_manager is None:
            self._reject_operation(
                "improvement_approval_request_rejected",
                "improvement_proposal",
                proposal_id,
                title=proposal["title"],
                reason="Evolution changes require the approval manager.",
                requested_by=created_by,
            )
        task_id = f"evolution-{target}-{uuid4().hex}"
        approval_id, approval = approval_manager.create_approval(
            permission_name=EVOLUTION_PERMISSION,
            approved_by=self._require_text(approved_by, "approved_by"),
            created_by=self._require_text(created_by, "created_by"),
            reason=self._require_text(reason, "reason"),
            task_id=task_id,
        )
        proposal["pending_transition"] = target
        proposal["pending_transition_task_id"] = task_id
        if target == "adopted":
            proposal["status"] = "approval"
        self._record_change(
            "proposals", proposal_id,
            f"Approval requested for {target}", "pending",
            changed_by=created_by,
        )
        self._save()
        self._record(
            "improvement_approval_requested", "improvement_proposal", proposal_id,
            title=proposal["title"],
            details={"target": target, "approval_id": approval_id, "task_id": task_id},
            requested_by=created_by,
        )
        return approval_id, approval

    def request_adoption_approval(self, proposal_id, *, approval_manager,
                                  approved_by, created_by, reason):
        return self._request_transition_approval(
            proposal_id,
            target="adopted",
            approval_manager=approval_manager,
            approved_by=approved_by,
            created_by=created_by,
            reason=reason,
        )

    def request_rollback_approval(self, proposal_id, *, approval_manager,
                                  approved_by, created_by, reason):
        return self._request_transition_approval(
            proposal_id,
            target="sandbox",
            approval_manager=approval_manager,
            approved_by=approved_by,
            created_by=created_by,
            reason=reason,
        )

    def reject_proposal(self, proposal_id, *, reason, rejected_by="user"):
        proposal = self._get_proposal(proposal_id)
        if proposal["status"] not in {"proposed", "sandbox", "approval"}:
            self._reject_operation(
                "improvement_rejection_denied",
                "improvement_proposal",
                proposal_id,
                title=proposal["title"],
                reason="Only a pending proposal can be rejected.",
                requested_by=rejected_by,
            )
        reason = self._require_text(reason, "reason")
        proposal["status"] = "rejected"
        proposal["rejection_reason"] = reason
        self._record_change(
            "proposals", proposal_id, reason, "rejected", changed_by=rejected_by
        )
        self._save()
        self._record(
            "improvement_rejected", "improvement_proposal", proposal_id,
            title=proposal["title"],
            details={"reason": reason},
            requested_by=rejected_by,
        )
        return deepcopy(proposal)

    def _get_proposal(self, proposal_id):
        proposal = self.data["proposals"].get(proposal_id)
        if proposal is None:
            raise ValueError(f"Unknown proposal: {proposal_id}")
        return proposal

    def _guarded_transition(self, proposal_id, *, target, reason,
                            permission_manager, approval, requested_by):
        proposal = self._get_proposal(proposal_id)
        expected = "approval" if target == "adopted" else "adopted"
        if proposal["status"] != expected:
            self._reject_operation(
                f"improvement_{target}_rejected",
                "improvement_proposal",
                proposal_id,
                title=proposal["title"],
                reason=f"Proposal must be {expected} before it can become {target}.",
                requested_by=requested_by,
            )
        if permission_manager is None or approval is None:
            self._reject_operation(
                f"improvement_{target}_rejected",
                "improvement_proposal",
                proposal_id,
                title=proposal["title"],
                reason="Evolution changes require permission and approval.",
                requested_by=requested_by,
            )
        if proposal.get("pending_transition") != target:
            self._reject_operation(
                f"improvement_{target}_rejected",
                "improvement_proposal",
                proposal_id,
                title=proposal["title"],
                reason="No matching transition approval was requested.",
                requested_by=requested_by,
            )
        task_id = proposal.get("pending_transition_task_id")
        if not task_id:
            self._reject_operation(
                f"improvement_{target}_rejected",
                "improvement_proposal",
                proposal_id,
                title=proposal["title"],
                reason="The transition has no task-bound approval identity.",
                requested_by=requested_by,
            )
        if approval.task_id != task_id:
            self._reject_operation(
                f"improvement_{target}_rejected",
                "improvement_proposal",
                proposal_id,
                title=proposal["title"],
                reason="Approval does not match the requested evolution transition.",
                requested_by=requested_by,
            )
        if not approval.is_approved or approval.used or approval.is_expired():
            self._reject_operation(
                f"improvement_{target}_rejected",
                "improvement_proposal",
                proposal_id,
                title=proposal["title"],
                reason="Evolution transition requires a current, unused approval.",
                requested_by=requested_by,
            )
        task = BoodaTask(
            task_id=task_id,
            title=f"{target.capitalize()} proposal: {proposal['title']}",
            description=reason,
        )

        def transition():
            current_proposal = self._get_proposal(proposal_id)
            old_status = current_proposal["status"]
            if target == "sandbox":
                history = self.data["snapshots"].get(
                    f"proposals:{proposal_id}", ()
                )
                approved_snapshots = [
                    item["snapshot"] for item in history
                    if item["snapshot"].get("status") == "sandbox"
                ]
                if not approved_snapshots:
                    raise ValueError("No prior sandbox version is available to restore.")
                self.data["proposals"][proposal_id] = deepcopy(
                    approved_snapshots[-1]
                )
                current_proposal = self.data["proposals"][proposal_id]
            else:
                current_proposal["status"] = target
                current_proposal["approval_status"] = "approved"
                current_proposal["changed_at"] = utc_now()
            current_proposal.pop("pending_transition", None)
            current_proposal.pop("pending_transition_task_id", None)
            self._record_change(
                "proposals", proposal_id,
                f"{old_status} -> {target}: {reason}",
                "approved", changed_by=requested_by,
            )
            self._save()
            self._record(
                f"improvement_{target}", "improvement_proposal", proposal_id,
                title=current_proposal["title"],
                details={"reason": reason, "approval_id": approval.approval_id},
                requested_by=requested_by,
            )
            return target

        self.executor.execute(
            task=task,
            action=transition,
            permission_manager=permission_manager,
            permission_name=EVOLUTION_PERMISSION,
            permission_policy=self.permission_policy,
            approval=approval,
            audit_log=self.audit_log,
            requested_by=requested_by,
        )
        return task

    def adopt_proposal(self, proposal_id, *, permission_manager, approval,
                       requested_by, reason="User approved adoption"):
        return self._guarded_transition(
            proposal_id,
            target="adopted",
            reason=self._require_text(reason, "reason"),
            permission_manager=permission_manager,
            approval=approval,
            requested_by=requested_by,
        )

    def rollback_proposal(self, proposal_id, *, permission_manager, approval,
                          requested_by, reason):
        return self._guarded_transition(
            proposal_id,
            target="sandbox",
            reason=self._require_text(reason, "reason"),
            permission_manager=permission_manager,
            approval=approval,
            requested_by=requested_by,
        )

    def add_knowledge(self, content, *, source, metadata=None,
                      changed_by="user"):
        content = self._require_text(content, "content")
        source = self._require_text(source, "source")
        knowledge_id = f"knowledge-{uuid4().hex}"
        record = asdict(KnowledgeRecord(
            knowledge_id=knowledge_id,
            content=content,
            source=source,
            metadata=dict(metadata or {}),
        ))
        self.data["knowledge"][knowledge_id] = record
        self._record_change(
            "knowledge", knowledge_id, "Knowledge added",
            "not_required", changed_by=changed_by,
        )
        self._save()
        self._record(
            "knowledge_added", "knowledge", knowledge_id,
            title=source,
            details={"source": source, "created_at": record["created_at"]},
            requested_by=changed_by,
        )
        return deepcopy(record)

    def update_knowledge(self, knowledge_id, *, content=None, source=None,
                         metadata=None, changed_by="user"):
        record = self.data["knowledge"].get(knowledge_id)
        if record is None:
            raise ValueError(f"Unknown knowledge record: {knowledge_id}")
        if content is not None:
            record["content"] = self._require_text(content, "content")
        if source is not None:
            record["source"] = self._require_text(source, "source")
        if metadata is not None:
            record["metadata"] = dict(metadata)
        record["updated_at"] = utc_now()
        self._record_change(
            "knowledge", knowledge_id, "Knowledge updated",
            "not_required", changed_by=changed_by,
        )
        self._save()
        self._record(
            "knowledge_updated", "knowledge", knowledge_id,
            title=record["source"],
            details={"source": record["source"], "updated_at": record["updated_at"]},
            requested_by=changed_by,
        )
        return deepcopy(record)

    def delete_knowledge(self, knowledge_id, *, changed_by="user"):
        record = self.data["knowledge"].pop(knowledge_id, None)
        if record is None:
            return False
        self._record_change(
            "knowledge", knowledge_id, "Knowledge deleted",
            "not_required", changed_by=changed_by,
        )
        self._save()
        self._record(
            "knowledge_deleted", "knowledge", knowledge_id,
            title=record["source"],
            details={"source": record["source"]},
            requested_by=changed_by,
        )
        return True

    def list_experience_lessons(self, *, include_inactive=True):
        lessons = [
            deepcopy(record)
            for record in self.data["knowledge"].values()
            if record.get("metadata", {}).get("kind") == "experience_lesson"
            and (
                include_inactive
                or record.get("metadata", {}).get("active", True)
            )
        ]
        self._record(
            "experience_lessons_listed",
            "knowledge",
            "experience_lessons",
            title="List experience lessons",
            details={"include_inactive": include_inactive, "count": len(lessons)},
            requested_by="user",
        )
        return lessons

    def add_starter_marketing_lessons(self, *, changed_by="user"):
        starter_lessons = (
            (
                "audience_problem",
                "قبل اختيار قناة التسويق، حددي جمهورًا واضحًا ومشكلة محددة "
                "لديه، ثم تحققي من احتياجه بدل افتراضه.",
                ("التسويق", "الجمهور", "المشكلة"),
            ),
            (
                "clear_offer",
                "اجعلي العرض يوضح الفائدة والسعر والشروط والخطوة التالية، "
                "وتجنبي الوعود التي لا يمكن إثباتها.",
                ("التسويق", "العرض", "السعر"),
            ),
            (
                "small_tests",
                "اختبري فكرة تسويقية واحدة على نطاق صغير وبميزانية محدودة، "
                "وغيّري متغيرًا واحدًا في كل تجربة لتسهيل المقارنة.",
                ("التسويق", "الإعلان", "التجربة"),
            ),
            (
                "measure_results",
                "حددي مقياس نجاح مرتبطًا بالهدف مثل الاستفسارات المؤهلة أو "
                "المبيعات، ولا تعتمدي على المشاهدات وحدها.",
                ("التسويق", "الإعلانات", "النتائج"),
            ),
            (
                "learn_cautiously",
                "قارني النتائج بالفترة أو المجموعة المناسبة، واعتبريها مؤشرًا "
                "لا إثباتًا للسببية، ثم حسّني الرسالة بناءً على ما تدعمه البيانات.",
                ("التسويق", "الحملة", "النتائج"),
            ),
        )
        existing_ids = {
            record.get("metadata", {}).get("starter_id")
            for record in self.data["knowledge"].values()
        }
        added = []
        for starter_id, content, keywords in starter_lessons:
            if starter_id in existing_ids:
                continue
            added.append(self.add_knowledge(
                content,
                source=f"booda://starter/marketing/{starter_id}",
                metadata={
                    "kind": "experience_lesson",
                    "origin": "curated_starter",
                    "starter_id": starter_id,
                    "active": True,
                    "keywords": list(keywords),
                },
                changed_by=changed_by,
            ))
        return added

    def recall_experience_lessons(self, query, *, limit=5):
        query = self._require_text(query, "query")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError("limit must be a non-negative integer.")
        query_terms = _experience_terms(query)
        ranked = []
        for record in self.data["knowledge"].values():
            metadata = record.get("metadata", {})
            if (
                metadata.get("kind") != "experience_lesson"
                or not metadata.get("active", True)
            ):
                continue
            lesson_terms = _experience_terms(record["content"])
            for keyword in metadata.get("keywords", []):
                lesson_terms.update(_experience_terms(keyword))
            overlap = len(query_terms & lesson_terms)
            if overlap:
                ranked.append((
                    overlap,
                    record.get("created_at", ""),
                    record,
                ))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        lessons = [
            {
                "knowledge_id": record["knowledge_id"],
                "content": record["content"],
                "source": record["source"],
                "outcome": record.get("metadata", {}).get("outcome"),
                "origin": record.get("metadata", {}).get(
                    "origin", "recorded_experience"
                ),
                "created_at": record["created_at"],
                "relevance": overlap,
            }
            for overlap, _, record in ranked[:limit]
        ]
        self._record(
            "experience_lessons_recalled",
            "knowledge",
            "planning_context",
            title="Recall experience lessons for planning",
            details={"count": len(lessons), "limit": limit},
            requested_by="agent",
        )
        return lessons

    def set_experience_lesson_active(
        self, knowledge_id, *, active, changed_by="user"
    ):
        if not isinstance(active, bool):
            raise ValueError("active must be a boolean.")
        record = self.data["knowledge"].get(knowledge_id)
        if record is None or record.get("metadata", {}).get("kind") != "experience_lesson":
            raise ValueError(f"Unknown experience lesson: {knowledge_id}")
        metadata = dict(record.get("metadata", {}))
        if metadata.get("active", True) == active:
            return deepcopy(record)
        metadata["active"] = active
        return self.update_knowledge(
            knowledge_id,
            metadata=metadata,
            changed_by=changed_by,
        )

    def delete_experience_lesson(self, knowledge_id, *, changed_by="user"):
        record = self.data["knowledge"].get(knowledge_id)
        if record is None or record.get("metadata", {}).get("kind") != "experience_lesson":
            raise ValueError(f"Unknown experience lesson: {knowledge_id}")
        return self.delete_knowledge(knowledge_id, changed_by=changed_by)

    def list_records(self, collection):
        if collection not in self.data:
            raise ValueError(f"Unknown evolution collection: {collection}")
        self._record(
            "evolution_records_listed", "evolution", collection,
            title=f"List Evolution records: {collection}",
            details={"collection": collection},
            requested_by="system",
        )
        if collection == "versions":
            return deepcopy(self.data[collection])
        if collection == "snapshots":
            return deepcopy(self.data[collection])
        return deepcopy(list(self.data[collection].values()))

    def get_experience(self, experience_id):
        item = self.data["experiences"].get(experience_id)
        self._record(
            "experience_read", "experience", experience_id,
            title="Read experience record",
            requested_by="system",
            outcome="completed" if item is not None else "rejected",
            reason=None if item is not None else "Experience record not found.",
        )
        return deepcopy(item) if item is not None else None

    def get_proposal(self, proposal_id):
        item = self.data["proposals"].get(proposal_id)
        self._record(
            "improvement_proposal_read", "improvement_proposal", proposal_id,
            title="Read improvement proposal",
            requested_by="system",
            outcome="completed" if item is not None else "rejected",
            reason=None if item is not None else "Improvement proposal not found.",
        )
        return deepcopy(item) if item is not None else None
