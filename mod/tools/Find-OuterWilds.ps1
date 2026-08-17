<#
.SYNOPSIS
    Locates the Outer Wilds install and prints its Managed folder.

.DESCRIPTION
    Used by the build when OwManagedDir is not set, so a contributor does not have to
    configure a path by hand.

    The primary source is Unity's own log. Line 1 of Player.log is:

        Mono path[0] = 'D:/Games/Outer Wilds/OuterWilds_Data/Managed'

    Unity writes it on every launch whatever the store, so this finds installs that have
    no registry entry or launcher manifest. It only requires that the game has been run
    once, which is true of anyone building a mod for it.

    Steam is checked as a fallback for a fresh install that has never been launched.
    The richer detection chain lives in the Python server (gcp/config.py); duplicating
    all of it in PowerShell would be two implementations of the same logic to keep in
    step, for a case the two sources here already cover.

.OUTPUTS
    The absolute path of OuterWilds_Data\Managed, or nothing if not found.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Test-GameDir {
    param([string] $Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    return Test-Path (Join-Path $Path 'OuterWilds_Data\Managed\Assembly-CSharp.dll')
}

function Find-FromPlayerLog {
    $logDir = Join-Path $env:USERPROFILE 'AppData\LocalLow\Mobius Digital\Outer Wilds'

    foreach ($name in @('Player.log', 'Player-prev.log')) {
        $log = Join-Path $logDir $name
        if (-not (Test-Path $log)) { continue }

        # The line is always first; the file itself can be megabytes.
        $head = Get-Content $log -TotalCount 1 -ErrorAction SilentlyContinue
        if (-not $head) { continue }

        $match = [regex]::Match($head, "Mono path\[0\]\s*=\s*'(.+?)'")
        if (-not $match.Success) { continue }

        $managed = $match.Groups[1].Value
        $root = Split-Path (Split-Path $managed -Parent) -Parent
        if (Test-GameDir $root) { return $root }
    }

    return $null
}

function Find-FromSteam {
    $steam = $null
    foreach ($key in @('HKLM:\SOFTWARE\WOW6432Node\Valve\Steam', 'HKLM:\SOFTWARE\Valve\Steam')) {
        try {
            $steam = (Get-ItemProperty -Path $key -Name InstallPath -ErrorAction Stop).InstallPath
            break
        } catch { }
    }
    if (-not $steam) { return $null }

    $libraries = @($steam)
    $vdf = Join-Path $steam 'steamapps\libraryfolders.vdf'
    if (Test-Path $vdf) {
        $text = Get-Content $vdf -Raw
        foreach ($m in [regex]::Matches($text, '"path"\s+"([^"]+)"')) {
            $libraries += $m.Groups[1].Value -replace '\\\\', '\'
        }
    }

    foreach ($library in $libraries) {
        $candidate = Join-Path $library 'steamapps\common\Outer Wilds'
        if (Test-GameDir $candidate) { return $candidate }
    }

    return $null
}

$root = Find-FromPlayerLog
if (-not $root) { $root = Find-FromSteam }

if ($root) {
    Write-Output (Join-Path $root 'OuterWilds_Data\Managed')
}
