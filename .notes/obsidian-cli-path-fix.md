# Obsidian CLI — PATH Fix for VS Code / Git Bash Terminals

## The Problem

Obsidian v1.12+ ships with an official CLI. When you enable it in Obsidian's settings
(Settings → General → Command Line Interface → Register CLI), Obsidian registers itself
by adding its install directory to the **Windows user-level PATH environment variable**.

This works fine in the native Windows terminal (cmd.exe / PowerShell / Windows Terminal)
because those shells inherit the Windows PATH on startup.

**But it does NOT work in Git Bash terminals**, including:
- The integrated terminal inside VS Code (when using Git Bash)
- Any terminal spawned by Claude Code inside VS Code

### Why Git Bash Doesn't See It

Git Bash is a POSIX-emulation layer (MSYS2/MinGW). It reads its PATH from:
1. `/etc/profile` and `/etc/profile.d/` (system-wide Git Bash config)
2. `~/.bash_profile` or `~/.bashrc` (user Git Bash config)

It does **not** automatically read the Windows user-level PATH registry entry that
Obsidian wrote to. So `obsidian version` works in cmd.exe but fails with
`command not found` in Git Bash.

---

## What Was Done to Fix It

### Step 1 — Located the Obsidian binary

The Windows user PATH showed Obsidian registered at:
```
C:\Program Files\Obsidian
```

Inspecting that directory confirmed the main executable is `Obsidian.exe`, and it
doubles as the CLI binary — passing `version` as an argument returns the version string:
```
Obsidian.exe version   →   1.12.7 (installer 1.12.7)
```

### Step 2 — Added the path to `~/.bashrc`

The Git Bash user config file is `~/.bashrc` (`C:\Users\danie\.bashrc` on Windows).
The following line was appended:

```bash
export PATH="$PATH:/c/Program Files/Obsidian"
```

Git Bash maps Windows drive paths using POSIX notation: `C:\` → `/c/`.

### Step 3 — Verified in the current session

To apply the change without reopening the terminal, the PATH was exported directly
in the running session:

```bash
export PATH="$PATH:/c/Program Files/Obsidian"
obsidian version
# → 1.12.7 (installer 1.12.7)
```

---

## How to Verify the Fix in a New Terminal

Open any Git Bash terminal (including VS Code integrated terminal) and run:

```bash
obsidian version
```

Expected output:
```
1.12.7 (installer 1.12.7)
```

If it still fails in VS Code, check that VS Code is using Git Bash as its terminal shell:
- `Ctrl+Shift+P` → "Terminal: Select Default Profile" → Git Bash

---

## Why `~/.bashrc` and Not Somewhere Else

| File | When it runs |
|---|---|
| `~/.bash_profile` | Login shells only (SSH, some terminal apps) |
| `~/.bashrc` | Every interactive non-login shell — this is what VS Code uses |
| `/etc/profile.d/*.sh` | System-wide, requires admin access |

`~/.bashrc` is the right place for user-level PATH additions that need to be visible
in VS Code's integrated terminal.

---

## Current State of `~/.bashrc`

```bash
export PATH="$PATH:/c/Program Files/Obsidian"
```

---

## Related: Obsidian CLI Setup

The CLI was enabled in Obsidian via:
> Settings → General → Command Line Interface → toggle ON → click "Register CLI"

Obsidian version: **1.12.7**

Next step (not yet done): install kepano's official Claude Code skill files so Claude Code
knows all the Obsidian CLI commands and can use them automatically.
See: `https://github.com/kepano/obsidian-claude-skills` (verify repo name — transcript
auto-captions may have garbled it as "typhoon skills").
