"""Arabic command-line intake for offline advertising analysis."""

from decimal import Decimal, InvalidOperation
from getpass import getpass

from core.ad_platform_connectors import (
    AdPlatformError,
    GoogleAdsReadOnlyConnector,
    MetaAdsReadOnlyConnector,
)


def _ask_text(label, *, default=None):
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _ask_number(label, *, whole=False, optional=False):
    hint = "، أو Enter لغير متوفر" if optional else ""
    while True:
        value = input(f"{label}{hint}: ").strip()
        if not value and optional:
            return None
        try:
            parsed = Decimal(value.replace(",", "."))
            if not parsed.is_finite() or parsed < 0:
                raise ValueError
            if whole:
                if parsed != parsed.to_integral_value():
                    raise ValueError
                return int(parsed)
            return parsed
        except (InvalidOperation, ValueError):
            print("أدخلي رقمًا صحيحًا غير سالب، أو اتركيه فارغًا إذا كان اختياريًا.")


def _format_value(value, *, currency=None, percent=False, multiplier=False):
    if value is None:
        return "غير متاح"
    suffix = "%" if percent else ("x" if multiplier else (f" {currency}" if currency else ""))
    return f"{value:,.2f}{suffix}"


def manage_ad_intelligence(manager):
    print("\nتحليل أداء الإعلان — البيانات تُحفظ على هذا الجهاز ولا يُتصل بحسابات الإعلانات.")
    try:
        campaign_id = _ask_text("معرّف ثابت للحملة (استخدميه مرة أخرى للمقارنة)")
        campaign_name = _ask_text("اسم الحملة")
        platform = _ask_text("المنصة، مثل Meta أو Google")
        objective = _ask_text("هدف الحملة")
        period_start = _ask_text("بداية الفترة (YYYY-MM-DD)")
        period_end = _ask_text("نهاية الفترة (YYYY-MM-DD)")
        currency = _ask_text("العملة بثلاثة أحرف", default="EGP")
        spend = _ask_number("الإنفاق")
        impressions = _ask_number("مرات الظهور", whole=True)
        clicks = _ask_number("النقرات", whole=True)
        conversions = _ask_number("التحويلات المسجلة (قد تكون كسرية من Google)", optional=True)
        revenue = _ask_number("الإيراد المنسوب للحملة", optional=True)
        target_cpa = _ask_number("هدف تكلفة التحويل", optional=True)
        target_roas = _ask_number("هدف العائد على الإنفاق (مثال 2.5)", optional=True)
        creative_text = input("نص الإعلان (اختياري، Enter للتخطي): ").strip() or None
        record = manager.record_snapshot(
            campaign_id=campaign_id, campaign_name=campaign_name,
            platform=platform, objective=objective,
            period_start=period_start, period_end=period_end,
            currency=currency, spend=spend, impressions=impressions,
            clicks=clicks, conversions=conversions, revenue=revenue,
            target_cpa=target_cpa, target_roas=target_roas,
            creative_text=creative_text,
        )
    except (ValueError, OSError) as error:
        print("ماقدرتش أحلل الفترة:", error)
        return

    labels = {
        "ctr_percent": ("معدل النقر CTR", True, False),
        "cpc": ("تكلفة النقرة CPC", False, False),
        "cpm": ("تكلفة ألف ظهور CPM", False, False),
        "conversion_rate_percent": ("معدل التحويل", True, False),
        "cpa": ("تكلفة التحويل CPA", False, False),
        "roas": ("العائد على الإنفاق ROAS", False, True),
    }
    print("\nالمؤشرات المحسوبة:")
    for name, (label, percent, multiplier) in labels.items():
        print(f"- {label}: {_format_value(record['metrics'][name], currency=record['currency'], percent=percent, multiplier=multiplier)}")
    print("\nالتقييم:", {
        "no_explicit_target": "لا يوجد هدف مدخل للحكم على النجاح.",
        "below_explicit_target": "مؤشر واحد أو أكثر دون الهدف المدخل.",
        "insufficient_data": "الهدف موجود لكن بيانات المقارنة غير مكتملة.",
        "meets_explicit_targets": "المؤشرات المحسوبة تحقق الأهداف المدخلة.",
    }[record["assessment"]["status"]])
    for section, title in (("signals", "إشارات من البيانات"),
                           ("hypotheses", "فرضيات تحتاج تحققًا"),
                           ("experiments", "تجارب مقترحة")):
        if record[section]:
            print(f"\n{title}:")
            for item in record[section]:
                print("-", item)
    if record["comparison"]:
        print("\nمقارنة وصفية بالفترة السابقة للحملة نفسها؛ لا تثبت أن تغييرًا معينًا سبب الفرق.")
        for metric in ("ctr_percent", "cpa", "roas"):
            delta = record["comparison"]["metrics"][metric]
            if delta["change"] is not None:
                print(f"- {metric}: التغير {delta['change']}، والنسبة {delta['change_percent'] if delta['change_percent'] is not None else 'غير متاحة'}٪")
    if record.get("creative_review"):
        print("\nمراجعة بنيوية لنص الإعلان (قائمة كلمات؛ راجعيها يدويًا):")
        for check in record["creative_review"]["checks"].values():
            print(f"- {check['label']}: {'رُصد' if check['detected'] else 'لم يُرصد'}")
        print("-", record["creative_review"]["interpretation_limit"])
    for note in record.get("source_notes", []):
        print("ملاحظة مصدر البيانات:", note)
    print("\nحُفظ التقرير محليًا:", record["report_path"])


