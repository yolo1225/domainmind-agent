param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("backup", "rebuild-index", "start", "start-fixture", "reset", "verify", "stop")]
    [string]$Action,
    [switch]$ConfirmReset
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$ProjectName = if ($env:COMPOSE_PROJECT_NAME) {
    $env:COMPOSE_PROJECT_NAME
} else {
    $candidate = ((Split-Path $ProjectRoot -Leaf).ToLowerInvariant() -replace "[^a-z0-9_-]", "").Trim("_-")
    if ($candidate -match "^[a-z](?:[a-z0-9_-]*[a-z0-9])?$") {
        $candidate
    } else {
        "cognivia"
    }
}
# Docker Compose otherwise derives a project name from the working directory.
# Submission packages live in localized, numbered folders that cannot form a
# valid image tag after Compose adds the service suffix.
$env:COMPOSE_PROJECT_NAME = $ProjectName

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Arguments -join ' ')"
    }
}

function Wait-Backend {
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health" -TimeoutSec 3
            if ($response.data.status -eq "ok") {
                return
            }
        } catch {
            # The service-state check below distinguishes startup delay from a crashed process.
        }

        $exitedServices = @(& docker compose ps --all --status exited --services backend 2>$null)
        if ($LASTEXITCODE -eq 0 -and $exitedServices -contains "backend") {
            Write-Host "Backend container exited before becoming healthy. Recent logs:"
            & docker compose logs --tail 100 backend
            throw "Backend container exited before becoming healthy."
        }

        Start-Sleep -Seconds 2
    }

    Write-Host "Backend health check timed out. Recent logs:"
    & docker compose logs --tail 100 backend
    throw "Backend did not become healthy within 120 seconds."
}

function Wait-Frontend {
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:5173/" -TimeoutSec 3 -UseBasicParsing
            if ($response.StatusCode -eq 200) {
                return
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "Frontend did not become healthy within 120 seconds."
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            return ([System.BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
        }
        finally {
            $stream.Dispose()
        }
    }
    finally {
        $algorithm.Dispose()
    }
}

function Get-BuildFingerprint {
    param([Parameter(Mandatory = $true)][string[]]$Paths)

    $parts = foreach ($path in $Paths) {
        $absolutePath = Join-Path $ProjectRoot $path
        if (-not (Test-Path $absolutePath)) {
            throw "Build input not found: $absolutePath"
        }
        "$path=$(Get-FileSha256 -Path $absolutePath)"
    }
    return $parts -join "`n"
}

function Ensure-ServiceImage {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][string[]]$BuildInputs
    )

    $stateDirectory = Join-Path $ProjectRoot "storage/exports/.docker-state"
    $stateFile = Join-Path $stateDirectory "$Service.build-fingerprint"
    $expectedFingerprint = Get-BuildFingerprint -Paths $BuildInputs
    $storedFingerprint = if (Test-Path $stateFile) {
        Get-Content $stateFile -Raw
    } else {
        ""
    }

    $imageIds = & docker images --quiet `
        --filter "label=com.docker.compose.project=$ProjectName" `
        --filter "label=com.docker.compose.service=$Service"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to inspect the Docker image for service: $Service"
    }

    if ($imageIds -and $storedFingerprint -eq $expectedFingerprint) {
        Write-Host "$Service image is up to date."
        return
    }

    Write-Host "Building $Service image..."
    Invoke-Compose -Arguments @("build", $Service)
    New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
    Set-Content -Path $stateFile -Value $expectedFingerprint -NoNewline
}

