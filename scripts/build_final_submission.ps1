[CmdletBinding()]
param(
    [ValidateSet("Draft", "Final")]
    [string]$Mode = "Draft",
    [string]$SubmissionContainer = "",
    [string]$ArchiveRoot = "",
    [string]$PackageName = "学校—申报人—Cognivia—联系电话",
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($SubmissionContainer)) {
    $SubmissionContainer = Join-Path (Split-Path -Parent $ProjectRoot) "Cognivia_比赛最终提交包_待冻结"
}
if ([string]::IsNullOrWhiteSpace($ArchiveRoot)) {
    $ArchiveRoot = Join-Path (Split-Path -Parent $ProjectRoot) "Cognivia_开发归档_不提交"
}
$SubmissionContainer = [System.IO.Path]::GetFullPath($SubmissionContainer)
$ArchiveRoot = [System.IO.Path]::GetFullPath($ArchiveRoot)
$PackageRoot = Join-Path $SubmissionContainer $PackageName
$FreezeInputRoot = Join-Path $SubmissionContainer "_冻结输入"
$FixtureRelativePath = "data\submission_fixtures\ai_app_dev_v1"
$FixtureRoot = Join-Path $ProjectRoot $FixtureRelativePath
$PrimaryDomainDataRoot = "04_测试数据与案例\01_主领域_人工智能应用开发实训_ai_app_dev"
$PrimaryDomainFixtureRelativePath = "$PrimaryDomainDataRoot\02_可执行启动夹具\ai_app_dev_submission_fixture_v1"
$SmartFixtureRelativePath = "data\submission_fixtures\smart_manufacturing_v1"
$SmartFixtureRoot = Join-Path $ProjectRoot $SmartFixtureRelativePath
$SecondaryDomainDataRoot = "04_测试数据与案例\02_第二领域_智能制造实训_smart_manufacturing"
$SecondaryDomainFixtureRelativePath = "$SecondaryDomainDataRoot\02_可执行启动夹具\smart_manufacturing_submission_fixture_v1"
$SmartEvidenceRoot = Join-Path $ProjectRoot "deliverables\smart_manufacturing-test-data"
$SmartLiveReport = Join-Path $ProjectRoot "reports\demo\smart-manufacturing-latest.json"

$ExcludedSegments = @(
    ".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache",
    "dist", "build", "coverage", "chroma", "candidate-index", "backups"
)
$ExcludedExtensions = @(".pyc", ".pyo", ".log", ".sql", ".sqlite", ".sqlite3", ".bak")

function Assert-Exists {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required source is missing: $Path"
    }
}

function Ensure-Directory {
    param([Parameter(Mandatory = $true)][string]$Path)
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Copy-FileExact {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    Assert-Exists -Path $Source
    Ensure-Directory -Path (Split-Path -Parent $Destination)
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function Test-ExcludedPath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    $parts = $RelativePath -split "[\\/]"
    if ($parts | Where-Object { $ExcludedSegments -contains $_ }) {
        return $true
    }
    $leaf = Split-Path -Leaf $RelativePath
    if ($leaf -eq ".env" -or [System.IO.Path]::GetExtension($leaf).ToLowerInvariant() -in $ExcludedExtensions) {
        return $true
    }
    return $false
}

function Copy-TreeFiltered {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    Assert-Exists -Path $Source
    $sourceRoot = [System.IO.Path]::GetFullPath($Source)
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart([char[]]@([char]92, [char]47))
        if (-not (Test-ExcludedPath -RelativePath $relative)) {
            Copy-FileExact -Source $_.FullName -Destination (Join-Path $Destination $relative)
        }
    }
}

function Copy-TreeForArchive {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    Assert-Exists -Path $Source
    $sourceRoot = [System.IO.Path]::GetFullPath($Source)
    $archiveCacheSegments = @(".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "build", "coverage")
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart([char[]]@([char]92, [char]47))
        $segments = $relative -split "[\\/]"
        if (-not ($segments | Where-Object { $archiveCacheSegments -contains $_ })) {
            Copy-FileExact -Source $_.FullName -Destination (Join-Path $Destination $relative)
        }
    }
}

function Write-Utf8File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Content
    )
    Ensure-Directory -Path (Split-Path -Parent $Path)
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

function Get-RelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $baseUri = [System.Uri]::new(([System.IO.Path]::GetFullPath($BasePath).TrimEnd([char]92, [char]47) + [System.IO.Path]::DirectorySeparatorChar))
    $pathUri = [System.Uri]::new([System.IO.Path]::GetFullPath($Path))
    return [System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($pathUri).ToString()).Replace("/", [string][char]92)
}

function Get-Json {
    param([Parameter(Mandatory = $true)][string]$Path)
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Test-Fixture {
    param([Parameter(Mandatory = $true)][string]$Root)
    $manifest = Get-Json -Path (Join-Path $Root "manifest.json")
    if ($manifest.fixture_version -ne "ai_app_dev_submission_fixture_v1" -or $manifest.domain_code -ne "ai_app_dev") {
        throw "Unexpected submission fixture identity."
    }
    $knowledge = Get-Json -Path (Join-Path $Root "knowledge_items.json")
    $relations = Get-Json -Path (Join-Path $Root "relations.json")
    $questions = Get-Json -Path (Join-Path $Root "diagnostic_questions.json")
    if ($knowledge.Count -ne 75 -or $relations.Count -ne 106 -or $questions.Count -ne 465) {
        throw "Fixture counts must be 75 knowledge items, 106 relations and 465 questions; actual $($knowledge.Count) / $($relations.Count) / $($questions.Count)."
    }
    $knowledgeIds = @{}
    foreach ($item in $knowledge) {
        $knowledgeId = [string]$item.knowledge_id
        if ([string]::IsNullOrWhiteSpace($knowledgeId) -or $knowledgeIds.ContainsKey($knowledgeId)) {
            throw "Fixture knowledge IDs must be unique and non-empty."
        }
        $knowledgeIds[$knowledgeId] = $true
    }
    $relationCounts = @{}
    $relationKeys = @{}
    foreach ($relation in $relations) {
        $relationType = [string]$relation.relation_type
        $sourceId = [string]$relation.source_knowledge_id
        $targetId = [string]$relation.target_knowledge_id
        $relationKey = "$relationType|$sourceId|$targetId"
        if ($relationType -notin @("prerequisite", "related") -or -not $knowledgeIds.ContainsKey($sourceId) -or -not $knowledgeIds.ContainsKey($targetId) -or $sourceId -eq $targetId -or $relationKeys.ContainsKey($relationKey)) {
            throw "Fixture relation reference is invalid."
        }
        $relationKeys[$relationKey] = $true
        if (-not $relationCounts.ContainsKey($relationType)) { $relationCounts[$relationType] = 0 }
        $relationCounts[$relationType]++
    }
    if ($relationCounts["prerequisite"] -ne 92 -or $relationCounts["related"] -ne 14 -or $relationCounts.Count -ne 2) {
        throw "Fixture relation distribution must be 92 prerequisite and 14 related."
    }
    $purposeCounts = @{}
    $purposeCoverage = @{
        diagnosis = @{}
        graded_quiz = @{}
        mastery_validation = @{}
    }
    $questionIds = @{}
    $externalIds = @{}
    foreach ($question in $questions) {
        $questionId = [string]$question.question_id
        $externalId = [string]$question.question_external_id
        $knowledgeId = [string]$question.knowledge_id
        $uses = @($question.answer_key.question_bank_uses)
        if ([string]::IsNullOrWhiteSpace($questionId) -or $questionIds.ContainsKey($questionId) -or [string]::IsNullOrWhiteSpace($externalId) -or $externalIds.ContainsKey($externalId) -or -not $knowledgeIds.ContainsKey($knowledgeId) -or $uses.Count -ne 1) {
            throw "Fixture question identity or reference is invalid."
        }
        $purpose = [string]$uses[0]
        if ($purpose -notin $purposeCoverage.Keys) { throw "Fixture question purpose is invalid." }
        $questionIds[$questionId] = $true
        $externalIds[$externalId] = $true
        if (-not $purposeCounts.ContainsKey($purpose)) { $purposeCounts[$purpose] = 0 }
        $purposeCounts[$purpose]++
        $purposeCoverage[$purpose][$knowledgeId] = $true
    }
    if ($purposeCounts["diagnosis"] -ne 90 -or $purposeCounts["graded_quiz"] -ne 225 -or $purposeCounts["mastery_validation"] -ne 150 -or $purposeCounts.Count -ne 3) {
        throw "Fixture question purpose distribution must be 90 / 225 / 150."
    }
    $invalidCoverageCounts = @($purposeCoverage.Values | ForEach-Object { $_.Count } | Where-Object { $_ -ne 75 })
    if ($invalidCoverageCounts.Count -ne 0) {
        throw "Each fixture question purpose must cover all 75 knowledge items."
    }
    foreach ($property in $manifest.files.PSObject.Properties) {
        $file = Join-Path $Root $property.Name
        Assert-Exists -Path $file
        $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$property.Value.sha256) {
            throw "Fixture hash mismatch: $($property.Name)"
        }
    }
    return $manifest
}