def manage_ad_intelligence_menu(manager):
    """Campaign analysis workspace: manual intake, CSV, saved history and export."""
    while True:
        print("\nذكاء الإعلانات — كل البيانات والتقارير محلية")
        print("1. تحليل فترة يدويًا")
        print("2. استيراد نتائج من CSV")
        print("3. عرض سجل الحملات والتقارير")
        print("4. تصدير كل التحليلات إلى CSV")
        print("5. إنشاء قالب استيراد CSV")
        print("6. جلب تقارير Meta مباشرة (قراءة فقط)")
        print("7. جلب تقارير Google Ads مباشرة (قراءة فقط)")
        print("0. رجوع")
        choice = input("اختاري: ").strip()
        if choice == "0":
            return
        if choice == "1":
            manage_ad_intelligence(manager)
        elif choice == "2":
            path = input("مسار ملف CSV: ").strip().strip('"')
            default_start = input("بداية فترة التقرير إذا لم تكن موجودة بالملف YYYY-MM-DD (Enter إذا موجودة): ").strip() or None
            default_end = input("نهاية فترة التقرير إذا لم تكن موجودة بالملف YYYY-MM-DD (Enter إذا موجودة): ").strip() or None
            default_platform = input("اسم المنصة إذا لم تُكتشف من الأعمدة (Meta Ads / Google Ads، Enter للاكتشاف): ").strip() or None
            default_currency = input("العملة إذا لم تكن بالملف [EGP]: ").strip() or "EGP"
            try:
                result = manager.import_csv(
                    path,
                    default_period_start=default_start,
                    default_period_end=default_end,
                    default_platform=default_platform,
                    default_currency=default_currency,
                )
            except (OSError, UnicodeError, ValueError) as error:
                print("تعذر استيراد الملف:", error)
                continue
            print(f"تم استيراد {len(result['imported'])} فترة.")
            for error in result["errors"]:
                print(f"- الصف {error['row']}: {error['error']}")
            if result["imported"]:
                print("التقارير محفوظة داخل outputs/ad_intelligence.")
            elif not result["errors"]:
                print("لم يحتوِ الملف على صفوف حملات قابلة للاستيراد.")
        elif choice == "3":
            snapshots = sorted(
                manager.list_snapshots(),
                key=lambda item: (item["campaign_name"].casefold(), item["period_start"]),
            )
            if not snapshots:
                print("لا توجد تحليلات محفوظة بعد.")
            for item in snapshots:
                metrics = item["metrics"]
                print(
                    f"- {item['campaign_name']} | {item['platform']} | "
                    f"{item['period_start']} إلى {item['period_end']} | "
                    f"CTR {metrics['ctr_percent'] if metrics['ctr_percent'] is not None else '—'}% | "
                    f"CPA {metrics['cpa'] if metrics['cpa'] is not None else '—'} {item['currency']} | "
                    f"ROAS {metrics['roas'] if metrics['roas'] is not None else '—'}x | "
                    f"{item['assessment']['status']}\n  {item['report_path']}"
                )
        elif choice == "4":
            path = input("مسار ملف التصدير [outputs/ad_intelligence/export.csv]: ").strip().strip('"')
            path = path or "outputs/ad_intelligence/export.csv"
            try:
                print("تم تصدير التحليلات إلى:", manager.export_csv(path).resolve())
            except OSError as error:
                print("تعذر التصدير:", error)
        elif choice == "5":
            path = input("مسار القالب [outputs/ad_intelligence/import_template.csv]: ").strip().strip('"')
            path = path or "outputs/ad_intelligence/import_template.csv"
            try:
                print("تم إنشاء القالب:", manager.write_csv_template(path).resolve())
                print("املئي الأعمدة؛ التاريخ YYYY-MM-DD والعملة مثل EGP. التحويلات والإيراد والأهداف ونص الإعلان اختيارية.")
            except OSError as error:
                print("تعذر إنشاء القالب:", error)
        elif choice == "6":
            _connect_meta_ads(manager)
        elif choice == "7":
            _connect_google_ads(manager)
        else:
            print("الاختيار غير صحيح.")


