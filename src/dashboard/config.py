import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class Settings:
    guild_id: int
    public_url: str
    client_id: str
    client_secret: str
    bot_token: str
    database_url: str
    officer_roles: set[str] = field(default_factory=set)
    visible_roles: set[str] = field(default_factory=set)
    aion_enabled: bool = False
    secure_cookie: bool = True
    refresh_seconds: int = 21600
    refresh_cooldown: int = 600
    membership_seconds: int = 60
    session_hours: int = 24

    @property
    def callback_url(self):
        return self.public_url + '/auth/discord/callback'

    @classmethod
    def from_env(cls):
        from dotenv import load_dotenv
        load_dotenv()
        load_dotenv('.env.dashboard', override=True)
        url = os.getenv('DASHBOARD_URL', 'http://localhost:8000').rstrip('/')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username is not None or parsed.password is not None:
            raise ValueError('DASHBOARD_URL must be an origin, without a path or credentials')
        if parsed.scheme != 'https' and parsed.hostname not in ('localhost', '127.0.0.1'):
            raise ValueError('A hosted dashboard requires HTTPS')
        guild = os.getenv('DASHBOARD_GUILD_ID') or os.getenv('DISCORD_GUILD_ID', '')
        required = {
            'guild_id': guild, 'client_id': os.getenv('DISCORD_CLIENT_ID', ''),
            'client_secret': os.getenv('DISCORD_CLIENT_SECRET', ''),
            'bot_token': os.getenv('DISCORD_BOT_TOKEN', ''),
            'database_url': os.getenv('DATABASE_URL', ''),
        }
        if not all(required.values()):
            raise ValueError('Set DATABASE_URL, DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_BOT_TOKEN and DASHBOARD_GUILD_ID')
        required['guild_id'] = int(guild)
        return cls(**required, public_url=url,
                   officer_roles=set(filter(None, os.getenv('DASHBOARD_OFFICER_ROLE_IDS', '').replace(' ', '').split(','))),
                   visible_roles=set(filter(None, os.getenv('DASHBOARD_VISIBLE_ROLE_IDS', '').replace(' ', '').split(','))),
                   aion_enabled=os.getenv('AION2_IMPORTS_ENABLED', 'false').lower() == 'true',
                   secure_cookie=parsed.scheme == 'https')
