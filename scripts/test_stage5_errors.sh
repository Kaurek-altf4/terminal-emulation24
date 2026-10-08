#!/usr/bin/env bash
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
for startup in "$project_dir"/scripts/stage5/errors/*.txt; do
    printf 'Проверка: %s\n' "$startup"
    bash "$project_dir/run.sh" --vfs "$project_dir/vfs/deep.zip" --script "$startup"
done
