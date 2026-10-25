from fastapi import HTTPException
from fastapi.testclient import TestClient
from src.dashboard.app import create_app
from src.dashboard.config import Settings
from src.dashboard.repository import Conflict


class Repo:
    def __init__(self):
        self.calls=[];self.valid_state=True;self.authenticated=True;self.links={}
    async def session(self,token):
        return {'user_id':9007199254740993,'csrf':'csrf-test'} if token=='valid' and self.authenticated else None
    async def rate(self,*args): return True
    async def state(self,token): self.state_token=token
    async def consume_state(self,token):
        valid=self.valid_state;self.valid_state=False;return valid
    async def create_session(self,*args): return 'new-session'
    async def logout(self,*args): self.authenticated=False
    async def roster(self,*args): return {'items':[],'total':0}
    async def profile(self,uid,balances=False):
        self.calls.append(('profile',uid,balances));return {'user_id':uid,'characters':[]}
    async def link(self,*args):
        self.calls.append(('link',args));return '1'
    async def change_link(self,*args,**kwargs): self.calls.append(('change',args))
    async def confirm(self,*args): self.calls.append(('confirm',args))
    async def queue_refresh(self,*args): self.calls.append(('refresh',args))


class Discord:
    def __init__(self): self.allowed=True;self.officer=False;self.fresh_officer=None
    def authorize_url(self,state): return 'https://discord.com/oauth2/authorize?state='+state
    async def member(self,uid,fresh=False):
        if not self.allowed: raise HTTPException(403,'Company server membership is required')
        officer=self.fresh_officer if fresh and self.fresh_officer is not None else self.officer
        return {'user_id':str(uid),'display_name':'Test','is_officer':officer,'avatar_url':None,'roles':[]}
    async def exchange(self,code): return {'id':'9007199254740993'}


def setup(imports=False):
    settings=Settings(1,'https://company.test','client','secret','bot','postgresql://test',aion_enabled=imports)
    repo,discord=Repo(),Discord()
    return create_app(settings,repo,discord,None),repo,discord


HEADERS={'Origin':'https://company.test','X-CSRF-Token':'csrf-test'}


def test_unauthenticated_and_nonmembers_rejected():
    app,repo,discord=setup()
    with TestClient(app) as client:
        assert client.get('/api/v1/members').status_code==401
        client.cookies.set('company_session','valid')
        discord.allowed=False
        assert client.get('/api/v1/members').status_code==403


def test_csrf_and_officer_role_rechecks():
    app,repo,discord=setup()
    with TestClient(app) as client:
        client.cookies.set('company_session','valid')
        path='/api/v1/character-links/1/confirm'
        assert client.post(path).status_code==403
        assert client.post(path,headers={**HEADERS,'Origin':'https://evil.test'}).status_code==403
        assert client.post(path,headers=HEADERS).status_code==403
        discord.officer=True;discord.fresh_officer=False
        assert client.post(path,headers=HEADERS).status_code==403
        discord.fresh_officer=True
        assert client.post(path,headers=HEADERS).status_code==200
        assert repo.calls==[('confirm',('9007199254740993',1))]


def test_balance_privacy_and_id_precision():
    app,repo,discord=setup()
    with TestClient(app) as client:
        client.cookies.set('company_session','valid')
        assert client.get('/api/v1/me').json()['user_id']=='9007199254740993'
        client.get('/api/v1/members/9007199254740993')
        client.get('/api/v1/members/9007199254740994')
        assert repo.calls[-2:]==[('profile','9007199254740993',True),('profile','9007199254740994',False)]
        assert client.get('/api/v1/members/9999999999999999999').status_code==422


def test_oauth_state_cookie_and_one_time_use():
    app,repo,discord=setup()
    with TestClient(app,base_url='https://company.test') as client:
        result=client.get('/auth/discord',follow_redirects=False)
        assert result.status_code==303
        token=repo.state_token
        assert client.get('/auth/discord/callback?code=x&state=wrong').status_code==400
        result=client.get('/auth/discord/callback?code=x&state='+token,follow_redirects=False)
        assert result.status_code==303
        assert 'HttpOnly' in result.headers['set-cookie']
        assert client.get('/auth/discord/callback?code=x&state='+token,follow_redirects=False).status_code==400


def test_manual_link_and_import_gate():
    app,repo,discord=setup()
    with TestClient(app) as client:
        client.cookies.set('company_session','valid')
        assert client.get('/api/v1/aion/search?region=nae&q=test').status_code==409
        body={'region':'nae','profile_url':'https://aion2.plaync.com/en-us/characters/detail?serverId=1&characterId=abc%3D&region=nae','name':'Test'}
        assert client.post('/api/v1/me/characters',json=body,headers=HEADERS).status_code==201
        args=repo.calls[-1][1]
        assert args[3]=='abc='
        assert args[5]=='manual'
        body['profile_url']='https://127.0.0.1/private'
        assert client.post('/api/v1/me/characters',json=body,headers=HEADERS).status_code==422


def test_logout_invalidates_session_and_security_headers():
    app,repo,discord=setup()
    with TestClient(app) as client:
        client.cookies.set('company_session','valid')
        result=client.post('/auth/logout',headers=HEADERS)
        assert result.status_code==200
        assert result.headers['cache-control']=='no-store'
        assert "frame-ancestors 'none'" in result.headers['content-security-policy']
        assert client.get('/api/v1/me').status_code==401
