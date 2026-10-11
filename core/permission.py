from core.risk import RiskLevel


class BoodaPermission:
    def __init__(
        self,
        name,
        category="general",
        risk_level=RiskLevel.LOW,
        allowed=False,
    ):
        self.name = name
        self.category = category
        self.risk_level = risk_level
        self.allowed = allowed

    def grant(self):
        self.allowed = True

    def revoke(self):
        self.allowed = False