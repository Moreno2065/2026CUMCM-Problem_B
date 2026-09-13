$ErrorActionPreference = 'Stop'
$packageRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$srcRoot = Split-Path -Parent $packageRoot
$workspaceRoot = Split-Path -Parent $srcRoot
$legacyRoot = Join-Path $srcRoot 'q3+4'
$records = [Collections.Generic.List[object]]::new()

function Copy-SourceFile {
    param([string]$Source, [string]$RelativeTarget, [string]$Role)
    $sourceFull = (Resolve-Path -LiteralPath $Source).Path
    $targetFull = [IO.Path]::GetFullPath((Join-Path $packageRoot $RelativeTarget))
    if (-not $targetFull.StartsWith($packageRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Target outside package: $targetFull"
    }
    $hash = (Get-FileHash -LiteralPath $sourceFull -Algorithm SHA256).Hash.ToLowerInvariant()
    if (Test-Path -LiteralPath $targetFull) {
        $existingHash = (Get-FileHash -LiteralPath $targetFull -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($existingHash -ne $hash) { throw "Snapshot differs; refusing overwrite: $RelativeTarget" }
    } else {
        New-Item -ItemType Directory -Path (Split-Path -Parent $targetFull) -Force | Out-Null
        Copy-Item -LiteralPath $sourceFull -Destination $targetFull
    }
    $targetHash = (Get-FileHash -LiteralPath $targetFull -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($targetHash -ne $hash) { throw "Copy hash mismatch: $RelativeTarget" }
    $records.Add([PSCustomObject]@{
        source = $sourceFull
        target = $RelativeTarget.Replace('\', '/')
        role = $Role
        bytes = (Get-Item -LiteralPath $targetFull).Length
        sha256 = $hash
    })
}

foreach ($name in @('B题.pdf', '附件1.docx', '附件2.docx')) {
    Copy-SourceFile (Join-Path $workspaceRoot "辅助材料/$name") "inputs/$name" 'official_problem_or_interface'
}

$legacyCode = Join-Path $legacyRoot 'code'
foreach ($dir in @('api', 'executor', 'experiment', 'geometry', 'policy', 'state', 'verifier', 'tests')) {
    $moduleRoot = Join-Path $legacyCode $dir
    foreach ($file in Get-ChildItem -LiteralPath $moduleRoot -Recurse -File -Filter '*.py' | Sort-Object FullName) {
        $rel = $file.FullName.Substring($legacyCode.Length + 1)
        Copy-SourceFile $file.FullName "baseline/code/$rel" 'legacy_source_or_test'
    }
}
foreach ($file in Get-ChildItem -LiteralPath $legacyCode -File -Filter '*.py' | Sort-Object Name) {
    Copy-SourceFile $file.FullName "baseline/code/$($file.Name)" 'legacy_entrypoint'
}
foreach ($dir in @('configs', 'models')) {
    foreach ($file in Get-ChildItem -LiteralPath (Join-Path $legacyCode $dir) -File | Sort-Object Name) {
        if ($file.Extension -in @('.yaml', '.json')) {
            Copy-SourceFile $file.FullName "baseline/code/$dir/$($file.Name)" 'legacy_config_or_trained_model_not_v2'
        }
    }
}

foreach ($rel in @(
    'docs/Q3_Q4_IMPLEMENTATION_SPEC_v2.2_CONSOLIDATED.md',
    'docs/Q3_Q4_MODEL_FREEZE_v2.2.json',
    'docs/Q3_Q4_CLAIM_EVIDENCE_CONTRACT_v1.0.md',
    'docs/experiments/q3_ml_experimental.md',
    'Q3_Q4_Paper_Model_Narrative_v2.0.md',
    'code/results/candidate_v1/performance_comparison_report.md',
    'code/results/q3_ml/budget_20260911/README.md'
)) {
    $name = [IO.Path]::GetFileName($rel)
    if ($rel -like '*budget*') { $name = 'legacy_ml_budget_README.md' }
    Copy-SourceFile (Join-Path $legacyRoot $rel) "baseline/docs/$name" 'legacy_document_historical'
}

$q3Run = Join-Path $legacyCode 'results/official_simulator/q3_202612004018_candidate_v3'
foreach ($name in @('metrics.json', 'actions.csv', 'observations.csv', 'config.yaml', 'provenance.json', 'run_report.json', 'verifier_report.json')) {
    Copy-SourceFile (Join-Path $q3Run $name) "baseline/evidence/q3_official_v3/$name" 'legacy_q3_http_run'
}
$q4Root = Join-Path $legacyCode 'results/e_branches_v1/matched/e_factorial_q4/e_combo_1000'
foreach ($caseDir in Get-ChildItem -LiteralPath $q4Root -Directory | Sort-Object Name) {
    foreach ($name in @('metrics.json', 'actions.csv', 'ground_truth.json', 'config.yaml', 'verifier_report.json')) {
        Copy-SourceFile (Join-Path $caseDir.FullName $name) "baseline/evidence/q4_e1_matched/$($caseDir.Name)/$name" 'legacy_q4_synthetic_matched'
    }
}
foreach ($name in @('selection_report.md', 'selection_report.json')) {
    Copy-SourceFile (Join-Path $legacyCode "results/e_branches_v1/matched/$name") "baseline/evidence/q4_$name" 'legacy_q4_factorial_selection'
}

$manifest = [ordered]@{
    format = 'q3q4-performance-v2-source-manifest-v1'
    created_at = (Get-Date).ToString('o')
    source_workspace = $workspaceRoot
    package_root = $packageRoot
    count = $records.Count
    files = @($records | Sort-Object target)
}
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText((Join-Path $packageRoot 'SOURCE_MANIFEST.json'), ($manifest | ConvertTo-Json -Depth 7), $utf8)
Write-Output "Copied and hash-verified $($records.Count) source files into $packageRoot"
