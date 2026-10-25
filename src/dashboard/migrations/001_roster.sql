CREATE TABLE member_profiles (
    guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
    display_name TEXT NOT NULL, avatar_url TEXT, roles JSONB NOT NULL DEFAULT '[]',
    preferences TEXT NOT NULL DEFAULT '', availability TEXT NOT NULL DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE aion_characters (
    id BIGSERIAL PRIMARY KEY, region TEXT NOT NULL, server_id INTEGER NOT NULL CHECK(server_id > 0),
    character_id TEXT NOT NULL, data JSONB NOT NULL DEFAULT '{}',
    source TEXT NOT NULL CHECK(source IN ('manual', 'imported')),
    last_success TIMESTAMPTZ, last_attempt TIMESTAMPTZ,
    refresh_status TEXT NOT NULL DEFAULT 'never_loaded',
    UNIQUE(region, server_id, character_id)
);
CREATE TABLE member_characters (
    id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
    character_id BIGINT NOT NULL REFERENCES aion_characters(id),
    is_main BOOLEAN NOT NULL DEFAULT FALSE,
    confirmed_by BIGINT, confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY(guild_id, user_id) REFERENCES member_profiles(guild_id, user_id),
    UNIQUE(guild_id, character_id)
);
CREATE UNIQUE INDEX one_main_per_member ON member_characters(guild_id,user_id) WHERE is_main;
CREATE INDEX member_links ON member_characters(guild_id,user_id);
CREATE TABLE character_snapshots (
    character_id BIGINT NOT NULL REFERENCES aion_characters(id) ON DELETE CASCADE,
    day DATE NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')::date,
    data JSONB NOT NULL, collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(character_id,day)
);
CREATE TABLE character_refresh_jobs (
    character_id BIGINT PRIMARY KEY REFERENCES aion_characters(id) ON DELETE CASCADE,
    next_attempt TIMESTAMPTZ NOT NULL DEFAULT now(), attempts INTEGER NOT NULL DEFAULT 0,
    lease_until TIMESTAMPTZ, lease_token TEXT
);
CREATE TABLE dashboard_sessions (
    token_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL,
    csrf TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE dashboard_oauth_states (
    token_hash TEXT PRIMARY KEY, expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE dashboard_audit_log (
    id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, actor_id BIGINT NOT NULL,
    action TEXT NOT NULL, details JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE dashboard_rate_limits (
    bucket TEXT PRIMARY KEY, window_start TIMESTAMPTZ NOT NULL DEFAULT now(),
    requests INTEGER NOT NULL DEFAULT 1
);
