param(
    [string]$Root = "."
)

$ErrorActionPreference = "Stop"
$Utf8Strict = [System.Text.UTF8Encoding]::new($false, $true)
$ExcludedDirs = @(".git", ".runtime", "logs", "vendor", "__pycache__")
$Extensions = @(
    ".py", ".js", ".css", ".html", ".md", ".yml", ".yaml", ".json",
    ".txt", ".sh", ".env", ".example", ".gitignore", ".gitattributes",
    ".editorconfig"
)

$badFiles = New-Object System.Collections.Generic.List[string]

Get-ChildItem -LiteralPath $Root -Recurse -File | ForEach-Object {
    $file = $_
    foreach ($dir in $ExcludedDirs) {
        if ($file.FullName -like "*\$dir\*") {
            return
        }
    }

    $name = $file.Name
    $ext = $file.Extension
    if (($Extensions -notcontains $ext) -and ($Extensions -notcontains $name)) {
        return
    }

    try {
        [void]$Utf8Strict.GetString([System.IO.File]::ReadAllBytes($file.FullName))
    }
    catch {
        $badFiles.Add($file.FullName)
    }
}

if ($badFiles.Count -gt 0) {
    Write-Host "Invalid UTF-8 files:"
    $badFiles | ForEach-Object { Write-Host $_ }
    exit 1
}

Write-Host "UTF-8 check passed."
