"""Build local VFS examples from versioned text sources."""

import base64
from pathlib import Path
import shutil
import zipfile


VFS_ROOT = Path(__file__).resolve().parents[1] / "vfs"


def archive_entry(source, path):
    name = path.relative_to(source).as_posix()
    data = path.read_bytes()
    if path.suffix == ".b64":
        name = name.removesuffix(".b64")
        data = base64.b64decode(b"".join(data.split()), validate=True)
    return name, data


def build_archive(name):
    source = VFS_ROOT / name
    target = VFS_ROOT / f"{name}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                entry_name, data = archive_entry(source, path)
                archive.writestr(entry_name, data)
        if name != "minimal":
            archive.writestr("empty/", b"")
    return target


def main():
    for name in ("minimal", "multiple", "deep"):
        build_archive(name)
    spaced = VFS_ROOT / "папка с пробелами"
    spaced.mkdir(exist_ok=True)
    shutil.copyfile(VFS_ROOT / "multiple.zip", spaced / "пример VFS.zip")
    (VFS_ROOT / "invalid.zip").write_text("Not a ZIP archive\n")
    print("Примеры VFS созданы в", VFS_ROOT)


if __name__ == "__main__":
    main()
