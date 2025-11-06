import ast
import asyncio
import json
import os
import sys
import tempfile

from pathlib import Path


async def async_dump(filepath: str, content):
    """An async wrapper for the safe ``json.dump(content, filepath, indent = 4, sort_keys = True)``."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    fd, tmppath = tempfile.mkstemp(
        prefix = path.name + ".",
        suffix = ".tmp",
        dir = path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding = "utf-8") as file:
            json.dump(content, file, indent = 4, sort_keys = True)
            file.flush()
            os.fsync(fd)  # use `file.fileno()` instead of `fd` in case `fd` is not available

        os.replace(tmppath, path)

        if os.name == "posix":
            dir_fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        Path(tmppath).unlink(missing_ok=True)


async def async_upload_from_string_json(blob, content):
    """An async wrapper for ``blob.upload_from_string(json.dumps(content, indent = 4, sort_keys = True), content_type="application/json; charset=utf-8")``."""
    data = json.dumps(content, indent = 4, sort_keys = True)
    blob.upload_from_string(data, content_type="application/json; charset=utf-8")


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


class FeatureState:
    """
    A set representing feature state that can be asynchronically changed.

    Attributes
    ----------
    set : set
        A set representing a preference.
    filepath : str
        A path of a file to store the feature state. When initializing, the contructor will try to import `self.set' from this file. Also used by `backup()`.
    blob : google.cloud.storage.blob.Blob
        A Google Cloud Storage bucket blob.

    Methods
    -------
    backup():
        Write the preference's value to the file specified by `self.filepath`.
    add(item):
        Add `item` to `self.set`.
    discard(item):
        Discard  `item` from `self.set`
    """
    
    def __init__(self, filepath: str, bucket = None):
        """If `bucket` is not ``None``, set `self.blob` to ``bucket.blob(filepath)``. Initialize `self.features`, set `self.filepath` from the corresponding arguments and create a task queue."""
        self.blob = bucket.blob(filepath) if bucket else None
        self.features = {
            "inst" : True,
            "yt_shorts": True,
            "ytm": True,
            "yt": True
        }
        self.__queue = asyncio.Queue()
        self.filepath = filepath
        self.__import_from_backup()
        self.__worker_task = None


    def __del__(self):
        """Cancel the running worker."""
        if self.__worker_task:
            self.__worker_task.cancel()

    def __ensure_worker(self):
        """Start a worker for the `self.__queue`."""
        if self.__worker_task is None:
            self.__worker_task = asyncio.create_task(worker(self.__queue))

    def __update_from_dict(self, data: dict) -> None:
        """Set `self.features` from `data`. Unrelated keys will be ignored. For non-boolean values, ``ValueError`` exceptions will be raised."""
        for key, value in data.items():
            if key in self.features:
                if isinstance(value, bool):
                    self.features[key] = value
                else:
                    raise ValueError(f"Unable to import {key} feature state from backup: The value is not bool")

    def __import_from_backup(self):
        """Try to import `self.features` from `self.filepath`. May not be async safe, so it's private (and is called only once, in `__init__()`)."""
        if not self.blob:
            if os.path.isfile(self.filepath):
                with open(self.filepath, "r", encoding = "utf-8") as file:
                    try:
                        raw = json.load(file)
                        if not isinstance(raw, dict):
                            raise ValueError("Unable to import the feature state from backup: File does not contain a JSON object")
                        self.__update_from_dict(raw)
                    except Exception:
                        print(traceback.format_exc(), file = sys.stderr)
        else:
            if self.blob.exists():
                try:
                    raw_text = self.blob.download_as_text(encoding = "utf-8")
                    raw = json.loads(raw_text)
                    if not isinstance(raw, dict):
                        raise ValueError("Unable to import the feature state from backup: File does not contain a JSON object")
                    self.__update_from_dict(raw)
                except Exception:
                    print(traceback.format_exc(), file = sys.stderr)

    async def backup(self) -> asyncio.Future:
        """Add a task to the queue to write `self.features` to `self.filepath`."""
        self.__ensure_worker()
        future = asyncio.get_running_loop().create_future()
        await self.__queue.put((
            async_dump(self.filepath, self.features) if not self.blob else async_upload_from_string_json(self.blob, self.features),
            future
        ))
        return future

    async def __set(self, key, value):
        """An async wrapper for `self.features[key] = value`."""
        self.features[key] = value

    async def set(self, feature: str, state: bool) -> asyncio.Future:
        """Add a task to the queue to set `self.features[feature]` to `state`."""
        self.__ensure_worker()
        future = asyncio.get_running_loop().create_future()
        await self.__queue.put((
            self.__set(feature, state),
            future
        ))
        return future
