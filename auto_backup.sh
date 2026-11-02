#!/usr/bin/env bash
# 仅备份源码：.env / *.db / data / uploads 已在 .gitignore 中排除。
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .git ]; then
  echo "[backup] 未初始化 git 仓库，跳过。"
  exit 0
fi

git add -A

if git diff --cached --name-only | grep -Eq '(^|/)\.env($|\.)|\.(db|sqlite3?)$|^(data|uploads|backups|cookies)/'; then
  echo "[backup] 检测到敏感文件，已中止并撤销暂存。"
  git reset >/dev/null
  exit 1
fi

if git diff --cached --quiet; then
  echo "[backup] 没有变化，跳过提交。"
  exit 0
fi

git commit -m "auto backup: $(date '+%Y-%m-%d %H:%M:%S')"
git push
echo "[backup] 源码已提交并推送。"