function Test-SmartManufacturingFixture {
    param([Parameter(Mandatory = $true)][string]$Root)

    $manifest = Get-Json -Path (Join-Path $Root "manifest.json")
    if ($manifest.fixture_version -ne "smart_manufacturing_submission_fixture_v1" -or $manifest.domain_code -ne "smart_manufacturing") {
        throw "Unexpected smart manufacturing submission fixture identity."
    }
    if ($manifest.counts.knowledge_items -ne 67 -or $manifest.counts.knowledge_relations -ne 49 -or $manifest.counts.active_questions -ne 402 -or $manifest.counts.evaluation_cases -ne 0 -or $manifest.counts.manual_demo_cases -ne 3 -or $manifest.counts.learner_profiles -ne 3) {
        throw "Unexpected smart manufacturing fixture manifest counts."
    }
    $manualAssets = $manifest.manual_import_assets
    if ($null -eq $manualAssets -or [string]::IsNullOrWhiteSpace([string]$manualAssets.knowledge_package) -or [string]::IsNullOrWhiteSpace([string]$manualAssets.question_workbook)) {
        throw "Smart manufacturing manual import asset pair is missing from the manifest."
    }
    Assert-Exists -Path (Join-Path $Root ([string]$manualAssets.knowledge_package))
    Assert-Exists -Path (Join-Path $Root ([string]$manualAssets.question_workbook))

    $knowledge = Get-Json -Path (Join-Path $Root "knowledge_items.json")
    $relations = Get-Json -Path (Join-Path $Root "relations.json")
    $questions = Get-Json -Path (Join-Path $Root "diagnostic_questions.json")
    $profiles = Get-Json -Path (Join-Path $Root "learner_profiles.json")
    $demoCases = Get-Json -Path (Join-Path $Root "manual_demo_cases.json")
    if ($knowledge.Count -ne 67 -or $relations.Count -ne 49 -or $questions.Count -ne 402 -or $profiles.Count -ne 3 -or $demoCases.cases.Count -ne 3) {
        throw "Smart manufacturing fixture content counts do not match the locked manifest."
    }
    if (Get-ChildItem -LiteralPath $Root -Recurse -File -Filter "evaluation_cases*.json" | Select-Object -First 1) {
        throw "Smart manufacturing fixture must not contain offline evaluation cases."
    }

    $knowledgeIds = @{}
    foreach ($item in $knowledge) {
        $knowledgeId = [string]$item.knowledge_id
        if ([string]::IsNullOrWhiteSpace($knowledgeId) -or $knowledgeIds.ContainsKey($knowledgeId)) {
            throw "Smart manufacturing knowledge IDs must be unique and non-empty."
        }
        $knowledgeIds[$knowledgeId] = $true
    }
    $relationKeys = @{}
    foreach ($relation in $relations) {
        $sourceId = [string]$relation.source_knowledge_id
        $targetId = [string]$relation.target_knowledge_id
        $relationKey = "$($relation.relation_type)|$sourceId|$targetId"
        if ($relation.relation_type -ne "next_step" -or -not $knowledgeIds.ContainsKey($sourceId) -or -not $knowledgeIds.ContainsKey($targetId) -or $sourceId -eq $targetId -or $relationKeys.ContainsKey($relationKey) -or $relation.generation_method -ne "curriculum_rule" -or $relation.evidence.evidence_kind -ne "curriculum_rule") {
            throw "Smart manufacturing curriculum relation is invalid."
        }
        $relationKeys[$relationKey] = $true
    }

    $purposeCounts = @{}
    $purposeCoverage = @{
        diagnosis = @{}
        graded_quiz = @{}
        mastery_validation = @{}
    }
    $questionIds = @{}
    $externalIds = @{}
    foreach ($question in $questions) {
        $questionId = [string]$question.question_id
        $externalId = [string]$question.question_external_id
        $knowledgeId = [string]$question.knowledge_id
        $uses = @($question.answer_key.question_bank_uses)
        if ([string]::IsNullOrWhiteSpace($questionId) -or $questionIds.ContainsKey($questionId) -or [string]::IsNullOrWhiteSpace($externalId) -or $externalIds.ContainsKey($externalId) -or -not $knowledgeIds.ContainsKey($knowledgeId) -or $question.status -ne "active" -or $uses.Count -ne 1) {
            throw "Smart manufacturing question identity, status or reference is invalid."
        }
        $purpose = [string]$uses[0]
        if (-not $purposeCoverage.ContainsKey($purpose)) { throw "Smart manufacturing question purpose is invalid." }
        $questionIds[$questionId] = $true
        $externalIds[$externalId] = $true
        if (-not $purposeCounts.ContainsKey($purpose)) { $purposeCounts[$purpose] = 0 }
        $purposeCounts[$purpose]++
        if (-not $purposeCoverage[$purpose].ContainsKey($knowledgeId)) { $purposeCoverage[$purpose][$knowledgeId] = 0 }
        $purposeCoverage[$purpose][$knowledgeId]++
    }
    if ($purposeCounts["diagnosis"] -ne 67 -or $purposeCounts["graded_quiz"] -ne 201 -or $purposeCounts["mastery_validation"] -ne 134 -or $purposeCounts.Count -ne 3) {
        throw "Smart manufacturing question purpose distribution must be 67 / 201 / 134."
    }
    foreach ($knowledgeId in $knowledgeIds.Keys) {
        if ($purposeCoverage["diagnosis"][$knowledgeId] -ne 1 -or $purposeCoverage["graded_quiz"][$knowledgeId] -ne 3 -or $purposeCoverage["mastery_validation"][$knowledgeId] -ne 2) {
            throw "Smart manufacturing formal-question six-slot coverage is incomplete: $knowledgeId"
        }
    }

    $profileIds = @{}
    foreach ($profile in $profiles) {
        if ([string]::IsNullOrWhiteSpace([string]$profile.profile_id) -or $profileIds.ContainsKey([string]$profile.profile_id) -or $profile.domain_code -ne "smart_manufacturing") {
            throw "Smart manufacturing learner profile is invalid."
        }
        $profileIds[[string]$profile.profile_id] = $true
    }
    $expectedCaseIds = @("SM-DEMO-BEGINNER-INITIAL", "SM-DEMO-INTERMEDIATE-REVIEW", "SM-DEMO-ADVANCED-CHALLENGE")
    $actualCaseIds = @($demoCases.cases | ForEach-Object { [string]$_.case_id } | Sort-Object)
    if ((Compare-Object -ReferenceObject ($expectedCaseIds | Sort-Object) -DifferenceObject $actualCaseIds)) {
        throw "Smart manufacturing manual demo cases are incomplete."
    }

    foreach ($property in $manifest.files.PSObject.Properties) {
        $file = Join-Path $Root $property.Name
        Assert-Exists -Path $file
        $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$property.Value.sha256) {
            throw "Smart manufacturing fixture hash mismatch: $($property.Name)"
        }
    }
    return $manifest
}

