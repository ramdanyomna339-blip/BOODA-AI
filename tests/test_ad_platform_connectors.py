import json
from decimal import Decimal
from urllib.error import HTTPError

import pytest

from core.ad_platform_connectors import (
    AdPlatformError,
    GoogleAdsReadOnlyConnector,
    MetaAdsReadOnlyConnector,
    TikTokReadOnlyConnector,
    YouTubeReadOnlyConnector,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_meta_connector_reads_campaign_report_with_token_only_in_auth_header():
    requests = []
    responses = [
        {"name": "Booda Meta Account", "currency": "EGP"},
        {
            "data": [{
                "campaign_id": "campaign-1", "campaign_name": "Spring",
                "objective": "OUTCOME_SALES", "spend": "125.50",
                "impressions": "1000", "inline_link_clicks": "20",
                "actions": [
                    {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "2"},
                    {"action_type": "add_to_cart", "value": "4"},
                ],
                "action_values": [
                    {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "500"},
                ],
            }],
        },
    ]

    def opener(request, timeout):
        requests.append(request)
        assert timeout == 30
        return FakeResponse(responses.pop(0))

    result = MetaAdsReadOnlyConnector(opener=opener).fetch_campaigns(
        account_id="act_123456", access_token="secret-token",
        period_start="2026-09-01", period_end="2026-09-07",
        conversion_action_type="offsite_conversion.fb_pixel_purchase",
    )

    assert result["account_name"] == "Booda Meta Account"
    assert result["currency"] == "EGP"
    assert result["campaigns"][0]["conversions"] == Decimal("2")
    assert result["campaigns"][0]["revenue"] == Decimal("500")
    assert "secret-token" not in requests[0].full_url
    assert requests[0].get_header("Authorization") == "Bearer secret-token"
    assert "POST" not in {request.get_method() for request in requests}


def test_meta_connector_leaves_conversion_metrics_empty_without_action_selection():
    responses = [{"name": "Account", "currency": "USD"}, {"data": []}]
    connector = MetaAdsReadOnlyConnector(
        opener=lambda _request, timeout: FakeResponse(responses.pop(0))
    )

    result = connector.fetch_campaigns(
        account_id="123", access_token="token",
        period_start="2026-09-01", period_end="2026-09-02",
    )

    assert result["campaigns"] == []


def test_google_connector_refreshes_oauth_and_reads_only_campaign_metrics():
    requests = []
    responses = [
        {"access_token": "temporary-access-token"},
        {"results": [{
            "campaign": {"id": "42", "name": "Search", "advertisingChannelType": "SEARCH"},
            "metrics": {
                "costMicros": "12345678", "impressions": "1000",
                "clicks": "25", "conversions": "2.5", "conversionsValue": "60",
            },
        }]},
        {"results": [{"customer": {"currencyCode": "USD"}}]},
    ]

    def opener(request, timeout):
        requests.append(request)
        assert timeout == 30
        return FakeResponse(responses.pop(0))

    result = GoogleAdsReadOnlyConnector(opener=opener).fetch_campaigns(
        customer_id="123-456-7890", developer_token="developer-secret",
        client_id="client-id", client_secret="client-secret",
        refresh_token="refresh-secret", period_start="2026-09-01",
        period_end="2026-09-07", login_customer_id="999-999-9999",
    )

    campaign = result["campaigns"][0]
    assert result["currency"] == "USD"
    assert campaign["spend"] == Decimal("12.345678")
    assert campaign["conversions"] == Decimal("2.5")
    assert campaign["revenue"] == Decimal("60")
    assert requests[0].full_url == "https://oauth2.googleapis.com/token"
    assert requests[1].get_header("Developer-token") == "developer-secret"
    assert requests[1].get_header("Login-customer-id") == "9999999999"
    assert "temporary-access-token" not in requests[1].full_url
    assert "FROM campaign" in json.loads(requests[1].data)["query"]
    assert "FROM customer" in json.loads(requests[2].data)["query"]


def test_google_connector_returns_actionable_error_without_leaking_request_secret():
    def denied(_request, timeout):
        raise HTTPError(
            "https://example.invalid/?token=secret", 403, "Denied", {}, None
        )

    connector = GoogleAdsReadOnlyConnector(opener=denied)
    with pytest.raises(AdPlatformError) as raised:
        connector.fetch_campaigns(
            customer_id="123", developer_token="developer-secret",
            client_id="client", client_secret="secret",
            refresh_token="secret", period_start="2026-09-02",
            period_end="2026-09-07",
        )
    assert "secret" not in str(raised.value)
    assert "HTTP 403" in str(raised.value)


def test_connected_campaign_is_saved_without_any_access_token(tmp_path, monkeypatch):
    from core.ad_intelligence import BoodaAdIntelligence
    import core.ad_intelligence_cli as cli

    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    )
    values = iter(["6", "123456", "2026-09-01", "2026-09-07", "", "0"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(values))
    monkeypatch.setattr(cli, "getpass", lambda _prompt: "one-time-access-token")

    class FakeMetaConnector:
        def fetch_campaigns(self, **kwargs):
            assert kwargs["access_token"] == "one-time-access-token"
            return {
                "account_name": "Account",
                "campaigns": [{
                    "campaign_id": "c1", "campaign_name": "Sale",
                    "platform": "Meta Ads", "objective": "Sales",
                    "period_start": "2026-09-01", "period_end": "2026-09-07",
                    "currency": "EGP", "spend": 100,
                    "impressions": 1000, "clicks": 20,
                    "conversions": None, "revenue": None,
                    "source_notes": [],
                }],
            }

    monkeypatch.setattr(cli, "MetaAdsReadOnlyConnector", FakeMetaConnector)
    cli.manage_ad_intelligence_menu(manager)

    persisted = (tmp_path / "ads.json").read_text(encoding="utf-8")
    assert "one-time-access-token" not in persisted
    assert manager.list_snapshots()[0]["campaign_id"] == "c1"


def test_youtube_connector_reads_public_channel_with_key_in_query_only():
    requests = []

    def opener(request, timeout):
        requests.append(request)
        return FakeResponse({"items": [{
            "id": "UC123", "snippet": {"title": "Channel", "publishedAt": "2020-01-01"},
            "statistics": {"viewCount": "100", "subscriberCount": "12", "videoCount": "3"},
        }]})

    channel = YouTubeReadOnlyConnector(opener=opener).fetch_channel(
        api_key="private-api-key", handle="@channel",
    )
    assert channel["view_count"] == Decimal("100")
    assert channel["subscriber_count"] == Decimal("12")
    assert "private-api-key" in requests[0].full_url
    assert requests[0].get_method() == "GET"


def test_tiktok_connector_reads_only_authorized_videos_and_hides_token_from_url():
    requests = []

    def opener(request, timeout):
        requests.append(request)
        return FakeResponse({"data": {"videos": [{"id": "v1", "view_count": 123}]}, "error": {"code": "ok"}})

    videos, cursor = TikTokReadOnlyConnector(opener=opener).fetch_videos(access_token="private-token")
    assert videos == [{"id": "v1", "view_count": 123}]
    assert cursor is None
    assert requests[0].get_method() == "POST"
    assert requests[0].get_header("Authorization") == "Bearer private-token"
    assert "private-token" not in requests[0].full_url


def test_tiktok_rejects_out_of_range_count_without_request():
    connector = TikTokReadOnlyConnector(opener=lambda *_args, **_kwargs: pytest.fail("must not call API"))
    with pytest.raises(AdPlatformError, match="from 1 to 20"):
        connector.fetch_videos(access_token="token", max_count=21)
