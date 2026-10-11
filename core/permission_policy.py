from core.risk import RiskLevel


class BoodaPermissionPolicy:
    def requires_approval(self, permission):
        return permission.risk_level in (
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        )

    def requires_task_bound_approval(self, permission):
        return permission.risk_level in (
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        )