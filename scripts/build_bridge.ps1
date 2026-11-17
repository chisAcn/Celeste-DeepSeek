param([string]$CelesteDir = $env:CELESTE_DIR)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath "$CelesteDir/Celeste.dll")) { throw 'Set CELESTE_DIR to your Everest installation.' }
$env:MSBuildEnableWorkloadResolver = 'false'
dotnet build "$PSScriptRoot/../bridge/CelesteAgentBridge" -c Release "-p:CelesteDir=$CelesteDir"
if ($LASTEXITCODE -ne 0) { throw 'Bridge build failed' }
