-- Account emails are matched case-insensitively; stop instead of merging accounts.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM users GROUP BY lower(email) HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Accounts differ only by email letter case; merge them before upgrading';
    END IF;
END
$$;
UPDATE users SET email = lower(email) WHERE email <> lower(email);
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower ON users (lower(email));
