import asyncio
import traceback
from typing import Callable, Coroutine, Dict
from logger import get_logger

log = get_logger("TASKS")

class TaskManager:
    """Manages background tasks, providing supervision and graceful shutdown."""
    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()

    def register(self, name: str, coro_func: Callable[..., Coroutine], *args, **kwargs) -> None:
        """Registers and starts a supervised background task."""
        if name in self._tasks:
            log.warning(f"Task '{name}' is already running.")
            return

        async def supervised_task():
            log.info(f"Background task '{name}' started.")
            try:
                while not self._shutdown_event.is_set():
                    try:
                        await coro_func(*args, **kwargs)
                        break  # Exit loop if task completes normally
                    except asyncio.CancelledError:
                        log.info(f"Task '{name}' was cancelled.")
                        raise
                    except Exception as e:
                        log.error(f"Task '{name}' crashed: {e}")
                        traceback.print_exc()
                        log.info(f"Restarting task '{name}' in 30 seconds...")
                        await asyncio.sleep(30)  # Bounded backoff
            finally:
                log.info(f"Background task '{name}' stopped.")
                self._tasks.pop(name, None)

        task = asyncio.create_task(supervised_task(), name=name)
        self._tasks[name] = task

    async def shutdown(self) -> None:
        """Gracefully cancels and awaits all managed tasks."""
        log.info("Shutting down background tasks...")
        self._shutdown_event.set()
        for name, task in list(self._tasks.items()):
            task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        log.info("All background tasks stopped.")

task_manager = TaskManager()
