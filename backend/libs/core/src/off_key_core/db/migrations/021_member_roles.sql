-- Roles bundle the permissions the application defines, and each member holds
-- one. 'admin' holds every permission and 'user' none, so every member keeps
-- exactly the access their former role gave them. Repeatable, so a database
-- that already has the table is left as it is.
CREATE TABLE IF NOT EXISTS member_roles (
    id text PRIMARY KEY,
    name text NOT NULL,
    permissions text[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_member_role_id CHECK (id ~ '^[a-z][a-z0-9-]{1,39}$')
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_member_roles_name_lower
    ON member_roles (lower(name));
INSERT INTO member_roles (id, name) VALUES
    ('admin', 'Administrator'),
    ('user', 'Member')
ON CONFLICT (id) DO NOTHING;
ALTER TABLE users ALTER COLUMN role TYPE text USING role::text;
DROP TYPE IF EXISTS roleenum;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'users'::regclass AND conname = 'users_role_fkey'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT users_role_fkey
            FOREIGN KEY (role) REFERENCES member_roles (id);
    END IF;
END $$;
