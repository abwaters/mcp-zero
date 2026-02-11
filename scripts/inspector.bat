@echo off
REM Launch the MCP Inspector pointed at the running gateway.
REM Usage: scripts\inspector.bat

cd /d %~dp0..

echo Connecting inspector to %URL%
npx -y @modelcontextprotocol/inspector
