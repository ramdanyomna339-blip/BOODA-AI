"""Reviewed desktop steps with a human result check between every action."""
import copy


class BoodaDesktopWorkflow:
    def __init__(self, steps):
        if not isinstance(steps, list) or not 1 <= len(steps) <= 10:
            raise ValueError("Choose one to ten desktop steps.")
        self.steps = copy.deepcopy(steps)
        for step in self.steps:
            if (not isinstance(step, dict) or set(step) != {"operation", "parameters", "expected"}
                    or not isinstance(step["parameters"], dict)
                    or not isinstance(step["expected"], str) or not step["expected"].strip()):
                raise ValueError("Each step needs an operation, parameters, and expected result.")
        self.index = 0
        self.state = "ready"
        self.task_id = None
        self.history = []
        self.last_result = None

    def next_step(self):
        if self.state != "ready":
            raise ValueError("Verify the previous result or stop before continuing.")
        step = copy.deepcopy(self.steps[self.index])
        if step["operation"] == "excerpt_summary" and step["parameters"] == {"from_previous_result": True}:
            if not isinstance(self.last_result, dict) or not isinstance(self.last_result.get("text"), str):
                raise ValueError("لا يوجد نص ناجح من الخطوة السابقة لتلخيصه.")
            step["parameters"] = {"text": self.last_result["text"]}
        return step

    def bind(self, task):
        step = self.next_step()
        if (task.metadata.get("operation") != step["operation"]
                or task.metadata.get("parameters") != step["parameters"]):
            raise ValueError("Prepared request differs from the reviewed step.")
        self.task_id = task.task_id
        self.state = "awaiting_execution"

    def record(self, task):
        if self.state != "awaiting_execution" or task.task_id != self.task_id:
            raise ValueError("Unexpected workflow request.")
        self.history.append({"task_id": task.task_id, "execution_status": task.status,
                             "verified_by_user": False})
        self.last_result = copy.deepcopy(getattr(task, "result", None)) if task.status == "completed" else None
        self.state = "awaiting_verification" if task.status == "completed" else "stopped"
        if task.metadata.get("operation") == "verify_text" and (
                not isinstance(self.last_result, dict) or self.last_result.get("verified") is not True):
            self.state = "stopped"

    def verify(self, confirmed):
        if self.state != "awaiting_verification" or type(confirmed) is not bool:
            raise ValueError("A completed step needs an explicit result check.")
        if not confirmed:
            self.state = "stopped"
            return
        self.history[-1]["verified_by_user"] = True
        self.index += 1
        self.state = "completed" if self.index == len(self.steps) else "ready"

    def stop(self):
        self.state = "stopped"


def notepad_check():
    return BoodaDesktopWorkflow([
        {"operation": "launch_app", "parameters": {"application": "notepad"},
         "expected": "نافذة مفكرة جديدة فارغة ظاهرة؛ لا تختَر مستندًا قديمًا في الخطوة التالية."},
        {"operation": "type", "parameters": {"text": "اختبار بودا: كل خطوة بموافقتي."},
         "expected": "ظهور النص: اختبار بودا: كل خطوة بموافقتي. دون حفظ أو إرسال."},
    ])
