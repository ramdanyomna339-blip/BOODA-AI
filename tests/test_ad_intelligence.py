import pytest
import csv

from core.ad_intelligence import BoodaAdIntelligence
from core.ad_intelligence_cli import manage_ad_intelligence
from core.artifact_manager import BoodaArtifactManager
from core.event_log import BoodaEventLog


def record(manager, **overrides):
    values = {
        "campaign_id": "spring-sale",
        "campaign_name": "Spring Sale",
        "platform": "Meta",
        "objective": "Sales",
        "period_start": "2026-09-01",
        "period_end": "2026-09-07",
        "currency": "EGP",
        "spend": 100,
        "impressions": 10_000,
        "clicks": 200,
        "conversions": 10,
        "revenue": 500,
    }
    values.update(overrides)
    return manager.record_snapshot(**values)


def test_ad_analysis_calculates_metrics_and_assesses_only_explicit_targets(tmp_path):
    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    )
    result = record(manager, target_cpa=12, target_roas=4)

    assert result["metrics"] == {
        "ctr_percent": 2.0,
        "cpc": 0.5,
        "cpm": 10.0,
        "conversion_rate_percent": 5.0,
        "cpa": 10.0,
        "roas": 5.0,
    }
    assert result["assessment"] == {
        "status": "meets_explicit_targets",
        "checks": {
            "cpa": {"target": 12.0, "actual": 10.0, "met": True},
            "roas": {"target": 4.0, "actual": 5.0, "met": True},
        },
    }
    assert result["comparison"] is None
    report = tmp_path / "reports" / f"{result['snapshot_id']}.md"
    assert report.is_file()
    assert "لا تُستخدم معايير عامة" in report.read_text(encoding="utf-8")


def test_ad_analysis_does_not_call_campaign_a_success_without_target(tmp_path):
    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    )
    result = record(manager)

    assert result["assessment"]["status"] == "no_explicit_target"
    assert any("لا يمكن الحكم على النجاح" in signal for signal in result["signals"])
    assert result["hypotheses"] == []


def test_ad_analysis_marks_zero_conversion_causes_as_hypotheses(tmp_path):
    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    )
    result = record(manager, conversions=0, target_cpa=10)

    assert result["metrics"]["cpa"] is None
    assert result["assessment"]["status"] == "insufficient_data"
    assert "التتبع" in result["hypotheses"][0]
    assert "لا تحدد السبب" in result["hypotheses"][0]


def test_ad_analysis_compares_the_same_campaign_without_claiming_causation(tmp_path):
    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    )
    first = record(manager, spend=100, clicks=100, conversions=5, revenue=200)
    second = record(
        manager, spend=80, clicks=160, conversions=8, revenue=400,
        period_start="2026-09-08", period_end="2026-09-14",
    )

    assert second["comparison"]["snapshot_id"] == first["snapshot_id"]
    assert second["comparison"]["metrics"]["cpa"]["change"] == -10
    assert second["comparison"]["metrics"]["cpa"]["change_percent"] == -50
    assert "لا تثبت" in second["interpretation_limits"][1]
    report = (tmp_path / "reports" / f"{second['snapshot_id']}.md").read_text(encoding="utf-8")
    assert "مقارنة وصفية بالفترة السابقة" in report
    assert "2026-09-01" in report


def test_ad_analysis_rejects_invalid_period_currency_targets_and_counts(tmp_path):
    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    )

    with pytest.raises(ValueError, match="period_start"):
        record(manager, period_start="2026-09-08", period_end="2026-09-07")
    with pytest.raises(ValueError, match="three-letter"):
        record(manager, currency="EGP1")
    with pytest.raises(ValueError, match="clicks"):
        record(manager, clicks=-1)
    with pytest.raises(ValueError, match="target_roas"):
        record(manager, target_roas=float("nan"))


def test_ad_analysis_stays_local_and_registers_a_report_artifact(tmp_path):
    events = BoodaEventLog(tmp_path / "events.jsonl")
    artifacts = BoodaArtifactManager(
        tmp_path / "artifacts.json", event_log=events
    )
    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports",
        event_log=events, artifact_manager=artifacts,
    )
    result = record(manager)

    saved = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    ).get_snapshot(result["snapshot_id"])
    assert saved["inputs"]["spend"] == 100.0
    artifact = artifacts.list(kind="ad_analysis")[0]
    assert artifact["path"] == result["report_path"]
    assert artifact["metadata"]["scope"] == "local-only"
    event = events.get_events(entity_type="ad_campaign")[0]
    assert event["details"] == {
        "campaign_id": "spring-sale", "local_only": True,
    }
    assert "100.0" not in str(event["details"])


