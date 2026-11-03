@echo off
rem Starts the public NEET Compass site (serve_public.py) and restarts it if it ever stops.
rem Windows runs this at login through a shortcut in the Startup folder; close this window to stop the site.
title NEET Compass live site
cd /d "%~dp0"
:run
"C:\Users\user\.venvs\neet-backend\Scripts\python.exe" serve_public.py
echo The site stopped. Restarting in 10 seconds (close this window to stop it for good)...
timeout /t 10 /nobreak >nul
goto run
