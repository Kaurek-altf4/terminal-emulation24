#!/usr/bin/env bash
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
bash "$project_dir/run.sh" --vfs "$project_dir/vfs/папка с пробелами/пример VFS.zip" --script "$project_dir/scripts/папка с пробелами/startup.txt"
