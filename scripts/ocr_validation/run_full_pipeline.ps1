# Run T2 through T6 sequentially on whatever sentences.jsonl contains.
# T1 must have produced sentences.jsonl before invoking this.
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

$timer = [System.Diagnostics.Stopwatch]::StartNew()

function step($name, $script) {
    $t = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    python -u $script 2>&1 | Tee-Object -FilePath "data\ocr_validation\_$name`_log.txt"
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] $name failed" -ForegroundColor Red; exit 1 }
    $t.Stop()
    Write-Host "[OK] $name in $('{0:N1}' -f $t.Elapsed.TotalSeconds)s" -ForegroundColor Green
}

step "T2_render_images"      "scripts\ocr_validation\02_render_images.py"
step "T3_run_ocr"            "scripts\ocr_validation\03_run_ocr.py"
step "T4_compute_metrics"    "scripts\ocr_validation\04_compute_metrics.py"
step "T5_analysis_charts"    "scripts\ocr_validation\05_analysis_charts.py"
step "T6_summary_report"     "scripts\ocr_validation\06_summary_report.py"
step "Visualization_HTML"    "scripts\ocr_validation\99_visualize.py"

$timer.Stop()
Write-Host "`n========================================" -ForegroundColor Yellow
Write-Host "Full pipeline done in $('{0:N1}' -f $timer.Elapsed.TotalSeconds)s" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow
