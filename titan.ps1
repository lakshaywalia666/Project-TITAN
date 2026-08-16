[CmdletBinding()]
param(
    [ValidateSet(
        "menu",
        "init",
        "doctor",
        "local-up",
        "local-status",
        "local-down",
        "github-configure",
        "cloud-smoke"
    )]
    [string] $Action = "menu",

    [string] $ConfigPath = "",
    [string] $Provider = "",
    [string] $Image = "",
    [switch] $Observability,
    [switch] $Portal,
    [string] $ConfirmGitHub = "",
    [string] $ConfirmCloud = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:ProjectRoot = $PSScriptRoot
$script:TitanRuntimeDirectory = Join-Path $script:ProjectRoot ".titan"
$script:DefaultConfigPath = Join-Path $script:TitanRuntimeDirectory "settings.json"
$script:ExampleConfigPath = Join-Path $script:ProjectRoot "titan.settings.example.json"
$script:EffectiveConfigPath = if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $script:DefaultConfigPath
} elseif ([IO.Path]::IsPathRooted($ConfigPath)) {
    $ConfigPath
} else {
    Join-Path $script:ProjectRoot $ConfigPath
}

function Write-Stage {
    param([Parameter(Mandatory)][string] $Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([Parameter(Mandatory)][string] $Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-WarningLine {
    param([Parameter(Mandatory)][string] $Message)
    Write-Host "[WARNING] $Message" -ForegroundColor Yellow
}

function Test-CommandAvailable {
    param([Parameter(Mandatory)][string] $Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Require-Command {
    param(
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][string] $InstallHint
    )
    if (-not (Test-CommandAvailable $Name)) {
        throw "Required command '$Name' is missing. $InstallHint"
    }
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory)][string] $Command,
        [Parameter(Mandatory)][string[]] $Arguments
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Command $($Arguments -join ' ')"
    }
}

function Ensure-RuntimeDirectory {
    if (-not (Test-Path -LiteralPath $script:TitanRuntimeDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $script:TitanRuntimeDirectory | Out-Null
    }
}

function Initialize-Settings {
    $settingsDirectory = Split-Path -Parent $script:EffectiveConfigPath
    if (-not (Test-Path -LiteralPath $settingsDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $settingsDirectory | Out-Null
    }
    if (Test-Path -LiteralPath $script:EffectiveConfigPath) {
        Write-WarningLine "Settings already exist; nothing was overwritten: $script:EffectiveConfigPath"
        return
    }
    if (-not (Test-Path -LiteralPath $script:ExampleConfigPath -PathType Leaf)) {
        throw "Missing settings template: $script:ExampleConfigPath"
    }
    Copy-Item -LiteralPath $script:ExampleConfigPath -Destination $script:EffectiveConfigPath
    Write-Success "Created private launcher settings: $script:EffectiveConfigPath"
    Write-Host "Edit only IDs, names, regions and the signed image digest. Never add cloud passwords or access keys."
}

function Get-Settings {
    if (-not (Test-Path -LiteralPath $script:EffectiveConfigPath -PathType Leaf)) {
        throw "Settings file does not exist. Run: .\titan.ps1 init"
    }
    $raw = Get-Content -LiteralPath $script:EffectiveConfigPath -Raw
    if ($raw -match '(?i)"[^"]*(password|secret|access.?key|private.?key|token)[^"]*"\s*:') {
        throw "The settings file appears to contain a credential field. Remove it; this launcher accepts OIDC identifiers only."
    }
    try {
        return $raw | ConvertFrom-Json
    } catch {
        throw "Settings JSON is invalid: $($_.Exception.Message)"
    }
}

function Assert-CommonCloudSettings {
    param([Parameter(Mandatory)] $Settings)
    if ($null -eq $Settings.github -or $null -eq $Settings.cloud) {
        throw "Settings must contain github and cloud objects."
    }
    if ($Settings.github.repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
        throw "github.repository must use OWNER/REPOSITORY form."
    }
    if ($Settings.github.repository -eq "OWNER/REPOSITORY") {
        throw "Replace the github.repository placeholder with your real OWNER/REPOSITORY."
    }
    if ($Settings.github.branch -notmatch '^[A-Za-z0-9._/-]+$') {
        throw "github.branch is invalid."
    }
    if ($Settings.github.environment -ne "cloud-smoke") {
        throw "github.environment must be cloud-smoke because the guarded workflow uses that environment."
    }
    if ($Settings.cloud.owner -notmatch '^[a-z0-9]([a-z0-9_-]{0,61}[a-z0-9])?$') {
        throw "cloud.owner must be a lowercase 1-63 character label."
    }
    if ($Settings.cloud.owner -eq "replace-me") {
        throw "Replace the cloud.owner placeholder with your lowercase owner label."
    }
}

function Resolve-Provider {
    param(
        [Parameter(Mandatory)] $Settings,
        [string] $RequestedProvider
    )
    $selected = if ([string]::IsNullOrWhiteSpace($RequestedProvider)) {
        [string] $Settings.cloud.defaultProvider
    } else {
        $RequestedProvider
    }
    $selected = $selected.ToLowerInvariant()
    if ($selected -notin @("aws", "azure", "gcp")) {
        throw "Provider must be aws, azure or gcp."
    }
    return $selected
}

function Assert-ProviderSettings {
    param(
        [Parameter(Mandatory)] $Settings,
        [Parameter(Mandatory)][string] $SelectedProvider
    )
    switch ($SelectedProvider) {
        "aws" {
            if ($Settings.cloud.aws.roleArn -notmatch '^arn:aws(-us-gov|-cn)?:iam::[0-9]{12}:role/.+$') {
                throw "cloud.aws.roleArn must be a valid GitHub OIDC role ARN."
            }
            if ($Settings.cloud.aws.region -notmatch '^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$') {
                throw "cloud.aws.region is invalid."
            }
        }
        "azure" {
            foreach ($name in @("clientId", "tenantId", "subscriptionId")) {
                if ($Settings.cloud.azure.$name -notmatch '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$') {
                    throw "cloud.azure.$name must be a GUID."
                }
            }
            if ($Settings.cloud.azure.location -notmatch '^[a-z0-9]+$') {
                throw "cloud.azure.location is invalid."
            }
        }
        "gcp" {
            if ($Settings.cloud.gcp.workloadIdentityProvider -notmatch '^projects/[0-9]+/locations/global/workloadIdentityPools/[A-Za-z0-9_-]+/providers/[A-Za-z0-9_-]+$') {
                throw "cloud.gcp.workloadIdentityProvider is invalid."
            }
            if ($Settings.cloud.gcp.serviceAccount -notmatch '^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$') {
                throw "cloud.gcp.serviceAccount is invalid."
            }
            if ($Settings.cloud.gcp.projectId -notmatch '^[a-z][a-z0-9-]{4,28}[a-z0-9]$') {
                throw "cloud.gcp.projectId is invalid."
            }
            if ($Settings.cloud.gcp.region -notin @("us-west1", "us-central1", "us-east1")) {
                throw "GCP smoke deployments are restricted to us-west1, us-central1 or us-east1."
            }
            if ($Settings.cloud.gcp.zone -notmatch '^(us-west1|us-central1|us-east1)-[a-z]$') {
                throw "cloud.gcp.zone must belong to an allowed region."
            }
            if (-not $Settings.cloud.gcp.zone.StartsWith("$($Settings.cloud.gcp.region)-")) {
                throw "cloud.gcp.zone must belong to cloud.gcp.region."
            }
        }
    }
}

function New-RandomHexToken {
    $bytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    } finally {
        $generator.Dispose()
    }
    return ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}

function Initialize-LocalEnvironment {
    $envPath = Join-Path $script:ProjectRoot ".env"
    if (Test-Path -LiteralPath $envPath -PathType Leaf) {
        Write-Success "Using existing ignored .env file."
        return
    }
    $examplePath = Join-Path $script:ProjectRoot ".env.example"
    if (-not (Test-Path -LiteralPath $examplePath -PathType Leaf)) {
        throw "Missing .env.example."
    }
    $token = New-RandomHexToken
    $content = Get-Content -LiteralPath $examplePath -Raw
    $content = $content.Replace("replace-with-at-least-24-random-characters", $token)
    [IO.File]::WriteAllText($envPath, $content, (New-Object Text.UTF8Encoding($false)))
    Write-Success "Generated a private .env with a random 256-bit administrator token."
}

function Get-LocalAdminToken {
    $envPath = Join-Path $script:ProjectRoot ".env"
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        throw ".env is missing. Run local-up first."
    }
    $line = Get-Content -LiteralPath $envPath | Where-Object { $_ -match '^TITAN_ADMIN_TOKEN=' } | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($line)) {
        throw "TITAN_ADMIN_TOKEN is missing from .env."
    }
    $token = $line.Substring("TITAN_ADMIN_TOKEN=".Length).Trim()
    if ($token.Length -lt 24 -or $token -match '^replace-') {
        throw "TITAN_ADMIN_TOKEN in .env is unsafe. Remove .env and run local-up to generate a safe token."
    }
    return $token
}

