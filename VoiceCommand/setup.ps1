$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# 의존성 설치 전 실행되는 부트스트랩이므로 Ari i18n 모듈에 의존하지 않습니다.

function Test-Python311 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [string[]]$PrefixArguments = @()
    )

    & $Command @PrefixArguments -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" *> $null
    return $LASTEXITCODE -eq 0
}

Push-Location -LiteralPath $PSScriptRoot
try {
    $bootstrapCommand = $null
    $bootstrapArguments = @()

    if ((Get-Command py -ErrorAction SilentlyContinue) -and
        (Test-Python311 -Command "py" -PrefixArguments @("-3.11"))) {
        $bootstrapCommand = "py"
        $bootstrapArguments = @("-3.11")
    }
    elseif ((Get-Command python -ErrorAction SilentlyContinue) -and
        (Test-Python311 -Command "python")) {
        $bootstrapCommand = "python"
    }

    if (-not $bootstrapCommand) {
        Write-Host "[Ari] Python 3.11을 찾지 못했습니다."
        Write-Host "[Ari] Python 3.11을 설치하고 py 런처 또는 PATH를 활성화해 주세요."
        $exitCode = 1
    }
    else {
        # 기본 실행에서는 부트스트랩 Python으로 venv만 만들며,
        # 패키지는 시스템 Python이 아니라 프로젝트 venv에 설치합니다.
        Write-Host "[Ari] 프로젝트 의존성을 설치합니다..."
        & $bootstrapCommand @bootstrapArguments "install_dependencies.py" @args
        $exitCode = $LASTEXITCODE

        if ($exitCode -eq 0) {
            Write-Host "[Ari] 설치를 완료했습니다."
        }
        else {
            Write-Host "[Ari] 설치에 실패했습니다. 위 출력을 확인해 주세요."
        }
    }
}
finally {
    Pop-Location
}

[void](Read-Host "계속하려면 Enter 키를 누르세요")
exit $exitCode
