import argparse
import base64
import getpass
import os
from pathlib import Path
import shlex
import socket
import stat
import zipfile
import zlib
import tkinter as tk




class VFSLoadError(Exception):
    """Ошибка чтения ZIP или структуры виртуальной файловой системы."""


class MemoryVFS:
    """Содержимое ZIP живёт только в памяти. Архив открыт лишь при загрузке."""
    def __init__(self):
        self.directories = {"/"}
        self.files = {}  # Виртуальный путь -> строка base64, включая двоичные файлы.
        self.cwd = "/"   # Не связан с текущей папкой реальной ОС.

    def add_directory(self, path):
        if path in self.files:
            raise VFSLoadError(f"путь одновременно является файлом и папкой: {path}")
        self.directories.add(path)

    @classmethod
    def from_zip(cls, archive_path):
        vfs = cls()
        seen = set()
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                for info in archive.infolist():
                    name = info.orig_filename
                    # У ZIP свои пути: только относительные имена с разделителем /.
                    parts = name.rstrip("/").split("/")
                    if (name.startswith("/") or "\\" in name or "\x00" in name
                            or any(part in ("", ".", "..") for part in parts)):
                        raise VFSLoadError(f"недопустимое имя в ZIP: {name!r}")
                    if stat.S_ISLNK(info.external_attr >> 16):
                        raise VFSLoadError(f"символические ссылки не поддерживаются: {name}")
                    path = "/" + "/".join(parts)
                    if path in seen:
                        raise VFSLoadError(f"повторяющийся путь в ZIP: {path}")
                    seen.add(path)
                    # ZIP может содержать файл a/b/c.txt без записей папок a/ и a/b/.
                    for length in range(1, len(parts)):
                        vfs.add_directory("/" + "/".join(parts[:length]))
                    if info.is_dir():
                        vfs.add_directory(path)
                    else:
                        if path in vfs.directories:
                            raise VFSLoadError(f"путь одновременно является файлом и папкой: {path}")
                        data = archive.read(info)  # Байты в памяти, НЕ extract()/extractall().
                        vfs.files[path] = base64.b64encode(data).decode("ascii")
        except FileNotFoundError as error:
            raise VFSLoadError(f"файл не найден: {archive_path}") from error
        except zipfile.BadZipFile as error:
            raise VFSLoadError(f"неверный формат или повреждённый ZIP: {archive_path}") from error
        except (OSError, ValueError, RuntimeError, NotImplementedError, EOFError, zlib.error) as error:
            raise VFSLoadError(f"не удалось прочитать ZIP: {error}") from error
        return vfs

    def resolve(self, path):
        """Разбирает /, относительные пути, . и .. только внутри VFS."""
        if not path or "\x00" in path:
            raise FileNotFoundError("пустой или недопустимый путь")
        parts = [] if path.startswith("/") else self.cwd.strip("/").split("/")
        parts = [part for part in parts if part]
        for part in path.split("/"):
            if not part:
                continue
            current = "/" + "/".join(parts)
            if current not in self.directories:
                raise NotADirectoryError(current)
            if part == ".":
                continue
            if part == "..":
                if parts:
                    parts.pop()  # Выше виртуального корня выйти нельзя.
                continue
            parts.append(part)
            candidate = "/" + "/".join(parts)
            if candidate not in self.directories and candidate not in self.files:
                raise FileNotFoundError(candidate)
        result = "/" + "/".join(parts)
        if path.endswith("/") and result not in self.directories:
            raise NotADirectoryError(result)
        return result

    def listdir(self, path="."):
        path = self.resolve(path)
        if path not in self.directories:
            raise NotADirectoryError(path)
        prefix = path.rstrip("/") + "/"
        names = set()
        for item in self.directories | self.files.keys():
            if item.startswith(prefix):
                tail = item[len(prefix):]
                if tail and "/" not in tail:
                    names.add(tail)
        return sorted(names)

    def chdir(self, path="/"):
        new_path = self.resolve(path)
        if new_path not in self.directories:
            raise NotADirectoryError(new_path)
        self.cwd = new_path

    def read_bytes(self, path):
        """Восстановление исходных байтов из памяти, без чтения файлов ОС."""
        path = self.resolve(path)
        if path in self.directories:
            raise IsADirectoryError(path)
        return base64.b64decode(self.files[path], validate=True)


