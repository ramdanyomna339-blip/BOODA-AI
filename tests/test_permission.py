from core.permission import BoodaPermission
from core.risk import RiskLevel


def test_permission_starts_denied():
    permission = BoodaPermission(
        name="send_message",
    )

    assert permission.allowed is False


def test_permission_can_be_granted():
    permission = BoodaPermission(
        name="send_message",
    )

    permission.grant()

    assert permission.allowed is True


def test_permission_can_be_revoked():
    permission = BoodaPermission(
        name="send_message",
        allowed=True,
    )

    permission.revoke()

    assert permission.allowed is False


def test_permission_keeps_risk_level():
    permission = BoodaPermission(
        name="spend_money",
        risk_level=RiskLevel.HIGH,
    )

    assert permission.risk_level == RiskLevel.HIGH