function Test-SmartManufacturingEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$EvidenceRoot,
        [Parameter(Mandatory = $true)][string]$ReportPath,
        [string]$CaseRelativePath = "脱敏学习者案例",
        [string]$ExportRelativePath = "资源导出",
        [string]$EvidenceNoteRelativePath = "运行报告.md"
    )

    Assert-Exists -Path $EvidenceRoot
    Assert-Exists -Path $ReportPath
    foreach ($file in @("README.md", $EvidenceNoteRelativePath)) { Assert-Exists -Path (Join-Path $EvidenceRoot $file) }
    $report = Get-Json -Path $ReportPath
    if ($report.status -ne "passed" -or $report.provider_mode -ne "live" -or $report.domain_code -ne "smart_manufacturing" -or @($report.cases).Count -ne 3) {
        throw "Smart manufacturing live demo report is incomplete or not passed."
    }
    $seenCases = @{}
    foreach ($caseResult in @($report.cases)) {
        $caseId = [string]$caseResult.case.case_id
        if ([string]::IsNullOrWhiteSpace($caseId) -or $seenCases.ContainsKey($caseId) -or $caseResult.status -ne "passed") {
            throw "Smart manufacturing live demo case is invalid."
        }
        $seenCases[$caseId] = $true
        Assert-Exists -Path (Join-Path $EvidenceRoot "$CaseRelativePath\$caseId.md")
        $resources = @($caseResult.baseline.resources)
        if ($resources.Count -ne 3) { throw "Smart manufacturing demo case has incomplete resource evidence: $caseId" }
        foreach ($resource in $resources) {
            $relativeExport = [string]$resource.submission_export_file
            $expectedHash = ([string]$resource.export.file_hash).Replace("sha256:", "")
            $exportFile = $relativeExport.Substring($relativeExport.LastIndexOf([char]92) + 1)
            if ($exportFile -eq $relativeExport) { $exportFile = $relativeExport.Substring($relativeExport.LastIndexOf([char]47) + 1) }
            $exportPath = Join-Path $EvidenceRoot "$ExportRelativePath\$exportFile"
            Assert-Exists -Path $exportPath
            if ((Get-FileHash -LiteralPath $exportPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
                throw "Smart manufacturing resource export hash mismatch: $relativeExport"
            }
        }
    }
    if ($seenCases.Count -ne 3) { throw "Smart manufacturing live demo case coverage is incomplete." }
    if ($report.cases[1].follow_up.recommended_action -ne "review" -or $report.cases[1].follow_up.task.profile_update_required[0] -ne $false) {
        throw "Smart manufacturing intermediate feedback evidence is invalid."
    }
    if ($report.cases[2].follow_up.recommended_action -ne "challenge") {
        throw "Smart manufacturing advanced challenge evidence is invalid."
    }
}

function Write-SmartManufacturingCaseEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$ReportPath,
        [Parameter(Mandatory = $true)][string]$ExportRoot,
        [Parameter(Mandatory = $true)][string]$DestinationRoot
    )

    Assert-Exists -Path $ReportPath
    Assert-Exists -Path $ExportRoot
    $report = Get-Json -Path $ReportPath
    if ($report.status -ne "passed" -or $report.provider_mode -ne "live" -or $report.domain_code -ne "smart_manufacturing" -or @($report.cases).Count -ne 3) {
        throw "Smart manufacturing report cannot be converted into submission cases."
    }

    Ensure-Directory -Path $DestinationRoot
    $readme = @'
# 三组差异化学习者完整输入输出

每个案例目录均按统一证据结构保存：输入画像、任务与 Agent 协同摘要、审核摘要、反馈决策和三类学习资源导出。
所有标识均为合成测试标识；不保存完整作答文本、原始 Agent payload、模型密钥或数据库备份。
'@
    Write-Utf8File -Path (Join-Path $DestinationRoot "README.md") -Content $readme

    $seen = @{}
    foreach ($caseResult in @($report.cases)) {
        $case = $caseResult.case
        $caseId = [string]$case.case_id
        if ([string]::IsNullOrWhiteSpace($caseId) -or $seen.ContainsKey($caseId) -or $caseResult.status -ne "passed") {
            throw "Smart manufacturing report contains an invalid case."
        }
        $seen[$caseId] = $true
        $caseRoot = Join-Path $DestinationRoot $caseId
        Ensure-Directory -Path $caseRoot
        $baseline = $caseResult.baseline
        $followUpProperty = $caseResult.PSObject.Properties["follow_up"]
        $followUp = if ($null -eq $followUpProperty) { $null } else { $followUpProperty.Value }
        $followUpTask = if ($null -eq $followUp) { $null } else { $followUp.task }
        $resources = @($baseline.resources)
        if ($resources.Count -ne 3) {
            throw "Smart manufacturing case has incomplete baseline resources: $caseId"
        }

        $caseInput = [ordered]@{
            schema_version = "submission-live-case-v1"
            case_id = $caseId
            domain_code = "smart_manufacturing"
            learner_id = $case.learner_id
            profile_id = $case.profile_id
            profile_type = $case.profile_type
            scenario = $case.scenario
            profile_input = $caseResult.input_profile
            weak_knowledge_ids = @($case.weak_knowledge_ids)
            learning_goal = $case.learning_goal
            resource_types = @($case.resource_types)
            expected_follow_up = $case.follow_up
        }
        Write-Utf8File -Path (Join-Path $caseRoot "case-input.json") -Content ($caseInput | ConvertTo-Json -Depth 16)

        $taskSummary = [ordered]@{
            schema_version = "submission-task-summary-v1"
            case_id = $caseId
            initial_task = [ordered]@{
                task_id = $baseline.task_id
                thread_id = $baseline.thread_id
                status = $baseline.task_status
                trigger_type = $baseline.trigger_type
                decision = $baseline.decision
                revision_count = $baseline.revision_count
                resource_types = @($resources | ForEach-Object { $_.resource_type })
            }
            follow_up_task = if ($null -eq $followUpTask) { $null } else { [ordered]@{
                task_id = $followUpTask.task_id
                thread_id = $followUpTask.thread_id
                status = $followUpTask.task_status
                trigger_type = $followUpTask.trigger_type
                decision = $followUpTask.decision
                revision_count = $followUpTask.revision_count
            } }
        }
        Write-Utf8File -Path (Join-Path $caseRoot "task-summary.json") -Content ($taskSummary | ConvertTo-Json -Depth 12)

        $agentTrace = [ordered]@{
            schema_version = "submission-agent-trace-summary-v1"
            case_id = $caseId
            contract_version = "agent-contract-v10"
            initial_task_id = $baseline.task_id
            initial_agent_runs = @($baseline.agent_runs)
            initial_structured_handoff_count = $baseline.structured_handoff_count
            follow_up_task_id = if ($null -eq $followUpTask) { $null } else { $followUpTask.task_id }
            follow_up_agent_runs = if ($null -eq $followUpTask) { @() } else { @($followUpTask.agent_runs) }
            follow_up_structured_handoff_count = if ($null -eq $followUpTask) { 0 } else { $followUpTask.structured_handoff_count }
        }
        Write-Utf8File -Path (Join-Path $caseRoot "agent-trace-summary.json") -Content ($agentTrace | ConvertTo-Json -Depth 16)

        $reviewSummary = [ordered]@{
            schema_version = "submission-review-summary-v1"
            case_id = $caseId
            primary_review_role = "primary_review_model"
            secondary_review_role = "secondary_review_model"
            initial_review_roles = @($baseline.review_model_roles)
            resources = @($resources | ForEach-Object { [ordered]@{
                resource_id = $_.resource_id
                resource_type = $_.resource_type
                difficulty = $_.difficulty
                review_status = $_.review_status
                source_knowledge_ids = @($_.source_knowledge_ids)
                quality_metrics = $_.quality_metrics
            } })
            follow_up_review_roles = if ($null -eq $followUpTask) { @() } else { @($followUpTask.review_model_roles) }
        }
        Write-Utf8File -Path (Join-Path $caseRoot "review-summary.json") -Content ($reviewSummary | ConvertTo-Json -Depth 16)

        $feedbackDecision = if ($null -eq $followUp) {
            [ordered]@{
                schema_version = "submission-feedback-decision-v1"
                case_id = $caseId
                type = "initial_generation"
                recommended_action = "no_follow_up"
                profile_update_required = $false
            }
        } else {
            $feedbackIdProperty = $followUp.PSObject.Properties["feedback_id"]
            $profileUpdateProperty = $followUp.PSObject.Properties["profile_update_required"]
            [ordered]@{
                schema_version = "submission-feedback-decision-v1"
                case_id = $caseId
                feedback_id = if ($null -eq $feedbackIdProperty) { $null } else { $feedbackIdProperty.Value }
                type = $case.follow_up.type
                recommended_action = $followUp.recommended_action
                profile_update_required = if ($null -eq $profileUpdateProperty) { $null } else { $profileUpdateProperty.Value }
                follow_up_task_id = $followUpTask.task_id
                follow_up_status = $followUpTask.task_status
            }
        }
        Write-Utf8File -Path (Join-Path $caseRoot "feedback-decision.json") -Content ($feedbackDecision | ConvertTo-Json -Depth 12)

        $resourceDirectory = Join-Path $caseRoot "resource-export"
        Ensure-Directory -Path $resourceDirectory
        foreach ($resource in $resources) {
            $submissionPath = ([string]$resource.submission_export_file).Replace("/", "\\")
            $exportName = Split-Path -Leaf $submissionPath
            $source = Join-Path $ExportRoot $exportName
            $target = Join-Path $resourceDirectory "$($resource.resource_type).md"
            Copy-FileExact -Source $source -Destination $target
            $expectedHash = ([string]$resource.export.file_hash).Replace("sha256:", "")
            $actualHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actualHash -ne $expectedHash) {
                throw "Smart manufacturing resource hash mismatch while packaging: $caseId/$($resource.resource_type)"
            }
        }

        $hashes = [ordered]@{}
        Get-ChildItem -LiteralPath $caseRoot -Recurse -File | Where-Object { $_.Name -ne "manifest.json" } | Sort-Object FullName | ForEach-Object {
            $relative = $_.FullName.Substring($caseRoot.Length).TrimStart([char[]]@([char]92, [char]47)).Replace("\\", "/")
            $hashes[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        $manifest = [ordered]@{
            schema_version = "submission-live-case-manifest-v1"
            case_id = $caseId
            fixture_version = $report.fixture_version
            captured_at = $report.evaluated_at
            initial_task_id = $baseline.task_id
            follow_up_task_id = if ($null -eq $followUpTask) { $null } else { $followUpTask.task_id }
            files = $hashes
        }
        Write-Utf8File -Path (Join-Path $caseRoot "manifest.json") -Content ($manifest | ConvertTo-Json -Depth 12)
    }
    if ($seen.Count -ne 3) {
        throw "Smart manufacturing case conversion is incomplete."
    }
}