def _record_connected_campaigns(manager, payload):
    saved, errors = 0, []
    for campaign in payload["campaigns"]:
        try:
            manager.record_snapshot(**campaign)
            saved += 1
        except (ValueError, OSError) as error:
            errors.append(str(error))
    print(f"تم حفظ {saved} حملة من الحساب: {payload['account_name']}")
    for error in errors:
        print("تعذر حفظ سجل:", error)
    if saved:
        print("التقارير المحلية داخل outputs/ad_intelligence.")


def _connect_meta_ads(manager):
    print("قراءة فقط. استخدمي رمزًا بصلاحية ads_read، ولا ترسليه في المحادثة.")
    account_id = input("رقم الحساب الإعلاني (من غير act_ أو به): ").strip()
    token = getpass("رمز الوصول (لن يظهر على الشاشة ولن يُحفظ): ").strip()
    period_start = input("بداية الفترة YYYY-MM-DD: ").strip()
    period_end = input("نهاية الفترة YYYY-MM-DD: ").strip()
    action_type = input("نوع حدث التحويل الدقيق (اختياري، مثل offsite_conversion.fb_pixel_purchase): ").strip() or None
    try:
        report = MetaAdsReadOnlyConnector().fetch_campaigns(
            account_id=account_id, access_token=token,
            period_start=period_start, period_end=period_end,
            conversion_action_type=action_type,
        )
    except AdPlatformError as error:
        print("تعذر الاتصال بـMeta:", error)
        return
    _record_connected_campaigns(manager, report)


def _connect_google_ads(manager):
    print("قراءة فقط. لا تدخلي كلمة مرور Google؛ استخدمي بيانات OAuth ورمز المطوّر.")
    customer_id = input("رقم حساب Google Ads: ").strip()
    developer_token = getpass("Google Ads developer token (مخفي ولن يُحفظ): ").strip()
    client_id = input("OAuth client ID: ").strip()
    client_secret = getpass("OAuth client secret (مخفي ولن يُحفظ): ").strip()
    refresh_token = getpass("OAuth refresh token (مخفي ولن يُحفظ): ").strip()
    login_customer_id = input("رقم حساب المدير إن وُجد، وإلا Enter: ").strip() or None
    period_start = input("بداية الفترة YYYY-MM-DD: ").strip()
    period_end = input("نهاية الفترة YYYY-MM-DD: ").strip()
    try:
        report = GoogleAdsReadOnlyConnector().fetch_campaigns(
            customer_id=customer_id, developer_token=developer_token,
            client_id=client_id, client_secret=client_secret,
            refresh_token=refresh_token, period_start=period_start,
            period_end=period_end, login_customer_id=login_customer_id,
        )
    except AdPlatformError as error:
        print("تعذر الاتصال بـGoogle Ads:", error)
        return
    _record_connected_campaigns(manager, report)