def read_config(argv=None):
    cli = argparse.ArgumentParser(description="GUI-эмулятор: этап 3, VFS в памяти")
    cli.add_argument("--vfs", default=str(Path(__file__).resolve().parent / "examples/vfs/minimal.zip"),
                     help="Путь к ZIP-архиву VFS (по умолчанию examples/vfs/minimal.zip)")
    cli.add_argument("--script", help="Путь к стартовому скрипту UTF-8")
    config = cli.parse_args(argv)

    
    config.vfs = os.path.abspath(os.path.expanduser(os.path.expandvars(config.vfs)))
    if config.script is not None:
        config.script = os.path.abspath(
            os.path.expanduser(os.path.expandvars(config.script))
        )
    return config


def config_text(config):
    return (
        "Параметры запуска:\n"
        f"  --vfs: {config.vfs}\n"
        f"  --script: {config.script or '(не задан)'}\n\n"
    )



def parser(user_input: str) -> dict:
    try:
        tokens = shlex.split(user_input.strip())
    except ValueError as error:
        return {"command": None, "args": [], "error": f"Ошибка ввода: {error}"}
    if not tokens:
        return {"command": None, "args": [], "error": None}
    args = [os.path.expanduser(os.path.expandvars(arg)) for arg in tokens[1:]]
    return {"command": tokens[0], "args": args, "error": None}



def command_result(output="", error=False, exit_requested=False):
    return {"output": output, "error": error, "exit_requested": exit_requested}


def path_error(command, path, error):
    if isinstance(error, FileNotFoundError):
        reason = "нет такого файла или каталога"
    elif isinstance(error, NotADirectoryError):
        reason = "не каталог"
    elif isinstance(error, PermissionError):
        reason = "доступ запрещён"
    else:
        reason = str(error)
    return command_result(f"{command}: {path}: {reason}", error=True)


def do_ls(args, vfs):
    if vfs is None:
        return command_result("ls: VFS не загружена", error=True)
    if len(args) > 1:
        return command_result("ls: ожидается не более одного пути", error=True)
    path = args[0] if args else "."
    try:
        return command_result("\n".join(vfs.listdir(path)))
    except (OSError, ValueError) as error:
        return path_error("ls", path, error)


def do_cd(args, vfs):
    if vfs is None:
        return command_result("cd: VFS не загружена", error=True)
    if len(args) > 1:
        return command_result("cd: ожидается не более одного пути", error=True)
    path = args[0] if args else "/"
    try:
        vfs.chdir(path)
        return command_result()
    except (OSError, ValueError) as error:
        return path_error("cd", path, error)


def do_exit(args, vfs=None):
    if args:
        return command_result("exit: аргументы не поддерживаются", error=True)
    # Окно закроет GUI после показа команды. Обработчик не трогает виджеты.
    return command_result(exit_requested=True)


def judge(parsed, vfs):
    if parsed["error"]:
        return command_result(parsed["error"], error=True)
    if parsed["command"] is None:
        return command_result()
    handlers = {"ls": do_ls, "cd": do_cd, "exit": do_exit}
    handler = handlers.get(parsed["command"])
    if handler is None:
        return command_result(f"{parsed['command']}: команда не найдена", error=True)
    return handler(parsed["args"], vfs)


def make_invitation(vfs):
    return f"{vfs.cwd}$ " if vfs is not None else "[VFS не загружена]$ "


def execute_line(text, write, vfs):
    
    write(f"{make_invitation(vfs)}{text}\n")
    result = judge(parser(text), vfs)
    if result["output"]:
        write(result["output"] + "\n")
    return result