function Wait-HttpEndpoint {
    param(
        [Parameter(Mandatory)][string] $Uri,
        [hashtable] $Headers = @{},
        [int] $TimeoutSeconds = 180
    )
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            Invoke-WebRequest -Uri $Uri -Headers $Headers -UseBasicParsing -TimeoutSec 3 | Out-Null
            return
        } catch {
            Start-Sleep -Seconds 2
        }
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "Timed out waiting for $Uri"
}

function Test-HttpEndpoint {
    param(
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][string] $Uri,
        [hashtable] $Headers = @{}
    )
    try {
        Invoke-WebRequest -Uri $Uri -Headers $Headers -UseBasicParsing -TimeoutSec 3 | Out-Null
        Write-Success "$Name is healthy: $Uri"
        return $true
    } catch {
        Write-WarningLine "$Name is not responding: $Uri"
        return $false
    }
}

function Assert-DockerReady {
    Require-Command "docker" "Install Docker Desktop and enable its WSL2 engine."
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker is installed but its engine is unavailable. Start Docker Desktop and wait until it reports Running."
    }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose v2 is unavailable. Update Docker Desktop."
    }
}

function Start-Portal {
    Require-Command "node" "Install Node.js 22."
    Require-Command "pnpm" "Install pnpm 11 after Node.js."
    Ensure-RuntimeDirectory
    $pidPath = Join-Path $script:TitanRuntimeDirectory "portal.pid"
    if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
        $existingPid = [int](Get-Content -LiteralPath $pidPath -Raw)
        if ($null -ne (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
            Write-Success "Portal process is already running with PID $existingPid."
            return
        }
        Remove-Item -LiteralPath $pidPath -Force
    }

    $portalDirectory = Join-Path $script:ProjectRoot "portal"
    if (-not (Test-Path -LiteralPath (Join-Path $portalDirectory "node_modules") -PathType Container)) {
        Write-Stage "Installing portal packages from the lockfile"
        Push-Location $portalDirectory
        try {
            Invoke-CheckedCommand "pnpm" @("install", "--frozen-lockfile")
        } finally {
            Pop-Location
        }
    }

    $stdoutPath = Join-Path $script:TitanRuntimeDirectory "portal.stdout.log"
    $stderrPath = Join-Path $script:TitanRuntimeDirectory "portal.stderr.log"
    $process = Start-Process -FilePath "cmd.exe" `
        -ArgumentList @("/d", "/s", "/c", "pnpm run dev") `
        -WorkingDirectory $portalDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru
    [IO.File]::WriteAllText($pidPath, [string]$process.Id)
    try {
        Wait-HttpEndpoint -Uri "http://127.0.0.1:3000" -TimeoutSeconds 180
    } catch {
        Write-WarningLine "Portal did not start. Inspect $stderrPath"
        throw
    }
    Write-Success "Portal is ready: http://127.0.0.1:3000"
}

