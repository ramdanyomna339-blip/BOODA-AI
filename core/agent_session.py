"""Durable snapshots of an agent's active goal and plan."""

from core.persistence import JsonObjectStore


class BoodaAgentSessionStore:
    def __init__(self, file_path="memory/agent_sessions.json"):
        self.store = JsonObjectStore(file_path)

    def load(self, session_id="default"):
        value = self.store.load().get(session_id)
        return dict(value) if value is not None else None

    def list_sessions(self):
        return [
            {"session_id": session_id, **dict(session)}
            for session_id, session in self.store.load().items()
        ]

    def save(self, session_id, state):
        sessions = self.store.load()
        goal = state.goal
        plan = state.plan
        sessions[session_id] = {
            "goal": None if goal is None else {
                "goal_id": goal.goal_id,
                "intent": goal.intent,
                "context": goal.context,
            },
            "plan": None if plan is None else {
                "goal_id": plan.goal_id,
                "plan_id": plan.plan_id,
                "steps": [{
                    "task_id": step.task_id,
                    "title": step.title,
                    "description": step.description,
                    "capability": step.capability,
                    "depends_on": list(step.depends_on),
                    "permission_name": step.permission_name,
                    "metadata": step.metadata,
                    "due_at": step.due_at,
                } for step in plan.steps],
            },
            "phase": state.phase,
            "plan_reviewed": state.plan_reviewed,
            "last_decision": state.last_decision,
            "replan_count": state.replan_count,
            "history": state.history[-200:],
            "conversation": getattr(state, "conversation", [])[-12:],
            "active_task_id": getattr(state.current_task, "task_id", None),
        }
        self.store.save(sessions)
