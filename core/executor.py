from core.risk import RiskLevel


class BoodaExecutor:
    def execute(
        self,
        task,
        action,
        permission_manager=None,
        permission_name=None,
        permission_policy=None,
        approval=None,
        audit_log=None,
        requested_by=None,
    ):
        action_name = getattr(
            action,
            "__name__",
            action.__class__.__name__,
        )
        approval_required = False

        def record_event(outcome, rejection_reason=None, event_action=None):
            if audit_log is not None:
                audit_log.record(
                    action=event_action or action_name,
                    task=task,
                    requested_by=requested_by,
                    permission_name=permission_name,
                    approval_required=approval_required,
                    approval=approval,
                    outcome=outcome,
                    rejection_reason=rejection_reason,
                )

        def reject(reason):
            task_error = None
            audit_error = None
            try:
                task.fail(reason)
            except Exception as error:
                task_error = error
            try:
                record_event("rejected", reason)
            except Exception as error:
                audit_error = error

            if task_error is not None:
                if audit_error is not None:
                    raise task_error from audit_error
                raise task_error
            if audit_error is not None:
                raise audit_error
            return None

        def validate_authorization():
            nonlocal approval_required

            if permission_manager is None:
                return "Permission manager is required."

            if (
                not isinstance(permission_name, str)
                or not permission_name.strip()
                or permission_name != permission_name.strip()
            ):
                return "A valid permission name is required."

            get_permission = getattr(permission_manager, "get_permission", None)
            if not callable(get_permission):
                return "Permission manager cannot validate permissions."

            permission = get_permission(permission_name)
            if permission is None:
                return "Permission not found."

            if getattr(permission, "name", None) != permission_name:
                return "Permission does not match the requested permission."

            if getattr(permission, "allowed", None) is not True:
                return "Permission denied."

            risk_level = getattr(permission, "risk_level", None)
            known_risk_levels = {
                RiskLevel.LOW,
                RiskLevel.MEDIUM,
                RiskLevel.HIGH,
                RiskLevel.CRITICAL,
            }
            if risk_level not in known_risk_levels:
                return "Permission has an unknown risk level."
            core_approval_required = risk_level in (
                RiskLevel.HIGH,
                RiskLevel.CRITICAL,
            )

            if permission_policy is None:
                return "Permission policy is required."

            requires_approval = getattr(
                permission_policy, "requires_approval", None
            )
            if not callable(requires_approval):
                return "Permission policy cannot validate approval requirements."

            approval_decision = requires_approval(permission)
            if not isinstance(approval_decision, bool):
                return "Permission policy returned an invalid approval decision."
            approval_required = core_approval_required or approval_decision
            if not approval_required and approval is None:
                return None

            if approval is None:
                return "Approval required."

            if getattr(approval, "is_approved", None) is not True:
                return "Approval not granted."

            if getattr(approval, "permission_name", None) != permission_name:
                return "Approval does not match permission."

            requires_task_bound_approval = getattr(
                permission_policy, "requires_task_bound_approval", None
            )
            if not callable(requires_task_bound_approval):
                return "Permission policy cannot validate task-bound approval."

            task_bound_decision = requires_task_bound_approval(permission)
            if not isinstance(task_bound_decision, bool):
                return "Permission policy returned an invalid task-bound approval decision."

            approval_task_id = getattr(approval, "task_id", None)
            if (core_approval_required or task_bound_decision) and approval_task_id is None:
                return "Task-bound approval required."

            if approval_task_id != task.task_id:
                return "Approval does not match task."

            is_expired = getattr(approval, "is_expired", None)
            if not callable(is_expired):
                return "Approval expiry cannot be verified."

            expired_decision = is_expired()
            if not isinstance(expired_decision, bool):
                return "Approval expiry could not be verified."
            if expired_decision:
                return "Approval expired."

            approval_used = getattr(approval, "used", None)
            if approval_used is not False:
                return (
                    "Approval already used."
                    if approval_used is True
                    else "Approval usage cannot be verified."
                )

            if not callable(getattr(approval, "claim_use", None)):
                return "Approval usage cannot be recorded."

            return None

        try:
            authorization_error = validate_authorization()
        except Exception as validation_error:
            try:
                reject("Permission or approval validation failed.")
            except Exception as rejection_error:
                raise validation_error from rejection_error
            raise

        if authorization_error is not None:
            return reject(authorization_error)

        if approval is not None:
            try:
                claim_error = approval.claim_use(
                    permission_name=permission_name,
                    task_id=task.task_id,
                )
            except Exception as reservation_error:
                try:
                    reject("Approval reservation failed.")
                except Exception as rejection_error:
                    raise reservation_error from rejection_error
                raise
            if claim_error is not None:
                return reject(claim_error)
            try:
                record_event(
                    "reserved",
                    event_action="approval_reserved",
                )
            except Exception as audit_error:
                state_error = None
                try:
                    approval.finish_execution(
                        "failed",
                        detail=(
                            "Reservation audit failed; the action was not invoked."
                        ),
                    )
                except Exception as error:
                    state_error = error
                try:
                    task.fail(
                        "Approval reservation could not be audited; "
                        "the action was not invoked."
                    )
                except Exception as error:
                    state_error = state_error or error
                if state_error is not None:
                    raise audit_error from state_error
                raise

        try:
            task.start()
        except Exception as start_error:
            secondary_error = None
            if approval is not None:
                try:
                    approval.finish_execution(
                        "failed",
                        detail="Task could not be started; the action was not invoked.",
                    )
                except Exception as state_error:
                    secondary_error = state_error
            try:
                task.fail("Task could not be started; the action was not invoked.")
            except Exception as task_error:
                secondary_error = secondary_error or task_error
            try:
                record_event(
                    "failed",
                    "Task could not be started; the action was not invoked.",
                )
            except Exception as audit_error:
                secondary_error = secondary_error or audit_error
            if secondary_error is not None:
                raise start_error from secondary_error
            raise

        if approval is not None:
            try:
                approval.start_execution()
            except Exception as start_error:
                cleanup_error = None
                try:
                    approval.finish_execution(
                        "failed",
                        detail="Execution could not be started; the action was not invoked.",
                    )
                except Exception as state_error:
                    cleanup_error = state_error
                try:
                    task.fail("Execution could not be started.")
                except Exception as task_error:
                    cleanup_error = cleanup_error or task_error
                try:
                    record_event(
                        "rejected",
                        "Execution could not be started; the action was not invoked.",
                    )
                except Exception as audit_error:
                    cleanup_error = cleanup_error or audit_error
                if cleanup_error is not None:
                    raise start_error from cleanup_error
                raise start_error

        try:
            record_event(
                "started",
                event_action="execution_started",
            )
        except Exception as audit_error:
            state_error = None
            if approval is not None:
                try:
                    approval.finish_execution(
                        "failed",
                        detail=(
                            "Execution-start audit failed; the action was not invoked."
                        ),
                    )
                except Exception as error:
                    state_error = error
            try:
                task.fail(
                    "Execution could not be audited; the action was not invoked."
                )
            except Exception as error:
                state_error = state_error or error
            if state_error is not None:
                raise audit_error from state_error
            raise

        try:
            result = action()
        except Exception as action_error:
            secondary_error = None
            if approval is not None:
                try:
                    approval.finish_execution(
                        "uncertain",
                        detail=(
                            "Action raised after execution began; an external "
                            "effect may have occurred."
                        ),
                    )
                except Exception as state_error:
                    secondary_error = state_error
            try:
                task.mark_uncertain(
                    "Execution outcome is uncertain; an external effect may have occurred."
                )
            except Exception as task_error:
                secondary_error = secondary_error or task_error
            try:
                record_event(
                    "uncertain",
                    "Action raised after execution began; an external effect may have occurred.",
                )
            except Exception as audit_error:
                secondary_error = secondary_error or audit_error
            if secondary_error is not None:
                raise action_error from secondary_error
            return None

        if approval is not None:
            try:
                approval.finish_execution(
                    "completed",
                    detail="Action returned successfully.",
                )
            except Exception as state_error:
                persistence_error = RuntimeError(
                    "Action returned successfully, but its final approval state "
                    "could not be persisted. Inspect the execution before retrying."
                )
                task_error = None
                audit_error = None
                try:
                    task.complete(result)
                except Exception as error:
                    task_error = error
                try:
                    record_event(
                        "completed",
                        "Action returned successfully, but approval state persistence failed.",
                        event_action="execution_result_persistence_failed",
                    )
                except Exception as error:
                    audit_error = error
                secondary_error = task_error or audit_error or state_error
                raise persistence_error from secondary_error

        task_error = None
        audit_error = None
        try:
            task.complete(result)
        except Exception as error:
            task_error = error
        try:
            record_event("completed")
        except Exception as error:
            audit_error = error

        if task_error is not None:
            if audit_error is not None:
                raise task_error from audit_error
            raise task_error
        if audit_error is not None:
            raise audit_error
        return result