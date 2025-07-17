import json
from pathlib import Path


class TodoCLI:
    def __init__(self):
        self.todo_file = Path.home() / "Documents" / "todos.json"
        self.tasks = []
        self.next_id = 1
        self.load_tasks()

    def load_tasks(self):
        if self.todo_file.exists():
            try:
                with self.todo_file.open('r') as f:
                    self.tasks = json.load(f)
            except Exception as e:
                print(f"Failed to load tasks: {e}")
                self.tasks = []
        if self.tasks:
            self.next_id = max(t['id'] for t in self.tasks) + 1
        else:
            self.next_id = 1

    def save_tasks(self):
        self.todo_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.todo_file.open('w') as f:
                json.dump(self.tasks, f, indent=2)
        except Exception as e:
            print(f"Failed to save tasks: {e}")

    def run(self):
        print("Simple To-Do CLI. Type 'help' for commands.")
        while True:
            try:
                command = input('> ').strip()
            except (EOFError, KeyboardInterrupt):
                print()  # new line
                self.save_tasks()
                break

            if not command:
                continue

            parts = command.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else None

            if cmd == 'help':
                self.print_help()
            elif cmd == 'add':
                self.add_task(arg)
            elif cmd in ('list', 'view'):
                self.list_tasks()
            elif cmd == 'done':
                self.mark_done(arg)
            elif cmd in ('exit', 'quit', 'q'):
                self.save_tasks()
                break
            else:
                print("Unknown command. Type 'help' for a list of commands.")
        print('Goodbye!')

    def print_help(self):
        print('Commands:')
        print('  add <task description>  - add a new task')
        print('  list                    - list tasks')
        print('  done <task id>          - mark task done')
        print('  exit                    - exit the program')

    def add_task(self, desc):
        if not desc:
            print('Usage: add <task description>')
            return
        self.tasks.append({
            'id': self.next_id,
            'desc': desc,
            'done': False
        })
        print(f'Added task {self.next_id}.')
        self.next_id += 1
        self.save_tasks()

    def list_tasks(self):
        if not self.tasks:
            print('No tasks yet.')
            return
        for task in self.tasks:
            status = '✓' if task['done'] else ' '
            print(f"[{status}] {task['id']}: {task['desc']}")

    def mark_done(self, task_id):
        if not task_id or not task_id.isdigit():
            print('Usage: done <task id>')
            return
        tid = int(task_id)
        for task in self.tasks:
            if task['id'] == tid:
                task['done'] = True
                print(f'Task {tid} marked done.')
                self.save_tasks()
                return
        print(f'No task with id {tid}.')


if __name__ == '__main__':
    TodoCLI().run()