function Stop-Portal {
    $pidPath = Join-Path $script:TitanRuntimeDirectory "portal.pid"
    if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
        return
    }
    $portalPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    if ($null -ne (Get-Process -Id $portalPid -ErrorAction SilentlyContinue)) {
        & taskkill.exe /PID $portalPid /T /F *> $null
        if ($LASTEXITCODE -notin @(0, 128)) {
            Write-WarningLine "Could not stop portal process tree $portalPid; inspect it manually."
        }
    }
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
}

function Start-LocalTitan {
    param(
        [bool] $IncludeObservability,
        [bool] $IncludePortal
    )
    Write-Stage "Checking Docker and preparing local secrets"
    Assert-DockerReady
    Initialize-LocalEnvironment
    $token = Get-LocalAdminToken

    $composeArguments = @("compose")
    if ($IncludeObservability) {
        $composeArguments += @("--profile", "observability")
    }
    $composeArguments += @("up", "--detach", "--build")

    Write-Stage "Building and starting Project TITAN"
    Push-Location $script:ProjectRoot
    try {
        Invoke-CheckedCommand "docker" $composeArguments
    } finally {
        Pop-Location
    }

    Write-Stage "Verifying local services"
    $authHeaders = @{ Authorization = "Bearer $token" }
    try {
        Wait-HttpEndpoint "http://127.0.0.1:8080/healthz"
        Wait-HttpEndpoint "http://127.0.0.1:8090/healthz"
        Wait-HttpEndpoint "http://127.0.0.1:8090/v1/projects" $authHeaders
        Wait-HttpEndpoint "http://127.0.0.1:8100/readyz"
        Wait-HttpEndpoint "http://127.0.0.1:8200/healthz"
        Wait-HttpEndpoint "http://127.0.0.1:8200/v1/catalog"
        Wait-HttpEndpoint "http://127.0.0.1:8300/healthz"
        Wait-HttpEndpoint "http://127.0.0.1:8300/v1/catalog"
    } catch {
        & docker compose ps
        & docker compose logs --tail 100
        throw
    }

    if ($IncludeObservability) {
        Wait-HttpEndpoint "http://127.0.0.1:9090/-/ready"
        Wait-HttpEndpoint "http://127.0.0.1:3001/api/health"
    }
    if ($IncludePortal) {
        Start-Portal
    }

    Write-Success "Project TITAN is running locally."
    Write-Host "Control API : http://127.0.0.1:8090"
    Write-Host "AI API      : http://127.0.0.1:8100"
    Write-Host "Titan Shop  : http://127.0.0.1:8200"
    Write-Host "Launchpad   : http://127.0.0.1:8300"
    if ($IncludePortal) {
        Write-Host "Portal      : http://127.0.0.1:3000"
    } else {
        Write-Host "Portal was not requested. Start it later with: .\titan.ps1 local-up -Portal"
    }
}

