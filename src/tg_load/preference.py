import ast
import asyncio
import os
import sys

from pathlib import Path


async def async_add(target_set: set, item):
    """An async wrapper for ``set.add()``."""
    target_set.add(item)


async def async_discard(target_set: set, item):
    """An async wrapper for ``set.discard()``."""
    target_set.discard(item)


async def async_write(filename: str, content: str):
    """An async wrapper for the safe ``file.write()``."""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(filename, 'w') as file:
        file.write(content)


async def async_upload_from_string_text(blob, text: str):
    """An async wrapper for ``blob.upload_from_string()`` with ``content_type="text/plain; charset=utf-8"``."""
    blob.upload_from_string(text, content_type="text/plain; charset=utf-8")


async def worker(task_queue: asyncio.Queue()):
    """Endlessly run tasks from `task_queue`."""
    while True:
        task_coro, done_future = await task_queue.get()
        try:
            await task_coro
        except Exception as e:
            done_future.set_exception(e)
        else:
            done_future.set_result(True)
        finally:
            task_queue.task_done()


class Preference:
    """
    A set representing a preference that can be asynchronically changed.

    Attributes
    ----------
    set : set
        A set representing a preference.
    filename : str
        The name of the file to store the preference's value. When initializing, the contructor will try to import `self.set' from this file. Also used by `backup()`.
        Must be a filename, not a filepath.
    blob : google.cloud.storage.blob.Blob
        A Google Cloud Storage bucket blob.

    Methods
    -------
    backup():
        Write the preference's value to the file specified by `self.filename`.
    add(item):
        Add `item` to `self.set`.
    discard(item):
        Discard  `item` from `self.set`
    """
    
    def __init__(self, filename: str, bucket = None):
        """If `bucket` is not ``None``, set `self.blob` to ``bucket.blob(filename)``. Create `self.set`, set `self.filename` from the corresponding arguments, create a task queue and start a worker for it."""
        self.blob = bucket.blob(filename) if bucket else None
        self.set = set()
        self.__queue = asyncio.Queue()
        self.filename = filename
        self.__import_from_backup()
        self.__worker_task = None

    def __iter__(self):
        """Inherit from `self.set` iterator."""
        return iter(self.set)

    def __del__(self):
        """Cancel the running worker."""
        if self.__worker_task:
            self.__worker_task.cancel()

    def __ensure_worker(self):
        if self.__worker_task is None:
            self.__worker_task = asyncio.create_task(worker(self.__queue))

    def __import_from_backup(self):
        """Try to import `self.set` from `self.filename`. May not be async safe, so it's private (and is called only once, in `__init__()`)."""
        if not self.blob:
            if os.path.isfile(self.filename):
                with open(self.filename, 'r') as file:
                    try:
                        file_str = file.read()
                        self.set = ast.literal_eval(file_str)
                    except Exception as e:
                        print(e, file = sys.stderr)
        else:
            if self.blob.exists():
                try:
                    file_str = self.blob.download_as_text(encoding="utf-8")
                    self.set = ast.literal_eval(file_str)
                except Exception as e:
                    print(e, file = sys.stderr)

    async def backup(self) -> asyncio.Future:
        """Add a task to the queue to write `self.set` to `self.filename`."""
        self.__ensure_worker()
        future = asyncio.get_running_loop().create_future()
        await self.__queue.put((
            async_write(self.filename, str(self.set)) if not self.blob else async_upload_from_string_text(self.blob, str(self.set)),
            future
        ))
        return future

    async def add(self, item) -> asyncio.Future:
        """Add a task to the queue to add `item` to `self.set`."""
        self.__ensure_worker()
        future = asyncio.get_running_loop().create_future()
        await self.__queue.put((
            async_add(self.set, item),
            future
        ))
        return future

    async def discard(self, item) -> asyncio.Future:
        """Add a task to the queue to discard `item` from `self.set`."""
        self.__ensure_worker()
        future = asyncio.get_running_loop().create_future()
        await self.__queue.put((
            async_discard(self.set, item),
            future
        ))
        return future
