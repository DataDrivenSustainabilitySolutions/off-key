Try using the package manager uv (in requirements-dev.txt) instead of the standard 'pip'.

1. Install the requirements-dev.txt (`pip -r install requirements-dev.txt`)
2. Install the requirements.txt via pip (`uv pip sync requirements.txt`)

Reference: [Documentation](https://docs.astral.sh/uv/pip/compile/#upgrading-requirements)
