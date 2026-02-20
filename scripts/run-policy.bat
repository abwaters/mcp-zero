@echo off
REM Run the gateway with a named policy from the policies/ directory.
REM Usage: scripts\run-policy.bat <policy-name> [extra-args...]
REM Example: scripts\run-policy.bat everything
REM          scripts\run-policy.bat everything --host 0.0.0.0 --port 9000

cd /d %~dp0..

if "%~1"=="" (
    echo Usage: scripts\run-policy.bat ^<policy-name^> [extra-args...]
    echo.
    echo Available policies:
    for %%f in (policies\*.yaml policies\*.yml policies\*.json) do (
        echo   %%~nf
    )
    exit /b 1
)

set POLICY_NAME=%~1
shift

REM Resolve the policy file (try .yaml, then .yml, then .json)
if exist "policies\%POLICY_NAME%.yaml" (
    set MCP_POLICY_FILE=policies\%POLICY_NAME%.yaml
) else if exist "policies\%POLICY_NAME%.yml" (
    set MCP_POLICY_FILE=policies\%POLICY_NAME%.yml
) else if exist "policies\%POLICY_NAME%.json" (
    set MCP_POLICY_FILE=policies\%POLICY_NAME%.json
) else (
    echo Error: No policy file found for "%POLICY_NAME%"
    echo Looked for: policies\%POLICY_NAME%.yaml, .yml, .json
    exit /b 1
)

echo Using policy: %MCP_POLICY_FILE%
call .venv\Scripts\activate.bat
set MCP_ALLOW_INSECURE=true
python -m mcp_zero %1 %2 %3 %4 %5 %6 %7 %8 %9 
