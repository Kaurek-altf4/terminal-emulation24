#!/usr/bin/env bash
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
export VFS_DEMO_DIR="/docs"
bash "$project_dir/run.sh" --vfs "$project_dir/vfs/multiple.zip" --script "$project_dir/scripts/startup_ok.txt"
