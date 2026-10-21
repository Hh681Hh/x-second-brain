param([ValidateSet('enable','disable','status')][string]$Action = 'status')
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonWindowless = Join-Path $projectDir '.venv\Scripts\pythonw.exe'
$pythonConsole = Join-Path $projectDir '.venv\Scripts\python.exe'
$startupDir = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDir 'X Second Brain.lnk'
Push-Location -LiteralPath $projectDir
try {
    if (-not (Test-Path -LiteralPath $pythonWindowless)) { throw 'Install the project Python environment first.' }
    $dataDir = & $pythonConsole -X utf8 -c 'from xsecondbrain.config import Settings; print(Settings.from_env().data_dir.resolve())'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read the project data directory.' }
    $enabledPath = Join-Path $dataDir 'autostart.enabled'
    if ($Action -eq 'enable') {
        New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
        New-Item -ItemType File -Path $enabledPath -Force | Out-Null
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $pythonWindowless
        $shortcut.Arguments = '-X utf8 -m xsecondbrain.autostart'
        $shortcut.WorkingDirectory = $projectDir
        $shortcut.Description = 'Start the local X knowledge reader at Windows sign-in'
        $shortcut.WindowStyle = 7
        $shortcut.Save()
        # Launch exactly the saved logon entry, so installation exercises its path.
        Start-Process -FilePath $shortcutPath -WindowStyle Hidden
    } elseif ($Action -eq 'disable') {
        if (Test-Path -LiteralPath $enabledPath) { Remove-Item -LiteralPath $enabledPath }
        if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }
        Write-Output 'Autostart disabled. The supervisor exits within 1 second; the existing service is left running.'
    }
    $shell = New-Object -ComObject WScript.Shell
    $registered = Test-Path -LiteralPath $shortcutPath
    $target = if ($registered) { $shell.CreateShortcut($shortcutPath) } else { $null }
    [pscustomobject]@{
        enabled = ($registered -and (Test-Path -LiteralPath $enabledPath))
        shortcut = $shortcutPath
        target = if ($target) { $target.TargetPath } else { '' }
        arguments = if ($target) { $target.Arguments } else { '' }
        directory = if ($target) { $target.WorkingDirectory } else { '' }
        scope = 'Current user, after Windows sign-in; no administrator privileges'
    } | ConvertTo-Json
} finally { Pop-Location }
