# Encoding Check

## Summary

The Korean text in the repository is stored as valid UTF-8. The visible mojibake during terminal reads is caused by the PowerShell execution/output environment, not by the checked files themselves.

## Evidence

- `web/templates/index.html` starts with `<meta charset="UTF-8">`.
- The title text `한스톡 자동매매 대시보드` is stored as UTF-8 bytes, for example `한` appears as `ED-95-9C`.
- The `.doc/*.md` files also contain UTF-8 Korean byte sequences.
- The repeated message `Microsoft.PowerShell_profile.ps1` cannot be loaded shows the shell is trying to load a user profile before each command.
- The terminal output then decodes UTF-8 bytes through the wrong legacy code page, so valid Korean appears like `í•œìŠ¤í†¡`.

## Root Cause

There are two separate issues:

1. The current shell session loads `C:\Users\bok\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`, but script execution is blocked by the execution policy.
2. Windows PowerShell 5.1 reads BOM-less UTF-8 files as the legacy ANSI code page unless `-Encoding UTF8` is specified. That turns valid UTF-8 Korean into mojibake before it is printed.

The files are not necessarily corrupted just because `Get-Content` output looks broken.

## Local Fix Applied

- The empty profile file at `C:\Users\bok\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1` was removed. It was 0 bytes and only caused the execution policy error.
- After removal, new shell commands no longer print the profile loading error.
- Korean text still requires explicit UTF-8 reads in Windows PowerShell 5.1:

```powershell
Get-Content web\templates\index.html -Encoding UTF8 -TotalCount 8
```

## Repository Fixes Added

- `.editorconfig` forces UTF-8 for source, web, config, and documentation files.
- `.gitattributes` fixes text checkout/commit encoding and treats binary files as binary.
- `tools/check-encoding.ps1` verifies text files with a strict UTF-8 decoder.

## Recommended Local Commands

Use these when checking Korean text in PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass
chcp 65001
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
```

Run the project UTF-8 check:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/check-encoding.ps1
```

Read UTF-8 project files explicitly in Windows PowerShell 5.1:

```powershell
Get-Content path\to\file -Encoding UTF8
```

If a terminal still shows mojibake after this, verify in an editor or browser before rewriting files.