function Show-LocalStatus {
    Assert-DockerReady
    Push-Location $script:ProjectRoot
    try {
        & docker compose ps
    } finally {
        Pop-Location
    }
    $token = $null
    try { $token = Get-LocalAdminToken } catch { }
    Test-HttpEndpoint "Reference API" "http://127.0.0.1:8080/healthz" | Out-Null
    Test-HttpEndpoint "Control API" "http://127.0.0.1:8090/healthz" | Out-Null
    if ($null -ne $token) {
        Test-HttpEndpoint "Authenticated control API" "http://127.0.0.1:8090/v1/projects" @{ Authorization = "Bearer $token" } | Out-Null
    }
    Test-HttpEndpoint "AI API" "http://127.0.0.1:8100/readyz" | Out-Null
    Test-HttpEndpoint "Titan Shop" "http://127.0.0.1:8200/healthz" | Out-Null
    Test-HttpEndpoint "Launchpad" "http://127.0.0.1:8300/healthz" | Out-Null
    Test-HttpEndpoint "Portal" "http://127.0.0.1:3000" | Out-Null
    Test-HttpEndpoint "Prometheus" "http://127.0.0.1:9090/-/ready" | Out-Null
    Test-HttpEndpoint "Grafana" "http://127.0.0.1:3001/api/health" | Out-Null
}

function Stop-LocalTitan {
    Assert-DockerReady
    Write-Stage "Stopping Project TITAN while preserving data volumes"
    Stop-Portal
    Push-Location $script:ProjectRoot
    try {
        Invoke-CheckedCommand "docker" @("compose", "--profile", "observability", "down", "--remove-orphans")
    } finally {
        Pop-Location
    }
    Write-Success "Project TITAN is stopped. Docker volumes were preserved."
}

function Show-Doctor {
    Write-Stage "Project TITAN prerequisite check"
    Write-Host "Project: $script:ProjectRoot"
    Write-Host "PowerShell: $($PSVersionTable.PSVersion)"
    $commands = @(
        @{ Name = "git"; Purpose = "source control" },
        @{ Name = "docker"; Purpose = "local platform" },
        @{ Name = "node"; Purpose = "portal" },
        @{ Name = "pnpm"; Purpose = "portal packages" },
        @{ Name = "gh"; Purpose = "GitHub configuration and cloud trigger" },
        @{ Name = "wsl"; Purpose = "Linux learning tools" }
    )
    foreach ($item in $commands) {
        if (Test-CommandAvailable $item.Name) {
            Write-Success "$($item.Name) is installed ($($item.Purpose))."
        } else {
            Write-WarningLine "$($item.Name) is missing ($($item.Purpose))."
        }
    }
    if (Test-CommandAvailable "docker") {
        & docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Docker engine is running."
        } else {
            Write-WarningLine "Docker is installed but its engine is not running."
        }
    }
    if (Test-Path -LiteralPath (Join-Path $script:ProjectRoot ".env") -PathType Leaf) {
        Write-Success "Local .env exists and is ignored by Git."
    } else {
        Write-WarningLine "Local .env is not created yet; local-up will create it safely."
    }
    if (Test-Path -LiteralPath $script:EffectiveConfigPath -PathType Leaf) {
        try {
            $settings = Get-Settings
            Assert-CommonCloudSettings $settings
            Write-Success "Launcher settings are valid: $script:EffectiveConfigPath"
        } catch {
            Write-WarningLine $_.Exception.Message
        }
    } else {
        Write-WarningLine "Launcher settings do not exist; run .\titan.ps1 init before GitHub/cloud setup."
    }
}