function Assert-EqualHash {
    param([string]$Left, [string]$Right, [string]$Label)
    Assert-Exists -Path $Left
    Assert-Exists -Path $Right
    $leftHash = (Get-FileHash -LiteralPath $Left -Algorithm SHA256).Hash.ToLowerInvariant()
    $rightHash = (Get-FileHash -LiteralPath $Right -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($leftHash -ne $rightHash) { throw "Duplicated submission data diverged: $Label" }
}

function New-FreezeInputGuide {
    Ensure-Directory -Path $FreezeInputRoot
    $guide = @'
# 冻结输入区（不随最终压缩包提交）

将最终冻结前才产生或审核的材料放到本目录。执行 `scripts/build_final_submission.ps1 -Mode Final -Rebuild`
时，脚本会把它们复制到正式提交根目录并进行完整性校验。

必需路径：

- `01_参赛报名表/已审核报名表.pdf`
- `02_作品材料/03_答辩PPT.pdf`
- `02_作品材料/04_系统演示视频.mp4`（不超过 10 分钟）
- `04_三组差异化案例/初学者_完整输入输出/`
- `04_三组差异化案例/进阶学习者_完整输入输出/`
- `04_三组差异化案例/高阶学习者_完整输入输出/`
- `06_正式运行结果与评测报告/formal-result.json`
- `06_正式运行结果与评测报告/formal-result.xlsx`
- `06_正式运行结果与评测报告/metric-report.md`

每组真实案例目录至少放入：`case-input.json`、`agent-trace-summary.json`、`resource-export/`
（至少一个导出资源）、`review-summary.json` 和 `feedback-decision.json`。内容必须由当前版本真实接口流程
产生并经脱敏处理；不要放密钥、数据库备份、完整日志或历史预冻结结果。
'@
    Write-Utf8File -Path (Join-Path $FreezeInputRoot "README.md") -Content $guide
}

function New-DraftPlaceholders {
    $note = @'
# 待补材料

本目录在 Draft 中仅用于标明冻结前缺口，不是正式提交证据。请将真实材料放入提交包外层的
`_冻结输入`，然后运行 `scripts/build_final_submission.ps1 -Mode Final -Rebuild` 重新生成正式包。
'@
    foreach ($folder in @("01_参赛报名表", "02_作品材料")) {
        Write-Utf8File -Path (Join-Path $PackageRoot "$folder\待补材料说明.md") -Content $note
    }
    $reportRoot = Join-Path $PackageRoot "06_正式运行结果与评测报告"
    if (-not (Test-Path -LiteralPath (Join-Path $reportRoot "formal-result.json"))) {
        Write-Utf8File -Path (Join-Path $reportRoot "待补材料说明.md") -Content $note
    }
    foreach ($caseName in @("初学者_完整输入输出", "进阶学习者_完整输入输出", "高阶学习者_完整输入输出")) {
        $caseRoot = Join-Path $PackageRoot "$PrimaryDomainDataRoot\05_差异化学习者真实案例\$caseName"
        if (-not (Test-Path -LiteralPath (Join-Path $caseRoot "case-input.json"))) {
            Write-Utf8File -Path (Join-Path $caseRoot "待补真实运行证据.md") -Content $note
        }
    }
}

function Copy-DraftEvidenceInputs {
    $reportPaths = @(
        "06_正式运行结果与评测报告\formal-result.json",
        "06_正式运行结果与评测报告\formal-result.xlsx",
        "06_正式运行结果与评测报告\metric-report.md"
    )
    if (@($reportPaths | Where-Object { -not (Test-Path -LiteralPath (Join-Path $FreezeInputRoot $_)) }).Count -eq 0) {
        foreach ($relativePath in $reportPaths) {
            Copy-FileExact -Source (Join-Path $FreezeInputRoot $relativePath) -Destination (Join-Path $PackageRoot $relativePath)
        }
    }
    foreach ($caseName in @("初学者_完整输入输出", "进阶学习者_完整输入输出", "高阶学习者_完整输入输出")) {
        $source = Join-Path $FreezeInputRoot "04_三组差异化案例\$caseName"
        if (Test-Path -LiteralPath $source) {
            Copy-TreeFiltered -Source $source -Destination (Join-Path $PackageRoot "$PrimaryDomainDataRoot\05_差异化学习者真实案例\$caseName")
        }
    }
}

function Copy-FinalInputs {
    $paths = @(
        @{ Relative = "01_参赛报名表\已审核报名表.pdf" },
        @{ Relative = "02_作品材料\03_答辩PPT.pdf" },
        @{ Relative = "02_作品材料\04_系统演示视频.mp4" },
        @{ Relative = "06_正式运行结果与评测报告\formal-result.json" },
        @{ Relative = "06_正式运行结果与评测报告\formal-result.xlsx" },
        @{ Relative = "06_正式运行结果与评测报告\metric-report.md" }
    )
    foreach ($item in $paths) {
        Copy-FileExact -Source (Join-Path $FreezeInputRoot $item.Relative) -Destination (Join-Path $PackageRoot $item.Relative)
    }
    foreach ($caseName in @("初学者_完整输入输出", "进阶学习者_完整输入输出", "高阶学习者_完整输入输出")) {
        $source = Join-Path $FreezeInputRoot "04_三组差异化案例\$caseName"
        Assert-Exists -Path $source
        Copy-TreeFiltered -Source $source -Destination (Join-Path $PackageRoot "$PrimaryDomainDataRoot\05_差异化学习者真实案例\$caseName")
    }
}

function Test-FinalInputs {
    foreach ($caseName in @("初学者_完整输入输出", "进阶学习者_完整输入输出", "高阶学习者_完整输入输出")) {
        $caseRoot = Join-Path $PackageRoot "$PrimaryDomainDataRoot\05_差异化学习者真实案例\$caseName"
        foreach ($file in @("case-input.json", "agent-trace-summary.json", "review-summary.json", "feedback-decision.json")) {
            $path = Join-Path $caseRoot $file
            Assert-Exists -Path $path
            $null = Get-Json -Path $path
        }
        $resourceDirectory = Join-Path $caseRoot "resource-export"
        Assert-Exists -Path $resourceDirectory
        if (-not (Get-ChildItem -LiteralPath $resourceDirectory -Recurse -File | Select-Object -First 1)) {
            throw "Real case has no exported resource: $caseName"
        }
    }
    $video = Join-Path $PackageRoot "02_作品材料\04_系统演示视频.mp4"
    if ((Get-Item -LiteralPath $video).Length -eq 0) { throw "Demo video is empty." }
    $videoMinutes = (Get-Item -LiteralPath $video).LastWriteTime # Duration requires a media parser; verify this manually before freeze.
}

function Test-SubmissionSafety {
    param([Parameter(Mandatory = $true)][string]$Root)
    $forbidden = Get-ChildItem -LiteralPath $Root -Force -Recurse -File | Where-Object {
        $relative = Get-RelativePath -BasePath $Root -Path $_.FullName
        Test-ExcludedPath -RelativePath $relative
    }
    if ($forbidden) {
        $listed = ($forbidden | Select-Object -First 5 -ExpandProperty FullName) -join "; "
        throw "Forbidden cache, secret, backup or log entered submission package: $listed"
    }
    $placeholders = Get-ChildItem -LiteralPath $Root -Recurse -File -Filter "待补*"
    if ($Mode -eq "Final" -and $placeholders) {
        throw "Final package contains draft placeholders."
    }
}

function Write-ChecksumManifest {
    $lines = Get-ChildItem -LiteralPath $PackageRoot -Recurse -File -Force |
        Where-Object { $_.Name -ne "SHA256SUMS.txt" } |
        Sort-Object FullName |
        ForEach-Object {
            $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            "$hash  $(Get-RelativePath -BasePath $PackageRoot -Path $_.FullName)"
        }
    Write-Utf8File -Path (Join-Path $PackageRoot "SHA256SUMS.txt") -Content (($lines -join "`n") + "`n")
}

function Test-ChecksumManifest {
    $manifest = Join-Path $PackageRoot "SHA256SUMS.txt"
    Assert-Exists -Path $manifest
    foreach ($line in Get-Content -LiteralPath $manifest -Encoding UTF8) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -notmatch "^([0-9a-f]{64})  (.+)$") { throw "Invalid SHA256SUMS line: $line" }
        $path = Join-Path $PackageRoot $Matches[2]
        Assert-Exists -Path $path
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Matches[1]) {
            throw "SHA256SUMS mismatch: $($Matches[2])"
        }
    }
}

