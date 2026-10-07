from tkinter import *
import getpass
import socket
import shlex
import os


def parser(user_input: str) -> dict:
    try:
        tokens = shlex.split(user_input)
    except ValueError as error:
        return {
            "command": None,
            "args": [],
            "error": f"Ошибка ввода: {error}"
        }

    if not tokens:
        return {"command": None, "args": [], "error": None}

    command = tokens[0]
    args = [os.path.expandvars(arg) for arg in tokens[1:]]

    return {"command": command, "args": args, "error": None}


def do_ls(args):
    return f"Команда: ls, аргументы: {args}"


def do_cd(args):
    return f"Команда: cd, аргументы: {args}"


def do_exit(args):
    GUI.destroy()
    return ""


def judge(parsed):
    if parsed["error"]:
        return parsed["error"]

    command = parsed["command"]
    args = parsed["args"]

    if command is None:
        return ""

    handlers = {
        "ls": do_ls,
        "cd": do_cd,
        "exit": do_exit
    }

    handler = handlers.get(command)

    if handler is None:
        return f"Ошибка: команда «{command}» не найдена"

    return handler(args)


GUI = Tk()
GUI.configure(bg="#000000")

username = getpass.getuser()
hostname = socket.gethostname()

GUI.title(f"Эмулятор - [{username}@{hostname}]")
GUI.geometry("700x450")
GUI.resizable(width=False, height=False)

input_row = Frame(GUI, bg="#000000")
input_row.pack(side=TOP, fill=X, padx=5, pady=5)

invitation = Label(
    input_row,
    text="$ ",
    bg="#000000",
    fg="#EBA10C",
    font=("Consolas", 11)
)
invitation.pack(side=LEFT)

entry = Entry(
    input_row,
    bg="#000000",
    fg="#FFFFFF",
    insertbackground="#FFFFFF",
    font=("Consolas", 11),
    borderwidth=0,
    highlightthickness=0
)
entry.pack(side=LEFT, fill=X, expand=True)

output = Text(
    GUI,
    bg="#000000",
    fg="#EBA10C",
    font=("Consolas", 11),
    borderwidth=0,
    highlightthickness=0,
    takefocus=0,
    state=DISABLED
)
output.pack(side=TOP, fill=BOTH, expand=True, padx=5, pady=(0, 5))


def output_print(text):
    output.configure(state=NORMAL)
    try:
        output.insert("1.0", text)
    finally:
        output.configure(state=DISABLED)


def on_enter(event):
    text = entry.get()
    entry.delete(0, END)

    output_print(f"$ {text}\n")

    parsed = parser(text)
    result = judge(parsed)

    if parsed["command"] == "exit":
        return "break"

    if result:
        output_print(result + "\n")

    entry.focus_set()
    return "break"


entry.bind("<Return>", on_enter)
GUI.after_idle(entry.focus_set)
GUI.mainloop()