function Sync-FrontendDependencies {
    $lockFile = Join-Path $ProjectRoot "frontend/package-lock.json"
    if (-not (Test-Path $lockFile)) {
        throw "Frontend package lock file not found: $lockFile"
    }

    $expectedHash = Get-FileSha256 -Path $lockFile
    $currentHashOutput = & docker compose run --rm --no-deps frontend `
        sh -c 'cat node_modules/.cognivia-package-lock.sha256 2>/dev/null || true'
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to inspect the frontend dependency volume."
    }
    $currentHash = $currentHashOutput | Select-Object -Last 1
    if ($null -eq $currentHash) {
        $currentHash = ""
    } else {
        $currentHash = $currentHash.Trim()
    }

    if ($currentHash -eq $expectedHash) {
        Write-Host "Frontend dependencies are up to date."
        return
    }

    Write-Host "Synchronizing frontend dependencies..."
    Invoke-Compose -Arguments @("stop", "frontend")
    $installCommand = "npm ci && printf '%s' '$expectedHash' > node_modules/.cognivia-package-lock.sha256"
    Invoke-Compose -Arguments @("run", "--rm", "--no-deps", "frontend", "sh", "-c", $installCommand)
}

function Sync-CandidateIndex {
    param([switch]$Reset)

    $indexArguments = @(
        "exec", "--no-TTY", "backend", "python", "-m",
        "app.scripts.build_chroma_candidate_index", "--live", "--json"
    )
    if ($Reset) {
        $indexArguments += "--reset"
    }

    # The normal path does not request embeddings when the manifest and source
    # snapshot are unchanged. A new volume, or a manifest whose Chroma collection
    # was lost, needs one full build to restore the atomic manifest/collection pair.
    $output = & docker compose @indexArguments 2>&1
    $exitCode = $LASTEXITCODE
    $output | Write-Output
    if ($exitCode -eq 0) {
        return
    }

    $failureDetail = ($output -join "`n").Trim()
    if ($failureDetail -match "EmbeddingConfigurationError|embedding provider configuration is missing") {
        Write-Warning "Model configuration is incomplete; skipped candidate index vectorization. Configure models on the Model Settings page, then run ./scripts/demo.ps1 rebuild-index."
        return
    }
    if ($Reset) {
        throw "Candidate index rebuild failed: $failureDetail"
    }
    if ($failureDetail -notmatch "candidate manifest is missing|manifest active_collection does not exist") {
        throw "Candidate index sync failed: $failureDetail"
    }

    Write-Host "Candidate index is unavailable; rebuilding the live index..."
    Invoke-Compose -Arguments @("exec", "--no-TTY", "backend", "python", "-m", "app.scripts.build_chroma_candidate_index", "--live", "--json", "--reset")
}

function Test-DemoEnvironment {
    Wait-Backend
    $dependencies = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health/dependencies" -TimeoutSec 10
    Invoke-Compose -Arguments @("exec", "--no-TTY", "backend", "python", "-m", "app.scripts.validate_rag_seed")
    $questionFile = Get-Content "data/seed/diagnostic_questions.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($questionFile.Length -lt 60) {
        throw "Diagnostic seed validation failed: expected at least 60 questions."
    }
    $rag = $dependencies.data.rag
    $ragReasonProperty = $rag.PSObject.Properties["reason"]
    $ragReason = if ($null -eq $ragReasonProperty) { $null } else { $ragReasonProperty.Value }
    [pscustomobject]@{
        backend = "ok"
        database = $dependencies.data.database.status
        chroma = $dependencies.data.chroma.status
        live_models_ready = $dependencies.data.ready_for_live_demo
        fixture_enabled = $dependencies.data.fixture_enabled
        rag_ready = $rag.ready
        rag_reason = $ragReason
        knowledge_items = "validated"
        diagnostic_questions = $questionFile.Length
    } | Format-List
    if (-not $dependencies.data.ready_for_live_demo) {
        Write-Warning "Infrastructure is ready, but real-model acceptance is blocked until .env is configured."
    }
    if (-not $rag.ready) {
        if ([string]::IsNullOrWhiteSpace($ragReason)) {
            $ragReason = "unknown readiness failure"
        }
        Write-Warning "Candidate RAG is not ready: $ragReason. Configure the embedding provider and rebuild the candidate index before generating resources."
    }
}

