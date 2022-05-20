# This file is part of SecureVoting.
# Copyright (C) 2021 Lihi Dery, Tamir Tassa, Avishay Yanai, Arthur Zamarin
#
# Foobar is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Foobar is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Foobar.  If not, see <https://www.gnu.org/licenses/>.

import tkinter as tk
import tkinter.messagebox as msgbox
from tkinter.ttk import Frame, Button, Label, Entry, Radiobutton, Checkbutton

import config
config = config.load()


class OrderSelection(Frame):
    def __init__(self, master, **kw):
        super().__init__(master)
        Label(self, text="Least Favorite").pack(fill=tk.X, padx=5, pady=5)
        self.listbox = tk.Listbox(self, selectmode=tk.SINGLE)
        for name in config.CANDIDATES:
            self.listbox.insert(tk.END, name)
        self.listbox.pack(fill=tk.BOTH)
        Label(self, text="Most Favorite").pack(fill=tk.X, padx=5, pady=5)
        self.listbox.bind('<Button-1>', self.set_current)
        self.listbox.bind('<B1-Motion>', self.shift_selection)
        self.curIndex = None

    def set_current(self, event):
        self.curIndex = self.listbox.nearest(event.y)

    def shift_selection(self, event):
        i = self.listbox.nearest(event.y)
        if i == self.curIndex:
            return
        x = self.listbox.get(i)
        self.listbox.delete(i)
        if i < self.curIndex:
            self.listbox.insert(i + 1, x)
        elif i > self.curIndex:
            self.listbox.insert(i - 1, x)
        self.curIndex = i

    def selection(self) -> [int]:
        texts = list(self.listbox.get(0, tk.END))
        return [texts.index(name) for name in config.CANDIDATES]


def validate_less(value: int):
    def func(value_if_allowed):
        try:
            return (not value_if_allowed) or (0 <= int(value_if_allowed) < value)
        except ValueError:
            return False
    return func


class RadioSelection(Frame):
    def __init__(self, master, onvalue: int):
        super().__init__(master)
        self.onvalue = onvalue
        self.var = tk.IntVar()
        for idx, name in enumerate(config.CANDIDATES):
            Radiobutton(self, text=name, variable=self.var, value=idx).pack(anchor=tk.W)

    def selection(self) -> [int]:
        arr = [1 - self.onvalue] * config.M
        arr[self.var.get()] = self.onvalue
        return arr


class CheckSelection(Frame):
    def __init__(self, master):
        super().__init__(master)
        self.vars = [tk.IntVar() for _ in config.CANDIDATES]
        for name, var in zip(config.CANDIDATES, self.vars):
            Checkbutton(self, text=name, variable=var, onvalue=1, offvalue=0).pack(anchor=tk.W)

    def selection(self) -> [int]:
        return tuple(map(tk.IntVar.get, self.vars))


class ValueSelection(Frame):
    def __init__(self, master, max_value: int):
        super().__init__(master)
        self.vars = [tk.StringVar() for _ in config.CANDIDATES]
        for name, var in zip(config.CANDIDATES, self.vars):
            (frame := Frame(self)).pack(fill=tk.X)
            Entry(frame, textvariable=var, width=6, validate='key', validatecommand=(frame.register(validate_less(max_value + 1)), '%P')).pack(side=tk.LEFT, padx=5, pady=5)
            Label(frame, text=name).pack(fill=tk.X, padx=5, expand=True)

    def selection(self) -> [int]:
        return tuple(map(int, map(tk.StringVar.get, self.vars)))


class RangeSelection(Frame):
    def __init__(self, master):
        super().__init__(master)
        self.vars = [tk.IntVar() for _ in config.CANDIDATES]
        for name, var in zip(config.CANDIDATES, self.vars):
            tk.Scale(self, variable=var, from_=0, to=config.L, orient=tk.HORIZONTAL, label=name).pack(fill=tk.X)

    def selection(self) -> [int]:
        return tuple(map(tk.IntVar.get, self.vars))


class VoteSystem(Frame):
    def setup_vote_system(self):
        if config.selected_vote_system == config.VoteSystem.PLURALITY:
            return RadioSelection(self, 1)
        elif config.selected_vote_system == config.VoteSystem.RANGE:
            return RangeSelection(self)
        elif config.selected_vote_system == config.VoteSystem.APPROVAL:
            return CheckSelection(self)
        elif config.selected_vote_system == config.VoteSystem.VETO:
            return RadioSelection(self, 0)
        elif config.selected_vote_system == config.VoteSystem.BORDA:
            return OrderSelection(self)

    def __init__(self):
        super().__init__()
        self.system = self.setup_vote_system()
        self.system.pack(fill=tk.BOTH)

    def reset_system(self, force: bool):
        self.system.destroy()
        self.system = ValueSelection(self, config.p) if force else self.setup_vote_system()
        self.system.pack(fill=tk.BOTH)

    def selection(self) -> [int]:
        return self.system.selection()


class Voter(Frame):
    def __init__(self):
        super().__init__()
        self.master.title("Voter")
        self.pack(fill=tk.BOTH, expand=True)

        Label(self, text=f'Voting {Voter.current_vote_rule()} rule', width=6).pack(fill=tk.X)
        (frame := Frame(self)).pack(fill=tk.X)
        Label(frame, text="Voter ID: ", width=6.3).pack(side=tk.LEFT, padx=5, pady=5)
        self.id = tk.StringVar()
        Entry(frame, validate='key', validatecommand=(self.register(validate_less(config.p)), '%P'), textvariable=self.id).pack(fill=tk.X, padx=5, expand=True)

        self.system = VoteSystem()
        self.system.pack(fill=tk.BOTH, expand=True)

        Button(self, text="Close", command=self.master.destroy).pack(side=tk.RIGHT, padx=5, pady=5)
        Button(self, text="OK", command=self.send_selection).pack(side=tk.RIGHT, padx=5, pady=5)
        if config.debug:
            Button(self, text="Force", command=lambda: self.system.reset_system(True)).pack(side=tk.RIGHT, padx=5, pady=5)

    @staticmethod
    def current_vote_rule():
        if config.selected_vote_system == config.VoteSystem.PLURALITY:
            return 'Plurality'
        elif config.selected_vote_system == config.VoteSystem.RANGE:
            return f'Range [0,{config.L}]'
        elif config.selected_vote_system == config.VoteSystem.APPROVAL:
            return 'Approval'
        elif config.selected_vote_system == config.VoteSystem.VETO:
            return 'Veto'
        elif config.selected_vote_system == config.VoteSystem.BORDA:
            return 'Board'
        else:
            return 'Custom'

    def send_selection(self):
        try:
            voter_id = int(self.id.get())
            from voter import main
            res = main(voter_id, self.system.selection())
            if res == 0:
                msgbox.showinfo('Verified', f'The vote was verified using {Voter.current_vote_rule()} rule for ID: {voter_id}')
                self.master.destroy()
            elif res == 1:
                msgbox.showerror('Not Verified', f'The vote was defined invalid by talliers: you have already voted or invalid vote.')
            else:
                msgbox.showerror('Not Verified', f'The vote was received incorrectly. The vote might be compromised.')
        except ValueError:
            msgbox.showinfo('Invalid ID', 'The ID is invalid')


def main():
    root = tk.Tk()
    Voter()
    root.mainloop()


if __name__ == '__main__':
    main()
