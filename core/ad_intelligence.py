"""Offline, evidence-led analysis of user-entered advertising snapshots."""

from copy import deepcopy
import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

from core.persistence import JsonObjectStore


def _nonnegative_number(value, name, *, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a non-negative number.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{name} must be a non-negative number.") from None
    if not number.is_finite() or number < 0:
        raise ValueError(f"{name} must be a non-negative finite number.")
    return number


def _count(value, name, *, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative whole number.")
    return value


def _decimal_output(value):
    if value is None:
        return None
    return float(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _parse_date(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO date (YYYY-MM-DD).")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(f"{name} must be an ISO date (YYYY-MM-DD).") from None


def _ratio(numerator, denominator, *, scale=Decimal("1")):
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator * scale


class BoodaAdIntelligence:
    """Store local campaign snapshots and report only what their data supports."""

    def __init__(self, file_path="knowledge/ad_intelligence.json", *,
                 output_dir="outputs/ad_intelligence", event_log=None,
                 artifact_manager=None):
        self.store = JsonObjectStore(file_path)
        self.output_dir = Path(output_dir)
        self.event_log = event_log
        self.artifact_manager = artifact_manager
        self.data = self.store.load()
        self.data.setdefault("snapshots", {})

    def list_snapshots(self, *, campaign_id=None):
        items = self.data["snapshots"].values()
        return [
            deepcopy(item) for item in items
            if campaign_id is None or item["campaign_id"] == campaign_id
        ]

    def get_snapshot(self, snapshot_id):
        item = self.data["snapshots"].get(snapshot_id)
        return deepcopy(item) if item is not None else None

    CSV_COLUMNS = (
        "campaign_id", "campaign_name", "platform", "objective",
        "period_start", "period_end", "currency", "spend", "impressions",
        "clicks", "conversions", "revenue", "target_cpa", "target_roas",
        "creative_text",
    )

    @classmethod
    def write_csv_template(cls, path):
        """Write a blank, documented import template without external dependencies."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            csv.writer(output).writerow(cls.CSV_COLUMNS)
        return path

    def import_csv(self, path, *, default_period_start=None,
                   default_period_end=None, default_platform=None,
                   default_currency="EGP"):
        """Import Booda-template, Meta Ads Manager, or Google Ads CSV snapshots."""
        path = Path(path)
        imported, errors = [], []
        with path.open("rb") as raw:
            content = raw.read()
        decoded = None
        for encoding in ("utf-8-sig", "utf-16", "cp1256", "cp1252"):
            try:
                decoded = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            raise ValueError("Could not decode the CSV. Save it as UTF-8 or UTF-16.")
        try:
            dialect = csv.Sniffer().sniff(decoded[:8192], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(decoded, newline=""), dialect=dialect)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row.")
        mapped, currency_from_header = self._map_export_headers(reader.fieldnames)
        missing = sorted({"campaign_name", "spend", "impressions", "clicks"} - set(mapped))
        if missing:
            raise ValueError(
                "CSV does not look like a supported campaign report; missing columns: "
                + ", ".join(missing)
            )
        for row_number, row in enumerate(reader, start=2):
            try:
                values = {key: (row.get(header) or "").strip() for key, header in mapped.items()}
                campaign_name = values["campaign_name"]
                if not campaign_name or self._is_summary_row(campaign_name):
                    continue
                period_start = values.get("period_start") or default_period_start
                period_end = values.get("period_end") or default_period_end
                if values.get("report_date"):
                    period_start = period_end = values["report_date"]
                if period_start:
                    period_start = self._normalize_export_date(period_start)
                if period_end:
                    period_end = self._normalize_export_date(period_end)
                spend = self._parse_export_number(values.get("spend"), "spend")
                impressions = self._parse_export_number(values.get("impressions"), "impressions", whole=True)
                clicks = self._parse_export_number(values.get("clicks"), "clicks", whole=True)
                conversions = self._parse_export_number(values.get("conversions"), "conversions", optional=True)
                revenue = self._parse_export_number(values.get("revenue"), "revenue", optional=True)
                currency = (values.get("currency") or currency_from_header or default_currency or "EGP").upper()
                platform = values.get("platform") or default_platform or self._detect_platform(mapped)
                objective = values.get("objective") or "غير محدد في ملف المنصة"
                creative_text = values.get("creative_text") or None
                campaign_id = values.get("campaign_id") or self._campaign_slug(campaign_name)
                if not period_start or not period_end:
                    errors.append({
                        "row": row_number,
                        "error": "Report period is missing. Add reporting dates to the export or use Booda's template.",
                    })
                    continue
                source_notes = []
                conversions_header = mapped.get("conversions", "")
                if self._normalize_header(conversions_header) in {"results", "النتائج"}:
                    indicator = values.get("result_indicator", "")
                    if "click" in indicator.casefold() or "نقر" in indicator:
                        conversions = None
                        source_notes.append("عمود Results في ملف المنصة يشير إلى نقرات، لذلك لم يُستخدم كعدد تحويلات.")
                    else:
                        source_notes.append("استُخدم عمود Results كعدد التحويلات؛ تحققي من نوع النتيجة وإعداد الإسناد في المنصة.")
                imported.append(self.record_snapshot(
                    campaign_id=campaign_id, campaign_name=campaign_name,
                    platform=platform, objective=objective,
                    period_start=period_start, period_end=period_end,
                    currency=currency, spend=spend, impressions=impressions,
                    clicks=clicks, conversions=conversions, revenue=revenue,
                    target_cpa=self._parse_export_number(values.get("target_cpa"), "target_cpa", optional=True),
                    target_roas=self._parse_export_number(values.get("target_roas"), "target_roas", optional=True),
                    creative_text=creative_text,
                    source_notes=source_notes,
                ))
            except (ValueError, TypeError, OSError, KeyError) as error:
                errors.append({"row": row_number, "error": str(error)})
        return {"imported": imported, "errors": errors}

    @staticmethod
    def _normalize_header(value):
        value = unicodedata.normalize("NFKD", str(value).casefold())
        value = "".join(char for char in value if not unicodedata.combining(char))
        value = re.sub(r"[ًٌٍَُِّْـ]", "", value)
        return re.sub(r"[^a-z0-9\u0600-\u06ff]+", "", value)

    @classmethod
    def _map_export_headers(cls, headers):
        aliases = {
            "campaign_id": ("campaign_id", "campaign id", "معرف الحملة", "رقم الحملة"),
            "campaign_name": ("campaign_name", "campaign name", "campaign", "اسم الحملة", "الحملة"),
            "platform": ("platform", "المنصة"),
            "objective": ("objective", "campaign objective", "هدف الحملة", "الهدف"),
            "period_start": ("period_start", "reporting starts", "date start", "بداية الفترة", "بداية التقرير"),
            "period_end": ("period_end", "reporting ends", "date end", "نهاية الفترة", "نهاية التقرير"),
            "report_date": ("date", "day", "report date", "التاريخ", "اليوم"),
            "currency": ("currency", "currency code", "العملة", "رمز العملة"),
            "spend": ("spend", "amount spent", "cost", "الإنفاق", "المبلغ المنفق", "التكلفة"),
            "impressions": ("impressions", "impr.", "impr", "مرات الظهور", "الظهور"),
            "clicks": ("link clicks", "clicks", "clicks (all)", "النقرات على الرابط", "نقرات الرابط", "النقرات"),
            "conversions": ("conversions", "all conversions", "purchases", "leads", "عمليات الشراء", "العملاء المحتملون", "التحويلات", "results", "النتائج"),
            "result_indicator": ("result indicator", "نوع النتيجة", "مؤشر النتيجة"),
            "revenue": ("revenue", "result value", "conversion value", "conv. value", "purchases conversion value", "قيمة التحويل", "قيمة النتائج", "الإيراد"),
            "target_cpa": ("target_cpa", "هدف تكلفة التحويل"),
            "target_roas": ("target_roas", "هدف العائد"),
            "creative_text": ("creative_text", "primary text", "ad text", "text", "نص الإعلان", "النص الأساسي"),
        }
        normalized = {
            cls._normalize_header(re.sub(r"\s*\([A-Za-z]{3}\)\s*$", "", header)): header
            for header in headers
        }
        mapped = {}
        for key, candidates in aliases.items():
            for candidate in candidates:
                header = normalized.get(cls._normalize_header(candidate))
                if header is not None:
                    mapped[key] = header
                    break
        currency = None
        for header in headers:
            match = re.search(r"\(([A-Za-z]{3})\)", header)
            if match and cls._normalize_header(header) == cls._normalize_header(mapped.get("spend", "")):
                currency = match.group(1)
                break
        return mapped, currency

    @staticmethod
    def _parse_export_number(value, name, *, whole=False, optional=False):
        if value is None or not str(value).strip() or str(value).strip() in {"—", "–", "-", "--", "N/A"}:
            if optional:
                return None
            raise ValueError(f"{name} is missing from this row.")
        text = str(value).strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")).replace("%", "")
        text = re.sub(r"[^\d,\.\-]", "", text)
        if "," in text and "." in text:
            text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
        elif "," in text:
            tail = text.rsplit(",", 1)[-1]
            text = text.replace(",", ".") if len(tail) in {1, 2} else text.replace(",", "")
        try:
            parsed = Decimal(text)
        except (InvalidOperation, ValueError):
            if optional:
                return None
            raise ValueError(f"{name} is not a number: {value}") from None
        if not parsed.is_finite() or parsed < 0:
            raise ValueError(f"{name} must be a non-negative finite number.")
        if whole:
            if parsed != parsed.to_integral_value():
                raise ValueError(f"{name} must be a whole number.")
            return int(parsed)
        return parsed

    @staticmethod
    def _detect_platform(mapped):
        source_headers = " ".join(mapped.values()).casefold()
        if "amount spent" in source_headers or "reporting starts" in source_headers or "link clicks" in source_headers:
            return "Meta Ads"
        if "cost" in source_headers or "impr." in source_headers or "conv. value" in source_headers:
            return "Google Ads"
        return "إعلانات مستوردة"

    @staticmethod
    def _normalize_export_date(value):
        value = str(value).strip()
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
        for pattern in ("%Y/%m/%d", "%b %d, %Y", "%d %b %Y"):
            try:
                return datetime.strptime(value, pattern).date().isoformat()
            except ValueError:
                continue
        slash_date = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
        if slash_date:
            first, second, year = map(int, slash_date.groups())
            if first > 12 and second <= 12:
                return date(year, second, first).isoformat()
            if second > 12 and first <= 12:
                return date(year, first, second).isoformat()
            raise ValueError(
                f"Ambiguous report date '{value}'. Use YYYY-MM-DD or set the report period manually."
            )
        return value

    @staticmethod
    def _campaign_slug(name):
        slug = re.sub(r"[^a-z0-9\u0600-\u06ff]+", "-", name.casefold()).strip("-")
        return f"imported-{slug[:80]}" or "imported-campaign"

    @classmethod
    def _is_summary_row(cls, name):
        return cls._normalize_header(name) in {"total", "totals", "grandtotal", "الإجمالي", "المجموع"}

    def export_csv(self, path):
        """Export saved snapshots and derived performance metrics to a CSV file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "snapshot_id", "campaign_id", "campaign_name", "platform",
            "objective", "period_start", "period_end", "currency", "spend",
            "impressions", "clicks", "conversions", "revenue", "target_cpa",
            "target_roas", "creative_text", "ctr_percent", "cpc", "cpm",
            "conversion_rate_percent", "cpa", "roas",
            "assessment", "report_path",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            for record in self.list_snapshots():
                row = {name: record.get(name) for name in fields}
                row.update(record["inputs"])
                row.update(record["metrics"])
                row["assessment"] = record["assessment"]["status"]
                writer.writerow(row)
        return path

    def record_snapshot(
        self, *, campaign_id, campaign_name, platform, objective,
        period_start, period_end, currency, spend, impressions, clicks,
        conversions=None, revenue=None, target_cpa=None, target_roas=None,
        compare_to=None, creative_text=None, source_notes=None,
    ):
        campaign_id = self._text(campaign_id, "campaign_id", 100)
        campaign_name = self._text(campaign_name, "campaign_name", 200)
        platform = self._text(platform, "platform", 100)
        objective = self._text(objective, "objective", 300)
        period_start = _parse_date(period_start, "period_start")
        period_end = _parse_date(period_end, "period_end")
        if period_start > period_end:
            raise ValueError("period_start must be on or before period_end.")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Za-z]{3}", currency):
            raise ValueError("currency must be a three-letter code, such as EGP or USD.")
        currency = currency.upper()

        spend = _nonnegative_number(spend, "spend")
        impressions = _count(impressions, "impressions")
        clicks = _count(clicks, "clicks")
        conversions = _nonnegative_number(conversions, "conversions", optional=True)
        revenue = _nonnegative_number(revenue, "revenue", optional=True)
        target_cpa = _nonnegative_number(target_cpa, "target_cpa", optional=True)
        target_roas = _nonnegative_number(target_roas, "target_roas", optional=True)
        if creative_text is not None:
            creative_text = self._text(creative_text, "creative_text", 10_000)
        snapshot_id = f"ad-snapshot-{uuid4().hex}"
        inputs = {
            "spend": _decimal_output(spend), "impressions": impressions,
            "clicks": clicks, "conversions": conversions,
            "revenue": _decimal_output(revenue),
            "target_cpa": _decimal_output(target_cpa),
            "target_roas": _decimal_output(target_roas),
        }
        metrics_decimal = {
            "ctr_percent": _ratio(Decimal(clicks), Decimal(impressions), scale=Decimal(100)),
            "cpc": _ratio(spend, Decimal(clicks)),
            "cpm": _ratio(spend * Decimal(1000), Decimal(impressions)),
            "conversion_rate_percent": _ratio(
                Decimal(conversions) if conversions is not None else None,
                Decimal(clicks), scale=Decimal(100),
            ),
            "cpa": _ratio(
                spend,
                Decimal(conversions) if conversions is not None else None,
            ),
            "roas": _ratio(revenue, spend),
        }
        metrics = {
            name: _decimal_output(value)
            for name, value in metrics_decimal.items()
        }
        assessment = self._assess_targets(
            inputs=inputs, metrics=metrics,
        )
        signals, hypotheses, experiments = self._diagnose(inputs, metrics)
        creative_review = self._review_creative(creative_text)
        comparison = self._compare(
            campaign_id, metrics, currency=currency, compare_to=compare_to,
        )
        record = {
            "snapshot_id": snapshot_id,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "platform": platform,
            "objective": objective,
            "period_start": period_start,
            "period_end": period_end,
            "currency": currency,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "inputs": inputs,
            "metrics": metrics,
            "assessment": assessment,
            "signals": signals,
            "hypotheses": hypotheses,
            "experiments": experiments,
            "creative_review": creative_review,
            "source_notes": list(source_notes or []),
            "comparison": comparison,
            "interpretation_limits": [
                "لا توجد مقارنة معيارية عامة هنا؛ النجاح يحدد بالهدف أو المقارنة التي قدمتها المستخدمة.",
                "المؤشرات تصف البيانات المدخلة ولا تثبت سبب النتيجة أو دلالتها الإحصائية.",
                "الفرضيات اقتراحات للفحص وليست تشخيصًا مؤكدًا لمشكلة الإعلان.",
            ],
        }
        report_path = self._write_report(record)
        record["report_path"] = str(report_path.resolve())
        self.data["snapshots"][snapshot_id] = record
        self.store.save(self.data)
        if self.event_log is not None:
            self.event_log.record(
                "ad_snapshot_analyzed", entity_type="ad_campaign",
                entity_id=snapshot_id,
                details={"campaign_id": campaign_id, "local_only": True},
            )
        if self.artifact_manager is not None:
            self.artifact_manager.register(
                report_path, kind="ad_analysis",
                title=f"تحليل أداء الإعلان: {campaign_name}",
                metadata={
                    "snapshot_id": snapshot_id,
                    "campaign_id": campaign_id,
                    "scope": "local-only",
                },
            )
        return deepcopy(record)

    @staticmethod
    def _text(value, name, limit):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f"{name} must contain 1–{limit} characters.")
        return value.strip()

    @staticmethod
    def _assess_targets(*, inputs, metrics):
        checks = {}
        if inputs["target_cpa"] is not None:
            actual = metrics["cpa"]
            checks["cpa"] = {
                "target": inputs["target_cpa"], "actual": actual,
                "met": None if actual is None else actual <= inputs["target_cpa"],
            }
        if inputs["target_roas"] is not None:
            actual = metrics["roas"]
            checks["roas"] = {
                "target": inputs["target_roas"], "actual": actual,
                "met": None if actual is None else actual >= inputs["target_roas"],
            }
        if not checks:
            status = "no_explicit_target"
        elif any(check["met"] is False for check in checks.values()):
            status = "below_explicit_target"
        elif any(check["met"] is None for check in checks.values()):
            status = "insufficient_data"
        else:
            status = "meets_explicit_targets"
        return {"status": status, "checks": checks}

    @staticmethod
    def _diagnose(inputs, metrics):
        signals, hypotheses, experiments = [], [], []
        if inputs["impressions"] == 0:
            signals.append("لا توجد مرات ظهور مسجلة؛ لا يمكن تقييم النقر أو التحويل لهذه الفترة.")
        elif inputs["clicks"] == 0:
            signals.append("لم تسجل الفترة نقرات رغم وجود مرات ظهور؛ هذا وحده لا يثبت سبب الأداء.")
            hypotheses.append("قد يكون العرض أو الجمهور أو الرسالة بحاجة إلى مراجعة؛ هذه فرضيات فقط.")
            experiments.append("راجعي ملاءمة الجمهور والعرض، واختبري تغيير عنصر إبداعي واحد مع تثبيت بقية العناصر.")
        elif inputs["conversions"] == 0:
            signals.append("سجلت الفترة نقرات دون تحويلات؛ تحققي أولًا من صحة تعريف التحويل والتتبع.")
            hypotheses.append("قد تكون المشكلة في التتبع أو صفحة الهبوط أو العرض؛ البيانات الحالية لا تحدد السبب.")
            experiments.append("اختبري مسار التحويل يدويًا ثم افحصي تجربة صفحة الهبوط قبل تغيير الإعلان.")
        elif inputs["conversions"] is None:
            signals.append("بيانات التحويل غير مدخلة؛ لا يمكن حساب معدل التحويل أو تكلفة التحويل.")
            experiments.append("أضيفي عدد التحويلات المؤكدة قبل اتخاذ قرار عن نتيجة الحملة.")
        if inputs["revenue"] is None:
            signals.append("الإيراد غير مدخل؛ لم يُحسب العائد على الإنفاق الإعلاني (ROAS).")
        if inputs["target_cpa"] is None and inputs["target_roas"] is None:
            signals.append("لم يُدخل هدف تكلفة أو عائد؛ لا يمكن الحكم على النجاح أو الفشل من المؤشرات وحدها.")
        return signals, hypotheses, experiments

    @staticmethod
    def _review_creative(text):
        """Check observable copy elements with a transparent keyword checklist."""
        if not text:
            return None
        checks = {
            "call_to_action": ("دعوة مباشرة لاتخاذ إجراء", (
                "اطلب", "اشتري", "اشتر", "تسوق", "احجز", "جرب", "ابدأ",
                "سجل", "تواصل", "buy", "shop", "order", "book", "try", "sign up",
            )),
            "offer": ("عرض أو حافز واضح", (
                "خصم", "عرض", "مجانا", "مجاني", "توصيل", "وفر", "هدية",
                "لفترة محدودة", "discount", "free", "offer", "save", "limited time",
            )),
            "benefit": ("فائدة أو نتيجة مذكورة", (
                "يساعد", "راحة", "نتيجة", "يوفر", "يمنح", "بشرة", "أسرع", "أسهل",
                "benefit", "improve", "easy", "fast", "results",
            )),
            "trust": ("إشارة ثقة أو إثبات اجتماعي", (
                "تقييم", "آراء", "مراجعات", "عملاء", "موثوق", "ضمان", "نتائج",
                "reviews", "customers", "trusted", "guarantee", "verified",
            )),
            "urgency": ("استعجال أو مدة محددة", (
                "لفترة محدودة", "اليوم فقط", "آخر فرصة", "الكمية محدودة", "ينتهي اليوم",
                "limited time", "today only", "last chance", "limited stock",
            )),
            "personal_relevance": ("مخاطبة مباشرة للجمهور", (
                "أنت", "انتي", "أنتِ", "لك", "لكِ", "لديك", "your", "you", "yourself",
            )),
            "claims_to_review": ("ادعاءات مطلقة تستحق التحقق", (
                "مضمون 100", "الأفضل في العالم", "يعالج نهائيًا", "يشفي", "بدون أي آثار",
                "guaranteed 100", "best in the world", "cures completely", "no side effects",
            )),
        }
        normalized = text.casefold()
        result = {
            "method": "transparent_keyword_checklist",
            "character_count": len(text),
            "word_count": len(re.findall(r"[\w\u0600-\u06ff]+", text)),
            "question_count": text.count("?") + text.count("؟"),
            "checks": {},
            "interpretation_limit": (
                "فحص كلمات ظاهر فقط؛ قد لا يلتقط الصياغات البديلة ولا يقيس الإقناع أو الأداء. راجعي النص يدويًا."
            ),
        }
        for name, (label, keywords) in checks.items():
            matches = [word for word in keywords if word in normalized]
            result["checks"][name] = {
                "label": label,
                "detected": bool(matches),
                "matched_terms": matches,
            }
        return result

    def _compare(self, campaign_id, metrics, *, currency, compare_to=None):
        previous = self.data["snapshots"].get(compare_to) if compare_to else None
        if compare_to is not None and previous is None:
            raise ValueError(f"Comparison snapshot not found: {compare_to}")
        if compare_to is not None and previous["campaign_id"] != campaign_id:
            raise ValueError("A comparison snapshot must belong to the same campaign.")
        if previous is None and compare_to is None:
            prior_records = sorted(
                (item for item in self.data["snapshots"].values()
                 if item["campaign_id"] == campaign_id),
                key=lambda item: item["created_at"],
            )
            previous = prior_records[-1] if prior_records else None
        if previous is None:
            return None
        if previous["currency"] != currency:
            if compare_to is not None:
                raise ValueError("A comparison snapshot must use the same currency.")
            return None
        deltas = {}
        for name, current in metrics.items():
            prior = previous["metrics"].get(name)
            if current is None or prior is None:
                deltas[name] = {"current": current, "previous": prior, "change": None, "change_percent": None}
                continue
            change = Decimal(str(current)) - Decimal(str(prior))
            change_percent = (
                _decimal_output(change / Decimal(str(prior)) * Decimal(100))
                if prior != 0 else None
            )
            deltas[name] = {
                "current": current, "previous": prior,
                "change": _decimal_output(change),
                "change_percent": change_percent,
            }
        return {"snapshot_id": previous["snapshot_id"], "metrics": deltas}

    def _write_report(self, record):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{record['snapshot_id']}.md"
        currency = record["currency"]
        metrics = record["metrics"]
        lines = [
            f"# تحليل أداء الإعلان: {record['campaign_name']}", "",
            f"- المنصة: {record['platform']}",
            f"- الهدف: {record['objective']}",
            f"- الفترة: {record['period_start']} إلى {record['period_end']}",
            f"- العملة: {currency}", "", "## المدخلات", "",
        ]
        for name, value in record["inputs"].items():
            lines.append(f"- {name}: {value if value is not None else 'غير متوفر'}")
        lines.extend(["", "## المؤشرات المحسوبة", ""])
        for name, value in metrics.items():
            suffix = "%" if name.endswith("percent") else ("x" if name == "roas" else f" {currency}")
            lines.append(f"- {name}: {value if value is not None else 'غير متاح'}{suffix if value is not None else ''}")
        comparison = record["comparison"]
        if comparison:
            previous = self.data["snapshots"].get(comparison["snapshot_id"], {})
            previous_period = (
                f" ({previous['period_start']} إلى {previous['period_end']})"
                if previous else ""
            )
            lines.extend(["", "## مقارنة وصفية بالفترة السابقة", "",
                          f"- الفترة المرجعية: {comparison['snapshot_id']}{previous_period}"])
            for name, delta in comparison["metrics"].items():
                lines.append(
                    f"- {name}: {delta['previous']} ← {delta['current']} "
                    f"(التغير {delta['change'] if delta['change'] is not None else 'غير متاح'}؛ "
                    f"{delta['change_percent'] if delta['change_percent'] is not None else 'غير متاح'}٪)"
                )
            lines.append("- المقارنة وصفية ولا تثبت أن تغييرًا معينًا سبب الفرق.")
        lines.extend([
            "", "## التقييم", "",
            f"- الحالة: {record['assessment']['status']}",
            "- لا تُستخدم معايير عامة؛ التقييم يعتمد على الهدف المدخل فقط.",
            "", "## إشارات من البيانات", "",
        ])
        lines.extend(f"- {item}" for item in record["signals"] or ["لا توجد إشارة إضافية من البيانات المدخلة."])
        lines.extend(["", "## فرضيات تحتاج تحققًا", ""])
        lines.extend(f"- {item}" for item in record["hypotheses"] or ["لا توجد فرضية محددة من هذه البيانات."])
        if record.get("source_notes"):
            lines.extend(["", "## ملاحظات على مصدر البيانات", ""])
            lines.extend(f"- {item}" for item in record["source_notes"])
        creative = record.get("creative_review")
        if creative:
            lines.extend(["", "## مراجعة بنيوية لنص الإعلان", "",
                          f"- عدد الأحرف: {creative['character_count']}"])
            for item in creative["checks"].values():
                detected = "رُصدت كلمات مرتبطة بالعنصر" if item["detected"] else "لم تُرصد كلمات من القائمة؛ تحققي يدويًا"
                terms = f" ({', '.join(item['matched_terms'])})" if item["matched_terms"] else ""
                lines.append(f"- {item['label']}: {detected}{terms}")
            lines.append(f"- {creative['interpretation_limit']}")
        lines.extend(["", "## تجارب مقترحة", ""])
        lines.extend(f"- {item}" for item in record["experiments"] or ["أدخلي هدفًا أو فترة مقارنة لتحديد تجربة مناسبة."])
        lines.extend(["", "## حدود التفسير", ""])
        lines.extend(f"- {item}" for item in record["interpretation_limits"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
