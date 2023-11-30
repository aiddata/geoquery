from datetime import datetime, timedelta

from utils.db.extract_task_watch import free_dangling_tasks

number_of_cleared_tasks = free_dangling_tasks(timedelta(minutes=1))

print(f"Cleared {number_of_cleared_tasks} dangling tasks.")
