@echo off
REM ============================================================
REM  Jervis — Windows startup launcher
REM  Run this to start Jervis in the background on login.
REM  To enable auto-start with Windows, see README (Task Scheduler).
REM ============================================================
cd /d "%~dp0"
echo Starting Jervis...
python jervis_agent.py
pause