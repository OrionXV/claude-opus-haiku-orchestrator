[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $PSCommandPath
$marker = '<!-- claude-orchestrator:start -->'
$profileNames = @('max', 'pro', 'max-2-subagents', 'pro-2-subagents', 'fable-xhigh-haiku-max', 'fable-medium-haiku-max', 'fable-medium-sonnet-high')
$bundledAgentRoles = @('explorer', 'worker', 'tester', 'reviewer', 'researcher')
$banner = @'
+---------------------------------------+
|                                       |
|        O R C H E S T R A T O R        |
|            for Claude Code            |
|                                       |
|    Orchestrate with Opus or Fable.    |
|     Execute with Haiku or Sonnet.     |
|                                       |
+---------------------------------------+
'@

[Console]::WriteLine($banner)
[Console]::WriteLine('Interactive project setup for Windows')

function Read-InputLine {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) {
        [Console]::Error.WriteLine('Setup cancelled: input ended before setup was complete.')
        exit 1
    }
    return $line
}

function Read-Confirmation {
    param(
        [Parameter(Mandatory)]
        [string]$Prompt,

        [Parameter(Mandatory)]
        [bool]$DefaultYes
    )

    $suffix = if ($DefaultYes) { '[Y/n]' } else { '[y/N]' }
    while ($true) {
        [Console]::Write("$Prompt $suffix ")
        $answer = (Read-InputLine).Trim().ToLowerInvariant()

        switch ($answer) {
            'y' { return $true }
            'yes' { return $true }
            'n' { return $false }
            'no' { return $false }
            '' { return $DefaultYes }
            default { [Console]::WriteLine('Please answer yes or no.') }
        }
    }
}

function Read-Profile {
    [Console]::WriteLine('Choose Profile to install')
    [Console]::WriteLine('  1) max - Opus 5.5 root, Haiku 5.5 subagents, Opus reviewer (default)')
    [Console]::WriteLine('  2) pro - Sonnet 5.5 root, Haiku 5.5 subagents, Opus reviewer')
    [Console]::WriteLine('  3) max-2-subagents - Opus 5.5 root, Haiku 5.5 subagents (2 concurrent), Opus reviewer')
    [Console]::WriteLine('  4) pro-2-subagents - Sonnet 5.5 root, Haiku 5.5 subagents (2 concurrent), Opus reviewer')
    [Console]::WriteLine('  5) fable-xhigh-haiku-max - Fable 5.1 root (xhigh), Haiku 5.5 subagents, Fable 5.1 reviewer (max)')
    [Console]::WriteLine('  6) fable-medium-haiku-max - Fable 5.1 root and reviewer (medium), Haiku 5.5 subagents')
    [Console]::WriteLine('  7) fable-medium-sonnet-high - Fable 5.1 root, Sonnet 5.5 subagents, Opus 5.5 researcher and reviewer')

    while ($true) {
        [Console]::Write('Select Profile [1-7] (default 1): ')
        $answer = (Read-InputLine).Trim().ToLowerInvariant()

        if ($answer -eq '') {
            return 'max'
        }
        if ($answer -match '^[1-7]$') {
            return $profileNames[([int]$answer) - 1]
        }
        if ($profileNames -contains $answer) {
            return $answer
        }
        [Console]::WriteLine('Please enter a listed profile number or name.')
    }
}