function Set-GitHubEnvironmentVariable {
    param(
        [Parameter(Mandatory)][string] $Repository,
        [Parameter(Mandatory)][string] $Environment,
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][string] $Value
    )
    Invoke-CheckedCommand "gh" @(
        "variable", "set", $Name,
        "--body", $Value,
        "--env", $Environment,
        "--repo", $Repository
    )
}

function Configure-GitHubEnvironment {
    param(
        [Parameter(Mandatory)] $Settings,
        [Parameter(Mandatory)][string] $SelectedProvider,
        [string] $Confirmation
    )
    if ($Confirmation -ne "CONFIGURE_GITHUB_TITAN") {
        throw "Refusing GitHub changes. Re-run with -ConfirmGitHub CONFIGURE_GITHUB_TITAN"
    }
    Assert-CommonCloudSettings $Settings
    Assert-ProviderSettings $Settings $SelectedProvider
    Require-Command "gh" "Install GitHub CLI and run: gh auth login"
    Invoke-CheckedCommand "gh" @("auth", "status")

    $repository = [string] $Settings.github.repository
    $environment = [string] $Settings.github.environment
    Write-Stage "Creating or updating GitHub environment $environment"
    Invoke-CheckedCommand "gh" @(
        "api", "--method", "PUT",
        "repos/$repository/environments/$environment"
    )
    Set-GitHubEnvironmentVariable $repository $environment "TITAN_OWNER" ([string] $Settings.cloud.owner)

    switch ($SelectedProvider) {
        "aws" {
            Set-GitHubEnvironmentVariable $repository $environment "AWS_ROLE_ARN" ([string] $Settings.cloud.aws.roleArn)
            Set-GitHubEnvironmentVariable $repository $environment "AWS_REGION" ([string] $Settings.cloud.aws.region)
        }
        "azure" {
            Set-GitHubEnvironmentVariable $repository $environment "AZURE_CLIENT_ID" ([string] $Settings.cloud.azure.clientId)
            Set-GitHubEnvironmentVariable $repository $environment "AZURE_TENANT_ID" ([string] $Settings.cloud.azure.tenantId)
            Set-GitHubEnvironmentVariable $repository $environment "AZURE_SUBSCRIPTION_ID" ([string] $Settings.cloud.azure.subscriptionId)
            Set-GitHubEnvironmentVariable $repository $environment "AZURE_LOCATION" ([string] $Settings.cloud.azure.location)
        }
        "gcp" {
            Set-GitHubEnvironmentVariable $repository $environment "GCP_WORKLOAD_IDENTITY_PROVIDER" ([string] $Settings.cloud.gcp.workloadIdentityProvider)
            Set-GitHubEnvironmentVariable $repository $environment "GCP_SERVICE_ACCOUNT" ([string] $Settings.cloud.gcp.serviceAccount)
            Set-GitHubEnvironmentVariable $repository $environment "GCP_PROJECT_ID" ([string] $Settings.cloud.gcp.projectId)
            Set-GitHubEnvironmentVariable $repository $environment "GCP_REGION" ([string] $Settings.cloud.gcp.region)
            Set-GitHubEnvironmentVariable $repository $environment "GCP_ZONE" ([string] $Settings.cloud.gcp.zone)
        }
    }
    Write-Success "GitHub environment variables for $SelectedProvider are configured without long-lived cloud credentials."
    Write-WarningLine "The provider-side OIDC trust must already exist. This command cannot create trust without provider administrator access."
}

