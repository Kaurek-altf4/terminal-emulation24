#!/usr/bin/env bash
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
for startup in "$project_dir/scripts/stage4/clear_error.txt" \
               "$project_dir/scripts/stage4/uptime_error.txt" \
               "$project_dir/scripts/stage4/ls_error.txt" \
               "$project_dir/scripts/stage4/cd_file_error.txt" \
               "$project_dir/scripts/errors/ls_extra.txt" \
               "$project_dir/scripts/errors/cd_extra.txt" \
               "$project_dir/scripts/errors/ls_file.txt" \
               "$project_dir/scripts/errors/ls_empty_path.txt" \
               "$project_dir/scripts/errors/cd_empty_path.txt"; do
    printf 'Проверка: %s\n' "$startup"
    bash "$project_dir/run.sh" --vfs "$project_dir/vfs/deep.zip" --script "$startup"
done
