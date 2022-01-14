# Copyright (C) 2021-2022 Arthur Zamarin
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import tkinter as tk
import tkinter.messagebox as msgbox
import tkinter.simpledialog as dialogs
from tkinter.ttk import Frame, Button, Label, Entry, Radiobutton, Checkbutton
from random import randint
from threading import Thread

import config
config = config.load()


class ReordableListbox(tk.Listbox):
    def __init__(self, master, values):
        super().__init__(master, selectmode=tk.SINGLE)
        for name in values:
            self.insert(tk.END, name)
        self.bind('<Button-1>', self.set_current)
        self.bind('<B1-Motion>', self.shift_selection)
        self.curIndex = None

    def set_current(self, event):
        self.curIndex = self.nearest(event.y)

    def shift_selection(self, event):
        i = self.nearest(event.y)
        if i == self.curIndex:
            return
        x = self.get(i)
        self.delete(i)
        if i < self.curIndex:
            self.insert(i + 1, x)
        elif i > self.curIndex:
            self.insert(i - 1, x)
        self.curIndex = i


class CandidatesPanel(Frame):
    def __init__(self, master):
        super().__init__(master, relief=tk.RAISED, borderwidth=1)
        Label(self, text="Candidates:", font=(None, 15)).grid(sticky="W", columnspan=4)
        self.list = ReordableListbox(self, config.CANDIDATES)
        self.list.grid(row=1, rowspan=7, columnspan=3)
        Button(self, text="+", command=self.insert).grid(sticky="W", row=1, column=4)
        Button(self, text="-", command=self.remove).grid(sticky="W", row=2, column=4)
        (frame := Frame(self)).grid(sticky="W", row=8, columnspan=5)
        Label(frame, text='Number of Winners (K):').pack(side=tk.LEFT, padx=5, pady=5)
        self.K = tk.Scale(frame, from_=1, to=len(config.CANDIDATES), orient=tk.HORIZONTAL)
        self.K.pack(side=tk.LEFT, padx=5, pady=5)
        self.K.set(config.K)

    def insert(self):
        pos = self.list.curselection() or tk.END
        if answer := dialogs.askstring("Candidate Name", "Enter candidate name", parent=self):
            self.list.insert(pos, answer)
            self.K.configure(to=len(self.list.get(0, tk.END)))

    def remove(self):
        if self.list.curselection():
            self.list.delete(self.list.curselection())
            self.K.configure(to=len(self.list.get(0, tk.END)))

    def collect(self):
        return {
            'CANDIDATES': self.list.get(0, tk.END),
            'K': int(self.K.get())
        }


class TalliersPanel(Frame):
    def __init__(self, master):
        self.p = tk.StringVar()
        self.p.set(str(config.p))
        super().__init__(master, relief=tk.RAISED, borderwidth=1)
        Label(self, text="Talliers:", font=(None, 15)).grid(sticky="W", columnspan=4)

        self.list = ReordableListbox(self, config.TALLIERS)
        self.list.grid(row=1, rowspan=7, columnspan=3)
        Button(self, text="+", command=self.insert).grid(row=1, column=4)
        Button(self, text="-", command=self.remove).grid(row=2, column=4)
        Button(self, text="Auto Local", command=self.auto_local).grid(row=3, column=4)

        (frame := Frame(self)).grid(sticky="W", row=8, columnspan=5)
        Label(frame, text='p:').pack(side=tk.LEFT, padx=5, pady=5)
        Entry(frame, textvariable=self.p).pack(side=tk.LEFT, padx=5, pady=5)

    def insert(self):
        pos = self.list.curselection() or tk.END
        if ipaddr := dialogs.askstring("Add Tallier", "Enter IP address", parent=self):
            if port := dialogs.askinteger("Add Tallier", "Enter port number", parent=self):
                self.list.insert(pos, (ipaddr, port))

    def remove(self):
        if self.list.curselection():
            self.list.delete(self.list.curselection())

    def auto_local(self):
        if amount := dialogs.askinteger("Auto Add Tallier", "Enter amount of talliers", parent=self):
            self.list.delete(0, tk.END)
            base = randint(4000, 6000 - amount)
            for port in range(amount):
                self.list.insert(tk.END, ('127.0.0.1', base + port))

    def collect(self):
        return {
            'TALLIERS': self.list.get(0, tk.END),
            'p': int(self.p.get())
        }


