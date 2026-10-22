param(
    [string]$PythonExe = '',
    [switch]$Basic,
    [switch]$NoAutostart,
    [switch]$SkipSkill,
    [switch]$NoStart,
    [switch]$EnablePublicFulltext
)
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectDir
try {
    $pythonExecutable = Join-Path $projectDir '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExecutable)) {
        $basePython = $PythonExe
        foreach ($candidate in @('py', 'python')) {
            if ($basePython) { break }
            $command = Get-Command $candidate -ErrorAction SilentlyContinue
            # Windows Store aliases can open an installer or wait indefinitely.
            # Require an installed interpreter instead of invoking these aliases.
            if (-not $command -or $command.Source -like '*\Microsoft\WindowsApps\*') { continue }
            $prefix = if ($candidate -eq 'py') { @('-3') } else { @() }
            $resolvedPython = & $candidate @prefix -c 'import sys; assert sys.version_info >= (3,11); print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolvedPython) { $basePython = $resolvedPython; break }
        }
        if (-not $basePython) { throw 'Python 3.11+ is required. Install it from python.org and enable PATH, or pass -PythonExe C:\path\python.exe.' }
        & $basePython -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Cannot create the Python environment.' }
    }
    & $pythonExecutable -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
    if ($LASTEXITCODE -ne 0) { throw 'This environment needs Python 3.11+.' }
    $package = if ($Basic) { '.' } else { '.[semantic]' }
    & $pythonExecutable -m pip install -e $package
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your network and retry; existing data is preserved.' }
    $envPath = Join-Path $projectDir '.env'
    $createdConfig = -not (Test-Path -LiteralPath $envPath)
    if ($createdConfig) { Copy-Item -LiteralPath (Join-Path $projectDir '.env.example') -Destination $envPath }
    $configText = [IO.File]::ReadAllText($envPath)
    if ($Basic -and $createdConfig) { $configText = $configText -replace '(?m)^EMBEDDING_PROVIDER=.*$', 'EMBEDDING_PROVIDER=none' }
    if ($EnablePublicFulltext) {
        # This explicit switch opts in to sending incomplete post IDs to FxEmbed.
        if ($configText -match '(?m)^X_PUBLIC_FULLTEXT_PROVIDER=') {
            $configText = $configText -replace '(?m)^X_PUBLIC_FULLTEXT_PROVIDER=.*$', 'X_PUBLIC_FULLTEXT_PROVIDER=fxembed'
        } else { $configText += "`nX_PUBLIC_FULLTEXT_PROVIDER=fxembed`n" }
    }
    if ($createdConfig -or $EnablePublicFulltext) { [IO.File]::WriteAllText($envPath, $configText, (New-Object Text.UTF8Encoding($false))) }
    if (-not $SkipSkill) {
        & $pythonExecutable -X utf8 -c 'import os; from pathlib import Path; import subprocess,sys; p=Path(os.environ.get("CODEX_HOME",str(Path.home()/".codex")))/"skills"/"x-second-brain"; print("Existing Codex Skill preserved: "+str(p)) if p.exists() else subprocess.run([sys.executable,"scripts/install_skill.py"],check=True)'
        if ($LASTEXITCODE -ne 0) { throw 'Codex Skill installation failed. See README.md.' }
    }
    if (-not $NoAutostart) { & (Join-Path $PSScriptRoot 'autostart.ps1') -Action enable }
    if (-not $NoStart) {
        & $pythonExecutable -X utf8 -m xsecondbrain.agent_cli start --setup-if-needed
        if ($LASTEXITCODE -ne 0) { throw 'Service startup failed. Check data/agent-console.log.' }
    }
    Write-Output 'Installed. Next: load xsecondbrain/browser_extension in Chrome or Edge, pair at http://127.0.0.1:8787/, and sign in to Codex CLI for AI reading. See README.md.'
    Write-Output 'Public fulltext lookup is optional; read its privacy notice before using -EnablePublicFulltext.'
} finally { Pop-Location }
