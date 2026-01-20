[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$SkipDocs
)

$ErrorActionPreference = 'Stop'

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message"
}

function Write-Warn {
    param([string]$Message)
    Write-Warning $Message
}

function Ensure-Dir {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        if ($DryRun) {
            Write-Info "Would create directory: $Path"
        } else {
            New-Item -ItemType Directory -Force -Path $Path | Out-Null
        }
    }
}

function Move-ItemSafe {
    param(
        [string]$Source,
        [string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        return
    }
    if (Test-Path -LiteralPath $Destination) {
        Write-Warn "Skipping move (destination exists): $Destination"
        return
    }
    Ensure-Dir (Split-Path -Parent $Destination)
    if ($DryRun) {
        Write-Info "Would move: $Source -> $Destination"
    } else {
        Move-Item -LiteralPath $Source -Destination $Destination
    }
}

function Move-DirectoryContents {
    param(
        [string]$Source,
        [string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        return
    }
    Ensure-Dir $Destination
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        if ([string]::IsNullOrWhiteSpace($_.Name)) {
            return
        }
        $target = Join-Path -Path $Destination -ChildPath $_.Name
        if (Test-Path -LiteralPath $target) {
            Write-Warn "Skipping move (destination exists): $target"
            return
        }
        if ($DryRun) {
            Write-Info "Would move: $($_.FullName) -> $target"
        } else {
            Move-Item -LiteralPath $_.FullName -Destination $target
        }
    }
    if (-not (Get-ChildItem -LiteralPath $Source -Force)) {
        if ($DryRun) {
            Write-Info "Would remove empty directory: $Source"
        } else {
            Remove-Item -LiteralPath $Source -Force
        }
    }
}

function Ensure-CoreSettings {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Warn "Settings file not found: $Path"
        return
    }
    $text = [System.IO.File]::ReadAllText($Path)
    if ($text -match 'CORE_DIR = BASE_DIR / "company_core"') {
        return
    }
    $newline = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }

    if ($text -notmatch '(?m)^import sys$') {
        $text = $text -replace '(?m)^from pathlib import Path', "from pathlib import Path${newline}import sys"
    }

    $snippet = @(
        "# Shared core apps live in company_core for reuse across projects."
        "CORE_DIR = BASE_DIR / ""company_core"""
        "if CORE_DIR.exists():"
        "    sys.path.insert(0, str(CORE_DIR))"
        ""
    ) -join $newline

    $marker = 'BASE_DIR = Path(__file__).resolve().parent.parent'
    $markerIndex = $text.IndexOf($marker)
    if ($markerIndex -ge 0) {
        $afterMarker = $markerIndex + $marker.Length
        $doubleNewline = $newline + $newline
        $insertPos = $text.IndexOf($doubleNewline, $afterMarker)
        if ($insertPos -ge 0) {
            $insertPos += $doubleNewline.Length
        } else {
            $insertPos = $text.IndexOf($newline, $afterMarker)
            if ($insertPos -ge 0) {
                $insertPos += $newline.Length
            } else {
                $insertPos = $afterMarker
            }
        }
        $text = $text.Insert($insertPos, $snippet + $newline)
    } else {
        $text = $snippet + $newline + $text
    }

    if ($DryRun) {
        Write-Info "Would update settings: $Path"
    } else {
        [System.IO.File]::WriteAllText($Path, $text)
    }
}

function Update-TextFile {
    param(
        [string]$Path,
        [array]$LiteralReplacements,
        [array]$RegexReplacements
    )
    try {
        $text = [System.IO.File]::ReadAllText($Path)
    } catch {
        Write-Warn "Skipping unreadable file: $Path"
        return
    }

    $updated = $text
    foreach ($pair in $LiteralReplacements) {
        $updated = $updated.Replace($pair[0], $pair[1])
    }
    foreach ($pair in $RegexReplacements) {
        $updated = [regex]::Replace($updated, $pair.Pattern, $pair.Replacement)
    }

    if ($updated -ne $text) {
        if ($DryRun) {
            Write-Info "Would update: $Path"
        } else {
            [System.IO.File]::WriteAllText($Path, $updated)
        }
    }
}

