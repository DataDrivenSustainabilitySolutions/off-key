-- Every browser sign-in now keeps a session; only one that chose "Remember
-- this device" keeps its cookie across browser restarts. Sessions made before
-- were all remembered ones.
ALTER TABLE remembered_sessions
    ADD COLUMN IF NOT EXISTS persistent boolean NOT NULL DEFAULT true;
