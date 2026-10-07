#!/usr/bin/env bash
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
# Пробелы и кириллица в ОБОИХ параметрах запуска и аргументах команд.
python3 GUI.py --vfs "$project_dir/examples/папка с пробелами" --script "$project_dir/examples/папка с пробелами/startup.txt"
