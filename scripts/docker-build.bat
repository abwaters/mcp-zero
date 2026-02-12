@echo off
cd /d %~dp0..
docker build -t mcp-zero .
