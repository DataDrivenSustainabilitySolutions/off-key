-- Favorites point at an entity, a catalogue reading or a monitor. The former
-- table starred entities only: its rows move here as kind 'entity' and it is
-- dropped. Fresh databases never had it, hence the guard.
CREATE TABLE IF NOT EXISTS member_favorites (
    user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind text NOT NULL,
    item_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, kind, item_id),
    CONSTRAINT ck_member_favorite_kind
        CHECK (kind IN ('entity', 'reading', 'monitor'))
);
DO $$
BEGIN
    IF to_regclass('favorites') IS NOT NULL THEN
        INSERT INTO member_favorites (user_id, kind, item_id)
        SELECT DISTINCT user_id, 'entity', charger_id FROM favorites
        ON CONFLICT DO NOTHING;
        DROP TABLE favorites;
    END IF;
END $$;
