"""Read-only Meta Ads and Google Ads reporting API adapters.

Credentials are accepted per invocation and never written to Booda state.
Only campaign performance fields are requested; no campaign mutation endpoints
exist in this module.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class AdPlatformError(RuntimeError):
    """Safe-to-display API setup or read failure."""


def _http_json(url, *, method="GET", headers=None, body=None, opener=urlopen):
    request = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with opener(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        # Never echo request URLs or response payloads, which can contain tokens.
        raise AdPlatformError(f"The advertising platform rejected the read request (HTTP {error.code}).") from None
    except (URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", None)
        label = "network connection failed" if reason else "request failed"
        raise AdPlatformError(f"Advertising platform {label}.") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AdPlatformError("Advertising platform returned an unreadable response.") from None


def _required(value, name):
    if not isinstance(value, str) or not value.strip():
        raise AdPlatformError(f"{name} is required.")
    return value.strip()


def _validate_period(start, end):
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except (TypeError, ValueError):
        raise AdPlatformError("Enter the reporting dates as YYYY-MM-DD.") from None
    if start_date > end_date:
        raise AdPlatformError("The reporting start date must not be after its end date.")


def _decimal_or_zero(value):
    if value in (None, ""):
        return Decimal(0)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise AdPlatformError("The API returned a metric in an unexpected format.") from None
    if not result.is_finite() or result < 0:
        raise AdPlatformError("The API returned a negative or invalid metric.")
    return result


class MetaAdsReadOnlyConnector:
    """Read Meta campaign insights with a user-supplied ads_read token."""

    def __init__(self, *, opener=urlopen, version=None):
        self.opener = opener
        self.version = (version or os.getenv("BOODA_META_GRAPH_VERSION") or "v26.0").strip()

    def fetch_campaigns(self, *, account_id, access_token, period_start,
                        period_end, conversion_action_type=None):
        account_id = _required(account_id, "Meta ad account ID")
        token = _required(access_token, "Meta access token")
        account_id = account_id.removeprefix("act_").replace("-", "")
        if not account_id.isdigit():
            raise AdPlatformError("Meta ad account ID should contain digits only.")
        if not self.version.startswith("v") or not self.version[1:].replace(".", "").isdigit():
            raise AdPlatformError("Meta Graph API version is invalid.")
        _validate_period(period_start, period_end)
        base = f"https://graph.facebook.com/{self.version}"
        headers = {"Authorization": f"Bearer {token}"}
        account = _http_json(
            f"{base}/act_{account_id}?" + urlencode({"fields": "name,currency"}),
            headers=headers, opener=self.opener,
        )
        currency = _required(account.get("currency"), "Meta account currency").upper()
        fields = "campaign_id,campaign_name,objective,spend,impressions,inline_link_clicks,actions,action_values"
        params = urlencode({
            "level": "campaign",
            "time_range": json.dumps({"since": period_start, "until": period_end}),
            "fields": fields,
            "limit": 500,
        })
        url = f"{base}/act_{account_id}/insights?{params}"
        records = []
        for _ in range(100):
            page = _http_json(url, headers=headers, opener=self.opener)
            for row in page.get("data", []):
                conversions = revenue = None
                if conversion_action_type:
                    action = conversion_action_type.strip()
                    conversions = sum(
                        (_decimal_or_zero(item.get("value")) for item in row.get("actions", [])
                         if item.get("action_type") == action), Decimal(0),
                    )
                    revenue = sum(
                        (_decimal_or_zero(item.get("value")) for item in row.get("action_values", [])
                         if item.get("action_type") == action), Decimal(0),
                    )
                records.append({
                    "campaign_id": str(row.get("campaign_id") or row.get("campaign_name") or ""),
                    "campaign_name": row.get("campaign_name") or "Unnamed Meta campaign",
                    "platform": "Meta Ads",
                    "objective": row.get("objective") or "Not provided by Meta",
                    "period_start": period_start,
                    "period_end": period_end,
                    "currency": currency,
                    "spend": _decimal_or_zero(row.get("spend")),
                    "impressions": int(_decimal_or_zero(row.get("impressions"))),
                    "clicks": int(_decimal_or_zero(row.get("inline_link_clicks"))),
                    "conversions": conversions,
                    "revenue": revenue,
                    "source_notes": ([] if conversion_action_type else [
                        "لم يُحدد نوع التحويل في Meta؛ لم تُستخدم قيم التحويل أو الإيراد في الحسابات."
                    ]),
                })
            paging = page.get("paging", {})
            cursor = paging.get("cursors", {}).get("after")
            if not cursor or not paging.get("next"):
                break
            url = f"{base}/act_{account_id}/insights?{params}&" + urlencode({"after": cursor})
        else:
            raise AdPlatformError("Meta report exceeded the safe page limit; narrow the date range and retry.")
        return {"account_name": account.get("name", "Meta ad account"), "currency": currency, "campaigns": records}


class GoogleAdsReadOnlyConnector:
    """Read Google Ads campaign metrics using OAuth refresh and developer tokens."""

    API_VERSION = "v25"
    OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
    API_BASE = "https://googleads.googleapis.com"

    def __init__(self, *, opener=urlopen, api_version=None):
        self.opener = opener
        self.api_version = api_version or self.API_VERSION

    def fetch_campaigns(self, *, customer_id, developer_token, client_id,
                        client_secret, refresh_token, period_start, period_end,
                        login_customer_id=None):
        values = {
            "Google Ads customer ID": customer_id,
            "Google Ads developer token": developer_token,
            "Google OAuth client ID": client_id,
            "Google OAuth client secret": client_secret,
            "Google OAuth refresh token": refresh_token,
        }
        values = {key: _required(value, key) for key, value in values.items()}
        customer_id = values["Google Ads customer ID"].replace("-", "")
        if not customer_id.isdigit():
            raise AdPlatformError("Google Ads customer ID should contain digits only.")
        _validate_period(period_start, period_end)
        token_body = urlencode({
            "grant_type": "refresh_token",
            "client_id": values["Google OAuth client ID"],
            "client_secret": values["Google OAuth client secret"],
            "refresh_token": values["Google OAuth refresh token"],
        }).encode("ascii")
        token_response = _http_json(
            self.OAUTH_TOKEN_URL, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=token_body, opener=self.opener,
        )
        access_token = _required(token_response.get("access_token"), "Google OAuth access token")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": values["Google Ads developer token"],
            "Content-Type": "application/json",
        }
        if login_customer_id:
            headers["login-customer-id"] = login_customer_id.replace("-", "")
        query = (
            "SELECT campaign.id, campaign.name, campaign.advertising_channel_type, "
            "metrics.cost_micros, metrics.impressions, metrics.clicks, "
            "metrics.conversions, metrics.conversions_value "
            "FROM campaign "
            f"WHERE segments.date BETWEEN '{period_start}' AND '{period_end}' "
            "AND campaign.status != 'REMOVED'"
        )
        url = f"{self.API_BASE}/{self.api_version}/customers/{customer_id}/googleAds:search"
        body = {"query": query, "pageSize": 10000}
        campaigns = []
        for _ in range(100):
            page = _http_json(
                url, method="POST", headers=headers,
                body=json.dumps(body).encode("utf-8"), opener=self.opener,
            )
            for item in page.get("results", []):
                campaign = item.get("campaign", {})
                metrics = item.get("metrics", {})
                cost = _decimal_or_zero(metrics.get("costMicros")) / Decimal(1_000_000)
                campaigns.append({
                    "campaign_id": str(campaign.get("id") or campaign.get("name") or ""),
                    "campaign_name": campaign.get("name") or "Unnamed Google campaign",
                    "platform": "Google Ads",
                    "objective": campaign.get("advertisingChannelType") or "Not provided by Google",
                    "period_start": period_start,
                    "period_end": period_end,
                    "currency": None,  # caller obtains currency from account settings.
                    "spend": cost,
                    "impressions": int(_decimal_or_zero(metrics.get("impressions"))),
                    "clicks": int(_decimal_or_zero(metrics.get("clicks"))),
                    "conversions": _decimal_or_zero(metrics.get("conversions")),
                    "revenue": _decimal_or_zero(metrics.get("conversionsValue")),
                    "source_notes": [
                        "تُقرأ قيمة التحويل حسب إعدادات التحويل والإسناد في Google Ads."
                    ],
                })
            page_token = page.get("nextPageToken")
            if not page_token:
                break
            body["pageToken"] = page_token
        else:
            raise AdPlatformError("Google Ads report exceeded the safe page limit; narrow the date range and retry.")
        currency = self._fetch_currency(customer_id, headers)
        for row in campaigns:
            row["currency"] = currency
        return {"account_name": customer_id, "currency": currency, "campaigns": campaigns}

    def _fetch_currency(self, customer_id, headers):
        url = f"{self.API_BASE}/{self.api_version}/customers/{customer_id}/googleAds:search"
        page = _http_json(
            url, method="POST", headers=headers,
            body=json.dumps({"query": "SELECT customer.currency_code FROM customer"}).encode("utf-8"),
            opener=self.opener,
        )
        results = page.get("results", [])
        if not results:
            raise AdPlatformError("Google Ads did not return the account currency.")
        currency = results[0].get("customer", {}).get("currencyCode")
        return _required(currency, "Google Ads account currency").upper()


class YouTubeReadOnlyConnector:
    """Read public YouTube channel metadata; each channels.list costs 1 quota unit."""

    API_URL = "https://www.googleapis.com/youtube/v3/channels"

    def __init__(self, *, opener=urlopen):
        self.opener = opener

    def fetch_channel(self, *, api_key, channel_id=None, handle=None):
        api_key = _required(api_key, "YouTube Data API key")
        if bool(channel_id) == bool(handle):
            raise AdPlatformError("Provide exactly one YouTube channel ID or handle.")
        params = {"part": "snippet,statistics", "key": api_key}
        params["id" if channel_id else "forHandle"] = _required(channel_id or handle, "YouTube channel")
        payload = _http_json(f"{self.API_URL}?{urlencode(params)}", opener=self.opener)
        items = payload.get("items", [])
        if not items:
            raise AdPlatformError("YouTube did not return a channel; check its ID or handle and API key.")
        item = items[0]
        snippet, stats = item.get("snippet", {}), item.get("statistics", {})
        return {
            "id": item.get("id"), "title": snippet.get("title"),
            "description": snippet.get("description"),
            "published_at": snippet.get("publishedAt"),
            "view_count": _decimal_or_zero(stats.get("viewCount")),
            "subscriber_count": (None if stats.get("hiddenSubscriberCount") else
                                 _decimal_or_zero(stats.get("subscriberCount"))),
            "video_count": _decimal_or_zero(stats.get("videoCount")),
            "url": f"https://www.youtube.com/channel/{item.get('id', '')}",
        }


class TikTokReadOnlyConnector:
    """Read the authorized TikTok user's public video metadata (video.list scope)."""

    API_URL = "https://open.tiktokapis.com/v2/video/list/"
    FIELDS = "id,title,video_description,create_time,view_count,like_count,comment_count,share_count"

    def __init__(self, *, opener=urlopen):
        self.opener = opener

    def fetch_videos(self, *, access_token, max_count=20):
        token = _required(access_token, "TikTok access token")
        try:
            count = int(max_count)
        except (TypeError, ValueError):
            raise AdPlatformError("TikTok video count must be from 1 to 20.") from None
        if not 1 <= count <= 20:
            raise AdPlatformError("TikTok video count must be from 1 to 20.")
        url = f"{self.API_URL}?{urlencode({'fields': self.FIELDS})}"
        result = _http_json(
            url, method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            body=json.dumps({"max_count": count}).encode("utf-8"), opener=self.opener,
        )
        error = result.get("error", {})
        if error and error.get("code") not in (None, "ok"):
            raise AdPlatformError("TikTok rejected the read request; verify consent and video.list access.")
        data = result.get("data", {})
        return data.get("videos", []), data.get("cursor")
