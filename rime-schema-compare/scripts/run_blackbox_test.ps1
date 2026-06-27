param(
    [string]$ArtifactsDir = "artifacts/blackbox",
    [string]$ReportDir = "report",
    [string]$ReportName = "other_latest.md",
    [int]$ProgressEvery = 0
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$artifactsPath = Join-Path $repoRoot $ArtifactsDir
$reportPath = Join-Path $repoRoot $ReportDir

New-Item -ItemType Directory -Path $artifactsPath -Force | Out-Null
New-Item -ItemType Directory -Path $reportPath -Force | Out-Null

$env:PYTHONPATH = Join-Path $repoRoot "src"

Push-Location $repoRoot
try {
    & python "scripts/benchmark_windows_pinyin.py" --ime microsoft_pinyin sogou_pinyin --progress-every $ProgressEvery --out-dir $artifactsPath
    if ($LASTEXITCODE -ne 0) {
        throw "benchmark_windows_pinyin.py exited with code $LASTEXITCODE"
    }

    $latestReport = Get-ChildItem -Path $artifactsPath -Filter "benchmark_windows_pinyin*_report.txt" -File |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1

    if (-not $latestReport) {
        throw "No benchmark_windows_pinyin*_report.txt file was generated under '$artifactsPath'."
    }

    $generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    $reportMarkdown = @(
        '# Windows 拼音输入法黑盒评测结果'
        ''
        "- 生成时间: $generatedAt"
        ('- 来源文件: `{0}`' -f $latestReport.Name)
        ''
        '## 评测摘要'
        ''
        '```text'
        (Get-Content -Path $latestReport.FullName -Encoding UTF8)
        '```'
        ''
    )

    Set-Content -Path (Join-Path $reportPath $ReportName) -Value $reportMarkdown -Encoding UTF8
}
finally {
    Pop-Location
}
