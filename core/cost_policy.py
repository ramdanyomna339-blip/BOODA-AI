"""Persist the user's explicit preference against paid AI services."""
import json
from pathlib import Path

COST_POLICY_PATH = Path(__file__).resolve().parents[1] / "config/ai_cost_policy.json"


def assert_paid_allowed():
    if COST_POLICY_PATH.exists():
        policy = json.loads(COST_POLICY_PATH.read_text(encoding="utf-8"))
        if policy.get("allow_paid_ai") is not True:
            raise PermissionError("الاستخدام المدفوع مقفول حسب طلبك؛ لم يُرسل طلب ولم تُفعّل خدمة مدفوعة.")
