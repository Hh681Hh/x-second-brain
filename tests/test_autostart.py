import pytest
import httpx
from types import SimpleNamespace

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


def test_scheduler_codex_path_is_available_before_loading_settings(monkeypatch, tmp_path):
    environment = {}
    executable = r'C:\Users\测试 用户\Codex\bin\codex.exe'
    monkeypatch.setattr(autostart, 'os', SimpleNamespace(name='nt', environ=environment))

    def load_settings():
        assert environment['CODEX_BINARY'] == executable
        return SimpleNamespace(data_dir=tmp_path)

    monkeypatch.setattr(autostart.Settings, 'from_env', load_settings)
    # No enabled marker: stop before acquiring a Windows lock or spawning work.
    autostart.main(['--codex-binary', executable])


def test_default_start_preserves_configured_reader(monkeypatch, tmp_path):
    environment = {'CODEX_BINARY': 'configured-reader'}
    monkeypatch.setattr(autostart, 'os', SimpleNamespace(name='nt', environ=environment))
    monkeypatch.setattr(autostart.Settings, 'from_env', lambda: SimpleNamespace(data_dir=tmp_path))
    autostart.main([])
    assert environment['CODEX_BINARY'] == 'configured-reader'
