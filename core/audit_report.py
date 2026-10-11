def format_audit_events(events):
    if not events:
        return "مفيش عمليات مسجلة."

    outcome_names = {
        "completed": "نجحت",
        "failed": "فشلت",
        "rejected": "اترفضت",
        "uncertain": "غير مؤكدة",
    }
    action_names = {
        "permission_granted": "منح صلاحية",
        "permission_revoked": "سحب صلاحية",
        "approval_created": "إنشاء موافقة",
        "approval_granted": "اعتماد موافقة",
        "approval_revoked": "إلغاء موافقة",
    }

    reports = []

    for event in events:
        outcome = outcome_names.get(event.outcome, event.outcome)
        action = action_names.get(event.action, event.action)
        timestamp = event.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

        if event.task_title or event.task_id:
            task = f"{event.task_title or ''} ({event.task_id or ''})"
        else:
            task = "غير مرتبطة بمهمة"

        lines = [
            f"الوقت: {timestamp}",
            f"العملية: {action}",
            f"المهمة: {task}",
            f"الصلاحية: {event.permission_name or 'غير محددة'}",
            f"بواسطة: {event.requested_by or 'غير معروف'}",
            f"النتيجة: {outcome}",
        ]

        if event.approval_id:
            lines.append(f"رقم الموافقة: {event.approval_id}")

        if event.approved_by:
            lines.append(f"وافق عليها: {event.approved_by}")

        if event.approval_used is not None:
            used = "نعم" if event.approval_used else "لا"
            lines.append(f"استُخدمت الموافقة: {used}")

        if event.rejection_reason:
            lines.append(f"السبب: {event.rejection_reason}")

        reports.append("\n".join(lines))

    return "\n\n".join(reports)