"""Bounded continuation of reviewed work, with evidence-based completion status."""


def execution_report(agent):
    plan = agent.state.plan
    rows = []
    for step in plan.steps if plan else ():
        task = agent.task_manager.get_task(step.task_id)
        rows.append({"task_id": step.task_id, "title": step.title,
                     "capability": step.capability,
                     "status": task.status if task else "missing",
                     "verification": agent._verification_status(step.task_id)})
    complete = bool(rows) and all(row["status"] == "completed" for row in rows)
    verified = complete and all(row["verification"] == "passed" for row in rows)
    return {"goal_id": agent.state.goal.goal_id if agent.state.goal else None,
            "phase": agent.state.phase, "tasks": rows,
            "tools_completed": complete, "results_verified": verified,
            "external_objective_verified": False,
            "next_step": (
                "review_plan" if plan and not agent.state.plan_reviewed else
                agent.state.phase if agent.state.phase.startswith("waiting_") else
                "inspect_failure_or_uncertainty" if agent.state.phase == "needs_attention" else
                "review_unverified_results" if complete and not verified else
                "review_goal_outcome" if complete else "continue_reviewed_work")}


def continue_reviewed_work(agent, *, max_steps=12):
    if type(max_steps) is not int or not 1 <= max_steps <= 100:
        raise ValueError("Continuation budget must be between 1 and 100 steps.")
    if agent.state.plan is None or not agent.state.plan_reviewed:
        raise RuntimeError("A reviewed plan is required; continuation cannot approve it.")
    if agent.state.interrupted_task_id is not None:
        raise RuntimeError("An interrupted action requires an explicit retry decision.")
    agent.run_until_blocked(max_steps=max_steps)
    return execution_report(agent)


def describe_execution(report):
    lines = ["حالة التنفيذ: " + report["phase"]]
    for row in report["tasks"]:
        lines.append(row["title"] + ": " + row["status"] + "؛ التحقق: " + row["verification"])
    lines.append("كل نتائج الخطوات اجتازت التحقق المسجل." if report["results_verified"]
                 else "لا يوجد دليل تحقق ناجح لكل النتائج؛ لا أعتبر الهدف مؤكد الاكتمال.")
    lines.append("الخطوة التالية: " + report["next_step"])
    return "\n".join(lines)
