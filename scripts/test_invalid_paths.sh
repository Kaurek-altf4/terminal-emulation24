#!/usr/bin/env bash
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
test_dir=$(mktemp -d)
trap 'rmdir "$test_dir"' EXIT
printf '%s\n' '1. VFS не существует.'
bash "$project_dir/run.sh" --vfs "$test_dir/missing.zip" --script "$project_dir/scripts/startup_minimal.txt"
printf '%s\n' '2. Неверный формат VFS.'
bash "$project_dir/run.sh" --vfs "$project_dir/vfs/invalid.zip" --script "$project_dir/scripts/startup_minimal.txt"
printf '%s\n' '3. Папка вместо ZIP-архива.'
bash "$project_dir/run.sh" --vfs "$project_dir/vfs" --script "$project_dir/scripts/startup_minimal.txt"
printf '%s\n' '4. Стартовый скрипт не существует.'
bash "$project_dir/run.sh" --vfs "$project_dir/vfs/minimal.zip" --script "$test_dir/missing.txt"
printf '%s\n' '5. Папка вместо стартового скрипта.'
bash "$project_dir/run.sh" --vfs "$project_dir/vfs/minimal.zip" --script "$project_dir/vfs"