# Expands a leading ~ or ~/ (or ~\) to the user's home directory.
function Expand-HomePath {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $userHome = [Environment]::GetFolderPath('UserProfile')
    if ($Path -eq '~') {
        return $userHome
    }
    if ($Path.StartsWith('~/') -or $Path.StartsWith('~\')) {
        return (Join-Path $userHome $Path.Substring(2))
    }
    return $Path
}

# Full path without a trailing separator, with a link's target followed where PowerShell can report it.
function Get-ComparablePath {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $full = [IO.Path]::GetFullPath($Path)
    $item = Get-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue
    if (($null -ne $item) -and (Test-IsReparsePoint -Item $item) -and ($null -ne $item.PSObject.Methods['ResolveLinkTarget'])) {
        $resolved = $item.ResolveLinkTarget($true)
        if ($null -ne $resolved) {
            $full = $resolved.FullName
        }
    }

    return $full.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
}

# True when two comparable paths are equal or one lies inside the other.
function Test-PathOverlap {
    param(
        [Parameter(Mandatory)]
        [string]$First,

        [Parameter(Mandatory)]
        [string]$Second
    )

    if ($env:OS -eq 'Windows_NT') {
        $comparison = [StringComparison]::OrdinalIgnoreCase
    }
    else {
        $comparison = [StringComparison]::Ordinal
    }
    $separator = [string][IO.Path]::DirectorySeparatorChar
    if ([string]::Equals($First, $Second, $comparison)) {
        return $true
    }
    return ($Second.StartsWith($First + $separator, $comparison) -or $First.StartsWith($Second + $separator, $comparison))
}

function Test-IsReparsePoint {
    param(
        [Parameter(Mandatory)]
        [System.IO.FileSystemInfo]$Item
    )

    return (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)
}

# Text shown for where a link points, or <unknown> when PowerShell cannot report it.
function Get-LinkTargetText {
    param(
        [Parameter(Mandatory)]
        [System.IO.FileSystemInfo]$Item
    )

    $target = $null
    if ($null -ne $Item.PSObject.Properties['Target']) {
        $target = $Item.PSObject.Properties['Target'].Value
    }
    if (($null -eq $target) -and ($null -ne $Item.PSObject.Properties['LinkTarget'])) {
        $target = $Item.PSObject.Properties['LinkTarget'].Value
    }
    $first = @($target) | Select-Object -First 1
    if ($null -eq $first) {
        return '<unknown>'
    }
    return [string]$first
}

function Copy-DirectoryContents {
    param(
        [Parameter(Mandatory)]
        [string]$Source,

        [Parameter(Mandatory)]
        [string]$Destination
    )

    foreach ($sourceChild in (Get-ChildItem -LiteralPath $Source -Force)) {
        $destinationChildPath = Join-Path $Destination $sourceChild.Name
        $destinationChild = Get-Item -LiteralPath $destinationChildPath -Force -ErrorAction SilentlyContinue

        if ($sourceChild.PSIsContainer) {
            if ($null -eq $destinationChild) {
                New-Item -ItemType Directory -Path $destinationChildPath | Out-Null
            }
            elseif (-not $destinationChild.PSIsContainer) {
                throw "Cannot merge directory over file: $destinationChildPath"
            }

            Copy-DirectoryContents -Source $sourceChild.FullName -Destination $destinationChildPath
        }
        else {
            if (($null -ne $destinationChild) -and $destinationChild.PSIsContainer) {
                throw "Cannot overwrite directory with file: $destinationChildPath"
            }

            Copy-Item -LiteralPath $sourceChild.FullName -Destination $destinationChildPath -Force
        }
    }
}

function Test-DirectoryMergeCompatible {
    param(
        [Parameter(Mandatory)]
        [string]$Source,

        [Parameter(Mandatory)]
        [string]$Destination
    )

    foreach ($sourceChild in (Get-ChildItem -LiteralPath $Source -Force)) {
        $destinationChildPath = Join-Path $Destination $sourceChild.Name
        $destinationChild = Get-Item -LiteralPath $destinationChildPath -Force -ErrorAction SilentlyContinue
        if ($null -eq $destinationChild) {
            continue
        }
        if ($sourceChild.PSIsContainer -ne $destinationChild.PSIsContainer) {
            return $false
        }
        if ($sourceChild.PSIsContainer -and (-not (Test-DirectoryMergeCompatible -Source $sourceChild.FullName -Destination $destinationChildPath))) {
            return $false
        }
    }

    return $true
}

# Regular files under a directory. Links and junctions are reported neither as files nor descended into.
function Get-RegularFiles {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    foreach ($child in (Get-ChildItem -LiteralPath $Path -Force)) {
        if (Test-IsReparsePoint -Item $child) {
            continue
        }
        if ($child.PSIsContainer) {
            Get-RegularFiles -Path $child.FullName
        }
        else {
            $child
        }
    }
}

# Relative path of a file under a root, using forward slashes for display.
function Get-DisplayRelativePath {
    param(
        [Parameter(Mandatory)]
        [string]$Root,

        [Parameter(Mandatory)]
        [string]$FullName
    )

    $relative = $FullName.Substring($Root.Length + 1)
    return $relative.Replace([string][IO.Path]::DirectorySeparatorChar, '/')
}

# Destination files that already exist with different content (they would be replaced).
function Get-ChangedPaths {
    param(
        [Parameter(Mandatory)]
        [string]$Source,

        [Parameter(Mandatory)]
        [string]$Destination,

        [Parameter(Mandatory)]
        [string]$Name
    )

    foreach ($sourceFile in (Get-RegularFiles -Path $Source)) {
        $relativePath = $sourceFile.FullName.Substring($Source.Length + 1)
        $destinationFile = Get-Item -LiteralPath (Join-Path $Destination $relativePath) -Force -ErrorAction SilentlyContinue
        if (($null -eq $destinationFile) -or $destinationFile.PSIsContainer) {
            continue
        }
        $sourceHash = (Get-FileHash -LiteralPath $sourceFile.FullName -Algorithm SHA256).Hash
        $destinationHash = (Get-FileHash -LiteralPath $destinationFile.FullName -Algorithm SHA256).Hash
        if ($sourceHash -ne $destinationHash) {
            Write-Output ($Name + '/' + (Get-DisplayRelativePath -Root $Source -FullName $sourceFile.FullName))
        }
    }
}

# Source files that the destination does not have yet.
function Get-NewPaths {
    param(
        [Parameter(Mandatory)]
        [string]$Source,

        [Parameter(Mandatory)]
        [string]$Destination
    )

    foreach ($sourceFile in (Get-RegularFiles -Path $Source)) {
        $relativePath = $sourceFile.FullName.Substring($Source.Length + 1)
        if ($null -eq (Get-Item -LiteralPath (Join-Path $Destination $relativePath) -Force -ErrorAction SilentlyContinue)) {
            Write-Output (Get-DisplayRelativePath -Root $Source -FullName $sourceFile.FullName)
        }
    }
}

# First link or junction on the path to a destination file that copying the source would write.
# Links elsewhere in the destination are ignored and never followed.
function Find-WritePathLink {
    param(
        [Parameter(Mandatory)]
        [string]$Source,

        [Parameter(Mandatory)]
        [string]$Destination
    )

    foreach ($sourceFile in (Get-RegularFiles -Path $Source)) {
        $relativePath = $sourceFile.FullName.Substring($Source.Length + 1)
        $current = $Destination
        foreach ($segment in $relativePath.Split([IO.Path]::DirectorySeparatorChar)) {
            $current = Join-Path $current $segment
            $item = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
            if ($null -eq $item) {
                break
            }
            if (Test-IsReparsePoint -Item $item) {
                return $item.FullName
            }
        }
    }

    return $null
}

# Frontmatter name of an agent file, or $null when it has none.
function Get-AgentName {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $lines = [IO.File]::ReadAllLines($Path)
    if (($lines.Count -eq 0) -or ($lines[0] -ne '---')) {
        return $null
    }
    for ($index = 1; $index -lt $lines.Count; $index++) {
        $line = $lines[$index]
        if ($line -eq '---') {
            return $null
        }
        if ($line -match '^name:\s*(.*)$') {
            return $Matches[1].Trim().Replace('"', '').Replace("'", '')
        }
    }

    return $null
}

# Existing agent files, other than the ones being installed, that declare a bundled role name.
function Get-AgentNameClashes {
    param(
        [Parameter(Mandatory)]
        [string]$Source,

        [Parameter(Mandatory)]
        [string]$Destination
    )

    foreach ($existingFile in (Get-RegularFiles -Path $Destination)) {
        if ($existingFile.Extension -cne '.md') {
            continue
        }
        $relativePath = $existingFile.FullName.Substring($Destination.Length + 1)
        if (Test-Path -LiteralPath (Join-Path $Source $relativePath) -PathType Leaf) {
            continue
        }
        $agentName = Get-AgentName -Path $existingFile.FullName
        if (($null -ne $agentName) -and ($bundledAgentRoles -ccontains $agentName)) {
            Write-Output ((Get-DisplayRelativePath -Root $Destination -FullName $existingFile.FullName) + ' (name: ' + $agentName + ')')
        }
    }
}

# Returns $false (after printing a skip message) if an existing parent of the component is a
# link or not a directory. Parents are every path segment of $Name except the last one.
function Test-ParentDirectories {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string]$TargetDirectory
    )

    $segments = $Name.Split('/')
    for ($index = 1; $index -lt $segments.Count; $index++) {
        $parentPath = Join-Path $TargetDirectory (($segments[0..($index - 1)]) -join [IO.Path]::DirectorySeparatorChar)
        $parentItem = Get-Item -LiteralPath $parentPath -Force -ErrorAction SilentlyContinue
        if ($null -eq $parentItem) {
            continue
        }
        if (Test-IsReparsePoint -Item $parentItem) {
            [Console]::Error.WriteLine("Skipped ${Name}: the existing target contains a symbolic link or junction ($parentPath).")
            return $false
        }
        if (-not $parentItem.PSIsContainer) {
            [Console]::Error.WriteLine("Skipped ${Name}: source and target types are incompatible.")
            return $false
        }
    }

    return $true
}

