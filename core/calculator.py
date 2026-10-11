"""Bounded decimal arithmetic; no eval, function calls or model guesses."""

import ast
from decimal import Decimal, DecimalException, localcontext
import re


def calculate_request(message):
    match = re.fullmatch(r"\s*(?:احسب|احسبي|calculate)\s+(.+?)\s*[؟?]?\s*", message, re.I)
    if match is None:
        return None
    expression = match[1].translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫×÷٪", "0123456789.*/%"))
    expression = re.sub(r"(-?\d+(?:\.\d+)?)\s*%\s*(?:من|of)\s*(\d+(?:\.\d+)?)",
                        r"(\1*\2/100)", expression, flags=re.I)
    if len(expression) > 200 or not re.fullmatch(r"[\d.\s+*/()-]+", expression):
        return "الحساب يدعم الأرقام والنسب وعمليات الجمع والطرح والضرب والقسمة فقط؛ لم أنفذ تعبيرًا آخر."
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 40:
            raise ValueError("Expression too complex")
        def evaluate(node):
            if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
                return Decimal(ast.get_source_segment(expression.strip(), node))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                number = evaluate(node.operand)
                return -number if isinstance(node.op, ast.USub) else number
            if isinstance(node, ast.BinOp):
                left, right = evaluate(node.left), evaluate(node.right)
                if isinstance(node.op, ast.Add): return left + right
                if isinstance(node.op, ast.Sub): return left - right
                if isinstance(node.op, ast.Mult): return left * right
                if isinstance(node.op, ast.Div): return left / right
            raise ValueError("Unsupported operation")
        with localcontext() as context:
            context.prec = 50
            value = evaluate(tree.body)
            if not value.is_finite() or abs(value) > Decimal('1e50'):
                raise ValueError("Out of range")
            return "نتيجة الحساب: " + format(value.normalize(), "f")
    except (ValueError, SyntaxError, DecimalException, TypeError, RecursionError):
        return "لم أقدر أحسب التعبير: راجع الصياغة أو القسمة على صفر؛ لم أخمّن نتيجة."
