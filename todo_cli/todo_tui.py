import curses

class TodoTUI:
    def __init__(self):
        self.tasks = []
        self.next_id = 1
        self.selected = 0

    def run(self):
        curses.wrapper(self._main)

    def _main(self, stdscr):
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
                break
            elif key == ord('c'):
                self._toggle_complete()
            elif key == ord('a'):
                self._add_task(stdscr, below=True)
            elif key == ord('A'):
                self._add_task(stdscr, below=False)
            elif key == ord('e'):
                self._edit_task(stdscr)
            elif key == ord('w'):
                self._move_task(-1)
            elif key == ord('s'):
                self._move_task(1)

    def _draw(self, stdscr):
        stdscr.clear()
        stdscr.addstr(0, 0, "TODOs (q=quit)")
        if not self.tasks:
            stdscr.addstr(2, 0, "No tasks yet. Press 'a' to add one.")
        for idx, task in enumerate(self.tasks):
            status = '✓' if task['done'] else ' '
            line = f"[{status}] {task['desc']}"
            if idx == self.selected:
                stdscr.addstr(idx + 2, 0, line, curses.A_REVERSE)
            else:
                stdscr.addstr(idx + 2, 0, line)
        stdscr.refresh()

    def _move_selection(self, delta):
        if not self.tasks:
            return
        self.selected = max(0, min(self.selected + delta, len(self.tasks) - 1))

    def _toggle_complete(self):
        if not self.tasks:
            return
        task = self.tasks[self.selected]
        task['done'] = not task['done']

    def _prompt(self, stdscr, prompt):
        curses.echo()
        stdscr.addstr(len(self.tasks) + 3, 0, ' ' * (curses.COLS - 1))
        stdscr.addstr(len(self.tasks) + 3, 0, prompt)
        stdscr.refresh()
        inp = stdscr.getstr(len(self.tasks) + 3, len(prompt)).decode('utf-8')
        curses.noecho()
        return inp

    def _add_task(self, stdscr, below=True):
        desc = self._prompt(stdscr, 'New task: ')
        if not desc.strip():
            return
        task = {'id': self.next_id, 'desc': desc, 'done': False}
        if below or not self.tasks:
            insert_at = self.selected + 1 if self.tasks else 0
        else:
            insert_at = self.selected
        self.tasks.insert(insert_at, task)
        self.next_id += 1
        self.selected = insert_at

    def _edit_task(self, stdscr):
        if not self.tasks:
            return
        task = self.tasks[self.selected]
        desc = self._prompt(stdscr, 'Edit task: ')
        if desc.strip():
            task['desc'] = desc

    def _move_task(self, delta):
        if not self.tasks:
            return
        idx = self.selected
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(self.tasks):
            return
        self.tasks[idx], self.tasks[new_idx] = self.tasks[new_idx], self.tasks[idx]
        self.selected = new_idx

if __name__ == '__main__':
    TodoTUI().run()
