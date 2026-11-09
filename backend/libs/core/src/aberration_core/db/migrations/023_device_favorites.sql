-- Favorites name a catalogue device instead of the entity it is recorded
-- under. The collection bindings say which device each recorded entity
-- belongs to; a device without bindings records under 'entity-' and the
-- SHA-256 of its id. Entity favorites of a device in the saved catalogue
-- become device favorites with that id, and the rest are removed, such as
-- those of a broker's readings without a device. Repeatable.
ALTER TABLE member_favorites DROP CONSTRAINT IF EXISTS ck_member_favorite_kind;
WITH devices AS (
    SELECT item ->> 'id' AS id
    FROM system_configuration,
        jsonb_array_elements(
            CASE WHEN jsonb_typeof(document -> 'devices') = 'array'
                THEN document -> 'devices' ELSE '[]'::jsonb END
        ) AS item
), owners AS (
    SELECT binding ->> 'entity_id' AS entity_id, binding ->> 'device_id' AS device_id
    FROM system_collection_configuration,
        jsonb_each(
            CASE WHEN jsonb_typeof(document -> 'bindings') = 'object'
                THEN document -> 'bindings' ELSE '{}'::jsonb END
        ) AS bound (stream_id, binding)
    UNION
    SELECT 'entity-' || encode(sha256(convert_to(id, 'UTF8')), 'hex'), id
    FROM devices
)
INSERT INTO member_favorites (user_id, kind, item_id, created_at)
SELECT favorite.user_id, 'device', owners.device_id, min(favorite.created_at)
FROM member_favorites AS favorite
JOIN owners ON owners.entity_id = favorite.item_id
JOIN devices ON devices.id = owners.device_id
WHERE favorite.kind = 'entity'
GROUP BY favorite.user_id, owners.device_id
ON CONFLICT DO NOTHING;
DELETE FROM member_favorites WHERE kind = 'entity';
ALTER TABLE member_favorites ADD CONSTRAINT ck_member_favorite_kind
    CHECK (kind IN ('device', 'reading', 'monitor'));
