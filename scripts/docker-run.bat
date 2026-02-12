@echo off
cd /d %~dp0..
docker run -p 8080:8080 %* mcp-zero
