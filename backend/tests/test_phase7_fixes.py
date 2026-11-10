"""Regression tests for the bugs found in the 10 November 2026 live audit. Runs after Phases 1-6."""
from app.services import datagen, reuse
from app.services.testing import numbers_in, rule_check

ADMIN = "registry.admin@registry.gov.example"
HR_OFFICER, HR_APPROVER = "daniel.okafor@hrl.gov.example", "noura.alketbi@hrl.gov.example"
HR_SECURITY = "saeed.almarri@hrl.gov.example"


# ───────────── rule checks ─────────────

def test_numbers_are_read_with_spaces_and_joined_hyphens():
    assert 1316.0 in numbers_in("Total: 1 316 accidents")
    assert 1316.0 in numbers_in("Total: 1 316 accidents")
    assert numbers_in("Dubai-1316") == {1316.0}
    assert numbers_in("2024-2025: 80,352.") == {2024.0, 2025.0, 80352.0}
    assert numbers_in("a change of -5 points") == {-5.0}
    assert 2025316.0 not in numbers_in("in 2025 316 accidents")  # a year is not a thousands group


def test_a_short_required_word_must_stand_on_its_own():
    disclosure = {"must_include_any": [["AI", "artificial intelligence", "automated"], ["officer", "human", "person"]]}
    assert rule_check("Please file a complaint by email; an officer will reply.", disclosure)  # 'ai' inside other words
    assert rule_check("I am an AI assistant. An officer makes the decision.", disclosure) == []
    assert rule_check("AI's answers are checked by a human.", disclosure) == []
    assert rule_check("Officers decide.", {"must_include": ["officer"]}) == []  # longer words still match inside plurals


def test_the_absent_row_case_is_also_read_by_the_judge():
    rows = [{"Emirate": e, "Type": t, "Count": 100 * i + j} for i, e in enumerate(["Dubai", "Sharjah", "Ajman"], 1)
            for j, t in enumerate(["Collision", "Run-over", "Rollover"], 1)]
    drafts = datagen.generate({"title": "T", "publisher": "P", "rows": rows, "measure": "Count", "dimensions": ["Emirate", "Type"],
                               "checksum": "abc"}, ["en"])
    absent = next(d for d in drafts if d.kind == "absent")
    assert "rubric" in absent.expected and absent.expected["must_include_any"]


# ───────────── reuse: seeded history is never evidence for a real model ─────────────

def test_seeded_history_is_not_reused_with_a_real_model():
    context = reuse.Context(use_case_id=1, audience_type="internal", data_sensitivity="internal", vulnerable_users=False,
                            risk_tier="low", thresholds={})
    source = reuse.Source(assessment_id=1, reference="ASM-2026-0001", department="HRL", use_case_title="Summariser", status="approved",
                          model_version_id=7, version="2.0", context=context, synthetic=True,
                          checks={"hallucination": reuse.SourceCheck(status="passed", score=0.96, origin_assessment_id=1)})
    target = reuse.Context(use_case_id=2, audience_type="internal", data_sensitivity="internal", vulnerable_users=False,
                           risk_tier="low", thresholds={})
    mock = reuse.evaluate(target, 7, "2.0", ["hallucination"], source)
    assert mock["outcome"] != "blocked" and mock["reused_checks"] == ["hallucination"]
    live = reuse.evaluate(target, 7, "2.0", ["hallucination"], source, allow_synthetic=False)
    assert live["outcome"] == "blocked" and live["reasons"][0]["rule"] == "R11" and live["rerun_checks"] == ["hallucination"]
    source.synthetic = False  # an assessment really run in this system stays reusable
    assert reuse.evaluate(target, 7, "2.0", ["hallucination"], source, allow_synthetic=False)["outcome"] != "blocked"


# ───────────── who may write provider evidence ─────────────

def test_an_officer_cannot_write_provider_evidence(client, login):
    body = dict(status="verified", value={"in_country_option": True, "contractual_commitment": True}, note="Trying to verify it myself.")
    assert client.put("/models/waha-70b/versions/3.3/evidence/data_residency", headers=login(HR_OFFICER), json=body).status_code == 403
    assert client.post("/models/waha-70b/versions", headers=login(HR_OFFICER), json={"version": "9.9"}).status_code == 403
    before = client.get("/models/waha-70b/versions/3.3/evidence/summary", headers=login(HR_OFFICER)).json()["counts"]
    assert client.put("/models/waha-70b/versions/3.3/evidence/pricing", headers=login(HR_SECURITY),
                      json=dict(status="claimed", value={}, note="Read the provider's price page.")).status_code == 200
    assert sum(before.values()) == sum(client.get("/models/waha-70b/versions/3.3/evidence/summary",
                                                  headers=login(HR_OFFICER)).json()["counts"].values())


# ───────────── small endpoint fixes ─────────────

def test_scenario_key_is_not_case_sensitive(client, login):
    refused = client.post("/scenarios/E/run", headers=login(HR_OFFICER))
    assert refused.status_code == 403 and "registry administrator" in refused.json()["detail"]


def test_an_impossible_data_source_id_is_not_found(client, login):
    assert client.get("/data-sources/99999999999999999999", headers=login(HR_OFFICER)).status_code == 404


# ───────────── lifecycle ─────────────

def test_a_second_scan_does_not_repeat_open_alerts(client, login):
    admin = login(ADMIN)
    client.post("/lifecycle/scan", headers=admin)
    first = len(client.get("/alerts?status=open", headers=admin).json())
    assert client.post("/lifecycle/scan", headers=admin).status_code == 200
    assert len(client.get("/alerts?status=open", headers=admin).json()) == first


def test_quarterly_check_does_not_clear_a_provider_terms_change(client, login):
    admin = login(ADMIN)
    client.post("/lifecycle/quarterly-check", headers=admin)
    changed = client.post("/lifecycle/events", headers=admin, json={
        "trigger_type": "provider_terms_change", "model_slug": "sahab-flash",
        "description": "The provider now trains on customer data by default."})
    assert changed.status_code == 201 and changed.json()["alerts"]
    affected = {a["deployment_id"] for a in client.get("/alerts?status=open", headers=admin).json() if a["id"] in changed.json()["alerts"]}
    result = client.post("/lifecycle/quarterly-check", headers=admin).json()["results"]
    held = [r for r in result if r["deployment_id"] in affected]
    assert held and all(r["after"] != "compliant" and r["status"] != "active" for r in held)
    rows = {d["deployment_id"]: d for d in client.get("/metrics", headers=admin).json()["compliance"]["per_deployment"]}
    assert all(rows[i]["compliance_status"] != "compliant" for i in affected)
