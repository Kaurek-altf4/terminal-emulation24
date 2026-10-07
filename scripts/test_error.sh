#!/usr/bin/env bash
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
# После unknown_command скрипт остановится, окно останется открытым.
python3 GUI.py --vfs "$project_dir/examples/vfs" --script "$project_dir/examples/startup_error.txt"
