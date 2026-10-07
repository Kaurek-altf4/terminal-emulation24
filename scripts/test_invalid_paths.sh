#!/usr/bin/env bash
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
# После каждого случая закрой окно, чтобы перейти к следующему.
# Временная пустая папка гарантирует отсутствие указанных файлов.
test_dir=$(mktemp -d)
trap 'rmdir "$test_dir"' EXIT
printf '%s\n' 'Проверка отсутствующей VFS: скрипт не должен запускаться.'
python3 GUI.py --vfs "$test_dir/missing-vfs" --script "$project_dir/examples/startup_ok.txt"
printf '%s\n' 'Проверка отсутствующего стартового скрипта.'
python3 GUI.py --vfs "$project_dir/examples/vfs" --script "$test_dir/missing-script.txt"
printf '%s\n' 'Проверка папки вместо стартового скрипта.'
python3 GUI.py --vfs "$project_dir/examples/vfs" --script "$project_dir/examples/vfs"
