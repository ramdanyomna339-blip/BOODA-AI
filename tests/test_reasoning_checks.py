import pytest

from core.local_plan_schema import plan_schema
from core.reasoning_checks import percentage_evidence, review_output, checked_percentage_conflict, describe_review
from core.reasoning_checks import extract_review_observations


def test_labeled_review_input_adapter_preserves_user_data_and_rejects_ambiguity():
    result = extract_review_observations("المقاس المطلوب 720×500. المقاس الملاحظ 800×500. "
        "النصوص المطلوبة عنوان ورمز-123. النص الملاحظ عنوان فقط.")
    assert result == {"required_dimensions": [720, 500], "observed_dimensions": [800, 500],
                      "required_text": ["عنوان", "رمز-123"], "observed_text": "عنوان"}
    assert extract_review_observations("راجع الصورة") is None
    assert extract_review_observations("المقاس المطلوب 720×500. المقاس المطلوب 100×100.") is None


def test_percentages_use_decimal_arithmetic_and_preserve_source():
    results = percentage_evidence("الأولى 25% من 7000 والثانية 12.5% of 80")
    assert [item["result"] for item in results] == ["1750", "10"]
    assert results[0]["expression"] == "25% من 7000"
    assert percentage_evidence("2250 هو المبلغ المتفق عليه") == []
    assert percentage_evidence("125% من 80") == []
    assert percentage_evidence("-25% من 80") == []


def test_output_review_checks_every_requirement_and_does_not_claim_image_inspection():
    result = review_output({"required_dimensions": [1080, 1080], "observed_dimensions": [1920, 1080],
                            "required_text": ["مرجان", "مرجع-742"], "observed_text": "مرجان"})
    assert result["ready"] is False
    assert result["missing_text"] == ["مرجع-742"]
    assert result["dimensions_match"] is False
    assert result["modified_output"] is False
    assert result["scope"] == "supplied_observations_only_not_visual_inspection"
    good = review_output({"required_dimensions": [500, 300], "observed_dimensions": [500, 300],
                          "required_text": ["logo"], "observed_text": "logo here"})
    assert good["ready"] is True


@pytest.mark.parametrize("value", [{}, {"required_dimensions": [True, 10]}, {"command": "execute"}])
def test_review_rejects_incomplete_or_invalid_observations(value):
    with pytest.raises(ValueError):
        review_output(value)


def test_local_schema_binds_capability_permission_and_required_parameters():
    schema = plan_schema({"search_local_knowledge": ("knowledge_read",), "review_output": ("output_review",)})
    variants = schema["properties"]["steps"]["items"]["anyOf"]
    search = variants[0]["properties"]
    assert search["capability"]["const"] == "search_local_knowledge"
    assert search["permission_name"]["enum"] == ["knowledge_read"]
    metadata = search["metadata"]
    assert metadata["required"] == ["parameters"]
    assert metadata["properties"]["parameters"]["required"] == ["query"]
    assert search["depends_on"]["maxItems"] == 0


def test_percentage_conflict_guard_generalizes_and_does_not_decide_fee():
    answer = checked_percentage_conflict("هل تحسم الأتعاب الحالية؟ 15% من 2000 وملاحظة 400")
    assert "300" in answer and "400" in answer and "اتفاق مختلف" in answer
    assert checked_percentage_conflict("احسب 15% من 2000") is None
    assert checked_percentage_conflict("هل تحسم؟ 15% من 2000 وملاحظة 300") is None


def test_review_formatter_preserves_exact_observed_and_required_values():
    result = review_output({"required_dimensions": [720, 720], "observed_dimensions": [1080, 720],
                            "required_text": ["رمز-123"], "observed_text": "عنوان"})
    answer = describe_review(result)
    assert "مش جاهز" in answer and "720×720" in answer and "1080×720" in answer and "رمز-123" in answer
    assert "لم أفحص الصورة" in answer
