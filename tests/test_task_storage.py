from core.task_manager import BoodaTaskManager


def test_task_status_and_result_survive_reopening(tmp_path):
    file_path = tmp_path / "memory" / "tasks.json"

    first_manager = BoodaTaskManager(file_path=file_path)
    task = first_manager.add_task(
        task_id="task-001",
        title="Send a message",
        description="Send the prepared message.",
    )

    task.start()
    task.complete("Message sent.")

    second_manager = BoodaTaskManager(file_path=file_path)
    restored_task = second_manager.get_task("task-001")

    assert restored_task is not None
    assert restored_task.title == "Send a message"
    assert restored_task.description == "Send the prepared message."
    assert restored_task.status == "completed"
    assert restored_task.result == "Message sent."

    restored_task.fail("A later retry failed.")

    third_manager = BoodaTaskManager(file_path=file_path)
    restored_task = third_manager.get_task("task-001")

    assert restored_task.status == "failed"
    assert restored_task.result == "A later retry failed."


def test_removed_task_stays_removed_after_reopening(tmp_path):
    file_path = tmp_path / "memory" / "tasks.json"

    first_manager = BoodaTaskManager(file_path=file_path)
    first_manager.add_task("task-002", "Temporary task")

    removed_task = first_manager.remove_task("task-002")

    second_manager = BoodaTaskManager(file_path=file_path)

    assert removed_task is not None
    assert second_manager.get_task("task-002") is None