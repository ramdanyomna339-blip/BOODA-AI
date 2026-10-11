from threading import Lock


class BoodaState:
    def __init__(self):
        self.is_online = True
        self.is_autonomous = False
        self.is_busy = False
        self.current_task = None
        self._task_lock = Lock()

    def set_task(self, task):
        with self._task_lock:
            if self.is_busy:
                return False
            self.current_task = task
            self.is_busy = True
            return True

    def clear_task(self):
        with self._task_lock:
            self.current_task = None
            self.is_busy = False