function Copy-ArchiveMaterial {
    Ensure-Directory -Path $ArchiveRoot
    $archiveReadme = @'
# Cognivia 开发归档（不提交）

本目录是提交冻结时生成的开发资料副本，不参与最终压缩包。为避免影响仍被代码或测试引用的文件，
脚本只复制、不删除开发仓库中的源文件。历史报告、初审编辑源、旧测试资料与工作簿均不得从此目录
回拷到正式提交包。
'@
    Write-Utf8File -Path (Join-Path $ArchiveRoot "README.md") -Content $archiveReadme
    $copyTrees = @(
        @{ Source = "reports"; Destination = "历史运行报告" },
        @{ Source = "deliverables\competition-initial-review"; Destination = "初审编辑源与历史冻结" },
        @{ Source = "data\backups"; Destination = "数据库与运行备份" },
        @{ Source = "data\rag_evaluation"; Destination = "旧RAG评测数据" },
        @{ Source = "data\knowledge_import_gold_v1"; Destination = "旧知识导入开发集" },
        @{ Source = "data\evaluation_cases\v3"; Destination = "旧V3评测数据" }
    )
    foreach ($item in $copyTrees) {
        $source = Join-Path $ProjectRoot $item.Source
        if (Test-Path -LiteralPath $source) { Copy-TreeForArchive -Source $source -Destination (Join-Path $ArchiveRoot $item.Destination) }
    }
    foreach ($legacyFile in @(
        "data\evaluation_cases\p0_cases.json",
        "ai_app_dev-question-bank-filled.xlsx",
        "smart_manufacturing-question-bank-filled.xlsx",
        "deliverables\smart_manufacturing-question-bank-filled.xlsx"
    )) {
        $source = Join-Path $ProjectRoot $legacyFile
        if (Test-Path -LiteralPath $source) { Copy-FileExact -Source $source -Destination (Join-Path $ArchiveRoot "旧题库与评测数据\$([System.IO.Path]::GetFileName($source))") }
    }
}

function Initialize-PackageRoot {
    if (Test-Path -LiteralPath $PackageRoot) {
        $items = @(Get-ChildItem -LiteralPath $PackageRoot -Force)
        if ($items.Count -gt 0) {
            if (-not $Rebuild) {
                throw "Submission root already contains files. Re-run with -Rebuild only when it is safe to replace the generated package: $PackageRoot"
            }
            Remove-Item -LiteralPath $PackageRoot -Recurse -Force
        }
    }
    Ensure-Directory -Path $PackageRoot
}

