# Run from repository root on Windows PowerShell.
# Requires: Python 3.14, uv, and a disposable PostgreSQL test database.
# This script does not modify migrations or push code.

$ErrorActionPreference = "Stop"

function Invoke-CheckedStep {
    param([string]$StepName, [string[]]$UvArguments)
    Write-Host "`n=== $StepName ===" -ForegroundColor Cyan
    & uv @UvArguments
    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed (exit code $LASTEXITCODE). Stop before pushing."
    }
}

Invoke-CheckedStep "Install dependencies using existing lock" @("sync", "--frozen")
Invoke-CheckedStep "Check Python syntax across repository" @("run", "python", "assets/scripts/check_python_syntax.py")
Invoke-CheckedStep "Check whether lock matches project dependencies" @("lock", "--check")
Invoke-CheckedStep "Django application checks" @("run", "python", "manage.py", "check")
Invoke-CheckedStep "Run PR143 reviewer regression tests" @(
    "run", "python", "manage.py", "test",
    "wearables.tests.test_pr143_queue_redis_followup",
    "wearables.tests.test_pr143_followup_fixes",
    "wearables.tests.test_older_pr143_security_cache_remap",
    "wearables.tests.test_reconnect_authorization_host",
    "wearables.tests.test_repeated_device_connect",
    "--verbosity", "2"
)
Invoke-CheckedStep "Run all wearable regression tests" @("run", "python", "manage.py", "test", "wearables.tests", "--verbosity", "2")
Invoke-CheckedStep "Run all backend tests" @("run", "python", "manage.py", "test", "--verbosity", "1")

Write-Host "`nAll configured local checks passed. Request review only after staging and Redis tests also pass." -ForegroundColor Green