class VotersPanel(Frame):
    def __init__(self, master):
        self.p = tk.StringVar()
        self.p.set(str(config.p))
        super().__init__(master, relief=tk.RAISED, borderwidth=1)
        Label(self, text="Voters:", font=(None, 15)).pack(fill=tk.X, expand=True)

        self.max_vote_var = tk.IntVar()
        self.max_vote = 0
        self.cb_max_vote = Checkbutton(self, text="Enforce Maximum Voter Count", variable=self.max_vote_var, onvalue=1, offvalue=0, command=self.ck_websockets)
        self.cb_max_vote.pack(fill=tk.X, expand=True)
        self.html_voting = tk.IntVar()
        Checkbutton(self, text="Allow HTML voting", variable=self.html_voting, onvalue=1, offvalue=0).pack(fill=tk.X, expand=True)

    def ck_websockets(self):
        self.cb_max_vote.config(text="Enforce Maximum Voter Count")
        if self.max_vote_var.get() == 1:
            if (amount := dialogs.askinteger("Voters Count", "Enter amount of voters", parent=self, initialvalue=self.max_vote)) and amount > 3:
                self.max_vote = amount
                self.cb_max_vote.config(text=f"Enforce Maximum Voter Count ({amount})")
            else:
                self.max_vote_var.set(0)
        else:
            self.max_vote = 0

    def collect(self):
        if self.max_vote == 0:
            return {}
        from uuid import uuid4
        from base64 import urlsafe_b64encode
        return {
            'websockets': bool(self.html_voting.get()),
            'VOTERS': [urlsafe_b64encode(uuid4().bytes).decode('ascii') for _ in range(self.max_vote)]
        }


class VoteSystem(Frame):
    def __init__(self, master):
        super().__init__(master, relief=tk.RAISED, borderwidth=1)
        self.L = config.L
        self.vote_system = tk.IntVar()
        self.vote_system.set(config.selected_vote_system.value)
        self.range_text = tk.StringVar()
        self.range_text.set(f'Range ({self.L})')
        Label(self, text="Voting Rule:", font=(None, 15)).grid(sticky="W", columnspan=4)
        Radiobutton(self, text='Plurality', variable=self.vote_system, value=0).grid(sticky="W", row=1, column=1)
        Radiobutton(self, textvariable=self.range_text, variable=self.vote_system, value=1, command=self.range_sel).grid(sticky="W", row=1, column=2)
        Radiobutton(self, text='Veto', variable=self.vote_system, value=3).grid(sticky="W", row=2, column=1)
        Radiobutton(self, text='Borda', variable=self.vote_system, value=4).grid(sticky="W", row=2, column=2)
        Radiobutton(self, text='Approval', variable=self.vote_system, value=2).grid(sticky="W", row=3, column=1)
        if config.debug:
            Radiobutton(self, text='Custom', variable=self.vote_system, value=5).grid(sticky="W", row=3, column=2)

    def range_sel(self):
        if L := dialogs.askinteger("Range Value", "Enter the L value for Range system", parent=self, initialvalue=self.L):
            if L > 0:
                self.L = L
                self.range_text.set(f'Range ({L})')

    def collect(self):
        return {
            'L': self.L,
            'selected_vote_system': self.vote_system.get()
        }


