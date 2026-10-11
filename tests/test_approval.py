from core.approval import BoodaApproval


def test_approval_starts_unapproved():
    approval = BoodaApproval(
        permission_name="spend_money",
        approved_by="Yomna",
    )

    assert approval.is_approved is False


def test_approval_can_be_approved():
    approval = BoodaApproval(
        permission_name="spend_money",
        approved_by="Yomna",
    )

    approval.approve()

    assert approval.is_approved is True


def test_approval_can_be_revoked():
    approval = BoodaApproval(
        permission_name="spend_money",
        approved_by="Yomna",
    )

    approval.approve()
    approval.revoke()

    assert approval.is_approved is False


def test_approval_can_be_marked_used():
    approval = BoodaApproval(
        permission_name="spend_money",
        approved_by="Yomna",
    )

    approval.mark_used()

    assert approval.used is True


def test_approval_expiration():
    approval = BoodaApproval(
        permission_name="spend_money",
        approved_by="Yomna",
        expires_in_minutes=-1,
    )

    assert approval.is_expired() is True


def test_approval_starts_unused():
    approval = BoodaApproval(
        permission_name="spend_money",
        approved_by="Yomna",
    )

    assert approval.used is False