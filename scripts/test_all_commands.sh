#!/usr/bin/env bash
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
export VFS_DEMO_DIR="/docs"
for startup in "$project_dir/scripts/startup_all.txt" \
               "$project_dir/scripts/startup_error.txt" \
               "$project_dir"/scripts/errors/*.txt \
               "$project_dir/scripts/startup_exit.txt"; do
    printf 'Проверка: %s\n' "$startup"
    bash "$project_dir/run.sh" --vfs "$project_dir/vfs/deep.zip" --script "$startup"
done
