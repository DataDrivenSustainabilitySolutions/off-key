"""Render Mosquitto password files from vaulted logins."""

import base64
import hashlib

# mosquitto_passwd's sha512-pbkdf2 format ($7$), which every Mosquitto 2 reads.
ITERATIONS = 1000


def mosquitto_password_file(logins):
    """Hash each {'username', 'password'} login into one password file line.

    The salt derives from the login itself, so the same vault renders the same
    file and the content-addressed secret only changes when a login changes.
    The file stays inside a Swarm secret readable by the broker alone.
    """
    lines = []
    for login in logins:
        username, password = login["username"], login["password"]
        if not username or ":" in username or "\n" in username:
            raise ValueError(
                "A Mosquitto username must be non-empty, without : or newlines"
            )
        salt = hashlib.sha512(
            f"off-key mosquitto\0{username}\0{password}".encode()
        ).digest()
        digest = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, ITERATIONS, 64)
        lines.append(
            f"{username}:$7${ITERATIONS}${base64.b64encode(salt).decode()}"
            f"${base64.b64encode(digest).decode()}\n"
        )
    return "".join(lines)


class FilterModule:
    def filters(self):
        return {"mosquitto_password_file": mosquitto_password_file}
