@echo off
REM Setup auto-update hooks for PROJECT.md (Windows)
REM 
REM Usage:
REM   setup-hooks.bat

setlocal enabledelayedexpansion

echo.
echo 🔧 Setting up PROJECT.md auto-update hooks...
echo.

REM Get git root
for /f "tokens=*" %%i in ('git rev-parse --show-toplevel') do set REPO_ROOT=%%i
set HOOKS_DIR=%REPO_ROOT%\.githooks

REM Create .githooks directory if it doesn't exist
if not exist "%HOOKS_DIR%" (
    echo 📁 Creating .githooks directory...
    mkdir "%HOOKS_DIR%"
)

REM Configure git to use .githooks
echo ⚙️  Configuring git hooks path...
git config core.hooksPath "%HOOKS_DIR%"

echo.
echo ✅ Hooks configured successfully!
echo.
echo 📋 What now happens automatically:
echo    1. When you stage code changes (.java, .cs, .feature files)
echo    2. The pre-commit hook runs update-project-mindmap.py
echo    3. PROJECT.md is updated with new API endpoints, services, tests
echo    4. PROJECT.md is automatically staged with your commit
echo.
echo 🚀 Next steps:
echo    - Make changes to any controller, service, or feature file
echo    - Run: git add ^<files^>
echo    - PROJECT.md will be updated automatically
echo    - Run: git commit -m "your message"
echo.
echo 📚 Manual update (anytime):
echo    python update-project-mindmap.py
echo.
pause
