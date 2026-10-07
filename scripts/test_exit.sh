#!/usr/bin/env bash
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
# Команда exit закроет окно, следующая команда не выполнится.
python3 GUI.py --vfs "$project_dir/examples/vfs" --script "$project_dir/examples/startup_exit.txt"
