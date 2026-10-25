import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import pytest
from src.dashboard.aion import AionAdapter, AionError, identity, normalize_profile, parse_profile_url, profile_url, safe_image


def test_region_identity_and_url_roundtrip():
    for region in ['nae','naw','eu','sa','asia','kr','tw']:
        assert parse_profile_url(profile_url(region, 1001, 'abc='), region) == (region, 1001, 'abc=')
    assert identity('nae', 1001, 'abc%3D') == ('nae', 1001, 'abc=')
    assert parse_qs(urlsplit(profile_url('sa', 1001, 'abc=')).query)['region'] == ['la']


@pytest.mark.parametrize('url', [
    'http://aion2.plaync.com/en-us/characters/detail?serverId=1&characterId=a&region=nae',
    'https://aion2.plaync.com.evil.test/en-us/characters/detail?serverId=1&characterId=a&region=nae',
    'https://user@aion2.plaync.com/en-us/characters/detail?serverId=1&characterId=a&region=nae',
    'https://aion2.plaync.com/en-us/other?serverId=1&characterId=a&region=nae',
    'https://aion2.plaync.com/en-us/characters/detail?serverId=1&characterId=a&region=eu',
    'https://127.0.0.1/en-us/characters/detail?serverId=1&characterId=a&region=nae',
])
def test_rejects_arbitrary_urls_and_wrong_region(url):
    with pytest.raises(ValueError):
        parse_profile_url(url, 'nae')


def test_normalization_preserves_missing_values_and_checks_identity():
    raw = json.loads((Path(__file__).parent/'fixtures/character.json').read_text())
    data = normalize_profile(raw, 'nae', 1001, 'fixture-id=')
    assert data['combat_power'] == 175000
    assert data['item_level'] == 2400
    assert data['image_url'].startswith('https://profileimg.plaync.com/')
    del raw['profile']['combatPower']
    assert normalize_profile(raw, 'nae', 1001, 'fixture-id=')['combat_power'] is None
    with pytest.raises(AionError):
        normalize_profile(raw, 'nae', 1001, 'different')
    with pytest.raises(AionError):
        normalize_profile({}, 'nae', 1001, 'fixture-id=')


def test_image_allowlist():
    assert safe_image('javascript:alert(1)') is None
    assert safe_image('https://evil.test/p.png') is None
    assert safe_image('//evil.test/p.png', True) is None
    assert safe_image('https://assets.playnccdn.com/p.png') is not None


class Response:
    def __init__(self, status, body=b'{}', headers=None):
        self.status, self.body, self.headers = status, body, headers or {}
        self.content = self
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    async def read(self, limit): return self.body[:limit]


class HTTP:
    def __init__(self, response): self.response=response
    def get(self,*args,**kwargs):
        assert kwargs['allow_redirects'] is False
        return self.response


@pytest.mark.parametrize('response,kind', [
    (Response(429,headers={'Retry-After':'120'}),'throttled'),
    (Response(403),'source_unavailable'), (Response(404),'source_unavailable'),
    (Response(200,b'<html>blocked</html>'),'invalid_response'),
    (Response(200,b'[]'),'invalid_response'),
])
def test_upstream_errors_are_explicit(response,kind):
    async def run():
        with pytest.raises(AionError) as e:
            await AionAdapter(HTTP(response)).get('https://aion2.plaync.com/api/character/info',{})
        assert e.value.kind == kind
        if kind == 'throttled': assert e.value.retry_after == 120
    asyncio.run(run())


def test_equipment_failure_preserves_summary():
    class Adapter(AionAdapter):
        async def get(self,url,params):
            if url.endswith('equipment'): raise AionError()
            return {'profile':{'characterId':'abc','characterName':'Test'}}
    result=asyncio.run(Adapter(None).character('nae',1001,'abc'))
    assert result['name']=='Test'
    assert result['equipment_status']=='unavailable'
