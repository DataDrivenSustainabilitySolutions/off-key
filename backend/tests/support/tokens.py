"""Access tokens for tests, issued through the production claim contract."""

from off_key_core.auth.tokens import AccessClaims, issue_access_token


def access_token(user, *, session_version=None) -> str:
    return issue_access_token(
        AccessClaims(
            sub=user.email,
            user_id=user.id,
            session_version=(
                user.session_version if session_version is None else session_version
            ),
        )
    )
