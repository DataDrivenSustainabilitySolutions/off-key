> [!WARNING]
> This page is **legacy / archived** and may be outdated.
> It is preserved for historical context only and is **not** the source of truth for current operations.
>
> Use current documentation instead:
- [Getting-Started](../getting-started.md)
- [Developer-Setup](../development/setup.md)
>
> You can also start from [Archive / Legacy Index](index.md).

---
# Setup Instructions

**Recommended Python Version:** `Python >= 3.12`

It is highly recommended to use Python 3.12 or newer for this project.

## Infrastructure Setup

Follow these steps to set up your development infrastructure:

1.  **Install Docker:**
    *   It is recommended to use Docker natively within the WSL (Ubuntu(. To install Docker this way, follow this [Gist](https://gist.github.com/dehsilvadeveloper/c3bdf0f4cdcc5c177e2fe9be671820c7). Alternatively, follow the official installation guide for your operating system: [Install Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) (Windows link provided, adapt for macOS/Linux if necessary).

2.  **Install uv (Python Package Installer):**
    *   Install `uv` using the Standalone Installer method: [uv Installation Guide](https://docs.astral.sh/uv/getting-started/installation/).

3.  **Install Yarn (JavaScript Package Manager):**
    *   Download Yarn: [Yarn v1.22.4 MSI (Windows)](https://github.com/yarnpkg/yarn/releases/download/v1.22.4/yarn-1.22.4.msi)
    *   For installation guidance, especially on Windows: [Yarn Installation Guide (Windows)](https://geekflare.com/dev/how-to-install-yarn-on-windows/).

4.  **Python Backend Environment Setup:**
    *   Navigate to your project's backend directory and use `uv` to sync dependencies (and optional dependencies if required):
        ```bash
        cd /your/project/root/backend
        uv sync
        uv sync --extra dev
        ```
    *   **Important:** Do **not** create the `.venv` using your IDE's automatic virtual environment creation tools. `uv sync` will handle this and create a `.venv` directory inside `/your/project/root/backend`.

    *   **IDE Configuration (after `uv sync`):**
        *   **PyCharm:**
            1.  Open your project settings to configure the Python interpreter.
            2.  Set a new interpreter (or modify an existing one) and select `existing environment`.
            3.  Point to the Python executable within the `.venv` directory created by `uv` (e.g., `/your/project/root/backend/.venv/bin/python` on Linux/macOS or `/your/project/root/backend/.venv/Scripts/python.exe` on Windows). Typically, PyCharm selects and existing `.venv` automatically.
            4.  Choose "Select Existing Interpreter" or the equivalent option.
        *   **Alternative (Symbolic Link):**
            To make the backend's virtual environment more accessible to tools or IDEs that expect a `.venv` in the project root, you can create a symbolic link.
            *   **Linux/macOS:**
                ```bash
                # Ensure you are in your project root: /your/project/root/
                # Replace /your/project/root/ with the actual absolute path to your project
                ln -s ./backend/.venv ./.venv
                ```
                _Example for a project named `off-key` in your home directory:_
                ```bash
                # cd ~/off-key
                # ln -s ./backend/.venv ./.venv
                ```
            *   **Windows (Command Prompt as Administrator):**
                Navigate to your project root (`/your/project/root/`) in an Administrator Command Prompt, then run:
                ```cmd
                mklink /D .venv backend\.venv
                ```

## Frontend Dependencies Setup

1.  **Navigate to the Frontend Directory:**
    ```bash
    cd /your/project/root/frontend
    # Or, if you are in the project root:
    # cd frontend
    ```

2.  **Install Dependencies:**
    Use Yarn to install the dependencies defined in `package.json`:
    ```bash
    yarn install
    ```
    (Alternatively, you can often just run `yarn`)

### Application Access

The different components of the application can be accessed after `docker-compose up --build`.
Keep in mind that `Docker Desktop` needs to be running for interacting with `Docker`.
- Access the `backend` (APIs) under `http://localhost:8000/`
  - Access the API documentation under `http://localhost:8000/docs`
- Access the `frontend` (UI) under `http://localhost:5173/`

## Setting Up Pre-Commit Hooks for Local Development

This guide outlines the steps to set up pre-commit hooks for this project in a new local development environment. Pre-commit hooks help ensure code quality and consistency by running checks before you commit your changes.

We use `uv` for managing Python environments and dependencies, and `pre-commit` for managing git hooks.

### Prerequisites

* **Git:** Ensure Git is installed on your system.
* **uv:** Ensure `uv` is installed. If not, you can find installation instructions at [https://github.com/astral-sh/uv](https://github.com/astral-sh/uv).
* **Project Code:** You should have the project code cloned to your local machine.

### Setup Steps

Follow these steps to install the necessary dependencies and activate the pre-commit hooks:

1.  **Navigate into the `./backend/` directory.**
    This is where the project's Python package and its main `pyproject.toml` are located.
    ```bash
    cd backend
    ```

2.  **Install project dependencies and development dependencies.**
    This command installs the main project dependencies and the development tools (like linters, formatters, and `pre-commit` itself) defined in `pyproject.toml`.
    ```bash
    uv pip install .
    uv pip install .[dev]
    ```
    * `uv pip install .` installs the core dependencies of the `off-key` project.
    * `uv pip install .[dev]` installs the optional dependencies specified under the `[project.optional-dependencies.dev]` section in the `pyproject.toml` file located in `./backend/`. This typically includes `pre-commit`, `black`, `ruff`, etc.

3.  **Install the pre-commit hooks.**
    This command installs the git hooks defined in the `.pre-commit-config.yml` file located in the project's root directory. It configures your local git repository to run the defined checks automatically before each commit.
    ```bash
    uv run pre-commit install --config ../.pre-commit-config.yml
    ```
    * `uv run pre-commit` executes the `pre-commit` tool within the environment managed by `uv`.
    * `install` is the `pre-commit` command to set up the hooks.
    * `--config ../.pre-commit-config.yml` specifies the path to the pre-commit configuration file, which is in the parent directory (the project root) relative to the `./backend/` directory.

### How it Works

Once installed, the pre-commit hooks will run automatically whenever you attempt to make a new commit using `git commit`.

* If any of the pre-commit checks fail (e.g., a linter finds an issue or a formatter needs to change a file), the commit will be aborted.
* You'll see output from the failing hook indicating what went wrong.
* Some hooks (like code formatters) might automatically fix the issues. If they do, you'll need to `git add` the modified files again and then re-attempt the commit.
* For other issues, you'll need to manually fix them before you can successfully commit.

### Updating Hooks

Occasionally, the pre-commit hook definitions or the tools they use might be updated. To update your local hooks to the latest versions defined in `.pre-commit-config.yml`, you can run:

```bash
# Navigate to the ./backend/ directory if you are not already there
cd path/to/your/project/backend/

# Then run the pre-commit update command
uv run pre-commit autoupdate --config ../.pre-commit-config.yml
