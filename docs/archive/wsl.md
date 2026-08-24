> [!WARNING]
> This page is **legacy / archived** and may be outdated.
> It is preserved for historical context only and is **not** the source of truth for current operations.
>
> Use current documentation instead:
- [Developer-Setup](../development/setup.md)
- [Deployment-Modes](../operations/deployment-modes.md)
>
> You can also start from [Archive / Legacy Index](index.md).

---
# WSL Mirrored Networking for Docker Swarm

This guide explains how to configure WSL mirrored networking mode to access Docker Swarm applications via `localhost` (127.0.0.1) instead of WSL's internal IP address.

## Prerequisites

- Windows 10/11 with WSL 2
- WSL version 2.0.0 or higher
- Docker installed in WSL

## Configuration Steps

### 1. Create .wslconfig File

Create a `.wslconfig` file in your Windows user directory:

**Location:** `C:\Users\<YourUsername>\.wslconfig`

**Content:**
```ini
[wsl2]
networkingMode=mirrored
```

### 2. Restart WSL

Shut down all WSL instances:

```powershell
wsl --shutdown
```

Start your WSL distribution again to apply the changes.

### 3. Verify Configuration

Your Docker Swarm services should now be accessible via:
- `http://localhost:<port>`
- `http://127.0.0.1:<port>`
