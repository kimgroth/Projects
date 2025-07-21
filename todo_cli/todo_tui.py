"""Text user interface version of the todo application."""

import curses
import json
from pathlib import Path
from pyfiglet import Figlet

class TodoTUI:
    """Curses based interface to display and edit todos."""

    def __init__(self):
        """Set up internal state and load tasks from disk."""
        self.todo_file = Path.home() / "Documents" / "todos.json"
        self.tasks = []
        self.next_id = 1
        self.selected = 0
        self.figlet = Figlet(font="slant")
        self.header_lines = self.figlet.renderText("TODOs").splitlines()
        self.help_lines = [
            "q: quit | a: add below | A: add above | e: edit | c: toggle complete",
            "w: move up | s: move down | r: remove | z: indent"
        ]
        self.load_tasks()

    def load_tasks(self):
        """Read tasks from :attr:`todo_file` and compute :attr:`next_id`."""

        if self.todo_file.exists():
            try:
                with self.todo_file.open('r') as f:
                    self.tasks = json.load(f)
            except Exception as e:
                print(f"Failed to load tasks: {e}")
                self.tasks = []
        for t in self.tasks:
            t.setdefault('indent', 0)
        if self.tasks:
            self.next_id = max(t['id'] for t in self.tasks) + 1
        else:
            self.next_id = 1

    def save_tasks(self):
        """Persist the current list of tasks to disk."""

        self.todo_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.todo_file.open('w') as f:
                json.dump(self.tasks, f, indent=2)
        except Exception as e:
            print(f"Failed to save tasks: {e}")

    def run(self):
        """Launch the TUI using :func:`curses.wrapper`."""

        curses.wrapper(self._main)

    def _main(self, stdscr):
        """Main curses event loop handling key input."""

        curses.curs_set(0)
        stdscr.nodelay(False)
        while True:
            self._draw(stdscr)
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord('k')):
                self._move_selection(-1)
            elif key in (curses.KEY_DOWN, ord('j')):
                self._move_selection(1)
            elif key == ord('q'):
                self.save_tasks()
                break
            elif key == ord('c'):
                self._toggle_complete()
                self.save_tasks()
            elif key == ord('a'):
                self._add_task(stdscr, below=True)
                self.save_tasks()
            elif key == ord('A'):
                self._add_task(stdscr, below=False)
                self.save_tasks()
            elif key == ord('e'):
                self._edit_task(stdscr)
                self.save_tasks()
            elif key == ord('w'):
                self._move_task(-1)
                self.save_tasks()
            elif key == ord('s'):
                self._move_task(1)
                self.save_tasks()
            elif key == ord('r'):
                self._delete_task()
                self.save_tasks()
            elif key == ord('z'):
                self._toggle_indent()
                self.save_tasks()

    def _draw(self, stdscr):
        """Render the current list of tasks to ``stdscr``."""

        stdscr.clear()
        y = 0
        for line in self.header_lines:
            stdscr.addstr(y, 0, line)
            y += 1
        for line in self.help_lines:
            stdscr.addstr(y, 0, line)
            y += 1
        if not self.tasks:
            stdscr.addstr(y, 0, "No tasks yet. Press 'a' to add one.")
        for idx, task in enumerate(self.tasks):
            status = '✓' if task['done'] else ' '
            desc = task['desc']
            indent = task.get('indent', 0)
            attr = 0
            if task['done']:
                desc = self._strike(desc)
                attr |= curses.A_DIM
            line = "  " * indent + f"[{status}] {desc}"
            if idx == self.selected:
                attr |= curses.A_REVERSE
            stdscr.addstr(idx + y, 0, line, attr)
        stdscr.refresh()

    def _move_selection(self, delta):
        """Move the selection cursor up or down by ``delta``."""

        if not self.tasks:
            return
        self.selected = max(0, min(self.selected + delta, len(self.tasks) - 1))

    def _toggle_complete(self):
        """Toggle completion state of the currently selected task."""

        if not self.tasks:
            return
        task = self.tasks[self.selected]
        task['done'] = not task['done']
        self.save_tasks()

    def _prompt(self, stdscr, prompt):
        """Display ``prompt`` and return user input."""

        curses.echo()
        stdscr.addstr(len(self.tasks) + 3, 0, ' ' * (curses.COLS - 1))
        stdscr.addstr(len(self.tasks) + 3, 0, prompt)
        stdscr.refresh()
        inp = stdscr.getstr(len(self.tasks) + 3, len(prompt)).decode('utf-8')
        curses.noecho()
        return inp

    def _add_task(self, stdscr, below=True):
        """Insert a new task either below or above the current one."""

        desc = self._prompt(stdscr, 'New task: ')
        if not desc.strip():
            return
        task = {'id': self.next_id, 'desc': desc, 'done': False, 'indent': 0}
        if below or not self.tasks:
            insert_at = self.selected + 1 if self.tasks else 0
        else:
            insert_at = self.selected
        self.tasks.insert(insert_at, task)
        self.next_id += 1
        self.selected = insert_at
        self.save_tasks()

    def _edit_task(self, stdscr):
        """Prompt the user to edit the currently selected task."""

        if not self.tasks:
            return
        task = self.tasks[self.selected]
        desc = self._prompt(stdscr, 'Edit task: ')
        if desc.strip():
            task['desc'] = desc
            self.save_tasks()

    def _move_task(self, delta):
        """Swap the selected task ``delta`` positions up or down."""

        if not self.tasks:
            return
        idx = self.selected
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(self.tasks):
            return
        self.tasks[idx], self.tasks[new_idx] = self.tasks[new_idx], self.tasks[idx]
        self.selected = new_idx
        self.save_tasks()

    def _delete_task(self):
        """Remove the currently selected task from the list."""

        if not self.tasks:
            return
        del self.tasks[self.selected]
        if self.selected >= len(self.tasks):
            self.selected = len(self.tasks) - 1
        if self.selected < 0:
            self.selected = 0
        self.save_tasks()

    def _toggle_indent(self):
        """Toggle a simple one-level indent on the current task."""

        if not self.tasks:
            return
        task = self.tasks[self.selected]
        task['indent'] = 0 if task.get('indent', 0) else 1
        self.save_tasks()

    def _strike(self, text):
        """Return *text* with strike-through Unicode combining characters."""

        return ''.join(ch + '\u0336' for ch in text)

if __name__ == '__main__':
    TodoTUI().run()
