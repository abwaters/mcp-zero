@echo off
REM Launch the MCP Inspector pointed at the running gateway.
REM Usage: scripts\inspector.bat
REM        scripts\inspector.bat http://localhost:9000/mcp

cd /d %~dp0..

set URL=%~1
if "%URL%"=="" set URL=http://localhost:8080/mcp

echo Connecting inspector to %URL%
npx -y @modelcontextprotocol/inspector --cli %URL%