if (-not (Test-Path -LiteralPath "manage.py")) {
    Write-Error "manage.py not found. Run this script from the Django project root."
    exit 1
}

Write-Info "Starting project restructure."

Ensure-Dir "company_core"

if ((Test-Path -LiteralPath "accounts") -and (Test-Path -LiteralPath "company_core/accounts")) {
    Write-Error "Both 'accounts' and 'company_core/accounts' exist. Resolve the conflict before running."
    exit 1
}
if (Test-Path -LiteralPath "accounts") {
    Move-ItemSafe "accounts" "company_core/accounts"
}

if ((Test-Path -LiteralPath "api") -and (Test-Path -LiteralPath "company_core/api")) {
    Write-Error "Both 'api' and 'company_core/api' exist. Resolve the conflict before running."
    exit 1
}
if (Test-Path -LiteralPath "api") {
    Move-ItemSafe "api" "company_core/api"
}

$templatesRoot = $null
if (Test-Path -LiteralPath "company_core/accounts/templates") {
    $templatesRoot = "company_core/accounts/templates"
} elseif (Test-Path -LiteralPath "accounts/templates") {
    $templatesRoot = "accounts/templates"
}

if ($templatesRoot) {
    Ensure-Dir "templates"
    Ensure-Dir "templates/emails"

    foreach ($name in @("base.html", "404.html", "500.html")) {
        Move-ItemSafe (Join-Path $templatesRoot $name) (Join-Path "templates" $name)
    }

    Get-ChildItem -Path $templatesRoot -Filter "public_*.html" -File -ErrorAction SilentlyContinue | ForEach-Object {
        Move-ItemSafe $_.FullName (Join-Path "templates" $_.Name)
    }

    Move-DirectoryContents (Join-Path $templatesRoot "public") (Join-Path "templates" "public")
    Move-DirectoryContents (Join-Path $templatesRoot "privacy") (Join-Path "templates" "privacy")

    Move-ItemSafe (Join-Path -Path $templatesRoot -ChildPath "emails/public_contact_admin.html") (Join-Path -Path "templates" -ChildPath "emails/public_contact_admin.html")
    Move-ItemSafe (Join-Path -Path $templatesRoot -ChildPath "emails/public_contact_user.html") (Join-Path -Path "templates" -ChildPath "emails/public_contact_user.html")
} else {
    Write-Warn "No accounts templates directory found. Skipping public template moves."
}

Ensure-CoreSettings "blank_template/settings.py"

if (-not $SkipDocs) {
    $docFiles = @()
    $docFiles += Get-ChildItem -Path . -File -Include *.md, *.txt, *.sh
    if (Test-Path -LiteralPath "docs") {
        $docFiles += Get-ChildItem -Path docs -File -Recurse -Include *.md, *.txt, *.sh
    }
    $docFiles = $docFiles | Sort-Object -Property FullName -Unique

    $literalReplacements = @(
        @('company_core/company_core/api/', 'company_core/api/'),
        @('/workspace/accounts/templates/', '/workspace/templates/'),
        @('/accounts/templates/', '/templates/'),
        @('`api/views.py`', '`company_core/api/views.py`'),
        @('`api/urls.py`', '`company_core/api/urls.py`'),
        @('`api/serializers.py`', '`company_core/api/serializers.py`'),
        @('`api/tests.py`', '`company_core/api/tests.py`'),
        @('api/views.py', 'company_core/api/views.py'),
        @('api/urls.py', 'company_core/api/urls.py'),
        @('api/serializers.py', 'company_core/api/serializers.py'),
        @('api/tests.py', 'company_core/api/tests.py'),
        @('git add api/', 'git add company_core/api/'),
        @('flake8 accounts/', 'flake8 company_core/accounts/')
    )

    $regexReplacements = @(
        @{ Pattern = '(?<!company_core/)accounts/templates/'; Replacement = 'templates/' },
        @{ Pattern = '(?<!company_core/)accounts/templates'; Replacement = 'templates' },
        @{ Pattern = '(?<!company_core\\)accounts\\templates\\'; Replacement = 'templates\\' }
    )

    foreach ($file in $docFiles) {
        Update-TextFile $file.FullName $literalReplacements $regexReplacements
    }
} else {
    Write-Info "Skipping docs updates."
}

Write-Info "Done."
