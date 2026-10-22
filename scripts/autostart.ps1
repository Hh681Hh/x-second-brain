param([ValidateSet('enable','disable','status')][string]$Action = 'status')
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonWindowless = Join-Path $projectDir '.venv\Scripts\pythonw.exe'
$pythonConsole = Join-Path $projectDir '.venv\Scripts\python.exe'
$startupDir = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDir 'X Second Brain.lnk'
$taskName = 'X Second Brain Watchdog'
Push-Location -LiteralPath $projectDir
try {
    if (-not (Test-Path -LiteralPath $pythonWindowless)) { throw 'Install the project Python environment first.' }
    $dataDir = & $pythonConsole -X utf8 -c 'from xsecondbrain.config import Settings; print(Settings.from_env().data_dir.resolve())'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read the project data directory.' }
    $enabledPath = Join-Path $dataDir 'autostart.enabled'
    if ($Action -eq 'enable') {
        $codexExecutable = & $pythonConsole -X utf8 -c 'from xsecondbrain.config import Settings; import shutil; print(shutil.which(Settings.from_env().codex_binary) or "")'
        if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve the Codex reader executable.' }
        $supervisorArguments = '-X utf8 -m xsecondbrain.autostart'
        if ($codexExecutable) {
            $supervisorArguments += ' --codex-binary "' + $codexExecutable + '"'
        } else {
            Write-Warning 'Codex CLI was not found. Saving and search work, but automatic AI reading is unavailable.'
        }
        New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
        New-Item -ItemType File -Path $enabledPath -Force | Out-Null
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $pythonWindowless
        $shortcut.Arguments = $supervisorArguments
        $shortcut.WorkingDirectory = $projectDir
        $shortcut.Description = 'Start the local X knowledge reader at Windows sign-in'
        $shortcut.WindowStyle = 7
        $shortcut.Save()
        try {
            # Windows owns this watchdog, so losing the launching terminal or
            # supervisor does not leave the service offline until next sign-in.
            $taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            $taskAction = New-ScheduledTaskAction -Execute $pythonWindowless -Argument $supervisorArguments -WorkingDirectory $projectDir
            $taskTriggers = @((New-ScheduledTaskTrigger -AtLogOn -User $taskUser), (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)))
            $taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
            $taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
            Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTriggers -Settings $taskSettings -Principal $taskPrincipal -Description 'Restore the local X bookmark service at sign-in and if its supervisor exits.' -Force -ErrorAction Stop | Out-Null
            Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
        } catch {
            Write-Warning 'Windows watchdog registration failed. Using the sign-in shortcut only; automatic supervisor recovery is unavailable.'
            Start-Process -FilePath $shortcutPath -WindowStyle Hidden
        }
    } elseif ($Action -eq 'disable') {
        if (Test-Path -LiteralPath $enabledPath) { Remove-Item -LiteralPath $enabledPath }
        if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }
        $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($existingTask) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop }
        Write-Output 'Autostart disabled. The supervisor exits within 1 second; the existing service is left running.'
    }
    $shell = New-Object -ComObject WScript.Shell
    $registered = Test-Path -LiteralPath $shortcutPath
    $target = if ($registered) { $shell.CreateShortcut($shortcutPath) } else { $null }
    $watchdog = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    [pscustomobject]@{
        enabled = ($registered -and (Test-Path -LiteralPath $enabledPath))
        shortcut = $shortcutPath
        target = if ($target) { $target.TargetPath } else { '' }
        arguments = if ($target) { $target.Arguments } else { '' }
        directory = if ($target) { $target.WorkingDirectory } else { '' }
        watchdog_task = if ($watchdog) { $watchdog.TaskName } else { '' }
        watchdog_state = if ($watchdog) { [string]$watchdog.State } else { 'Not registered' }
        health_command = '.venv/Scripts/python.exe -m xsecondbrain.agent_cli status'
        scope = 'Current user, after Windows sign-in; no administrator privileges'
    } | ConvertTo-Json
} finally { Pop-Location }
