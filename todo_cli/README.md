# Simple To-Do CLI

This is a small interactive command line application written in Python. It keeps
your tasks in memory for the duration of the session.

## Usage

Run the application using Python:

```bash
python todo.py
```

Alternatively, use the interactive TUI:

```bash
python todo_tui.py
```

Then use the following commands:

- `add <task description>` – add a new task.
- `list` or `view` – display current tasks.
- `done <task id>` – mark a task as done.
- `exit` – quit the program.

### TUI controls
- Navigate with arrow keys.
- `e` to edit the selected task.
- `c` to toggle completion.
- `a` to add below.
- `A` to add above.
- `w` to move up.
- `s` to move down.
- `r` to remove the selected task.

Completed tasks are shown greyed out with a strikethrough effect.

Tasks are stored only in memory, so they disappear when you exit the program.