def test_ad_analysis_cli_records_a_snapshot_without_network(monkeypatch, tmp_path, capsys):
    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    )
    answers = iter([
        "spring-sale", "Spring Sale", "Meta", "Sales",
        "2026-09-01", "2026-09-07", "EGP", "100", "10000", "200",
        "10", "500", "12", "4", "",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    manage_ad_intelligence(manager)

    output = capsys.readouterr().out
    assert "معدل النقر CTR: 2.00%" in output
    assert "تحقق الأهداف المدخلة" in output
    assert len(manager.list_snapshots(campaign_id="spring-sale")) == 1


def test_ad_csv_template_imports_valid_rows_and_reports_bad_rows(tmp_path):
    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    )
    template = manager.write_csv_template(tmp_path / "import.csv")
    with template.open("a", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output)
        writer.writerow([
            "spring-sale", "Spring Sale", "Meta", "Sales", "2026-09-01",
            "2026-09-07", "EGP", "100", "10000", "200", "10", "500", "12", "4",
        ])
        writer.writerow([
            "bad", "Broken", "Meta", "Sales", "not-a-date", "2026-09-07",
            "EGP", "100", "10000", "200", "10", "500", "12", "4",
        ])

    result = manager.import_csv(template)

    assert len(result["imported"]) == 1
    assert result["imported"][0]["metrics"]["roas"] == 5
    assert result["errors"] == [{
        "row": 3,
        "error": "period_start must be an ISO date (YYYY-MM-DD).",
    }]


def test_ad_csv_import_rejects_missing_columns_and_export_round_trips(tmp_path):
    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    )
    bad_file = tmp_path / "bad.csv"
    bad_file.write_text("campaign_name,spend\nSale,10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        manager.import_csv(bad_file)

    record(manager)
    export_path = manager.export_csv(tmp_path / "export.csv")
    with export_path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 1
    assert rows[0]["campaign_id"] == "spring-sale"
    assert rows[0]["ctr_percent"] == "2.0"
    assert rows[0]["assessment"] == "no_explicit_target"


def test_ad_analysis_menu_can_return_without_mutating_state(monkeypatch, tmp_path):
    from core.ad_intelligence_cli import manage_ad_intelligence_menu

    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "0")

    manage_ad_intelligence_menu(manager)

    assert manager.list_snapshots() == []


def test_ad_import_reads_meta_ads_manager_columns_and_currency_from_header(tmp_path):
    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    )
    source = tmp_path / "meta.csv"
    source.write_text(
        "Reporting starts,Reporting ends,Campaign name,Amount spent (USD),"
        "Impressions,Link clicks,Results,Purchases conversion value\n"
        '2026-09-01,2026-09-07,Autumn Sale,"1,234.50",10000,250,12,5000\n',
        encoding="utf-8-sig",
    )

    result = manager.import_csv(source)

    assert result["errors"] == []
    snapshot = result["imported"][0]
    assert snapshot["platform"] == "Meta Ads"
    assert snapshot["currency"] == "USD"
    assert snapshot["inputs"]["spend"] == 1234.5
    assert snapshot["inputs"]["conversions"] == 12
    assert snapshot["inputs"]["revenue"] == 5000


def test_ad_import_reads_google_ads_daily_export_and_fractional_conversions(tmp_path):
    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    )
    source = tmp_path / "google.csv"
    source.write_text(
        "Campaign,Day,Cost,Impr.,Clicks,Conversions,Conv. value,Currency code\n"
        "Search Sale,2026-09-10,250.75,5000,125,3.5,1000,EGP\n",
        encoding="utf-8",
    )

    result = manager.import_csv(source)

    assert result["errors"] == []
    snapshot = result["imported"][0]
    assert snapshot["platform"] == "Google Ads"
    assert snapshot["period_start"] == snapshot["period_end"] == "2026-09-10"
    assert snapshot["inputs"]["conversions"] == 3.5
    assert snapshot["metrics"]["cpa"] == pytest.approx(71.6429)


def test_creative_review_reports_keyword_matches_without_claiming_quality(tmp_path):
    manager = BoodaAdIntelligence(
        tmp_path / "ads.json", output_dir=tmp_path / "reports"
    )
    result = record(
        manager,
        creative_text="خصم 20% على المنتج. اطلب الآن لتحصلي على نتيجة أفضل مع ضمان.",
    )

    review = result["creative_review"]
    assert review["checks"]["call_to_action"]["detected"] is True
    assert review["checks"]["offer"]["detected"] is True
    assert review["checks"]["benefit"]["detected"] is True
    assert review["checks"]["trust"]["detected"] is True
    assert review["word_count"] > 0
    assert "claims_to_review" in review["checks"]
    assert "لا يقيس الإقناع أو الأداء" in review["interpretation_limit"]
    report = (tmp_path / "reports" / f"{result['snapshot_id']}.md").read_text(encoding="utf-8")
    assert "مراجعة بنيوية لنص الإعلان" in report
