param(
    [string]$ArtifactsDir = "artifacts",
    [string]$ReportDir = "report",
    [string]$RimeDllPath = "lib/rime.dll",
    [string]$DateFormat = "yyyy-MM-dd",
    [int]$ProgressEvery = 0
)

$ErrorActionPreference = "Stop"

function Get-SubmoduleSnapshots {
    param(
        [string]$RepoRoot
    )

    $gitModulesPath = Join-Path $RepoRoot ".gitmodules"
    if (-not (Test-Path $gitModulesPath)) {
        return @()
    }

    $entries = & git config --file $gitModulesPath --get-regexp '^submodule\..*\.path$'
    if ($LASTEXITCODE -ne 0 -or -not $entries) {
        return @()
    }

    $snapshots = @()
    foreach ($entry in $entries) {
        $parts = $entry -split '\s+', 2
        if ($parts.Count -lt 2) {
            continue
        }

        $key = $parts[0]
        $path = $parts[1]
        $name = $key -replace '^submodule\.', '' -replace '\.path$', ''
        $fullPath = Join-Path $RepoRoot $path

        if (-not (Test-Path $fullPath)) {
            continue
        }

        $commitId = (& git -C $fullPath rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $commitId) {
            continue
        }

        $branchOutput = & git config --file $gitModulesPath --get "submodule.$name.branch"
        if ($LASTEXITCODE -ne 0 -or -not $branchOutput) {
            $branch = ""
        }
        else {
            $branch = ($branchOutput | Select-Object -First 1).Trim()
        }

        $snapshots += [pscustomobject]@{
            Name = $name
            Path = $path
            Branch = $branch
            CommitId = $commitId
        }
    }

    return $snapshots
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$artifactsPath = Join-Path $repoRoot $ArtifactsDir
$reportPath = Join-Path $repoRoot $ReportDir
$resolvedRimeDllPath = if ([System.IO.Path]::IsPathRooted($RimeDllPath)) {
    $RimeDllPath
}
else {
    Join-Path $repoRoot $RimeDllPath
}

New-Item -ItemType Directory -Path $artifactsPath -Force | Out-Null
New-Item -ItemType Directory -Path $reportPath -Force | Out-Null

if (-not (Test-Path $resolvedRimeDllPath)) {
    throw "rime.dll not found: $resolvedRimeDllPath"
}

$env:PYTHONPATH = Join-Path $repoRoot "src"
$env:RIME_DLL = $resolvedRimeDllPath

Push-Location $repoRoot
try {
    & python "scripts/benchmark_sentences.py" --progress-every $ProgressEvery --out-dir $artifactsPath --rime-dll $resolvedRimeDllPath
    if ($LASTEXITCODE -ne 0) {
        throw "benchmark_sentences.py exited with code $LASTEXITCODE"
    }

    $latestReport = Get-ChildItem -Path $artifactsPath -Filter "*_report.txt" -File |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1

    if (-not $latestReport) {
        throw "No *_report.txt file was generated under '$artifactsPath'."
    }

    $generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    $datedReportName = "{0}.md" -f (Get-Date -Format $DateFormat)
    $submoduleSnapshots = Get-SubmoduleSnapshots -RepoRoot $repoRoot
    $reportMarkdown = @(
        '# Rime 评测结果'
        ''
        "- 生成时间: $generatedAt"
        ('- 来源文件: `{0}`' -f $latestReport.Name)
        ''
        '## Vendor 子模块版本'
        ''
    )

    foreach ($snapshot in $submoduleSnapshots) {
        if ($snapshot.Branch) {
            $reportMarkdown += ('- `{0}` (`{1}`): `{2}`' -f $snapshot.Path, $snapshot.Branch, $snapshot.CommitId)
        }
        else {
            $reportMarkdown += ('- `{0}`: `{1}`' -f $snapshot.Path, $snapshot.CommitId)
        }
    }

    if (-not $submoduleSnapshots) {
        $reportMarkdown += '- 未检测到子模块信息'
    }

    $reportMarkdown += @(
        ''
        '## 评测摘要'
        ''
        '```text'
        (Get-Content -Path $latestReport.FullName -Encoding UTF8)
        '```'
        ''
    )

    Set-Content -Path (Join-Path $reportPath "latest.md") -Value $reportMarkdown -Encoding UTF8
    Set-Content -Path (Join-Path $reportPath $datedReportName) -Value $reportMarkdown -Encoding UTF8
}
finally {
    Pop-Location
}