import loki.cli as cli
from loki.engine.devices import suggest_device_names
from loki.models import IncidentReport


def test_suggest_device_names_matches_aliases():
    assert suggest_device_names("iphone15prp")[0] == "iphone-15-pro"
    assert suggest_device_names("pixl-7")[0] == "pixel-7"


def test_suggest_device_names_includes_playwright_catalog():
    devices = {"iPhone 14 Pro": {}}

    assert suggest_device_names("iphone14proo", devices)[0] == "iPhone 14 Pro"


def test_suggest_device_names_skips_known_aliases_and_unrelated_inputs():
    assert suggest_device_names("iphone-15-pro") == []
    assert suggest_device_names("zzzzzzzzzz") == []


def test_unknown_device_warning_includes_suggestions(monkeypatch):
    messages = []
    monkeypatch.setattr(cli.console, "print", messages.append)
    report = IncidentReport(target_url="http://localhost:8000")

    cli._print_attack_summary(report, requested_device="pixl-7")

    assert any("Did you mean: pixel-7" in str(message) for message in messages)