class ConfigEditor(Frame):
    def __init__(self, master):
        super().__init__(master)
        master.title("Config Editor")
        self.pack(fill=tk.BOTH, expand=True)
        self.parts = (CandidatesPanel(self), TalliersPanel(self), VotersPanel(self), VoteSystem(self))
        for p in self.parts:
            p.pack(fill=tk.X, pady=5)

        Button(self, text="Close", command=self.master.destroy).pack(side=tk.RIGHT, padx=5, pady=5)
        Button(self, text="OK", command=self.ok).pack(side=tk.RIGHT, padx=5, pady=5)

    def ok(self):
        import functools
        res = functools.reduce(dict.__or__, (p.collect() for p in self.parts))
        if len(res['CANDIDATES']) < 2:
            msgbox.showerror("Bad Configuration", "Need more candidates")
        elif not 0 < res['K'] <= len(res['CANDIDATES']):
            msgbox.showerror("Bad Configuration", "Bad value for K")
        elif len(res['TALLIERS']) < 3:
            msgbox.showerror("Bad Configuration", "Need more talliers")
        elif not (2 ** 13 - 1 <= res['p'] <= 2 ** 32):
            msgbox.showerror("Bad Configuration", "Bad value for p")
        else:
            config.D = res['K']
            import json
            with open('config.json', 'w') as f:
                json.dump(res, f)
            msgbox.showinfo("Configuration", "Configuration saved")
            if 'VOTERS' in res:
                vote_config = {
                    'C': res['CANDIDATES'],
                    'r': res['selected_vote_system'],
                    'p': res['p'],
                    'T': [f'ws://{ip}:{port + 1000}' for ip, port in res['TALLIERS']]
                }
                if res['selected_vote_system'] == config.VoteSystem.RANGE.value:
                    vote_config['L'] = res['L']
                with open('config_voters.csv', 'w') as f:
                    if res['websockets']:
                        f.write(f'UID,"URL link"\n')
                    from base64 import b64encode
                    for uid in res['VOTERS']:
                        f.write(f'"{uid}",')
                        if res['websockets']:
                            data = b64encode(json.dumps(vote_config | {'U': uid}, separators=(',', ':')).encode()).decode('ascii')
                            f.write(f'"voter.html?data={data}"\n')
                        else:
                            f.write('\n')
                    msgbox.showinfo("Configuration - Voters", "Voters information saved into 'config_voters.csv'")


class MainWindow(Frame):
    def __init__(self):
        super().__init__()
        self.master.title("Administrator")
        self.pack(fill=tk.BOTH, expand=True)
        Button(self, text="Config Edit", command=self.open_config).pack(fill=tk.X, padx=5, pady=5)
        Button(self, text="Local Launch", command=lambda: Thread(target=self.launch).start()).pack(fill=tk.X, padx=5, pady=5)
        Button(self, text="Vote CSV", command=lambda: Thread(target=self.vote_csv).start()).pack(fill=tk.X, padx=5, pady=5)
        Button(self, text="End Vote", command=lambda: Thread(target=self.end_vote).start()).pack(fill=tk.X, padx=5, pady=5)

    def open_config(self):
        from config import load
        global config
        config = load()
        ConfigEditor(tk.Toplevel(self.master))

    @staticmethod
    def launch():
        import config
        config = config.load()
        from time import sleep
        from tallier import main
        import subprocess
        import sys
        for num in range(2, config.D + 1):
            Thread(target=subprocess.run, args=([sys.executable, 'tallier.py', str(num)], )).start()
            sleep(2)
        msgbox.showinfo("Winners", '\n'.join((f'#{i + 1} : {name}' for i, name in enumerate(main(1)))))

    def vote_csv(self):
        import config
        config = config.load()
        from csv import reader
        from tkinter.filedialog import askopenfilename
        import asyncio
        from codecs import open as open_utf8
        from voter import main
        fname = askopenfilename(title='Select csv', parent=self, filetypes=(('CSV file', '*.csv'), ('All files', '*.*')))
        if not fname: return
        with open_utf8(fname, 'r', 'utf-8') as f:
            asyncio.set_event_loop(asyncio.new_event_loop())
            count, bad = 0, 0
            next(iter := reader(f))  # skip first row
            for row in map(tuple, iter):
                if len(row) != config.M + 1:
                    bad += 1
                elif 0 != main(int(row[0]), map(int, row[1:])):
                    bad += 1
                count += 1
            if bad == 0:
                msgbox.showinfo("CSV voting", f'{count} votes were casted')
            else:
                msgbox.showerror("CSV voting", f"{count - bad} votes were casted, and {bad} weren't accepted")

    @staticmethod
    def end_vote():
        from end_vote import main
        main()


def main():
    root = tk.Tk()
    MainWindow()
    root.mainloop()


if __name__ == '__main__':
    main()