function New-ParentDirectories {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string]$TargetDirectory
    )

    $segments = $Name.Split('/')
    for ($index = 1; $index -lt $segments.Count; $index++) {
        $parentPath = Join-Path $TargetDirectory (($segments[0..($index - 1)]) -join [IO.Path]::DirectorySeparatorChar)
        if ($null -eq (Get-Item -LiteralPath $parentPath -Force -ErrorAction SilentlyContinue)) {
            New-Item -ItemType Directory -Path $parentPath | Out-Null
        }
    }
}

function Install-Directory {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string]$SourcePath,

        [Parameter(Mandatory)]
        [string]$TargetDirectory
    )

    $sourceItem = Get-Item -LiteralPath $SourcePath -Force -ErrorAction SilentlyContinue
    if ($null -eq $sourceItem) {
        throw "Setup source is missing: $SourcePath"
    }

    if (-not (Test-ParentDirectories -Name $Name -TargetDirectory $TargetDirectory)) {
        return $false
    }

    $destinationPath = Join-Path $TargetDirectory ($Name.Replace('/', [IO.Path]::DirectorySeparatorChar))
    $destinationItem = Get-Item -LiteralPath $destinationPath -Force -ErrorAction SilentlyContinue
    if ($null -eq $destinationItem) {
        New-ParentDirectories -Name $Name -TargetDirectory $TargetDirectory
        Copy-Item -LiteralPath $SourcePath -Destination $destinationPath -Recurse -Force
        [Console]::WriteLine("Installed $Name.")
        return $true
    }

    if (Test-IsReparsePoint -Item $destinationItem) {
        [Console]::Error.WriteLine("Skipped ${Name}: the existing target is a symbolic link or junction.")
        return $false
    }

    if (-not $destinationItem.PSIsContainer) {
        [Console]::Error.WriteLine("Skipped ${Name}: source and target types are incompatible.")
        return $false
    }

    $linkedPath = Find-WritePathLink -Source $SourcePath -Destination $destinationPath
    if ($null -ne $linkedPath) {
        [Console]::Error.WriteLine("Skipped ${Name}: the existing target contains a symbolic link or junction ($linkedPath).")
        return $false
    }

    if (-not (Test-DirectoryMergeCompatible -Source $SourcePath -Destination $destinationPath)) {
        [Console]::Error.WriteLine("Skipped ${Name}: source and target types conflict.")
        return $false
    }

    if ($Name -eq '.claude/agents') {
        $clashes = @(Get-AgentNameClashes -Source $SourcePath -Destination $destinationPath)
        if ($clashes.Count -gt 0) {
            [Console]::WriteLine('WARNING: these existing agents use the same name and may shadow the installed ones:')
            foreach ($clash in $clashes) {
                [Console]::WriteLine("  - $Name/$clash")
            }
        }
    }

    $overwritePaths = @(Get-ChangedPaths -Source $SourcePath -Destination $destinationPath -Name $Name)
    $addedPaths = @(Get-NewPaths -Source $SourcePath -Destination $destinationPath)
    if (($overwritePaths.Count -eq 0) -and ($addedPaths.Count -eq 0)) {
        [Console]::WriteLine("$Name already up to date.")
        return $false
    }

    if ($overwritePaths.Count -gt 0) {
        [Console]::WriteLine('WARNING: the following existing files will be overwritten:')
        foreach ($path in $overwritePaths) {
            [Console]::WriteLine("  - $path")
        }

        if (-not (Read-Confirmation -Prompt "Update ${Name}? New files will be added; only paths listed above will be replaced." -DefaultYes $false)) {
            [Console]::WriteLine("Skipped $Name (existing target left unchanged).")
            return $false
        }
    }

    Copy-DirectoryContents -Source $SourcePath -Destination $destinationPath
    [Console]::WriteLine("Updated $Name.")
    return $true
}

