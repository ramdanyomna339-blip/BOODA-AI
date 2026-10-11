"""Small deterministic checks used as evidence, never as model-generated facts."""

from decimal import Decimal, localcontext
import re


def extract_review_observations(text):
    """Parse only explicit labeled Arabic observations; ambiguity returns None.

    This is an input adapter, not inference or image inspection. Unlabeled
    requests still require model interpretation and review.
    """
    parameters = {}
    for label, field in (("المطلوب", "required_dimensions"), ("الملاحظ", "observed_dimensions")):
        matches = re.findall(r"المقاس\s+" + label + r"\s*[:：]?\s*(\d{1,5})\s*[×xX*]\s*(\d{1,5})", text)
        if len(matches) != 1:
            return None
        parameters[field] = [int(n) for n in matches[0]]
    required = re.findall(r"النصوص المطلوبة\s*[:：]?\s*([^\.\n؟]+)", text)
    observed = re.findall(r"النص الملاحظ\s*[:：]?\s*([^\.\n؟]+)", text)
    if len(required) != 1 or len(observed) != 1:
        return None
    # Clause boundaries must be explicit; never absorb another field label.
    if any(label in value for value in required + observed
           for label in ("المقاس", "النصوص المطلوبة", "النص الملاحظ")):
        return None
    parameters["required_text"] = [part.strip() for part in re.split(r"\s+و\s*|[،,;؛]", required[0])]
    parameters["observed_text"] = re.sub(r"\s+فقط\s*$", "", observed[0]).strip()
    try:
        review_output(parameters)
    except ValueError:
        return None
    return parameters


def percentage_evidence(text):
    result = []
    for match in re.finditer(r"(?<![-\d.])([\d]+(?:\.[\d]+)?)\s*[%٪]\s*(?:من|of)\s*(?:(?:الميزانية|المبلغ|ميزانية|budget|amount)\s*)?\(?([\d]+(?:\.[\d]+)?)(?:\s*\))?", text, re.I):
        if len(match.group(0)) > 80:
            continue
        rate, base = map(Decimal, match.groups())
        if rate > 100:
            continue
        with localcontext() as context:
            context.prec = 90
            value = rate * base / Decimal(100)
            result.append({"expression": match.group(0), "result": format(value.normalize(), "f"),
                           "start": match.start(), "end": match.end(),
                           "method": "decimal_arithmetic_not_model_guess"})
    return result


def checked_percentage_conflict(text):
    """Resolve arithmetic only; never decide the user's contractual fee."""
    if not re.search(r"تعارض|تحسم|حسم|الفارق|الأتعاب الحالية|الاتعاب الحالية", text):
        return None
    calculations = percentage_evidence(text)
    if len(calculations) != 1:
        return None
    calculation = calculations[0]
    remainder = text.replace(calculation["expression"], "", 1)
    other = re.findall(r"(?<![\d.])\d+(?:\.\d+)?", remainder)
    if len(other) != 1 or Decimal(other[0]) == Decimal(calculation["result"]):
        return None
    return (f"الحساب المؤكد: {calculation['expression']} = {calculation['result']}. "
            f"وده مختلف عن المبلغ المذكور {other[0]}. ماقدرش أحسم الأتعاب المعتمدة من النص وحده: "
            "هل فيه رسوم إضافية أو اتفاق مختلف؟")


def describe_review(result):
    if result.get("scope") != "supplied_observations_only_not_visual_inspection":
        return None
    issues = []
    if not result["dimensions_match"]:
        expected = "×".join(map(str, result["required_dimensions"]))
        observed = "×".join(map(str, result["observed_dimensions"]))
        issues.append(f"المقاس الملاحظ {observed} بدل المطلوب {expected}")
    if result["missing_text"]:
        issues.append("النص المفقود: " + "، ".join(result["missing_text"]))
    if issues:
        return "مش جاهز للتسليم بحسب الملاحظات المعطاة: " + "; ".join(issues) + ". لم أعدّل المخرج ولم أفحص الصورة نفسها."
    return "المقاس والنصوص مطابقين للملاحظات المعطاة؛ ده مش تقييم شامل لجودة التصميم أو فحص للصورة نفسها."


def review_output(parameters):
    fields = {"required_dimensions", "observed_dimensions", "required_text", "observed_text"}
    if not isinstance(parameters, dict) or set(parameters) != fields:
        raise ValueError("Output review requires exactly dimensions and text observations.")
    for key in ("required_dimensions", "observed_dimensions"):
        value = parameters[key]
        if not isinstance(value, list) or len(value) != 2 or any(type(n) is not int or not 1 <= n <= 20000 for n in value):
            raise ValueError("Dimensions must contain two positive integer pixels.")
    required = parameters["required_text"]
    observed = parameters["observed_text"]
    if not isinstance(required, list) or len(required) > 30 or any(
        not isinstance(item, str) or not item.strip() or len(item) > 500 for item in required
    ) or not isinstance(observed, str) or len(observed) > 10000:
        raise ValueError("Invalid review text.")
    missing = [item for item in required if item not in observed]
    dimensions_match = parameters["required_dimensions"] == parameters["observed_dimensions"]
    return {"private": True, "ready": dimensions_match and not missing,
            "dimensions_match": dimensions_match, "missing_text": missing,
            "required_dimensions": parameters["required_dimensions"],
            "observed_dimensions": parameters["observed_dimensions"],
            "scope": "supplied_observations_only_not_visual_inspection", "modified_output": False}
