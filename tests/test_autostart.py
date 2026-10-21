import pytest
import httpx

from xsecondbrain import autostart


def test_existing_service_is_not_restarted(monkeypatch):
    monkeypatch.setattr(autostart, 'running', lambda _: {'pid': 123})
    monkeypatch.setattr(autostart, 'start', lambda *a, **k: pytest.fail('duplicate start'))
    assert not autostart.ensure_service(object())


def test_disconnected_service_is_started_without_browser(monkeypatch):
    calls = []
    settings = object()
    monkeypatch.setattr(autostart, 'running', lambda _: None)
    monkeypatch.setattr(autostart, 'start', lambda *a, **k: calls.append((a, k)))
    assert autostart.ensure_service(settings)
    assert calls == [((settings,), {'setup': False, 'engine': 'codex'})]


def test_timeout_does_not_spawn_another_service(monkeypatch):
    def timeout(_):
        raise httpx.ReadTimeout('busy service')
    monkeypatch.setattr(autostart, 'running', timeout)
    monkeypatch.setattr(autostart, 'start', lambda *a, **k: pytest.fail('duplicate start'))
    with pytest.raises(httpx.ReadTimeout):
        autostart.ensure_service(object())