function Test-HasProperty {
    param(
        [Parameter(Mandatory)]
        $Object,

        [Parameter(Mandatory)]
        [string]$Name
    )

    return ($null -ne $Object.PSObject.Properties[$Name])
}

# True when an existing JSON value is a string equal to the profile string (case-sensitive).
# A number such as 4 is not treated as equal to "4", so it is rewritten as a string.
function Test-SameString {
    param(
        $Old,

        [string]$New
    )

    if ($Old -isnot [string]) {
        return $false
    }
    return ([string]$Old -ceq $New)
}

function Get-JsonDisplay {
    param(
        [bool]$Present,

        $Value
    )

    if (-not $Present) {
        return '<unset>'
    }
    return (ConvertTo-Json -InputObject $Value -Compress)
}

# Parses JSON, keeping ISO date-like strings as strings where this PowerShell version supports it.
function Read-JsonText {
    param(
        [Parameter(Mandatory)]
        [string]$Text
    )

    if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')) {
        return (ConvertFrom-Json -InputObject $Text -DateKind String)
    }
    return (ConvertFrom-Json -InputObject $Text)
}

# Re-indents ConvertTo-Json output to two spaces per level and removes the double space after
# colons that Windows PowerShell 5.1 emits, so the file matches the Python-written layout.
function Format-JsonText {
    param(
        [Parameter(Mandatory)]
        [string]$Json
    )

    $depth = 0
    $result = New-Object System.Collections.Generic.List[string]
    foreach ($rawLine in ($Json -split "\r?\n")) {
        $line = $rawLine.Trim()
        if ($line -eq '') {
            continue
        }
        if ($line -match '^[\]\}]') {
            $depth--
        }
        $line = $line -replace '^("(?:[^"\\]|\\.)*"):\s+', '$1: '
        $result.Add(('  ' * $depth) + $line)
        if ($line -match '[\[\{]$') {
            $depth++
        }
    }

    return (($result -join "`n") + "`n")
}

