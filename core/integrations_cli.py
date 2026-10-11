"""Local, read-only account integrations available from Booda's console."""

from getpass import getpass

from core.ad_platform_connectors import (
    AdPlatformError, TikTokReadOnlyConnector, YouTubeReadOnlyConnector,
)


def manage_integrations():
    while True:
        print("\nمركز ربط الحسابات — قراءة فقط، ولا تُحفظ مفاتيح الدخول")
        print("1. قراءة معلومات قناة YouTube عامة (مفتاح API وحصة مجانية محدودة)")
        print("2. قراءة فيديوهات TikTok الخاصة بالحساب (OAuth وموافقة التطبيق)")
        print("3. عرض حالة ومتطلبات باقي الخدمات")
        print("0. رجوع")
        choice = input("اختاري: ").strip()
        if choice == "0":
            return
        if choice == "1":
            _read_youtube()
        elif choice == "2":
            _read_tiktok()
        elif choice == "3":
            _show_status()
        else:
            print("الاختيار غير صحيح.")


def _read_youtube():
    print("القناة العامة فقط حاليًا؛ قراءة تحليلات حسابك الخاصة تحتاج OAuth منفصل.")
    key = getpass("YouTube Data API key (مخفي ولن يُحفظ): ").strip()
    channel = input("Channel ID، أو اتركيه فارغًا لإدخال @handle: ").strip()
    handle = None if channel else input("YouTube @handle: ").strip()
    try:
        data = YouTubeReadOnlyConnector().fetch_channel(
            api_key=key, channel_id=channel or None, handle=handle or None,
        )
    except AdPlatformError as error:
        print("تعذر قراءة قناة YouTube:", error)
        return
    print(f"القناة: {data['title']} | المشاهدات: {data['view_count']:,} | الفيديوهات: {data['video_count']:,}")
    print("المشتركون:", "مخفيون" if data["subscriber_count"] is None else f"{data['subscriber_count']:,}")
    print(data["url"])


def _read_tiktok():
    print("يتطلب تطبيق TikTok معتمدًا وصلاحية video.list وموافقة الحساب؛ لا ترسلي الرمز هنا.")
    token = getpass("TikTok access token (مخفي ولن يُحفظ): ").strip()
    try:
        videos, _cursor = TikTokReadOnlyConnector().fetch_videos(access_token=token)
    except AdPlatformError as error:
        print("تعذر قراءة TikTok:", error)
        return
    if not videos:
        print("لم يُرجع الحساب فيديوهات متاحة.")
    for video in videos:
        print(f"- {video.get('title') or video.get('video_description') or 'فيديو بدون عنوان'} | مشاهدات: {video.get('view_count', '—')} | إعجابات: {video.get('like_count', '—')}")


def _show_status():
    print("\nالمتاح حاليًا:")
    print("- Facebook / Instagram Ads: ربط تقارير قراءة فقط في الخيار 35، بصلاحية إعلانية.")
    print("- Google Ads: ربط تقارير قراءة فقط في الخيار 35؛ يحتاج OAuth ورمز مطوّر.")
    print("- YouTube: القنوات العامة من هذا القسم؛ لا نشر ولا تعديل.")
    print("- TikTok: قراءة فيديوهات الحساب بعد موافقة تطبيق TikTok.")
    print("- X: واجهة المطور مدفوعة حسب الاستخدام؛ غير مفعّلة حفاظًا على شرط عدم وجود تكلفة.")
    print("- ChatGPT API: منفصلة عن اشتراك ChatGPT وقد تُحاسب حسب الاستخدام؛ لا تُفعّل تلقائيًا.")
    print("- Gemini Flash: مزوّد Booda الافتراضي؛ يطلب مفتاحًا مخفيًا ويشترط تأكيد أن المشروع غير مربوط بالفوترة.")
    print("- Manus API: يحتاج مفتاح Manus؛ قبل تشغيله يجب مراجعة رصيد/تكلفة الحساب.")
    print("- الربط الفعلي لحسابات Meta وGoogle وTikTok يحتاج إعداد OAuth/صلاحيات من بوابات المطور الرسمية.")

