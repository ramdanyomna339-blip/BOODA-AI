class BoodaTask:
    def __init__(
        self,
        task_id,
        title,
        description="",
        status="pending",
        result=None,
        on_change=None,
        depends_on=None,
        metadata=None,
        project_id=None,
        due_at=None,
        goal_id=None,
    ):
        self.task_id = task_id
        self.title = title
        self.description = description
        self.status = status
        self.result = result
        self.depends_on = tuple(depends_on or ())
        self.metadata = dict(metadata or {})
        self.project_id = project_id
        self.goal_id = goal_id
        if due_at is not None:
            from core.scheduler import parse_due_at

            parse_due_at(due_at)
        self.due_at = due_at
        self._on_change = on_change

    def _notify_change(self):
        if self._on_change is not None:
            self._on_change()

    def start(self):
        self.status = "running"
        self._notify_change()

    def complete(self, result=None):
        self.status = "completed"
        self.result = result
        self._notify_change()

    def fail(self, result=None):
        self.status = "failed"
        self.result = result
        self._notify_change()

    def mark_uncertain(self, result=None):
        self.status = "uncertain"
        self.result = result
        self._notify_change()