function Backup-DemoEnvironment {
    $stamp = Get-Date -Format "yyyyMMddTHHmmss"
    $backupDirectory = Join-Path $ProjectRoot "reports/preflight/$stamp"
    New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null

    Invoke-Compose -Arguments @("ps") | Out-File (Join-Path $backupDirectory "compose-ps.txt") -Encoding utf8
    & docker images | Out-File (Join-Path $backupDirectory "docker-images.txt") -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to capture Docker image inventory."
    }
    try {
        Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health/dependencies" -TimeoutSec 10 |
            ConvertTo-Json -Depth 12 | Set-Content (Join-Path $backupDirectory "health-dependencies.json") -Encoding utf8
    } catch {
        "health endpoint unavailable: $($_.Exception.Message)" |
            Set-Content (Join-Path $backupDirectory "health-dependencies.txt") -Encoding utf8
    }

    $runningServices = @(& docker compose ps --status running --services)
    $mysqlVolume = & docker volume ls --quiet --filter "label=com.docker.compose.project=$ProjectName" --filter "label=com.docker.compose.volume=mysql_data"
    if ($LASTEXITCODE -ne 0 -or -not $mysqlVolume) {
        throw "Could not find the MySQL Docker volume for project '$ProjectName'."
    }
    if ($runningServices -contains "mysql") {
        $sqlPath = Join-Path $backupDirectory "mysql-yunchuan_zhihui.sql"
        & docker compose exec --no-TTY mysql sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' |
            Out-File $sqlPath -Encoding utf8
        if ($LASTEXITCODE -ne 0) {
            throw "MySQL backup failed."
        }
    } else {
        & docker run --rm `
            -v "$($mysqlVolume | Select-Object -First 1):/source:ro" `
            -v "${backupDirectory}:/backup" `
            alpine:3.20 tar -czf /backup/mysql-data.tgz -C /source .
        if ($LASTEXITCODE -ne 0) {
            throw "Stopped MySQL volume backup failed."
        }
    }

    $chromaVolume = & docker volume ls --quiet --filter "label=com.docker.compose.project=$ProjectName" --filter "label=com.docker.compose.volume=chroma_data"
    if ($LASTEXITCODE -ne 0 -or -not $chromaVolume) {
        throw "Could not find the Chroma Docker volume for project '$ProjectName'."
    }
    $archivePath = Join-Path $backupDirectory "chroma-data.tgz"
    & docker run --rm `
        -v "$($chromaVolume | Select-Object -First 1):/source:ro" `
        -v "${backupDirectory}:/backup" `
        alpine:3.20 tar -czf /backup/chroma-data.tgz -C /source .
    if ($LASTEXITCODE -ne 0) {
        throw "Chroma backup failed."
    }
    if ($runningServices -contains "backend") {
        Invoke-Compose -Arguments @("exec", "--no-TTY", "backend", "sh", "-c", "if [ -f /app/storage/candidate-index/ai_app_dev/manifest.json ]; then cat /app/storage/candidate-index/ai_app_dev/manifest.json; fi") |
            Set-Content (Join-Path $backupDirectory "candidate-manifest.json") -Encoding utf8
    } else {
        "backend was not running; candidate manifest was not available through the container." |
            Set-Content (Join-Path $backupDirectory "candidate-manifest.txt") -Encoding utf8
    }
    Write-Host "Preflight backup saved to $backupDirectory"
}

