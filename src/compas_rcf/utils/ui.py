from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from os import name
from os import system
from tkinter import Tk
from tkinter.filedialog import askopenfilename
import threading
import sys

from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import PygmentsTokens
import pygments
from pygments.lexers.data import YamlLexer

if name == "nt":
    import msvcrt

__all__ = ["open_file_dialog", "pygment_yaml", "clear_screen"]

root = Tk()
root.withdraw()


def open_file_dialog(initial_dir="/", file_type=("JSON files", "*.json")):
    filename = askopenfilename(
        initialdir=initial_dir,
        title="Select file",
        filetypes=(file_type, ("all files", "*.*")),
    )
    return filename


def pygment_yaml(yaml):
    lexed_yaml = list(pygments.lex(yaml, lexer=YamlLexer()))
    print_formatted_text(PygmentsTokens(lexed_yaml))


def clear_screen():
    if name == "nt":
        system("cls")
    else:
        system("clear")


def return_pressed_key():
    keyhit = msvcrt.kbhit()
    if keyhit:
        result = ord(msvcrt.getch())
    else:
        result = 0
    return result


def read_input(caption, default=None, timeout=5):
    class KeyboardThread(threading.Thread):
        def run(self):
            self.timedout = False
            self.input = ""
            while True:
                if msvcrt.kbhit():
                    chr_ = msvcrt.getche()
                    if ord(chr_) == 13:
                        break
                    elif ord(chr_) >= 32:
                        self.input += chr_.decode("utf-8")
                if len(self.input) == 0 and self.timedout:
                    break

    sys.stdout.write("%s(%s):" % (caption, default))
    result = default
    it = KeyboardThread()
    it.start()
    it.join(timeout)
    it.timedout = True
    if len(it.input) > 0:
        # wait for rest of input
        it.join()
        result = it.input
    print("")  # needed to move to next line

    return result