function Install-Settings {
    param(
        [Parameter(Mandatory)]
        [string]$SourcePath,

        [Parameter(Mandatory)]
        [string]$TargetDirectory
    )

    $name = '.claude/settings.json'
    $destinationPath = Join-Path (Join-Path $TargetDirectory '.claude') 'settings.json'

    if (-not (Test-ParentDirectories -Name $name -TargetDirectory $TargetDirectory)) {
        return $false
    }

    $destinationItem = Get-Item -LiteralPath $destinationPath -Force -ErrorAction SilentlyContinue
    if ($null -eq $destinationItem) {
        New-ParentDirectories -Name $name -TargetDirectory $TargetDirectory
        Copy-Item -LiteralPath $SourcePath -Destination $destinationPath -Force
        [Console]::WriteLine("Installed $name.")
        return $true
    }

    if (Test-IsReparsePoint -Item $destinationItem) {
        [Console]::Error.WriteLine("Skipped ${name}: the existing target is a symbolic link or junction.")
        return $false
    }

    if ($destinationItem.PSIsContainer) {
        [Console]::Error.WriteLine("Skipped ${name}: source and target types are incompatible.")
        return $false
    }

    $profileSettings = Read-JsonText -Text ([IO.File]::ReadAllText($SourcePath))

    $existing = $null
    $parsed = $true
    try {
        $existing = Read-JsonText -Text ([IO.File]::ReadAllText($destinationPath))
    }
    catch {
        $parsed = $false
    }
    if (-not $parsed) {
        [Console]::WriteLine("Skipped ${name}: existing file is not valid JSON; left unchanged.")
        return $false
    }
    if (($null -eq $existing) -or ($existing.PSObject.BaseObject -isnot [System.Management.Automation.PSCustomObject])) {
        [Console]::WriteLine("Skipped ${name}: top-level value is not a JSON object; left unchanged.")
        return $false
    }

    $hasEnv = Test-HasProperty -Object $existing -Name 'env'
    $existingEnv = if ($hasEnv) { $existing.PSObject.Properties['env'].Value } else { [PSCustomObject]@{} }
    if (($null -eq $existingEnv) -or ($existingEnv.PSObject.BaseObject -isnot [System.Management.Automation.PSCustomObject])) {
        [Console]::WriteLine("Skipped ${name}: 'env' is not a JSON object; left unchanged.")
        return $false
    }

    $changes = New-Object System.Collections.Generic.List[string]
    $topUpdates = [ordered]@{}
    $envUpdates = [ordered]@{}

    if (-not (Test-HasProperty -Object $existing -Name '$schema')) {
        $changes.Add('  $schema: <unset> -> ' + (ConvertTo-Json -InputObject $profileSettings.'$schema' -Compress))
    }

    foreach ($key in @('model', 'effortLevel')) {
        $present = Test-HasProperty -Object $existing -Name $key
        $oldValue = if ($present) { $existing.PSObject.Properties[$key].Value } else { $null }
        $newValue = [string]$profileSettings.PSObject.Properties[$key].Value
        if ((-not $present) -or (-not (Test-SameString -Old $oldValue -New $newValue))) {
            $changes.Add("  ${key}: " + (Get-JsonDisplay -Present $present -Value $oldValue) + ' -> ' + (Get-JsonDisplay -Present $true -Value $newValue))
            $topUpdates[$key] = $newValue
        }
    }

    foreach ($envProperty in $profileSettings.env.PSObject.Properties) {
        $key = $envProperty.Name
        $newValue = [string]$envProperty.Value
        $present = Test-HasProperty -Object $existingEnv -Name $key
        $oldValue = if ($present) { $existingEnv.PSObject.Properties[$key].Value } else { $null }
        if ((-not $present) -or (-not (Test-SameString -Old $oldValue -New $newValue))) {
            $changes.Add("  env.${key}: " + (Get-JsonDisplay -Present $present -Value $oldValue) + ' -> ' + (Get-JsonDisplay -Present $true -Value $newValue))
            $envUpdates[$key] = $newValue
        }
    }

    if ($changes.Count -eq 0) {
        [Console]::WriteLine("$name already matches the profile; nothing to merge.")
        return $false
    }

    [Console]::WriteLine("Keys that will change in ${name}:")
    foreach ($change in $changes) {
        [Console]::WriteLine($change)
    }

    if (-not (Read-Confirmation -Prompt "Merge into existing $name?" -DefaultYes $false)) {
        [Console]::WriteLine("Skipped $name (existing target left unchanged).")
        return $false
    }

    $newEnv = [ordered]@{}
    foreach ($envProperty in $existingEnv.PSObject.Properties) {
        if ($envUpdates.Contains($envProperty.Name)) {
            $newEnv[$envProperty.Name] = $envUpdates[$envProperty.Name]
        }
        else {
            $newEnv[$envProperty.Name] = $envProperty.Value
        }
    }
    foreach ($key in $envUpdates.Keys) {
        if (-not $newEnv.Contains($key)) {
            $newEnv[$key] = $envUpdates[$key]
        }
    }

    $merged = [ordered]@{}
    if (-not (Test-HasProperty -Object $existing -Name '$schema')) {
        $merged['$schema'] = $profileSettings.'$schema'
    }
    foreach ($property in $existing.PSObject.Properties) {
        if ($property.Name -eq 'env') {
            $merged['env'] = $newEnv
        }
        elseif ($topUpdates.Contains($property.Name)) {
            $merged[$property.Name] = $topUpdates[$property.Name]
        }
        else {
            $merged[$property.Name] = $property.Value
        }
    }
    foreach ($key in $topUpdates.Keys) {
        if (-not $merged.Contains($key)) {
            $merged[$key] = $topUpdates[$key]
        }
    }
    if (-not $merged.Contains('env')) {
        $merged['env'] = $newEnv
    }

    $json = Format-JsonText -Json (ConvertTo-Json -InputObject $merged -Depth 32)
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    $tempPath = Join-Path (Split-Path -Parent $destinationPath) ('.settings-' + [guid]::NewGuid().ToString('N') + '.json.tmp')
    try {
        [IO.File]::WriteAllText($tempPath, $json, $utf8NoBom)
        Move-Item -LiteralPath $tempPath -Destination $destinationPath -Force -ErrorAction Stop
    }
    catch {
        # Any failure while writing is reported as a skip, matching the sh installer's OSError handling.
        if (Test-Path -LiteralPath $tempPath) {
            Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
        }
        [Console]::WriteLine("Skipped ${name}: could not write the file.")
        return $false
    }
    [Console]::WriteLine("Merged $name.")
    return $true
}