function Build-Package {
    $fixture = Test-Fixture -Root $FixtureRoot
    $smartFixture = Test-SmartManufacturingFixture -Root $SmartFixtureRoot
    Test-SmartManufacturingEvidence -EvidenceRoot $SmartEvidenceRoot -ReportPath $SmartLiveReport
    Initialize-PackageRoot
    Ensure-Directory -Path $FreezeInputRoot

    # 01/02 official materials available now.
    Copy-FileExact -Source (Join-Path $ProjectRoot "deliverables\competition-initial-review\01_作品设计实现方案\01_作品设计实现方案.pdf") -Destination (Join-Path $PackageRoot "02_作品材料\01_作品设计实现方案.pdf")
    Copy-FileExact -Source (Join-Path $ProjectRoot "deliverables\competition-initial-review\02_作品介绍\02_作品介绍.pdf") -Destination (Join-Path $PackageRoot "02_作品材料\02_作品介绍.pdf")

    # Runnable program uses its dedicated bootstrap fixture, not a database dump.
    Copy-TreeFiltered -Source (Join-Path $ProjectRoot "backend") -Destination (Join-Path $PackageRoot "03_程序运行包\backend")
    Copy-TreeFiltered -Source (Join-Path $ProjectRoot "frontend") -Destination (Join-Path $PackageRoot "03_程序运行包\frontend")
    # Keep only reproducibility and core-evaluation entry points. Fixture builders,
    # evidence capture utilities, and release staging scripts remain in the development archive.
    foreach ($script in @(
        "README.md",
        "evaluate.py",
        "run_live.py",
        "stability.py",
        "demo_acceptance.py",
        "probe_sse.py",
        "path_progression_acceptance.py",
        "remediation_live_acceptance.py",
        "smart_manufacturing_demo_acceptance.py"
    )) {
        Copy-FileExact -Source (Join-Path $ProjectRoot "test_script\$script") -Destination (Join-Path $PackageRoot "03_程序运行包\test_script\$script")
    }
    foreach ($script in @(
        "demo.ps1",
        "submission-fixture.ps1",
        "fill_submission_question_template.py",
        "fill_question_template_from_source.py",
        "capture_submission_demo_cases.py"
    )) {
        Copy-FileExact -Source (Join-Path $ProjectRoot "scripts\$script") -Destination (Join-Path $PackageRoot "03_程序运行包\scripts\$script")
    }
    Copy-TreeFiltered -Source $FixtureRoot -Destination (Join-Path $PackageRoot "03_程序运行包\$FixtureRelativePath")
    Copy-TreeFiltered -Source $SmartFixtureRoot -Destination (Join-Path $PackageRoot "03_程序运行包\$SmartFixtureRelativePath")
    Copy-TreeFiltered -Source (Join-Path $ProjectRoot "data\seed") -Destination (Join-Path $PackageRoot "03_程序运行包\data\seed")
    Copy-FileExact -Source (Join-Path $ProjectRoot "data\evaluation_cases\manifest.json") -Destination (Join-Path $PackageRoot "03_程序运行包\data\evaluation_cases\manifest.json")
    Copy-FileExact -Source (Join-Path $ProjectRoot "data\evaluation_cases\v4\p0_cases.json") -Destination (Join-Path $PackageRoot "03_程序运行包\data\evaluation_cases\v4\p0_cases.json")
    foreach ($document in @("deployment.md", "agent-contract-v10.md")) {
        Copy-FileExact -Source (Join-Path $ProjectRoot "docs\$document") -Destination (Join-Path $PackageRoot "03_程序运行包\docs\$document")
    }
    Copy-TreeFiltered -Source (Join-Path $ProjectRoot "docs\contracts\v10") -Destination (Join-Path $PackageRoot "03_程序运行包\docs\contracts\v10")
    Copy-FileExact -Source (Join-Path $ProjectRoot "docker-compose.yml") -Destination (Join-Path $PackageRoot "03_程序运行包\docker-compose.yml")
    Copy-FileExact -Source (Join-Path $ProjectRoot "docker-compose.submission.yml") -Destination (Join-Path $PackageRoot "03_程序运行包\docker-compose.submission.yml")
    Copy-FileExact -Source (Join-Path $ProjectRoot ".env.example") -Destination (Join-Path $PackageRoot "03_程序运行包\.env.example")
    Copy-FileExact -Source (Join-Path $ProjectRoot "start.bat") -Destination (Join-Path $PackageRoot "03_程序运行包\start.bat")
    Copy-FileExact -Source (Join-Path $ProjectRoot "README.md") -Destination (Join-Path $PackageRoot "03_程序运行包\README.md")
    Write-Utf8File -Path (Join-Path $PackageRoot "03_程序运行包\storage\.gitkeep") -Content ""
    Write-Utf8File -Path (Join-Path $PackageRoot "03_程序运行包\reports\.gitkeep") -Content ""
    Write-Utf8File -Path (Join-Path $PackageRoot "03_程序运行包\单元测试说明.md") -Content @'
# 单元测试与复现说明

1. 复制 `.env.example` 为 `.env`，填写模型与密钥配置；`.env` 不得提交。
2. 在新克隆或已清空 Docker 卷的环境中，执行 `./scripts/submission-fixture.ps1 bootstrap`。
3. 执行 `./scripts/submission-fixture.ps1 verify`，应得到主领域 `75 / 106 / 465` 与 `90 / 225 / 150`。
4. 在 backend 容器中执行 `python -m pytest -q tests/unit/test_submission_fixture.py`。
5. 对导入能力演示，上传 `data/submission_fixtures/ai_app_dev_v1/import_source/01-ai-app-dev-complete.md`，下载当次题库模板，
   再用 `scripts/fill_submission_question_template.py` 填充 450 题题源。该路径不得与启动夹具叠加到同一数据库。
6. 三组主领域差异化案例由 `scripts/capture_submission_demo_cases.py` 通过真实业务 API 创建学习者、完成诊断、生成、审核与反馈，并写出脱敏输入输出证据。
7. 三组智能制造差异化案例由 `test_script/smart_manufacturing_demo_acceptance.py` 执行；它使用独立 Docker Compose 项目，不与主领域数据库混用。
'@
    Write-Utf8File -Path (Join-Path $PackageRoot "03_程序运行包\部署与复现说明.md") -Content @'
# 部署与复现说明

## 环境

- Docker Desktop（Docker Compose v2）
- 可选：OpenAI-compatible 模型配置。未配置时可导入数据并查看诊断、知识管理等页面；完整的检索、生成与双模型审核需要配置模型。

## 从空环境启动

1. 直接执行 `start.bat`。它会在缺少 `.env` 时从 `.env.example` 创建本地配置，并启动 Docker、迁移数据库、创建管理员和加载完整比赛夹具。
2. 浏览器访问 `http://localhost:5173/`。
3. 执行 `./scripts/submission-fixture.ps1 verify`，主领域应显示 75 条知识、106 条关系、465 道活动题（90 / 225 / 150）。
4. 完整生成、双模型审核和 Candidate RAG 需要在 `.env` 或管理员模型配置页面填写生成、双审核和 embedding 模型配置；配置后执行 `./scripts/demo.ps1 rebuild-index`。

## 核验

```powershell
docker compose exec backend python -m pytest -q tests/unit/test_submission_fixture.py
docker compose exec backend python -m ruff check app tests
docker compose exec backend python -m pytest -q
docker compose exec frontend npm run build
```

正式 50 例指标评测、SSE 检查和学习路径/反馈闭环的脚本位于 `test_script/`；运行说明见该目录的 `README.md`。

## 三组差异化案例复现

提交包的 `04_测试数据与案例/` 已包含脱敏后的输入与输出证据。重新运行时请输出到新的目录，不覆盖已提交证据。

```powershell
$env:SUBMISSION_ADMIN_PASSWORD = "<初始管理员密码>"
python scripts/capture_submission_demo_cases.py `
  --base-url http://localhost:8000/api/v1 `
  --output-dir reports/reproduced-ai-app-dev-cases
```

该命令重跑人工智能应用开发实训的初学者、进阶反馈和高阶挑战三组案例，输出输入画像、诊断结果、Agent 协同摘要、审核摘要、反馈决策和三类资源导出。

智能制造案例使用独立数据库与端口，避免与主领域夹具叠加：

```powershell
./scripts/submission-fixture.ps1 bootstrap `
  -FixtureDir data/submission_fixtures/smart_manufacturing_v1 `
  -ComposeProject cognivia_sm_test `
  -ComposeFile docker-compose.submission.yml
python test_script/smart_manufacturing_demo_acceptance.py `
  --base-url http://localhost:18000/api/v1
```
'@

    # The full fixture is the sole executable 465-question baseline for the primary domain.
    Copy-TreeFiltered -Source $FixtureRoot -Destination (Join-Path $PackageRoot $PrimaryDomainFixtureRelativePath)
    Copy-FileExact -Source (Join-Path $FixtureRoot "import_source\01-ai-app-dev-complete.md") -Destination (Join-Path $PackageRoot "$PrimaryDomainDataRoot\01_知识库切片与来源\01-ai-app-dev-complete.md")
    Copy-FileExact -Source (Join-Path $FixtureRoot "knowledge_items.json") -Destination (Join-Path $PackageRoot "$PrimaryDomainDataRoot\01_知识库切片与来源\知识点与来源许可清单.json")
    Copy-FileExact -Source (Join-Path $FixtureRoot "relations.json") -Destination (Join-Path $PackageRoot "$PrimaryDomainDataRoot\01_知识库切片与来源\知识关系.json")
    Copy-FileExact -Source (Join-Path $FixtureRoot "import_source_manifest.json") -Destination (Join-Path $PackageRoot "$PrimaryDomainDataRoot\01_知识库切片与来源\来源许可清单.json")
    Copy-FileExact -Source (Join-Path $FixtureRoot "template_question_source.json") -Destination (Join-Path $PackageRoot "$PrimaryDomainDataRoot\03_题库导入数据\450题模板兼容题源.json")
    Copy-FileExact -Source (Join-Path $FixtureRoot "supplemental_diagnosis_questions.json") -Destination (Join-Path $PackageRoot "$PrimaryDomainDataRoot\03_题库导入数据\补充15道诊断题.json")
    Write-Utf8File -Path (Join-Path $PackageRoot "$PrimaryDomainDataRoot\03_题库导入数据\题库用途说明.md") -Content @'
# 题库用途说明

启动夹具 `02_可执行启动夹具/ai_app_dev_submission_fixture_v1/diagnostic_questions.json` 是唯一的
465 道活动题运行基线：90 道 `diagnosis`、225 道 `graded_quiz`、150 道 `mastery_validation`。图谱基线为 75 个知识点、106 条关系（92 条前置、14 条关联）。
每种用途覆盖 75 个主领域知识点，夹具的 `manifest.json` 记录其哈希与数量。

导入能力演示不提交预填 XLSX：系统需先按当次知识版本下载题库模板，再以 450 题模板兼容题源填充。
450 题为每知识点 1 道诊断、3 道分阶测验、2 道掌握检查；另 15 道补充诊断题只用于完整启动夹具。
'@
    Copy-FileExact -Source (Join-Path $FixtureRoot "evaluation_cases_v4.json") -Destination (Join-Path $PackageRoot "$PrimaryDomainDataRoot\04_离线评测_50例\evaluation_cases_v4.json")
    Copy-FileExact -Source (Join-Path $FixtureRoot "evaluation_manifest.json") -Destination (Join-Path $PackageRoot "$PrimaryDomainDataRoot\04_离线评测_50例\manifest.json")
    Write-Utf8File -Path (Join-Path $PackageRoot "$PrimaryDomainDataRoot\04_离线评测_50例\评测口径说明.md") -Content @'
# 评测口径说明

本目录锁定 V4 的 50 例离线评测输入：40 例首次生成、5 例反馈复核、5 例挑战任务。离线 `test_script`
是指标事实来源；输入中的 `observed_result` 为可复现基准，不替代当前版本真实模型运行结果。正式运行结果仅在
冻结后进入 `06_正式运行结果与评测报告`。
'@
    Copy-FileExact -Source (Join-Path $FixtureRoot "manual_demo_cases.json") -Destination (Join-Path $PackageRoot "$PrimaryDomainDataRoot\05_差异化学习者真实案例\结构化演示输入_复现参考.json")

    # The secondary-domain fixture and its real, sanitized test evidence are independent of the primary-domain evaluation baseline.
    Copy-TreeFiltered -Source $SmartFixtureRoot -Destination (Join-Path $PackageRoot $SecondaryDomainFixtureRelativePath)
    Copy-FileExact -Source (Join-Path $SmartFixtureRoot "import_source\01-smart-manufacturing-complete.md") -Destination (Join-Path $PackageRoot "$SecondaryDomainDataRoot\01_知识库切片与来源\01-smart-manufacturing-complete.md")
    Copy-FileExact -Source (Join-Path $SmartFixtureRoot "knowledge_items.json") -Destination (Join-Path $PackageRoot "$SecondaryDomainDataRoot\01_知识库切片与来源\知识点与来源许可清单.json")
    Copy-FileExact -Source (Join-Path $SmartFixtureRoot "relations.json") -Destination (Join-Path $PackageRoot "$SecondaryDomainDataRoot\01_知识库切片与来源\知识关系.json")
    Copy-FileExact -Source (Join-Path $SmartFixtureRoot "import_source_manifest.json") -Destination (Join-Path $PackageRoot "$SecondaryDomainDataRoot\01_知识库切片与来源\来源许可清单.json")
    Copy-FileExact -Source (Join-Path $SmartFixtureRoot "template_question_source.json") -Destination (Join-Path $PackageRoot "$SecondaryDomainDataRoot\03_题库导入数据\402题模板兼容题源.json")
    Copy-FileExact -Source (Join-Path $ProjectRoot "deliverables\smart_manufacturing-question-source.xlsx") -Destination (Join-Path $PackageRoot "$SecondaryDomainDataRoot\03_题库导入数据\402题题目源数据.xlsx")
    Write-Utf8File -Path (Join-Path $PackageRoot "$SecondaryDomainDataRoot\03_题库导入数据\题库用途说明.md") -Content @'
# 题库用途说明

智能制造启动夹具的 402 道活动题包含：67 道 `diagnosis`、201 道 `graded_quiz` 与 134 道 `mastery_validation`。
`402题题目源数据.xlsx` 仅保存可填写的题目内容与知识点、用途、层级信息；它不是系统导入模板，不能直接上传。
评委或演示者导入 Markdown 后，须从系统下载该次知识目录生成的题库模板，将本文件中的题目内容填入模板的可编辑列后上传。
启动夹具与 Markdown/XLSX 导入演示是两条互斥路径，不能在同一数据库叠加执行。
'@
    Write-SmartManufacturingCaseEvidence `
        -ReportPath $SmartLiveReport `
        -ExportRoot (Join-Path $SmartEvidenceRoot "资源导出") `
        -DestinationRoot (Join-Path $PackageRoot "$SecondaryDomainDataRoot\04_差异化学习者完整输入输出")
    Copy-FileExact -Source $SmartLiveReport -Destination (Join-Path $PackageRoot "$SecondaryDomainDataRoot\05_运行报告\smart-manufacturing-latest.json")
    Copy-FileExact -Source (Join-Path $SmartEvidenceRoot "运行报告.md") -Destination (Join-Path $PackageRoot "$SecondaryDomainDataRoot\05_运行报告\运行报告.md")
    Write-Utf8File -Path (Join-Path $PackageRoot "$SecondaryDomainDataRoot\00_测试边界与复现说明.md") -Content @'
# 智能制造第二领域测试边界与复现说明

本目录是 `smart_manufacturing` 的独立数据库切片与三组脱敏差异化学情测试材料。夹具锁定 67 条知识、49 条
`next_step` 课程关系和 402 道活动正式题：67 道 `diagnosis`、201 道 `graded_quiz`、134 道
`mastery_validation`。每个知识点均具备 1/3/2 的六用途槽位覆盖。

三组真实 Docker 运行案例分别覆盖：PLC 与工业互联网基础补救的初学者、TIA 组态与机器人 I/O 复核的中阶学习者、
UR ROS 2 集成与恢复挑战的高阶学习者。每组均按统一目录保存合成画像、协同摘要、审核结果、反馈决策、
审核通过的三种学习者版资源及 SHA-256，
不保存完整作答文本、原始 Agent payload、数据库备份、容器日志或模型密钥。

本第二领域不包含 `evaluation_cases`，不包含 50 例离线评测，不以三例运行替代正式质量评测或声明质量指标。
主领域 `ai_app_dev` 的 75 条知识、106 条关系、465 道题和 50 例离线评测基线保持独立且不受影响。

复现时在新 Docker 卷中执行：

```powershell
scripts/submission-fixture.ps1 bootstrap `
  -FixtureDir data/submission_fixtures/smart_manufacturing_v1 `
  -ComposeProject cognivia_sm_test `
  -ComposeFile docker-compose.submission.yml
python test_script/smart_manufacturing_demo_acceptance.py `
  --base-url http://localhost:18000/api/v1
```

启动夹具与 `import_source/` 的 Markdown/XLSX 导入演示互斥，不能在同一数据库叠加。
'@
    Write-Utf8File -Path (Join-Path $PackageRoot "$SecondaryDomainDataRoot\README.md") -Content @'
# 第二领域：智能制造实训测试数据

本目录提供智能制造领域的可执行数据库切片和三组已完成的脱敏测试案例，满足赛题对领域知识库、不同背景学习者
输入画像特征、多智能体协同决策中间摘要和最终个性化学习资源示例的测试数据要求。

| 目录 | 内容 |
| --- | --- |
| `00_测试边界与复现说明.md` | 数据范围、隐私边界及 Docker 复现命令 |
| `01_知识库切片与来源/` | 原始领域文档、67 条知识点、49 条关系与来源许可清单 |
| `02_可执行启动夹具/` | 67 知识、49 关系、402 正式题、3 画像、来源副本与哈希清单 |
| `03_题库导入数据/` | 402 题题源、题库导入示例与用途说明 |
| `04_差异化学习者完整输入输出/` | 三组案例的输入画像、任务/Agent/审核/反馈摘要和三类资源导出 |
| `05_运行报告/` | 真实 Docker 运行通过报告和简要运行说明 |

该目录不含第二领域 50 例离线评测；三例运行仅用于展示差异化学情和反馈决策闭环，不替代主领域正式评测。
'@

    if ($Mode -eq "Draft") {
        Copy-DraftEvidenceInputs
        New-DraftPlaceholders
        New-FreezeInputGuide
    } else {
        Copy-FinalInputs
        Test-FinalInputs
    }

    $markdownCodeTick = [string][char]96
    Write-Utf8File -Path (Join-Path $PackageRoot "00_提交说明.md") -Content @"
# Cognivia 参赛提交说明

- 打包状态：$Mode
- 正式主领域：人工智能应用开发实训（${markdownCodeTick}ai_app_dev${markdownCodeTick}）
- 数据基线：${markdownCodeTick}ai_app_dev_submission_fixture_v1${markdownCodeTick}
- 夹具规模：75 个知识点、106 条关系、465 道活动题（90 / 225 / 150）
- 第二领域：智能制造实训（${markdownCodeTick}smart_manufacturing${markdownCodeTick}），67 个知识点、49 条关系、402 道活动题（67 / 201 / 134）和 3 组脱敏测试案例
- 复现入口：${markdownCodeTick}03_程序运行包/scripts/submission-fixture.ps1${markdownCodeTick}

本目录由白名单脚本生成。启动夹具与 Markdown/XLSX 导入演示是两条互斥复现路径，不能在同一数据库叠加执行。
智能制造第二领域不包含 ${markdownCodeTick}evaluation_cases${markdownCodeTick} 或 50 例离线评测，三例测试运行不替代主领域正式评测。所有文件的 SHA-256 见根目录 ${markdownCodeTick}SHA256SUMS.txt${markdownCodeTick}。
"@

    $runtimeFixtureRoot = Join-Path $PackageRoot "03_程序运行包\$FixtureRelativePath"
    $submissionFixtureRoot = Join-Path $PackageRoot $PrimaryDomainFixtureRelativePath
    $runtimeSmartFixtureRoot = Join-Path $PackageRoot "03_程序运行包\$SmartFixtureRelativePath"
    $submissionSmartFixtureRoot = Join-Path $PackageRoot $SecondaryDomainFixtureRelativePath
    Test-Fixture -Root $runtimeFixtureRoot | Out-Null
    Test-Fixture -Root $submissionFixtureRoot | Out-Null
    Test-SmartManufacturingFixture -Root $runtimeSmartFixtureRoot | Out-Null
    Test-SmartManufacturingFixture -Root $submissionSmartFixtureRoot | Out-Null
    Assert-EqualHash -Left (Join-Path $runtimeFixtureRoot "knowledge_items.json") -Right (Join-Path $submissionFixtureRoot "knowledge_items.json") -Label "fixture knowledge baseline"
    Assert-EqualHash -Left (Join-Path $runtimeFixtureRoot "relations.json") -Right (Join-Path $submissionFixtureRoot "relations.json") -Label "fixture relation baseline"
    Assert-EqualHash -Left (Join-Path $runtimeFixtureRoot "diagnostic_questions.json") -Right (Join-Path $submissionFixtureRoot "diagnostic_questions.json") -Label "fixture 465-question baseline"
    Assert-EqualHash -Left (Join-Path $submissionFixtureRoot "knowledge_items.json") -Right (Join-Path $PackageRoot "$PrimaryDomainDataRoot\01_知识库切片与来源\知识点与来源许可清单.json") -Label "knowledge slice"
    Assert-EqualHash -Left (Join-Path $submissionFixtureRoot "relations.json") -Right (Join-Path $PackageRoot "$PrimaryDomainDataRoot\01_知识库切片与来源\知识关系.json") -Label "knowledge relations"
    Assert-EqualHash -Left (Join-Path $submissionFixtureRoot "template_question_source.json") -Right (Join-Path $PackageRoot "$PrimaryDomainDataRoot\03_题库导入数据\450题模板兼容题源.json") -Label "template question source"
    Assert-EqualHash -Left (Join-Path $submissionFixtureRoot "evaluation_cases_v4.json") -Right (Join-Path $PackageRoot "$PrimaryDomainDataRoot\04_离线评测_50例\evaluation_cases_v4.json") -Label "evaluation cases"
    Assert-EqualHash -Left (Join-Path $submissionFixtureRoot "import_source\01-ai-app-dev-complete.md") -Right (Join-Path $PackageRoot "$PrimaryDomainDataRoot\01_知识库切片与来源\01-ai-app-dev-complete.md") -Label "import source"
    Assert-EqualHash -Left (Join-Path $runtimeSmartFixtureRoot "knowledge_items.json") -Right (Join-Path $submissionSmartFixtureRoot "knowledge_items.json") -Label "smart manufacturing knowledge baseline"
    Assert-EqualHash -Left (Join-Path $runtimeSmartFixtureRoot "relations.json") -Right (Join-Path $submissionSmartFixtureRoot "relations.json") -Label "smart manufacturing relation baseline"
    Assert-EqualHash -Left (Join-Path $runtimeSmartFixtureRoot "diagnostic_questions.json") -Right (Join-Path $submissionSmartFixtureRoot "diagnostic_questions.json") -Label "smart manufacturing 402-question baseline"
    Assert-EqualHash -Left (Join-Path $submissionSmartFixtureRoot "knowledge_items.json") -Right (Join-Path $PackageRoot "$SecondaryDomainDataRoot\01_知识库切片与来源\知识点与来源许可清单.json") -Label "smart manufacturing knowledge slice"
    Assert-EqualHash -Left (Join-Path $submissionSmartFixtureRoot "relations.json") -Right (Join-Path $PackageRoot "$SecondaryDomainDataRoot\01_知识库切片与来源\知识关系.json") -Label "smart manufacturing relation slice"
    Assert-EqualHash -Left (Join-Path $submissionSmartFixtureRoot "template_question_source.json") -Right (Join-Path $PackageRoot "$SecondaryDomainDataRoot\03_题库导入数据\402题模板兼容题源.json") -Label "smart manufacturing template question source"
    Assert-EqualHash -Left (Join-Path $submissionSmartFixtureRoot "import_source\01-smart-manufacturing-complete.md") -Right (Join-Path $PackageRoot "$SecondaryDomainDataRoot\01_知识库切片与来源\01-smart-manufacturing-complete.md") -Label "smart manufacturing import source"
    Assert-EqualHash -Left (Join-Path $ProjectRoot "deliverables\smart_manufacturing-question-source.xlsx") -Right (Join-Path $PackageRoot "$SecondaryDomainDataRoot\03_题库导入数据\402题题目源数据.xlsx") -Label "smart manufacturing question source workbook"
    $standardizedSmartCases = Join-Path $PackageRoot "$SecondaryDomainDataRoot\04_差异化学习者完整输入输出"
    foreach ($caseId in @("SM-DEMO-BEGINNER-INITIAL", "SM-DEMO-INTERMEDIATE-REVIEW", "SM-DEMO-ADVANCED-CHALLENGE")) {
        $caseRoot = Join-Path $standardizedSmartCases $caseId
        foreach ($file in @("case-input.json", "task-summary.json", "agent-trace-summary.json", "review-summary.json", "feedback-decision.json", "manifest.json")) {
            $path = Join-Path $caseRoot $file
            Assert-Exists -Path $path
            $null = Get-Json -Path $path
        }
        $resourceDirectory = Join-Path $caseRoot "resource-export"
        if (@(Get-ChildItem -LiteralPath $resourceDirectory -File).Count -ne 3) {
            throw "Smart manufacturing standardized case has incomplete resource exports: $caseId"
        }
    }
    Test-SubmissionSafety -Root $PackageRoot
    Write-ChecksumManifest
    Test-ChecksumManifest
    Copy-ArchiveMaterial

    [ordered]@{
        status = "ok"
        mode = $Mode
        package_root = $PackageRoot
        archive_root = $ArchiveRoot
        fixture_version = $fixture.fixture_version
        fixture_counts = $fixture.counts
        secondary_fixture_version = $smartFixture.fixture_version
        secondary_fixture_counts = $smartFixture.counts
        final_ready = ($Mode -eq "Final")
    } | ConvertTo-Json -Depth 6
}

Build-Package