def script_steps(path, write, vfs):
    try:
        
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError, ValueError) as error:
        write(f"Ошибка чтения стартового скрипта: {error}\n")
        return

    for line_number, text in enumerate(lines, start=1):

        if not text.strip() or text.lstrip().startswith("#"):
            continue
        result = execute_line(text, write, vfs)
        if result["error"]:
            write(f"Стартовый скрипт остановлен: ошибка в строке {line_number}.\n")
        yield result
        if result["error"] or result["exit_requested"]:
            return
    write("Стартовый скрипт выполнен.\n")



class EmulatorApp:
    def __init__(self, GUI, config):
        self.GUI = GUI
        self.config = config
        self.vfs = None
        self.running_script = False
        GUI.configure(bg="#000000")
        GUI.title(f"Эмулятор - [{getpass.getuser()}@{socket.gethostname()}]")
        GUI.geometry("700x450")
        GUI.resizable(width=False, height=False)

        input_row = tk.Frame(GUI, bg="#000000")
        input_row.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        self.invitation = tk.Label(
            input_row, text="", bg="#000000", fg="#EBA10C",
            font=("Consolas", 11), anchor="w"
        )
        self.invitation.pack(side=tk.LEFT)
        self.entry = tk.Entry(
            input_row, bg="#000000", fg="#FFFFFF", insertbackground="#FFFFFF",
            font=("Consolas", 11), borderwidth=0, highlightthickness=0
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        output_row = tk.Frame(GUI, bg="#000000")
        output_row.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))
        scrollbar = tk.Scrollbar(output_row)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.output = tk.Text(
            output_row, bg="#000000", fg="#EBA10C", font=("Consolas", 11),
            borderwidth=0, highlightthickness=0, takefocus=0, state=tk.DISABLED,
            yscrollcommand=scrollbar.set
        )
        self.output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.configure(command=self.output.yview)

        self.output_print(config_text(config))
        self.update_invitation()
        self.entry.bind("<Return>", self.on_enter)
        
        self.entry.configure(state=tk.DISABLED)
        GUI.after_idle(self.startup)

    def output_print(self, text):
        self.output.configure(state=tk.NORMAL)
        try:
            self.output.insert(tk.END, text)
            self.output.see(tk.END)
        finally:
            self.output.configure(state=tk.DISABLED)

    def update_invitation(self):
        self.invitation.configure(text=make_invitation(self.vfs))

    def enable_input(self):
        self.running_script = False
        self.entry.configure(state=tk.NORMAL)
        self.update_invitation()
        self.entry.focus_set()

    def on_enter(self, event=None):
        if self.running_script:
            return "break"
        text = self.entry.get()
        self.entry.delete(0, tk.END)
        result = execute_line(text, self.output_print, self.vfs)
        if result["exit_requested"]:
            self.GUI.destroy()
            return "break"
        self.update_invitation()
        self.entry.focus_set()
        return "break"

    def startup(self):
        try:
            self.vfs = MemoryVFS.from_zip(self.config.vfs)
        except VFSLoadError as error:
            self.output_print(f"Ошибка загрузки VFS: {error}\nСтартовый скрипт не запущен.\n")
            self.enable_input()
            return
        self.output_print(f"VFS загружена в память: файлов — {len(self.vfs.files)}, "
                          f"папок — {len(self.vfs.directories)} (включая /).\n")
        self.update_invitation()
        if self.config.script is None:
            self.enable_input()
            return
        self.running_script = True
        self.steps = script_steps(self.config.script, self.output_print, self.vfs)
        self.run_next_script_line()

    def run_next_script_line(self):
        try:
            result = next(self.steps)
        except StopIteration:
            self.enable_input()
            return
        self.update_invitation()
        if result["exit_requested"]:
            self.steps.close()
            self.GUI.after(100, self.GUI.destroy)
        elif result["error"]:
            self.steps.close()
            self.enable_input()
        else:
            
            self.GUI.after(60, self.run_next_script_line)


def main(argv=None):
    config = read_config(argv)
    print(config_text(config), end="", flush=True)
    try:
        GUI = tk.Tk()
    except tk.TclError as error:
        print(f"Не удалось открыть GUI: {error}")
        return 1
    EmulatorApp(GUI, config)
    GUI.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
