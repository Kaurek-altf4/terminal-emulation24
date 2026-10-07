#!/usr/bin/env bash
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
# Оба параметра, раскрытие переменной ОС, ls без аргументов и cd.
export REPL_DEMO_ROOT="$project_dir/examples/vfs"
python3 GUI.py --vfs "$project_dir/examples/vfs" --script "$project_dir/examples/startup_ok.txt"