# Prints a note when an AGENTS.md exists in an ancestor of the target directory.
function Write-AncestorAgentsNote {
    param(
        [Parameter(Mandatory)]
        [string]$TargetDirectory
    )

    $current = $TargetDirectory
    while ($true) {
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrEmpty($parent) -or ($parent -eq $current)) {
            break
        }
        if ($null -ne (Get-Item -LiteralPath (Join-Path $parent 'AGENTS.md') -Force -ErrorAction SilentlyContinue)) {
            $parentDisplay = $parent.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
            [Console]::WriteLine("Note: $parentDisplay/AGENTS.md exists above the target; Claude Code stops reading AGENTS.md files once a CLAUDE.md is present. Add an @-import if you still need it.")
        }
        $current = $parent
    }
}

function Install-ClaudeInstructions {
    param(
        [Parameter(Mandatory)]
        [string]$SourcePath,

        [Parameter(Mandatory)]
        [string]$TargetDirectory
    )

    $name = 'CLAUDE.md'
    $destinationPath = Join-Path $TargetDirectory $name
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    $instructions = [IO.File]::ReadAllText($SourcePath)

    $destinationItem = Get-Item -LiteralPath $destinationPath -Force -ErrorAction SilentlyContinue
    if (($null -ne $destinationItem) -and (Test-IsReparsePoint -Item $destinationItem)) {
        $linkTarget = Get-LinkTargetText -Item $destinationItem
        [Console]::Error.WriteLine("Skipped CLAUDE.md: it is a symbolic link to $linkTarget. Append the contents of $SourcePath to that file manually.")
        return $false
    }

    if ($null -eq $destinationItem) {
        $hasRootAgents = $null -ne (Get-Item -LiteralPath (Join-Path $TargetDirectory 'AGENTS.md') -Force -ErrorAction SilentlyContinue)
        $hasClaudeAgents = $null -ne (Get-Item -LiteralPath (Join-Path (Join-Path $TargetDirectory '.claude') 'AGENTS.md') -Force -ErrorAction SilentlyContinue)
        # Claude Code reads AGENTS.md only when CLAUDE.md is absent, so import it explicitly.
        $prefix = ''
        if ($hasRootAgents) {
            $prefix += "@AGENTS.md`n"
        }
        if ($hasClaudeAgents) {
            $prefix += "@.claude/AGENTS.md`n"
        }
        if ($prefix -ne '') {
            $prefix += "`n"
        }
        [IO.File]::WriteAllText($destinationPath, $prefix + $instructions, $utf8NoBom)
        [Console]::WriteLine("Installed $name.")
        Write-AncestorAgentsNote -TargetDirectory $TargetDirectory
        return $true
    }

    if ($destinationItem.PSIsContainer) {
        [Console]::Error.WriteLine("Skipped ${name}: source and target types are incompatible.")
        return $false
    }

    $reader = [IO.StreamReader]::new($destinationPath, [Text.Encoding]::UTF8, $true)
    try {
        $existing = $reader.ReadToEnd()
        $encoding = $reader.CurrentEncoding
    }
    finally {
        $reader.Dispose()
    }

    if ($existing.Contains($marker)) {
        [Console]::WriteLine("Skipped ${name}: instructions already present.")
        return $false
    }

    [IO.File]::AppendAllText($destinationPath, "`n`n" + $instructions, $encoding)
    [Console]::WriteLine("Appended instructions to ${name}. Existing contents preserved.")
    return $true
}

