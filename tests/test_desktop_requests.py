from types import SimpleNamespace
import pytest
from core.desktop_requests import request_plan, excerpt_summary
from core.desktop_lessons import DesktopLessons


def test_request_maps_to_reviewed_steps_without_execution():
    flow = request_plan("اكتب في المفكرة: اختبار بودا")
    assert [row["operation"] for row in flow.steps] == ["launch_app", "type", "verify_text"]
    assert flow.state == "ready" and not flow.history


@pytest.mark.parametrize("request_text", ["احذف كل الملفات", "شغّل powershell", "ابحث عن " + "س" * 200, "اكتب في المفكرة: " + "س" * 501])
def test_unsupported_or_large_request_refused(request_text):
    with pytest.raises(ValueError): request_plan(request_text)


def test_actual_previous_transcript_used_only_after_success_and_verification():
    flow = request_plan("افتح الفيديو ولخصه https://youtu.be/iG9CE55wbtY")
    for i, result in enumerate(({}, {"text": "نص حقيقي من المصدر."})):
        step = flow.next_step()
        task = SimpleNamespace(task_id=str(i), metadata=step, status="completed", result=result)
        flow.bind(task)
        flow.record(task)
        with pytest.raises(ValueError): flow.next_step()
        flow.verify(True)
    assert flow.next_step()["parameters"] == {"text": "نص حقيقي من المصدر."}


def test_failed_automatic_verification_cannot_be_confirmed_away():
    flow = request_plan("اكتب في المفكرة: اختبار بودا")
    for index in range(3):
        step = flow.next_step()
        task = SimpleNamespace(task_id=str(index), metadata=step, status="completed", result={"verified": False})
        flow.bind(task)
        flow.record(task)
        if index < 2:
            flow.verify(True)
    assert flow.state == "stopped"
    with pytest.raises(ValueError): flow.verify(True)


def test_summary_quotes_exist_in_actual_text():
    text = "\n".join(f"النقطة رقم {index}." for index in range(12))
    result = excerpt_summary(text)
    assert all(quote in text for quote in result["quotes"])
    assert not result["comprehensive_summary"]


def test_correction_is_reviewed_persistent_and_never_executable(tmp_path):
    path = tmp_path / "lessons.sqlite3"
    lessons = DesktopLessons(path)
    with pytest.raises(PermissionError): lessons.save("اكتب في المفكرة: اختبار", "أنشئ صفحة فارغة")
    lessons.save("اكتب في المفكرة: اختبار", "أنشئ صفحة فارغة", user_confirmed=True)
    recalled = DesktopLessons(path).recall("اكتب في المفكرة: اختبار")
    assert recalled[0]["correction"] == "أنشئ صفحة فارغة" and not recalled[0]["executable"]
    lessons.save("اكتب في المفكرة: اختبار", "تأكد من الصفحة الفارغة قبل الكتابة", user_confirmed=True)
    assert len(lessons.recall("اكتب في المفكرة: اختبار")) == 1
    assert "تأكد" in lessons.recall("اكتب في المفكرة: اختبار")[0]["correction"]


def test_unrelated_correction_not_recalled(tmp_path):
    lessons = DesktopLessons(tmp_path / "lessons.sqlite3")
    lessons.save("ابحث عن تاريخ القاهرة", "راجع المصدر", user_confirmed=True)
    assert not lessons.recall("اكتب في المفكرة: اختبار بودا")
