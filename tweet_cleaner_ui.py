import subprocess
import tkinter as tk
from tkinter import messagebox

SCRIPT = r"C:\Users\lenno\delete_tweets.py"

def run_cleaner(mode, dry_run, max_actions):
    dry = "True" if dry_run else "False"

    with open(SCRIPT, "r", encoding="utf-8") as f:
        code = f.read()

    code = code.replace('MODE = "posts"', f'MODE = "{mode}"')
    code = code.replace('MODE = "reposts"', f'MODE = "{mode}"')
    code = code.replace('MODE = "likes"', f'MODE = "{mode}"')

    code = code.replace("DRY_RUN = True", f"DRY_RUN = {dry}")
    code = code.replace("DRY_RUN = False", f"DRY_RUN = {dry}")

    import re
    code = re.sub(r"MAX_ACTIONS = \d+", f"MAX_ACTIONS = {max_actions}", code)

    temp_script = r"C:\Users\lenno\delete_tweets_temp.py"

    with open(temp_script, "w", encoding="utf-8") as f:
        f.write(code)

    subprocess.Popen(["powershell", "-NoExit", "-Command", f"py {temp_script}"])

def start():
    mode = mode_var.get()
    dry_run = dry_var.get()
    max_actions = actions_entry.get().strip()

    if not max_actions.isdigit():
        messagebox.showerror("Error", "Max actions must be a number")
        return

    if not dry_run:
        confirm = messagebox.askyesno(
            "Confirm Live Mode",
            "DRY RUN is OFF.\n\nThis will actually change your X account.\n\nContinue?"
        )
        if not confirm:
            return

    run_cleaner(mode, dry_run, int(max_actions))

root = tk.Tk()
root.title("Tweet Nuke 6000")
root.geometry("360x300")
root.configure(bg="#07090f")

tk.Label(root, text="Tweet Nuke 6000", fg="#ff008c", bg="#07090f",
         font=("Segoe UI", 18, "bold")).pack(pady=15)

mode_var = tk.StringVar(value="posts")
dry_var = tk.BooleanVar(value=True)

tk.Label(root, text="Mode", fg="white", bg="#07090f").pack()

tk.OptionMenu(root, mode_var, "posts", "reposts", "likes").pack(pady=5)

tk.Checkbutton(root, text="Dry Run", variable=dry_var,
               fg="white", bg="#07090f", selectcolor="#121722").pack(pady=10)

tk.Label(root, text="Max Actions", fg="white", bg="#07090f").pack()

actions_entry = tk.Entry(root)
actions_entry.insert(0, "10")
actions_entry.pack(pady=5)

tk.Button(root, text="Start Cleaner", command=start,
          bg="#ff008c", fg="white", font=("Segoe UI", 11, "bold")).pack(pady=20)

tk.Label(root, text="Log: C:\\Users\\lenno\\deleted_log.txt",
         fg="#7f8899", bg="#07090f", font=("Segoe UI", 8)).pack(pady=5)

root.mainloop()