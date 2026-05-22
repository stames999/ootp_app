@echo off
REM Pistachio desktop launcher. Double-click on Windows to start the
REM Streamlit app locally and open it in your default browser.
REM
REM Streamlit prints a "Local URL: http://localhost:8501" line when it's
REM ready; the browser opens automatically. Close this terminal window
REM to stop the server.

title Pistachio (Streamlit) - close this window to stop

cd /d "%~dp0"

REM Use `python -m streamlit` since streamlit isn't on PATH for this
REM user's environment (per CLAUDE memory). --server.headless=false keeps
REM the default behaviour of opening the browser on startup.
python -m streamlit run streamlit_app.py

REM If streamlit exited with an error, hold the window open so the user
REM can read the traceback instead of having it flash and close.
if %ERRORLEVEL% neq 0 (
    echo.
    echo Streamlit exited with code %ERRORLEVEL%. Press any key to close.
    pause >nul
)