function Start-CloudSmoke {
    param(
        [Parameter(Mandatory)] $Settings,
        [Parameter(Mandatory)][string] $SelectedProvider,
        [string] $RequestedImage,
        [string] $Confirmation
    )
    if ($Confirmation -ne "DEPLOY_AND_DESTROY_TITAN") {
        throw "Refusing cloud deployment. Re-run with -ConfirmCloud DEPLOY_AND_DESTROY_TITAN"
    }
    Assert-CommonCloudSettings $Settings
    Assert-ProviderSettings $Settings $SelectedProvider

    $selectedImage = if ([string]::IsNullOrWhiteSpace($RequestedImage)) {
        [string] $Settings.cloud.image
    } else {
        $RequestedImage
    }
    if ($selectedImage -notmatch '^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$') {
        throw "Image must be a public GHCR image pinned with @sha256:<64 lowercase hex characters>."
    }
    $repository = [string] $Settings.github.repository
    $expectedImage = "ghcr.io/$($repository.ToLowerInvariant())"
    $imageRepository = $selectedImage.Substring(0, $selectedImage.IndexOf("@sha256:"))
    if ($imageRepository -ne $expectedImage) {
        throw "Image must belong to this repository: $expectedImage"
    }
    Require-Command "gh" "Install GitHub CLI and run: gh auth login"
    Invoke-CheckedCommand "gh" @("auth", "status")

    Write-WarningLine "This creates temporary cloud resources. Automatic destroy is attempted, but a zero bill cannot be guaranteed."
    Write-Stage "Triggering one disposable $SelectedProvider smoke deployment"
    Invoke-CheckedCommand "gh" @(
        "workflow", "run", "cloud-smoke.yml",
        "--repo", $repository,
        "--ref", ([string] $Settings.github.branch),
        "--field", "provider=$SelectedProvider",
        "--field", "image=$selectedImage",
        "--field", "confirmation=DEPLOY_AND_DESTROY_TITAN"
    )
    Write-Success "Cloud smoke workflow was queued."
    Write-Host "Watch it at: https://github.com/$repository/actions/workflows/cloud-smoke.yml"
    Write-Host "Require TITAN_CLOUD_SMOKE_OK, successful destroy, and final provider-console deletion confirmation."
}

function Show-Menu {
    Write-Host ""
    Write-Host "Project TITAN Launcher" -ForegroundColor Cyan
    Write-Host "1. Check this computer"
    Write-Host "2. Create private settings file"
    Write-Host "3. Start local TITAN"
    Write-Host "4. Start local TITAN with portal"
    Write-Host "5. Show local status"
    Write-Host "6. Stop local TITAN"
    Write-Host "7. Configure GitHub cloud environment"
    Write-Host "8. Run disposable cloud smoke test"
    Write-Host "0. Exit"
    $choice = Read-Host "Choose"
    switch ($choice) {
        "1" { Show-Doctor }
        "2" { Initialize-Settings }
        "3" { Start-LocalTitan -IncludeObservability:$false -IncludePortal:$false }
        "4" { Start-LocalTitan -IncludeObservability:$false -IncludePortal:$true }
        "5" { Show-LocalStatus }
        "6" { Stop-LocalTitan }
        "7" {
            $settings = Get-Settings
            $selectedProvider = Resolve-Provider $settings (Read-Host "Provider (aws, azure, gcp)")
            $confirmation = Read-Host "Type CONFIGURE_GITHUB_TITAN"
            Configure-GitHubEnvironment $settings $selectedProvider $confirmation
        }
        "8" {
            $settings = Get-Settings
            $selectedProvider = Resolve-Provider $settings (Read-Host "Provider (aws, azure, gcp)")
            $requestedImage = Read-Host "Signed image digest (leave empty to use settings)"
            $confirmation = Read-Host "Type DEPLOY_AND_DESTROY_TITAN"
            Start-CloudSmoke $settings $selectedProvider $requestedImage $confirmation
        }
        "0" { return }
        default { throw "Unknown menu choice."
        }
    }
}

try {
    switch ($Action) {
        "menu" { Show-Menu }
        "init" { Initialize-Settings }
        "doctor" { Show-Doctor }
        "local-up" { Start-LocalTitan -IncludeObservability:$Observability.IsPresent -IncludePortal:$Portal.IsPresent }
        "local-status" { Show-LocalStatus }
        "local-down" { Stop-LocalTitan }
        "github-configure" {
            $settings = Get-Settings
            $selectedProvider = Resolve-Provider $settings $Provider
            Configure-GitHubEnvironment $settings $selectedProvider $ConfirmGitHub
        }
        "cloud-smoke" {
            $settings = Get-Settings
            $selectedProvider = Resolve-Provider $settings $Provider
            Start-CloudSmoke $settings $selectedProvider $Image $ConfirmCloud
        }
    }
} catch {
    Write-Host "`nTITAN launcher stopped: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