try {
    [Console]::Write('Target repository path: ')
    $targetPath = Expand-HomePath -Path (Read-InputLine)

    $targetItem = $null
    if (-not [string]::IsNullOrWhiteSpace($targetPath)) {
        $targetItem = Get-Item -LiteralPath $targetPath -Force -ErrorAction SilentlyContinue
    }
    if (($null -eq $targetItem) -or (-not $targetItem.PSIsContainer)) {
        $shown = if ([string]::IsNullOrEmpty($targetPath)) { '<empty>' } else { $targetPath }
        [Console]::Error.WriteLine("Error: target must be an existing directory: $shown")
        exit 1
    }

    $targetDirectory = $targetItem.FullName
    $targetComparable = Get-ComparablePath -Path $targetDirectory
    $sourceComparable = Get-ComparablePath -Path $scriptDir
    if (Test-PathOverlap -First $targetComparable -Second $sourceComparable) {
        [Console]::Error.WriteLine('Error: target repository must be different from the setup source directory.')
        exit 1
    }

    $profileName = Read-Profile
    $profileDirectory = Join-Path (Join-Path (Join-Path $scriptDir 'profiles') $profileName) 'claude'

    $installed = 0
    foreach ($component in '.claude/agents', '.claude/skills/claude-orchestrator', '.claude/settings.json', 'CLAUDE.md') {
        if (Read-Confirmation -Prompt "Install ${component}?" -DefaultYes $true) {
            if ($component -eq '.claude/agents') {
                $result = Install-Directory -Name $component -SourcePath (Join-Path $profileDirectory 'agents') -TargetDirectory $targetDirectory
            }
            elseif ($component -eq '.claude/skills/claude-orchestrator') {
                $result = Install-Directory -Name $component -SourcePath (Join-Path (Join-Path $profileDirectory 'skills') 'claude-orchestrator') -TargetDirectory $targetDirectory
            }
            elseif ($component -eq '.claude/settings.json') {
                $result = Install-Settings -SourcePath (Join-Path $profileDirectory 'settings.json') -TargetDirectory $targetDirectory
            }
            else {
                $result = Install-ClaudeInstructions -SourcePath (Join-Path $scriptDir 'CLAUDE.md') -TargetDirectory $targetDirectory
            }
            if ($result) {
                $installed++
            }
        }
        else {
            [Console]::WriteLine("Skipped $component.")
        }
    }

    [Console]::WriteLine()
    [Console]::WriteLine("Setup complete. $installed component(s) installed in $targetDirectory (profile: $profileName).")
    [Console]::WriteLine('See guides/ for model, effort and fast-mode options.')
}
catch {
    [Console]::Error.WriteLine("Setup cancelled: $($_.Exception.Message)")
    exit 1
}
