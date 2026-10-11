"""Bounded conversation evidence and checks independent of model fluency."""

import re
from decimal import Decimal

from core.reasoning_checks import percentage_evidence


def arithmetic_errors(answer):
    errors = []
    for calculation in percentage_evidence(answer):
        end = calculation["end"]
        stated = re.match(r"\s*(?:=|يساوي|تساوي)\s*([\d]+(?:\.[\d]+)?)", answer[end:])
        if stated and Decimal(stated[1]) != Decimal(calculation["result"]):
            errors.append(calculation)
    return errors


def checked_answer(answer):
    errors = arithmetic_errors(answer)
    if not errors:
        return answer
    facts = "؛ ".join(f"{item['expression']} = {item['result']}" for item in errors)
    return "رد النموذج احتوى حسابًا خاطئًا، فلم أعتمده. الحساب الصحيح: " + facts + ". باقي الاستنتاج محتاج مراجعة."


def checked_execution_claim(answer, tasks):
    claims = (
        (r"(?:تم حفظ|حفظت)", {"save_task_content", "create_plan_artifact", "laptop_write_file"}),
        (r"(?:تم (?:إرسال|ارسال|نشر)|أرسلت|ارسلت|نشرت)", {"send_message", "publish"}),
        (r"(?:تم حذف|حذفت)", {"delete_file"}),
        (r"(?:تم (?:الدفع|الشراء)|دفعت|اشتريت)", {"spend_money"}),
    )
    for pattern, capabilities in claims:
        if re.match(r"\s*(?:لقد\s+)?" + pattern, answer) and not any(
            task.get("capability") in capabilities and task.get("status") == "completed"
            and task.get("verification") == "passed" for task in tasks
        ):
            return "رد النموذج ادّعى إجراءً لا يوجد له دليل تنفيذ متحقق في هذه الجلسة، فلم أعتمده. راجع حالة المهام؛ لم أنفذ إجراءً إضافيًا من الرد."
    return answer


def safe_turn(message, answer):
    # Conversation history is private reference data, never new authority.
    from core.memory import BoodaStructuredMemoryStore
    try:
        BoodaStructuredMemoryStore._validate_safe_value({"message": message, "answer": answer})
    except ValueError:
        return None
    return {"message": message[:2000], "answer": answer[:3000]}


def literal_fields(message, sources):
    """Answer explicit field-only requests by quotation, never by inference."""
    request = re.search(r"اذكر\s+(.+?)\s+فقط", message)
    if request is None or request[1] == "ه":
        request = re.search(r"(?:ما|إيه|ايه)\s+(.+?)\s+الذي وجدته", message)
    if not request:
        return None
    fields = [value.strip() for value in re.split(r"\s+و\s*|[،,]", request[1])]
    if not 1 <= len(fields) <= 5 or any(not 2 <= len(field) <= 60 for field in fields):
        return None
    subject = re.search(r"(?:العميل|عميل)\s+([\w-]+)", message)
    eligible = [source for source in sources if not subject or subject[1] in source.get("text", "")]
    answers, citations = [], set()
    historical = False
    for field in fields:
        values = set()
        for source in eligible:
            for clause in re.split(r"[،,\n;؛]|(?<=[.!?؟])\s+", source.get("text", "")):
                match = re.fullmatch(re.escape(field) + r"(?:\s*[:：]\s*|\s+)(.{1,200})", clause.strip())
                if match:
                    values.add(match[1].strip().rstrip(".؟!"))
                    citations.add(source.get("title", "مرجع محلي"))
                    historical |= source.get("reference_status") == "unverified_historical"
        if len(values) > 1:
            return "وجدت قيمًا متعارضة للحقل «" + field + "»؛ محتاج تحديد المرجع أو العميل قبل الحسم."
        if not values:
            return None
        answers.append(field + ": " + next(iter(values)))
    note = " (تاريخي غير مؤكد)" if historical else ""
    return "\n".join(answers) + "\nالمصدر: " + "، ".join(sorted(citations)) + note