switch ($Action) {
    "backup" {
        Backup-DemoEnvironment
    }
    "rebuild-index" {
        Sync-CandidateIndex -Reset
        Write-Host "Candidate index rebuilt. Run ./scripts/demo.ps1 verify to check RAG readiness."
    }
    "start" {
        # Source is bind-mounted for development, so recreating containers
        # picks up code changes. Images rebuild only when dependencies change.
        Ensure-ServiceImage -Service "backend" -BuildInputs @("backend/Dockerfile", "backend/pyproject.toml")
        Ensure-ServiceImage -Service "frontend" -BuildInputs @("frontend/Dockerfile", "frontend/package.json", "frontend/package-lock.json")
        Sync-FrontendDependencies
        # Runtime dependencies retain durable state. Compose still recreates a
        # dependency when its service configuration changes, but an ordinary
        # source refresh should not churn the database or Chroma containers.
        Invoke-Compose -Arguments @("up", "--detach", "--no-build", "mysql", "chromadb", "redis")
        Invoke-Compose -Arguments @("up", "--detach", "--no-build", "--force-recreate", "backend")
        Wait-Backend
        Invoke-Compose -Arguments @("exec", "--no-TTY", "backend", "alembic", "upgrade", "head")
        Invoke-Compose -Arguments @("exec", "--no-TTY", "backend", "python", "-m", "app.scripts.init_admin")
        Invoke-Compose -Arguments @("exec", "--no-TTY", "backend", "python", "-m", "app.scripts.seed_data", "--json")
        Sync-CandidateIndex
        Invoke-Compose -Arguments @("up", "--detach", "--no-build", "--force-recreate", "frontend")
        Wait-Frontend
        Test-DemoEnvironment
        Write-Host "Demo environment: http://localhost:5173/"
    }
    "start-fixture" {
        # The submission launcher uses the hash-locked competition baseline.
        # It refuses ordinary seed data rather than mixing two domain baselines.
        Ensure-ServiceImage -Service "backend" -BuildInputs @("backend/Dockerfile", "backend/pyproject.toml")
        Ensure-ServiceImage -Service "frontend" -BuildInputs @("frontend/Dockerfile", "frontend/package.json", "frontend/package-lock.json")
        Sync-FrontendDependencies
        Invoke-Compose -Arguments @("up", "--detach", "--no-build", "mysql", "chromadb", "redis")
        Invoke-Compose -Arguments @("up", "--detach", "--no-build", "--force-recreate", "backend")
        Wait-Backend
        Invoke-Compose -Arguments @("exec", "--no-TTY", "backend", "alembic", "upgrade", "head")
        Invoke-Compose -Arguments @("exec", "--no-TTY", "backend", "python", "-m", "app.scripts.init_admin")
        Invoke-Compose -Arguments @(
            "exec", "--no-TTY", "backend", "python", "-m", "app.scripts.seed_data",
            "--fixture-dir", "/app/data/submission_fixtures/ai_app_dev_v1", "--json"
        )
        try {
            Sync-CandidateIndex
        } catch {
            # A judge can inspect the complete imported baseline without an
            # external embedding provider. Keep all other index failures fatal.
            $indexError = $_.Exception.Message
            if ($indexError -match "EmbeddingConfigurationError|embedding provider configuration is missing") {
                Write-Warning "Model configuration is incomplete; started without Candidate RAG. Configure the embedding provider and run ./scripts/demo.ps1 rebuild-index before live generation."
            } else {
                throw
            }
        }
        Invoke-Compose -Arguments @("up", "--detach", "--no-build", "--force-recreate", "frontend")
        Wait-Frontend
        Test-DemoEnvironment
        Write-Host "Submission fixture environment: http://localhost:5173/ (75 knowledge items, 106 relations, 465 active questions)"
    }
    "reset" {
        if (-not $ConfirmReset) {
            $answer = Read-Host "This deletes MySQL, Chroma and frontend volumes. Type RESET to continue"
            if ($answer -cne "RESET") {
                throw "Reset cancelled."
            }
        }
        Invoke-Compose -Arguments @("down", "--volumes")
        Ensure-ServiceImage -Service "backend" -BuildInputs @("backend/Dockerfile", "backend/pyproject.toml")
        Ensure-ServiceImage -Service "frontend" -BuildInputs @("frontend/Dockerfile", "frontend/package.json", "frontend/package-lock.json")
        Sync-FrontendDependencies
        Invoke-Compose -Arguments @("up", "--detach", "--no-build", "backend")
        Wait-Backend
        Invoke-Compose -Arguments @("exec", "--no-TTY", "backend", "alembic", "upgrade", "head")
        Invoke-Compose -Arguments @("exec", "--no-TTY", "backend", "python", "-m", "app.scripts.init_admin")
        Invoke-Compose -Arguments @("exec", "--no-TTY", "backend", "python", "-m", "app.scripts.seed_data", "--json")
        Sync-CandidateIndex -Reset
        Invoke-Compose -Arguments @("up", "--detach", "--no-build", "--force-recreate", "frontend")
        Wait-Frontend
        Test-DemoEnvironment
    }
    "verify" {
        Test-DemoEnvironment
    }
    "stop" {
        Invoke-Compose -Arguments @("stop")
    }
}
