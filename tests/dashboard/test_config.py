import pytest
from src.dashboard.config import Settings


@pytest.mark.parametrize('url', ['http://company.test','https://:secret@company.test','https://company.test/path','https://company.test?next=evil'])
def test_rejects_unsafe_public_origins(monkeypatch,url):
    import dotenv
    monkeypatch.setattr(dotenv,'load_dotenv',lambda *args,**kwargs:None)
    monkeypatch.setenv('DASHBOARD_URL',url)
    with pytest.raises(ValueError):
        Settings.from_env()


def test_localhost_can_use_http_but_hosted_sessions_require_secure_cookies(monkeypatch):
    import dotenv
    monkeypatch.setattr(dotenv,'load_dotenv',lambda *args,**kwargs:None)
    for key,value in {'DASHBOARD_GUILD_ID':'1','DISCORD_CLIENT_ID':'client','DISCORD_CLIENT_SECRET':'secret',
                      'DISCORD_BOT_TOKEN':'bot','DATABASE_URL':'postgresql://test'}.items():
        monkeypatch.setenv(key,value)
    monkeypatch.setenv('DASHBOARD_URL','http://localhost:8000')
    assert not Settings.from_env().secure_cookie
    monkeypatch.setenv('DASHBOARD_URL','https://company.test')
    assert Settings.from_env().secure_cookie
