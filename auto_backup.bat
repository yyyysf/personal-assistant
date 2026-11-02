@echo off
setlocal
cd /d "%~dp0"

if not exist ".git" (
  echo [backup] 未初始化 git 仓库，跳过。
  exit /b 0
)

git add -A

git diff --cached --name-only > "%TEMP%\assistant_backup_stage.txt"
findstr /I /C:".env" /C:".db" /C:".sqlite" /C:"data/" /C:"uploads/" "%TEMP%\assistant_backup_stage.txt" >nul
if not errorlevel 1 (
  echo [backup] 检测到敏感文件，已中止并撤销暂存。
  git reset >nul
  del "%TEMP%\assistant_backup_stage.txt" >nul 2>&1
  exit /b 1
)
del "%TEMP%\assistant_backup_stage.txt" >nul 2>&1

git diff --cached --quiet
if not errorlevel 1 (
  echo [backup] 没有变化，跳过提交。
  exit /b 0
)

git commit -m "auto backup: %date% %time%"
if errorlevel 1 exit /b 1

git push
if errorlevel 1 exit /b 1

echo [backup] 源码已提交并推送。
exit /b 0
