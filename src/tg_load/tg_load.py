import sys
import logging
import tomllib
import ast
import asyncio
import multiprocessing
import os
import pathlib
import shutil
import traceback
import io
from environs import env
from contextlib import contextmanager
from typing import Optional, Callable
from types import MethodType
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from functools import partial

from telegram import Update, Message, InputMediaPhoto, InputMediaVideo, InputMediaAudio, InputMediaDocument, Bot
from telegram.ext import Defaults, ApplicationBuilder, CallbackContext, ContextTypes, CommandHandler, MessageHandler, filters

import instaloader
from instaloader.__main__ import import_session
from instaloader import Profile, StoryItem
from instaloader.exceptions import InstaloaderException

import ytm
from ytm.apis.YouTubeMusicDL.YouTubeMusicDL import YouTubeMusicDL
import yt_dlp

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC


class Timeout(Exception):
    """
    An exception to be raised when an action is forcely timed out.

    Inherits from `Exception` and presents no overrides or unique methods.
    """
    
    pass


async def repeat_until_task_done(interval: float, task: asyncio.Task, action: Callable, *action_args, **action_kwargs):
    """Repeat `action` every `interval` seconds until `task` is done."""
    while not task.done():
        await action(*action_args, **action_kwargs)
        await asyncio.sleep(interval)


async def repeat_while_process_alive(interval: float, process: multiprocessing.Process, action: Callable, *action_args, **action_kwargs):
    """Repeat `action` every `interval` seconds while `process` is alive."""
    while process.is_alive():
        await action(*action_args, **action_kwargs)
        await asyncio.sleep(interval)


@contextmanager
def error_catcher(self, extra_info: Optional[str] = None):
    """
    Redefine ``InstaloaderContext.error_catcher()`` so that is also calls ``send_to_logging_chats()``.

    Notes
    -----
    ``application.bot`` must be set before calling this
    """
    # to keep the format of the logs, we have to copy-paste
    # WARNING: check this method when updating instaloader
    try:
        yield
    except InstaloaderException as err:
        if extra_info:
            error = '{}: {}'.format(extra_info, err)
        else:
            error = '{}'.format(err)
        self.error(error)
        asyncio.create_task(
            send_to_logging_chats(error, application.bot)
        )
        if self.raise_all_errors:
            raise


async def async_add(target_set: set, item):
    """An async wrapper for ``set.add()``."""
    target_set.add(item)


async def async_discard(target_set: set, item):
    """An async wrapper for ``set.discard()``."""
    target_set.discard(item)


async def async_write(filename: str, content: str):
    """An async wrapper for the safe ``file.write()``."""
    with open(filename, 'w') as file:
        file.write(content)


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
    set: set
        A set representing a preference.
    filename: str
        The name of the file to store the preference's value. When initializing, the contructor will try to import `self.set' from this file. Also used by `backup()`.
        Must be a filename, not a filepath.
    loop: asyncio.AbstractEventLoop
        An asyncio loop to run the workers.

    Methods
    -------
    backup():
        Write the preference's value to the file specified by `self.filename`.
    add(item):
        Add `item` to `self.set`.
    discard(item):
        Discard  `item` from `self.set`
    """
    
    def __init__(self, filename: str, loop: asyncio.AbstractEventLoop):
        """Create `self.set`, set `self.filename` and `self.loop` from the corresponding arguments, create a task queue and start a worker for it."""
        self.set = set()
        self.__queue = asyncio.Queue()
        self.filename = filename
        self.__import_from_backup()
        self.loop = loop
        self.__worker_task = loop.create_task(worker(self.__queue))

    def __iter__(self):
        """Inherit from `self.set` iterator."""
        return iter(self.set)

    async def __del__(self):
        """Cancel the running worker and wait for it to stop."""
        self.__worker_task.cancel()
        await self.__worker_task

    def __import_from_backup(self):
        """Try to import `self.set` from `self.filename`. May not be async safe, so it's private (and is called only once, in `__init__()`)."""
        if os.path.isfile(self.filename):
            with open(self.filename, 'r') as file:
                try:
                    file_str = file.read()
                    self.set = ast.literal_eval(file_str)
                except Exception as e:
                    print(e, file = sys.stderr)

    async def backup(self) -> asyncio.Future:
        """Add a task to the queue to write `self.set` to `self.filename`."""
        future = self.loop.create_future()
        await self.__queue.put((
            async_write(self.filename, str(self.set)),
            future
        ))
        return future

    async def add(self, item) -> asyncio.Future:
        """Add a task to the queue to add `item` to `self.set`."""
        future = self.loop.create_future()
        await self.__queue.put((
            async_add(self.set, item),
            future
        ))
        return future

    async def discard(self, item) -> asyncio.Future:
        """Add a task to the queue to discard `item` from `self.set`."""
        future = self.loop.create_future()
        await self.__queue.put((
            async_discard(self.set, item),
            future
        ))
        return future


def sanitize_html_style(msg: str) -> str:
    """
    Replace forbidden in Telegram HTML style symbols with the corresponding HTML entities. See https://core.telegram.org/bots/api#html-style

    Parameters
    ----------
    msg : str
        A string without tags and HTML entities.

    Returns
    -------
    str
        Modified `msg`, so that it can be send in an HTML-styled Telegram message.
    """
    res = msg
    res = res.replace('&', '&amp;')
    res = res.replace('<', '&lt;')
    res = res.replace('>', '&gt;')
    return res


async def send_to_logging_chats(msg: str, bot: Bot):
    """Send `msg` to the logging chats."""
    for chat_id in config["logging_chat_ids"]:
        try:
            await bot.send_message(
                chat_id,
                msg,
                parse_mode = 'HTML',
            )
        except Exception as e:
            if "empty" in str(e):
                return
            else:
                print(traceback.format_exc())


async def application_exception_handler(update: Optional[object], context: CallbackContext):
    """
    A custom exception handler for ``telegram.ext.Application``. Print the exception and send it to the logging chats.

    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.application.html#telegram.ext.Application.add_error_handler
    """
    print(
        f"An exception occurred:\n{traceback.format_exc()}",
        file = sys.stderr
    )
    error = f"An exception occurred:\n<pre><code class=\"language-log\">{sanitize_html_style(traceback.format_exc())}</code></pre>"
    await send_to_logging_chats(error, context.bot)


async def format_message(message: str, context: ContextTypes.DEFAULT_TYPE, *args) -> str:
    """Format `message` with the allowed replacement fields (see config.toml)."""
    res = message
    if "{bot_name}" in res:
        # WARNING: this generates a request to Telegram Bot API every time the bot's name is used
        # however, the bot is much more limited by instagram account restrictions, so it will never reach the Telegram's limit
        bot_name = (await context.bot.get_my_name()).name
        res = res.replace("{bot_name}", bot_name)
    if "{bot_username}" in res:
        bot_username = context.application.bot.name
        res = res.replace("{bot_username}", bot_username)
    for arg in args:
        res = res.format(arg)
    return res


def is_admin(user_id: int) -> bool:
    """Check whether the user with `user_id` is the bot administrator."""
    return user_id in config["admin_ids"]


async def ensure_admin(message: Message, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check whether the author of `message` is the bot administrator and reply with a corresponding error message if not."""
    config_context = config["messages"]
    
    res = is_admin(message.from_user.id)
    if not res:
        await message.reply_html(
            await format_message(config_context["not_admin"], context)
        )
    return res


async def ensure_active_chat(message: Message, context: ContextTypes.DEFAULT_TYPE, public_reply = True) -> bool:
    """Check whether the bot is enabled in the chat where `message` was sent and reply with a corresponding error message if not."""
    config_context = config["messages"]
    
    res = message.chat.id in active_chat_ids
    if not res:
        if message.chat.type == 'private':
            await message.reply_html(
                await format_message(config_context["private_not_enabled"], context)
            )
        elif public_reply:
            await message.reply_html(
                await format_message(config_context["not_enabled"], context)
            )
    return res


async def ensure_not_banned_author(message: Message, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check whether the author of `message` is banned and reply with a corresponding error message if they are."""
    config_context = config["messages"]
    
    res = message.from_user.id not in banned_user_ids
    if not res:
        await message.reply_html(
            await format_message(config_context["banned"], context)
        )
    return res


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for ``/start`` command.

    Reply with the corresponding message.
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    config_context = config["messages"]
    
    # update.effective_message is not None since it's a command handler
    message = update.effective_message
    await message.reply_html(
        await format_message(config_context["start"], context)
    )


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for ``/help`` command.

    Reply with the corresponding message.
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    config_context = config["messages"]
    
    # update.effective_message is not None since it's a command handler
    message = update.effective_message
    await message.reply_html(
        await format_message(config_context["help"], context)
    )


async def enable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for ``/enable`` command. Enable the bot in the chat where the command has been used.

    If the bot is already enabled in the chat, reply with the "no_need" message.
    Otherwise, ensure the command is used by an admin, enable the bot in the chat (add the chat to `active_chat_ids`) and reply with the "success" message.
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    config_context = config["messages"]["enable"]
    
    # update.effective_message is not None since it's a command handler
    message = update.effective_message
    if update.effective_chat.id in active_chat_ids:
        await message.reply_html(
            await format_message(config_context["no_need"], context)
        )
    elif await ensure_admin(message, context):
        future = await active_chat_ids.add(update.effective_chat.id)
        await future
        future = await active_chat_ids.backup()
        await future
        await message.reply_html(
            await format_message(config_context["success"], context)
        )


async def disable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for ``/disable`` command. Disable the bot in the chat where the command has been used.

    If the bot is already disabled in the chat, reply with the "no_need" message.
    Otherwise, ensure the command is used by an admin, disable the bot in the chat (discard the chat from `active_chat_ids`) and reply with the "success" message.
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    config_context = config["messages"]["disable"]
    
    # update.effective_message is not None since it's a command handler
    message = update.effective_message
    if update.effective_chat.id not in active_chat_ids:
        await message.reply_html(
            await format_message(config_context["no_need"], context)
        )
    elif await ensure_admin(message, context):
        future = await active_chat_ids.discard(update.effective_chat.id)
        await future
        future = await active_chat_ids.backup()
        await future
        await message.reply_html(
            await format_message(config_context["success"], context)
        )


async def disable_captions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for ``/disable_captions`` command. Disable captions for Instagram posts in the chat where the command has been used.

    Ensure the bot is enabled in the chat the command us used by a non-banned user.
    If captions are already disabled in the chat, reply with the "no_need" message.
    Otherwise, disable captions in the chat (add the chat to `no_captions_chat_ids`) and reply with the "success" message.
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    config_context = config["messages"]["disable_captions"]
    
    # update.effective_message is not None since it's a command handler
    message = update.effective_message
    if await ensure_active_chat(message, context) and await ensure_not_banned_author(message, context):
        if update.effective_chat.id in no_captions_chat_ids:
            await message.reply_html(
                await format_message(config_context["no_need"], context)
            )
        else:
            future = await no_captions_chat_ids.add(update.effective_chat.id)
            await future
            future = await no_captions_chat_ids.backup()
            await future
            await message.reply_html(
                await format_message(config_context["success"], context)
            )


async def enable_captions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for ``/enable_captions`` command. Enable captions for Instagram posts in the chat where the command has been used.

    Ensure the bot is enabled in the chat the command us used by a non-banned user.
    If captions are already enabled in the chat, reply with the "no_need" message.
    Otherwise, enable captions in the chat (discard the chat from `no_captions_chat_ids`) and reply with the "success" message.
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    config_context = config["messages"]["enable_captions"]
    
    # update.effective_message is not None since it's a command handler
    message = update.effective_message
    if await ensure_active_chat(message, context) and await ensure_not_banned_author(message, context):
        if update.effective_chat.id not in no_captions_chat_ids:
            await message.reply_html(
                await format_message(config_context["no_need"], context)
            )
        else:
            future = await no_captions_chat_ids.discard(update.effective_chat.id)
            await future
            future = await no_captions_chat_ids.backup()
            await future
            await message.reply_html(
                await format_message(config_context["success"], context)
            )


async def reply_media(target: str, message: Message, compress: bool = True):
    """
    Reply to `message` with images and videos (and a caption if desired) from `target`, then remove `target`.

    Reply with an error message in case of any errors.

    Parameters
    ----------
    target : str
        A path to a folder with the files to reply with.
    message : telegram.Message
        A Telegram message to reply to.
    compress : bool, optional
        Whether to compress the images and videos from `target` when sending. Default is ``True``.
    """
    filenames = sorted(os.listdir(target))
            
    media = []
    errors = ""
    errors_formatted = ""
    errors_formatted_traceback = ""
    for filename in filenames:
        suffix = pathlib.PurePath(filename).suffix
        try:
            with open(os.path.join(target, filename), 'rb') as file:
                # see https://core.telegram.org/type/storage.FileType
                if suffix in [".jpg", ".png", ".webp"]:
                    media.append(
                        InputMediaPhoto(file) if compress else InputMediaDocument(file)
                    )      
                elif suffix in [".mp4", ".mv4", ".f4v", ".lrv", ".mov"]:
                    media.append(
                        InputMediaVideo(file) if compress else InputMediaDocument(file)
                    )
                elif suffix != ".txt":
                    print(
                        f"Ignored {filename} in reply_media when handling message:\n{message.text}",
                        file = sys.stderr
                    )
                    await send_to_logging_chats(
                        f"Ignored {sanitize_html_style(filename)} in reply_media when handling message:\n{sanitize_html_style(message.text)}",
                        message.get_bot()
                    )
        except Exception as e:
            errors += f"{traceback.format_exc()}\n"
            errors_formatted += f"<pre><code class=\"language-log\">{sanitize_html_style(str(e))}</code></pre>\n"
            errors_formatted_traceback += f"<pre><code class=\"language-log\">{sanitize_html_style(traceback.format_exc())}</code></pre>\n"
    if errors:
        print(
            f"When constructing InputMedia objects, the following errors occured:\n{errors}\nThe handled message:\n{message.text}",
            file = sys.stderr
        )
        await message.reply_html(
            f"When constructing InputMedia objects, the following errors occured:\n{errors_formatted}"
        )
        await send_to_logging_chats(
            f"When constructing InputMedia objects, the following errors occured:\n{errors_formatted_traceback}\nThe handled message:\n{sanitize_html_style(message.text)}",
            message.get_bot()
        )

    # a media group includes a maximum of 10 elements
    if "file.txt" in filenames:
        with open(os.path.join(target, "file.txt"), 'r', encoding='UTF-8') as caption_file:
            caption = caption_file.read()
            # message captions must be 0-1024 characters after entities parsing
            caption = caption if len(caption) < 1024 else caption[:1023] + "…"
            await message.reply_media_group(
                media[:10],
                disable_notification = True,
                caption = caption
            )
            media = media[10:]
    while media:
        await message.reply_media_group(
            media[:10],
            disable_notification = True
        )
        media = media[10:]

    # remove target with all the files
    shutil.rmtree(target)


async def reply_audios(target: str, message: Message):
    """
    Reply to `message` with audios from `target`, then remove `target`.

    Reply with an error message in case of any errors.

    Parameters
    ----------
    target : str
        A path to a folder with the audios to reply with.
    message : telegram.Message
        A Telegram message to reply to.
    """
    filenames = sorted(
        os.listdir(target),
        key = lambda filename: os.path.getctime(os.path.join(target, filename))
    )
            
    audios = []
    errors = ""
    errors_formatted = ""
    errors_formatted_traceback = ""
    for filename in filenames:
        filepath = os.path.join(target, filename)
        suffix = pathlib.PurePath(filename).suffix
        # see https://core.telegram.org/type/storage.FileType
        if suffix in [".mp3"]:
            # Telegram requires the cover to be passed as a separate file, so we need to extract it
            thumb_file = None
            try:
                audio = MP3(filepath, ID3=ID3)
                # the tag is set here: https://github.com/tombulled/python-youtube-music/blob/0817d2688db3615a884453c6482008dac9977bf3/ytm/apis/YouTubeMusicDL/YouTubeMusicDL.py# L167
                apic_tag = audio.tags.get("APIC:Cover")
                if apic_tag:
                    thumb_file = io.BytesIO(apic_tag.data)
                    thumb_file.name = "cover.jpg"
            except Exception as e:
                print(
                    f"An error occured while preparing the cover for {filename}:\n{traceback.format_exc()}",
                    file = sys.stderr
                )
                await message.reply_html(
                    f"An error occured while preparing the cover for <code>{sanitize_html_style(filename)}</code>:\n<pre><code class=\"language-log\">{sanitize_html_style(str(e))}</code></pre>"
                )
                await send_to_logging_chats(
                    f"An error occured while preparing the cover for <code>{sanitize_html_style(filename)}:\n<pre><code class=\"language-log\">{sanitize_html_style(traceback.format_exc())}</code></pre>",
                    message.get_bot()
                )
            try:
                with open(filepath, 'rb') as file:
                    audios.append(
                        InputMediaAudio(
                            file,
                            thumbnail = thumb_file
                        )
                    )      
            except Exception as e:
                errors += f"{traceback.format_exc()}\n"
                errors_formatted += f"<pre><code class=\"language-log\">{sanitize_html_style(str(e))}</code></pre>\n"
                errors_formatted_traceback += f"<pre><code class=\"language-log\">{sanitize_html_style(traceback.format_exc())}</code></pre>\n"
        elif suffix != ".txt":
            print(
                f"Ignored {filename} in reply_audio when handling message:\n{message.text}",
                file = sys.stderr
            )
            await send_to_logging_chats(
                f"Ignored {sanitize_html_style(filename)} in reply_audio when handling message:\n{sanitize_html_style(message.text)}",
                message.get_bot()
            )
    if errors:
        print(
            f"When constructing InputMediaAudio objects, the following errors occured:\n{errors}\nThe handled message:\n{message.text}",
            file = sys.stderr
        )
        await message.reply_html(
            f"When constructing InputMediaAudio objects, the following errors occured:\n{errors_formatted}"
        )
        await send_to_logging_chats(
            f"When constructing InputMediaAudio objects, the following errors occured:\n{errors_formatted_traceback}\nThe handled message:\n{sanitize_html_style(message.text)}",
            message.get_bot()
        )

    # a media group includes a maximum of 10 elements
    while audios:
        try:
            await message.reply_media_group(
                audios[:10],
                disable_notification = True
            )
        except Exception:
            print(
                f"An error occured when sendind an audio group:\n{traceback.format_exc()}",
                file = sys.stderr
            )
        audios = audios[10:]

    # remove target with all the files
    shutil.rmtree(target)


async def download_post_and_reply(shortcode: str, message: Message, compress: bool = True):
    """
    Download an Instagram post (or reel) and reply with it.

    Use ``instaloader`` to download the post defined by `shortcode`, then call ``reply_media()``.
    Set the corresponding chat actions. Reply with an error message in case of any errors. Remove the downloaded files before finishing working.

    Parameters
    ----------
    shortcode : str
        A shortcode of a post to download (e.g. ``DH4NzQ_TAlx``).
    message : telegram.Message
        A Telegram message to reply to.
    compress : bool, optional
        Whether to compress the downloaded images and videos when sending. Passed to ``reply_media()``. Default is ``True``.
    """
    await message.reply_chat_action('typing')
    
    L = L_captions if message.chat.id not in no_captions_chat_ids else L_no_captions
    try:
        loop = asyncio.get_running_loop()
        post_from_shortcode_task = loop.run_in_executor(
            None,
            # instaloader.Post.from_shortcode(L.context, shortcode)
            instaloader.Post.from_shortcode,
            L.context,
            shortcode
        )
        post_from_shortcode_task = asyncio.ensure_future(post_from_shortcode_task)

        reply_chat_action_task = asyncio.create_task(
            repeat_until_task_done(
                5,  # see https://core.telegram.org/bots/api#sendchataction
                post_from_shortcode_task,
                # message.reply_chat_action('typing')
                message.reply_chat_action,
                'typing'
            )
        )
        
        post = await post_from_shortcode_task
        await reply_chat_action_task
    except Exception as e:
        print(
            f"An error occured when retrieving the post:\n{traceback.format_exc()}\nThe determined shortcode: {shortcode}",
            file = sys.stderr
        )
        await message.reply_html(
            f"An error occured when retrieving the post:\n<pre><code class=\"language-log\">{sanitize_html_style(str(e))}</code></pre>\nThe determined shortcode: <code>{sanitize_html_style(shortcode)}</code>"
        )
        await send_to_logging_chats(
            f"An error occured when retrieving the post:\n<pre><code class=\"language-log\">{sanitize_html_style(traceback.format_exc())}</code></pre>\nThe determined shortcode: <code>{sanitize_html_style(shortcode)}</code>",
            message.get_bot()
        )
    else:
        target = str(message.chat.id) + "-" + str(message.id) + "-post-" + shortcode
        try:
            loop = asyncio.get_running_loop()
            download_post_task = loop.run_in_executor(
                None,
                # L.download_post(post, target)
                L.download_post,
                post,
                target
            )
            download_post_task = asyncio.ensure_future(download_post_task)

            reply_chat_action_task = asyncio.create_task(
                repeat_until_task_done(
                    5,  # see https://core.telegram.org/bots/api#sendchataction
                    download_post_task,
                    # message.reply_chat_action('typing')
                    message.reply_chat_action,
                    'typing'
                )
            )
            
            await download_post_task
            await reply_chat_action_task
        except Exception as e:
            print(
                f"An error occured when downloading the post {shortcode}:\n{traceback.format_exc()}",
                file = sys.stderr
            )
            await message.reply_html(
                f"An error occured when downloading the post <code>{sanitize_html_style(shortcode)}</code>:\n<pre><code class=\"language-log\">{sanitize_html_style(str(e))}</code></pre>"
            )
            await send_to_logging_chats(
                f"An error occured when downloading the post <code>{sanitize_html_style(shortcode)}</code>:\n<pre><code class=\"language-log\">{sanitize_html_style(traceback.format_exc())}</code></pre>",
                message.get_bot()
            )
        else:
            await message.reply_chat_action('upload_document')
            
            reply_media_task = asyncio.create_task(
                reply_media(target, message, compress)
            )

            reply_chat_action_task = asyncio.create_task(
                repeat_until_task_done(
                    5,  # see https://core.telegram.org/bots/api#sendchataction
                    reply_media_task,
                    # message.reply_chat_action('upload_document')
                    message.reply_chat_action,
                    'upload_document'
                )
            )
            
            await reply_media_task
            await reply_chat_action_task
        finally:
            await reply_chat_action_task
            # remove target with all the files, if any were created
            shutil.rmtree(target, ignore_errors = True)


async def download_storyitem_and_reply(story_item: StoryItem, message: Message, compress: bool = True):
    """
    Download a story and reply with it.

    Use ``instaloader`` to download `story_item`, then call ``reply_media()``.
    Set the corresponding chat actions. Reply with an error message in case of any errors. Remove the downloaded files before finishing working.

    Parameters
    ----------
    story_item : StoryItem
        A story to download. For reference, see https://instaloader.github.io/module/structures.html#instaloader.StoryItem
    message : telegram.Message
        A Telegram message to reply to.
    compress : bool, optional
        Whether to compress the downloaded image or video when sending. Passed to ``reply_media()``. Default is ``True``.
    """
    await message.reply_chat_action('typing')
    
    L = L_captions if message.chat.id not in no_captions_chat_ids else L_no_captions
    target = str(message.chat.id) + "-" + str(message.id) + "-story-" + str(story_item.mediaid)
    try:
        loop = asyncio.get_running_loop()
        download_storyitem_task = loop.run_in_executor(
            None,
            # L.download_storyitem(story_item, target)
            L.download_storyitem,
            story_item,
            target
        )
        download_storyitem_task = asyncio.ensure_future(download_storyitem_task)

        reply_chat_action_task = asyncio.create_task(
            repeat_until_task_done(
                5,  # see https://core.telegram.org/bots/api#sendchataction
                download_storyitem_task,
                # message.reply_chat_action('typing')
                message.reply_chat_action,
                'typing'
            )
        )
        
        await download_storyitem_task
        await reply_chat_action_task
    except Exception as e:
        print(
            f"An error occured when downloading the story {story_item.mediaid}:\n{traceback.format_exc()}",
            file = sys.stderr
        )
        await message.reply_html(
            f"An error occured when downloading the story <code>{sanitize_html_style(story_item.mediaid)}</code>:\n<pre><code class=\"language-log\">{sanitize_html_style(str(e))}</code></pre>"
        )
        await send_to_logging_chats(
            f"An error occured when downloading the story <code>{sanitize_html_style(story_item.mediaid)}</code>:\n<pre><code class=\"language-log\">{sanitize_html_style(traceback.format_exc())}</code></pre>",
            message.get_bot()
        )
    else:
        await message.reply_chat_action('upload_document')
            
        reply_media_task = asyncio.create_task(
            reply_media(target, message, compress)
        )

        reply_chat_action_task = asyncio.create_task(
            repeat_until_task_done(
                5,  # see https://core.telegram.org/bots/api#sendchataction
                reply_media_task,
                # message.reply_chat_action('upload_document')
                message.reply_chat_action,
                'upload_document'
            )
        )
            
        await reply_media_task
        await reply_chat_action_task
    finally:
        await reply_chat_action_task
        # remove target with all the files, if any were created
        shutil.rmtree(target, ignore_errors = True)


async def download_stories_and_reply(profile: Profile, message: Message, compress: bool = True):
    """
    Download all the stories from `profile` and reply with them.

    Use ``instaloader`` to download stories from `profile`, then call ``reply_media()``.
    Set the corresponding chat actions. Reply with an error message in case of any errors. Remove the downloaded files before finishing working.

    Parameters
    ----------
    profile : Profile
        A profile to get stories from. For reference, see https://instaloader.github.io/module/structures.html#instaloader.Profile
    message : telegram.Message
        A Telegram message to reply to.
    compress : bool, optional
        Whether to compress the downloaded images and videos when sending. Passed to ``reply_media()``. Default is ``True``.
    """
    await message.reply_chat_action('typing')
    
    L = L_captions if message.chat.id not in no_captions_chat_ids else L_no_captions
    target = str(message.chat.id) + "-" + str(message.id) + "-stories-" + str(profile.userid)
    try:
        loop = asyncio.get_running_loop()
        download_stories_with_arguments = partial(
            # L.download_stories([profile], filename_target = target)
            L.download_stories,
            [profile],
            filename_target = target
        )
        download_stories_task = loop.run_in_executor(
            None,
            # keyword arguments are not supported
            download_stories_with_arguments
        )
        download_stories_task = asyncio.ensure_future(download_stories_task)

        reply_chat_action_task = asyncio.create_task(
            repeat_until_task_done(
                5,  # see https://core.telegram.org/bots/api#sendchataction
                download_stories_task,
                # message.reply_chat_action('typing')
                message.reply_chat_action,
                'typing'
            )
        )
        
        await download_stories_task
        await reply_chat_action_task
    except Exception as e:
        print(
            f"An error occured when downloading stories for the profile {profile.username}:\n{traceback.format_exc()}",
            file = sys.stderr
        )
        await message.reply_html(
            f"An error occured when downloading stories for the profile <code>{sanitize_html_style(profile.username)}</code>:\n<pre><code class=\"language-log\">{sanitize_html_style(str(e))}</code></pre>"
        )
        await send_to_logging_chats(
            f"An error occured when downloading stories for the profile <code>{sanitize_html_style(profile.username)}</code>:\n<pre><code class=\"language-log\">{sanitize_html_style(traceback.format_exc())}</code></pre>",
            message.get_bot()
        )
    else:
        await message.reply_chat_action('upload_document')
            
        reply_media_task = asyncio.create_task(
            reply_media(target, message, compress)
        )

        reply_chat_action_task = asyncio.create_task(
            repeat_until_task_done(
                5,  # see https://core.telegram.org/bots/api#sendchataction
                reply_media_task,
                # message.reply_chat_action('upload_document')
                message.reply_chat_action,
                'upload_document'
            )
        )
            
        await reply_media_task
        await reply_chat_action_task
    finally:
        await reply_chat_action_task
        # remove target with all the files, if any were created
        shutil.rmtree(target, ignore_errors = True)


def create_ytlm_and_download_song(song_id, directory):
    """
    Call ``YouTubeMusicDL.download_song`` with certain parameters.

    The parameters passed to ``yt_dlp.YoutubeDL``:
    ``ffmpeg_location = env("FFMPEG_LOCATION")``
    ``no_warnings = True``
    ``noprogress = True``

    Parameters
    ----------
    song_id : str
        An id of the song to download, e.g. ``dQw4w9WgXcQ``.
    directory
        Either a string representing a path segment, or an object implementing the ``os.PathLike`` interface where the ``__fspath__()`` method returns a string, such as another path object.
        Used as an argument of https://docs.python.org/3/library/pathlib.html#pathlib.Path
    """
    ytml = YouTubeMusicDL(youtube_downloader = yt_dlp.YoutubeDL)
    # Merge https://github.com/tombulled/python-youtube-music/pull/30
    # Merge https://github.com/tombulled/python-youtube-music/pull/32
    ytml.download_song(
        song_id,
        directory = directory,
        ffmpeg_location = env("FFMPEG_LOCATION"),
        no_warnings = True,
        noprogress = True,
        # we can't pass a custom logger that calls send_to_logging_chats(), as application.bot is not picklable
    )


def create_ytlm_and_download_album(album_id, directory):
    """
    Call ``YouTubeMusicDL.download_album`` with certain parameters.

    The parameters passed to ``yt_dlp.YoutubeDL``:
    ``ffmpeg_location = env("FFMPEG_LOCATION")``
    ``no_warnings = True``
    ``noprogress = True``
    ``download_archive = os.path.join(directory, "download_archive.txt")``

    Parameters
    ----------
    album_id : str
        An id of the album to download, e.g. ``OLAK5uy_nmDUsWOMoEcz0SsVqUwir0oxu-k1oUyXE``.
    directory
        Either a string representing a path segment, or an object implementing the ``os.PathLike`` interface where the ``__fspath__()`` method returns a string, such as another path object.
        Used as an argument of https://docs.python.org/3/library/pathlib.html#pathlib.Path
    """
    ytml = YouTubeMusicDL(youtube_downloader = yt_dlp.YoutubeDL)
    # Merge https://github.com/tombulled/python-youtube-music/pull/30
    # Merge https://github.com/tombulled/python-youtube-music/pull/32
    ytml.download_album(
        album_id,
        directory = directory,
        ffmpeg_location = env("FFMPEG_LOCATION"),
        no_warnings = True,
        noprogress = True,
        download_archive = os.path.join(directory, "download_archive.txt")
        # we can't pass a custom logger that calls send_to_logging_chats(), as application.bot is not picklable
    )


def create_ytlm_and_download_video(video_id, directory):
    """
    Call ``YouTubeMusicDL.download_video`` with certain parameters.

    The parameters passed to ``yt_dlp.YoutubeDL``:
    ``ffmpeg_location = env("FFMPEG_LOCATION")``
    ``no_warnings = True``
    ``noprogress = True``

    Parameters
    ----------
    video_id : str
        An id of the video to download, e.g. ``dQw4w9WgXcQ``.
    directory
        Either a string representing a path segment, or an object implementing the ``os.PathLike`` interface where the ``__fspath__()`` method returns a string, such as another path object.
        Used as an argument of https://docs.python.org/3/library/pathlib.html#pathlib.Path
    """
    ytml = YouTubeMusicDL(youtube_downloader = yt_dlp.YoutubeDL)
    # Merge https://github.com/tombulled/python-youtube-music/pull/30
    # Merge https://github.com/tombulled/python-youtube-music/pull/32
    ytml.download_video(
        video_id,
        directory = directory,
        ffmpeg_location = env("FFMPEG_LOCATION"),
        no_warnings = True,
        noprogress = True,
        download_archive = os.path.join(directory, "download_archive.txt")
        # we can't pass a custom logger that calls send_to_logging_chats(), as application.bot is not picklable
    )


async def download_yt_and_reply(id: str, type: str, message: Message, compress = True):
    """
    Download a YT audio/album/short and reply with it.

    Use ``ytm.apis.YouTubeMusicDL.YouTubeMusicDL.YouTubeMusicDL`` to download the desired `type`, then call ``reply_media()``.
    Set the corresponding chat actions. Reply with an error message in case of any errors. Remove the downloaded files before finishing working.

    Parameters
    ----------
    id : str
        An id of the item to download.
    type : str
        A type of the item to download. Must be 'audio', 'album' or 'short'.
    message : telegram.Message
        A Telegram message to reply to.
    compress : bool, optional
        If `type` is ``'short'``, whether to compress the downloaded video when sending. Passed to ``reply_media()``. Default is ``True``.
    """
    if type not in ["audio", "album", "short"]:
        return
    
    await message.reply_chat_action('typing')

    target = str(message.chat.id) + "-" + str(message.id) + "-audio-" + id
    worth_trying = True
    try_count = 0
    if type == "audio":
        MAX_TRY_COUNT = 3
        TIMEOUT = 180
    elif type == "album":
        MAX_TRY_COUNT = 3
        TIMEOUT = 360
    else:  # type == "short"
        MAX_TRY_COUNT = 3
        TIMEOUT = 180
    exitcode = 1
    try:
        while worth_trying:
            await message.reply_chat_action('typing')
            try_count += 1
            worth_trying = False
            try:
                if type == "audio":
                    download_process = multiprocessing.Process(
                        target = create_ytlm_and_download_song,
                        args = (id, target)
                    )
                elif type == "album":
                    download_process = multiprocessing.Process(
                        target = create_ytlm_and_download_album,
                        args = (id, target)
                    )
                else:  # type == "short"
                    download_process = multiprocessing.Process(
                        target = create_ytlm_and_download_video,
                        args = (id, target)
                    )
                download_process.start()
                    
                reply_chat_action_task = asyncio.create_task(
                    repeat_while_process_alive(
                        5,  # see https://core.telegram.org/bots/api#sendchataction
                        download_process,
                        # message.reply_chat_action('typing')
                        message.reply_chat_action,
                        'typing'
                    )
                )
                await asyncio.to_thread(download_process.join, timeout = TIMEOUT)
            except:
                raise
            else:
                if download_process.is_alive():
                    worth_trying = try_count < MAX_TRY_COUNT
                    if worth_trying:
                        print(
                            f"Downloading the {type} {id} has been timed out; retrying... [{try_count}/{MAX_TRY_COUNT}]"
                        )
                    else:
                        raise Timeout
                else:
                    exitcode = download_process.exitcode
            finally:
                download_process.terminate()
                await asyncio.to_thread(download_process.join)
                await reply_chat_action_task
    except Timeout:
        print(
            f"{type.capitalize()} {id} donwload has been timed out; the maximum number of attempts ({MAX_TRY_COUNT}) reached.",
            file = sys.stderr
        )
        await message.reply_html(
            f"{sanitize_html_style(type.capitalize())} <code>{sanitize_html_style(id)}</code> download has failed ({MAX_TRY_COUNT} attempts). Please try again later."
        )
        await send_to_logging_chats(
            f"{sanitize_html_style(type.capitalize())} <code>{sanitize_html_style(id)}</code> donwload has been timed out; the maximum number of attempts ({MAX_TRY_COUNT}) reached.",
            message.get_bot()
        )
    except Exception as e:
        print(
            f"An error occured when downloading the {type} {id}:\n{traceback.format_exc()}",
            file = sys.stderr
        )
        await message.reply_html(
            f"An error occured when downloading the {sanitize_html_style(type)} <code>{sanitize_html_style(id)}</code>:\n<pre><code class=\"language-log\">{sanitize_html_style(str(e))}</code></pre>"
        )
        await send_to_logging_chats(
            f"An error occured when downloading the {sanitize_html_style(type)} <code>{sanitize_html_style(id)}</code>:\n<pre><code class=\"language-log\">{sanitize_html_style(traceback.format_exc())}</code></pre>",
            message.get_bot()
        )
    else:
        if exitcode == 0:
            await message.reply_chat_action('upload_document')
                    
            if type != "short":
                reply_yt_task = asyncio.create_task(
                    reply_audios(target, message)
                )
            else:
                reply_yt_task = asyncio.create_task(
                    reply_media(target, message, compress)
                )

            reply_chat_action_task = asyncio.create_task(
                repeat_until_task_done(
                    5,  # see https://core.telegram.org/bots/api#sendchataction
                    reply_yt_task,
                    # message.reply_chat_action('upload_document')
                    message.reply_chat_action,
                    'upload_document'
                )
            )

            await reply_yt_task
            await reply_chat_action_task
        else:
            print(
                f"{type.capitalize()} {id} download process terminated with exitcode {exitcode}",
                file = sys.stderr
            )
            await message.reply_html(
                #exitcode is int
                f"{sanitize_html_style(type.capitalize())} <code>{sanitize_html_style(id)}</code> download process terminated with exitcode <code>{exitcode}</code>"
            )
            await send_to_logging_chats(
                #exitcode is int
                f"{sanitize_html_style(type.capitalize())} <code>{sanitize_html_style(id)}</code> download process terminated with exitcode <code>{exitcode}</code>",
                message.get_bot()
            )
    finally:
        # remove target with all the files, if any were created
        shutil.rmtree(target, ignore_errors = True)


def find_first_of(text: str, chars: list[str]) -> int:
    """Return the position of the first occurrence of any element of `chars` in `text`, or the length of `text` if there are no `chars`."""
    res = len(text)
    for char in chars:
        if char in text:
            res = min(res, text.find(char))
    return res


async def handle_message(message: Message,
                         download_inst: bool = True,
                         download_yt_shorts: bool = True,
                         download_ytm: bool = True,
                         download_yt: bool = False,
                         compress: bool = True
                         ) -> bool:
    """Get supported links from `message`, initialize donwloads and reply.

    Set the corresponding chat action. Reply with an error message in case of any errors.
    Currently supported: Instagram ('p', 'reel', 'reels', 'stories'), YouTube Music ('watch', 'playlist', 'browse'), YouTube (same as YT Music + 'shorts').

    Parameters
    ----------
    message : Message
        A Telegram message to handle.
    download_inst : bool, optional
        Whether to handle Instagram links. Default is ``True``.
    download_yt_shorts : bool, optional
        Whether to handle YouTube Shorts links. Default is ``True``.
    download_ytm : bool, optional
        Whether to handle YouTube Music links. Default is ``True``.
    download_yt : bool, optional
        Whether to handle YouTube links. Default is ``False``.
    compress : bool, optional
        Whether to compress the downloaded images and videos when sending. Passed to the corresponding functions. Default is ``True``.

    Return
    ------
    bool
        Whether a download has been initialized.
    """
    await message.reply_chat_action('typing')
    
    download_initialized = False
    text_orig = message.text if message.text else message.caption
    if text_orig:
        # get markdown links
        entities = message.entities if message.entities else message.caption_entities
        text_link_urls = [(entity.url + " ") for entity in [entity for entity in entities if entity.type == 'text_link']]
        if text_link_urls:
            text_orig += " " + ' '.join(text_link_urls)

        text = text_orig
        L = L_captions if message.chat.id not in no_captions_chat_ids else L_no_captions
        inst_domain = "instagram.com/"
        while download_inst and inst_domain in text:
            link_type_start = text.find(inst_domain) + len(inst_domain)
            text = text[link_type_start:]
            link_type_end = find_first_of(text, ['/'])
            link_type = text[:link_type_end]
            text = text[(link_type_end + 1):]
            if link_type in ["p", "reel", "reels"]:
                # it's a post / reel link (https://www.instagram.com/p/<shortcode> or https://www.instagram.com/reel/<shortcode>)
                shortcode = text[:find_first_of(text, ['/', '?', ' ', '\n'])]
                download_initialized = True
                await download_post_and_reply(shortcode, message, compress)
            elif link_type in ["stories"]:
                # it's a stories link, let's find out the type
                username = text[:find_first_of(text, ['/', '?', ' ', '\n'])]

                first_slash = text.find("/") if "/" in text else len(text)
                text = text[(first_slash + 1):]
                mediaid = text[:find_first_of(text, ['/', '?', ' ', '\n'])]
                try:
                    profile = Profile.from_username(L.context, username)
                except Exception as e:
                    print(
                        f"An error occured when retrieving the profile {username}:\n{traceback.format_exc()}",
                        file = sys.stderr
                    )
                    await message.reply_html(
                        f"An error occured when retrieving the profile <code>{sanitize_html_style(username)}</code>:\n<pre><code class=\"language-log\">{sanitize_html_style(str(e))}</code></pre>"
                    )
                    await send_to_logging_chats(
                        f"An error occured when retrieving the profile <code>{sanitize_html_style(username)}</code>:\n<pre><code class=\"language-log\">{sanitize_html_style(traceback.format_exc())}</code></pre>",
                        message.get_bot()
                    )
                else:
                    if mediaid:
                        # it's a link to a certain story
                        # StoryItem.from_mediaid(L.context, mediaid) does not work, see https://github.com/instaloader/instaloader/issues/2531
                        # A workaround with L.get_stories():
                        try:
                            stories = L.get_stories([profile.userid])
                        except Exception as e:
                            print(
                                f"An error occured when retrieving the stories from profile {username}:\n{traceback.format_exc()}",
                                file = sys.stderr
                            )
                            await message.reply_html(
                                f"An error occured when retrieving the stories from profile <code>{sanitize_html_style(username)}</code>:\n<pre><code class=\"language-log\">{sanitize_html_style(str(e))}</code></pre>"
                            )
                            await send_to_logging_chats(
                                f"An error occured when retrieving the stories from profile <code>{sanitize_html_style(username)}</code>:\n<pre><code class=\"language-log\">{sanitize_html_style(traceback.format_exc())}</code></pre>",
                                message.get_bot()
                            )
                        else:
                            for story in stories:
                                for story_item in story.get_items():
                                    if str(story_item.mediaid) == mediaid:
                                        download_initialized = True
                                        await download_storyitem_and_reply(story_item, message, compress)
                    else:
                        # it's a link to profile's stories (https://www.instagram.com/stories/<username>)
                        download_initialized = True
                        await download_stories_and_reply(profile, message, compress)

        text = text_orig
        yt_shorts_domain = "youtube.com/shorts/"
        while download_yt_shorts and yt_shorts_domain in text:
            videoid_start = text.find(yt_shorts_domain) + len(yt_shorts_domain)
            text = text[videoid_start:]
            videoid = text[:find_first_of(text, ['&', '/', '?', ' ', '\n'])]
            download_initialized = True
            await download_yt_and_reply(videoid, "short", message, compress)

        text = text_orig
        audio_domains = []
        if download_ytm: audio_domains.append("music.youtube.com/")
        if download_yt:
            # ensure that "youtube.com" is not a part of "music.youtube.com"
            audio_domains.append(" youtube.com/")
            audio_domains.append("www.youtube.com/")
            audio_domains.append("//youtube.com/")
        if audio_domains:
            while any(domain in text for domain in audio_domains):
                type_start = len(text)
                for domain in audio_domains:
                    if domain in text: type_start = min(type_start, text.find(domain) + len(domain))
                text = text[type_start:]
                link_type_end = find_first_of(text, ['?', '/'])
                link_type = text[:link_type_end]
                text = text[(link_type_end + 1):]
                if link_type in ["watch"]:
                    value_pref = "v=" 
                    songid_start = text.find(value_pref) + len(value_pref)
                    text = text[songid_start:]
                    songid = text[:find_first_of(text, ['&', '/', '?', ' ', '\n'])]
                    download_initialized = True
                    await download_yt_and_reply(songid, "audio", message)
                elif link_type in ["shorts"]:
                    videoid = text[:find_first_of(text, ['&', '/', '?', ' ', '\n'])]
                    download_initialized = True
                    await download_yt_and_reply(videoid, "audio", message)
                elif link_type in ["playlist", "browse"]:
                    if link_type == "playlist":
                        value_pref = "list=" 
                        playlistid_start = text.find(value_pref) + len(value_pref)
                        text = text[playlistid_start:]
                    playlistid = text[:find_first_of(text, ['&', '/', '?', ' ', '\n'])]
                    # see https://github.com/tombulled/python-youtube-music/blob/0817d2688db3615a884453c6482008dac9977bf3/ytm/apis/AbstractYouTubeMusic/methods/album.py
                    union_album_type = ytm.types.Union(
                        ytm.types.AlbumPlaylistId,
                        ytm.types.AlbumPlaylistBrowseId,
                        ytm.types.AlbumBrowseId,
                        ytm.types.AlbumId,
                        ytm.types.AlbumRadioId,
                        ytm.types.AlbumShuffleId,
                    )
                    # non-album playlists are not supported as YouTubeMusicDL.download_playlist is broken
                    if ytm.utils.isinstance(playlistid, union_album_type):
                        download_initialized = True
                        await download_yt_and_reply(playlistid, "album", message)
    
    return download_initialized


async def check_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for text messages. Call ``handle_message()``.

    Ensure the bot is enabled in the chat and the message author is not banned.
    Call ``handle_message()`` and print the "no links" message if it returns ``False`` (no downloads have been initialized).
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    config_context = config["messages"]
    
    # update.effective_message is not None since it's a message handler
    message = update.effective_message
    if await ensure_active_chat(message, context, public_reply = False) and await ensure_not_banned_author(message, context):
        download_initialized = await handle_message(message)
        if not download_initialized:
            await message.reply_html(
                await format_message(config_context["no_links"], context)
            )


async def handle_mention(message: Message, context: ContextTypes.DEFAULT_TYPE, **handle_message_args):
    """
    Call ``handle_message()`` for `message` and it's reply-to.

    Print the "no links" message if no downloads have been initialized.
    """
    config_context = config["messages"]
    
    download_initialized_origin = await handle_message(message, **handle_message_args)
    download_initialized_reply_to = False
    if message.reply_to_message:
        download_initialized_reply_to = await handle_message(message.reply_to_message, **handle_message_args)
    if not download_initialized_origin and not download_initialized_reply_to:
        await message.reply_html(
            await format_message(config_context["no_links"], context)
        )


async def mentioned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for mentions. Call ``handle_mention()``.

    Ensure the bot is enabled in the chat and the message author is not banned; call ``handle_mention()``.
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    # update.effective_message is not None since it's a message handler
    message = update.effective_message
    if await ensure_active_chat(message, context) and await ensure_not_banned_author(message, context):
        await handle_mention(message, context)


async def uncompressed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for ``/uncompressed`` command. Send only uncompressed files for Instagram and YouTube Shorts links in the message and it's reply-to.

    Ensure the bot is enabled in the chat and the message author is not banned; call ``handle_mention()`` with the following parameters:
    ``download_inst = True``
    ``download_ytm = False``
    ``download_yt = False``
    ``download_yt_shorts = True``
    ``compress = False``
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    # update.effective_message is not None since it's a command handler
    message = update.effective_message
    if await ensure_active_chat(message, context) and await ensure_not_banned_author(message, context):
        await handle_mention(message, context, download_inst = True, download_ytm = False, download_yt = False, download_yt_shorts = True, compress = False)


async def audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for ``/audio`` command. Send only audios for YouTube and YouTube Shorts links in the message and it's reply-to.

    Ensure the bot is enabled in the chat and the message author is not banned; call ``handle_mention()`` with the following parameters:
    ``download_inst = False``
    ``download_ytm = False``
    ``download_yt = True``
    ``download_yt_shorts = True``
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    # update.effective_message is not None since it's a command handler
    message = update.effective_message
    if await ensure_active_chat(message, context) and await ensure_not_banned_author(message, context):
        await handle_mention(message, context, download_inst = False, download_ytm = False, download_yt = True, download_yt_shorts = True)


async def admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for ``/admin_panel`` command.

    Reply with the corresponding message.
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    config_context = config["admin_messages"]
    
    # update.effective_message is not None since it's a command handler
    message = update.effective_message
    if await ensure_admin(message, context):
        await message.reply_html(
            await format_message(config_context["admin_commands"], context)
        )


async def enable_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for ``/enable_chats`` command. Enable the bot in the chats from the args.

    Format: ``/enable_chats [chat_id] [chat_id] … [chat_id]``, chat_ids must be convertible to ``int``.
    For each chat, if the bot is already enabled in the chat, reply with the "no_need" message.
    Otherwise, ensure the command is used by an admin, enable the bot in the chat (add the chat to `active_chat_ids`) and reply with the "success" message.
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    config_context = config["admin_messages"]["enable_chats"]
    
    # update.effective_message is not None since it's a command handler
    message = update.effective_message
    if await ensure_admin(message, context):
        for arg in context.args:
            try:
                chat_id = int(arg)
            except Exception:
                await message.reply_html(
                    await format_message(config_context["arg_not_int"], context, arg)
                )
            else:
                if chat_id in active_chat_ids:
                    await message.reply_html(
                        await format_message(config_context["no_need"], context, arg)
                    )
                else:
                    future = await active_chat_ids.add(chat_id)
                    await future
                    future = await active_chat_ids.backup()
                    await future
                    await message.reply_html(
                        await format_message(config_context["success"], context, arg)
                    )


async def disable_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for ``/disable_chats`` command. Enable the bot in the chats from the args.

    Format: ``/disable_chats [chat_id] [chat_id] … [chat_id]``, chat_ids must be convertible to ``int``.
    For each chat, if the bot is already disabled in the chat, reply with the "no_need" message.
    Otherwise, ensure the command is used by an admin, disable the bot in the chat (discard the chat from `active_chat_ids`) and reply with the "success" message.
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    config_context = config["admin_messages"]["disable_chats"]
    
    # update.effective_message is not None since it's a command handler
    message = update.effective_message
    if await ensure_admin(message, context):
        for arg in context.args:
            try:
                chat_id = int(arg)
            except Exception:
                await message.reply_html(
                    await format_message(config_context["arg_not_int"], context, arg)
                )
            else:
                if chat_id not in active_chat_ids:
                    await message.reply_html(
                        await format_message(config_context["no_need"], context, arg)
                    )
                else:
                    future = await active_chat_ids.discard(chat_id)
                    await future
                    future = await active_chat_ids.backup()
                    await future
                    await message.reply_html(
                        await format_message(config_context["success"], context, arg)
                    )


async def ban_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for ``/ban_users`` command. Ban users with ids from the args (prevent them from using the bot).

    Format: ``/ban_users [user_id] [user_id] … [user_id]``, user_ids must be convertible to ``int``.
    For each user, if they are already banned, reply with the "no_need" message. If the target user is an admin, reply with the "arg_admin" message.
    Otherwise, ensure the command is used by an admin, ban the target user (add them to `banned_user_ids`) and reply with the "success" message.
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    config_context = config["admin_messages"]["ban_users"]
    
    # update.effective_message is not None since it's a command handler
    message = update.effective_message
    if await ensure_admin(message, context):
        for arg in context.args:
            try:
                user_id = int(arg)
            except Exception:
                await message.reply_html(
                    await format_message(config_context["arg_not_int"], context, arg)
                )
            else:
                if not is_admin(user_id):
                    # the user we're going to ban is not an admin
                    if user_id in banned_user_ids:
                        await message.reply_html(
                            await format_message(config_context["no_need"], context, arg)
                        )
                    else:
                        future = await banned_user_ids.add(user_id)
                        await future
                        future = await banned_user_ids.backup()
                        await future
                        await message.reply_html(
                            await format_message(config_context["success"], context, arg)
                        )
                else:
                    await message.reply_html(
                        await format_message(config_context["arg_admin"], context, arg)
                    )


async def unban_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    A handler for ``/unban_users`` command. Unban users with ids from the args (allow using the bot).

    Format: ``/unban_users [user_id] [user_id] … [user_id]``, user_ids must be convertible to ``int``.
    For each user, if they are already not banned, reply with the "no_need" message.
    Otherwise, ensure the command is used by an admin, unban the target user (discard them from `banned_user_ids`) and reply with the "success" message.
    For reference, see https://docs.python-telegram-bot.org/en/stable/telegram.ext.basehandler.html#telegram.ext.BaseHandler
    """
    config_context = config["admin_messages"]["unban_users"]
    
    # update.effective_message is not None since it's a command handler
    message = update.effective_message
    if await ensure_admin(message, context):
        for arg in context.args:
            try:
                user_id = int(arg)
            except Exception:
                await message.reply_html(
                    await format_message(config_context["arg_not_int"], context, arg)
                )
            else:
                # we don't need to check is_admin(user_id) here, as if an admin is somehow banned (which should be impossible), there must be an option to unban them (available for them as well)
                if user_id not in banned_user_ids:
                    await message.reply_html(
                        await format_message(config_context["no_need"], context, arg)
                    )
                else:
                    future = await banned_user_ids.discard(user_id)
                    await future
                    future = await banned_user_ids.backup()
                    await future
                    await message.reply_html(
                        await format_message(config_context["success"], context, arg)
                    )


def main():
    global config
    global L_captions
    global L_no_captions
    global active_chat_ids
    global no_captions_chat_ids
    global banned_user_ids
    
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.WARNING
    )

    DIRECTORY = pathlib.Path(__file__).resolve().parents[0]
    ROOT_DIRECTORY = DIRECTORY.parents[1] if "src" in str(DIRECTORY) else DIRECTORY
    
    # prepare envs and configs
    env.read_env()
    config_path = os.path.join(DIRECTORY, "settings", "config.toml")
    with open(config_path, 'rb') as config_file:
        config = tomllib.load(config_file)

    L_captions = instaloader.Instaloader(
        quiet = True,
        download_video_thumbnails = False,
        save_metadata = False,
        filename_pattern = "file"
    )

    L_no_captions = instaloader.Instaloader(
        quiet = True,
        download_video_thumbnails = False,
        save_metadata = False,
        filename_pattern = "file",
        # Merge https://github.com/instaloader/instaloader/pull/2578
        download_captions = False
    )
    # L.login("username", "password") does not work since login file request does not receive sessionid
    # A workaround for missing sessionid (see https://github.com/instaloader/instaloader/issues/2487):
    # Merge https://github.com/instaloader/instaloader/pull/2577 (session import fixes)
    # Optionally, merge https://github.com/borisbabic/browser_cookie3/pull/226 (Firefox MSiX support)
    # Optionally, merge https://github.com/borisbabic/browser_cookie3/pull/225 (Firefox via Flatpak support)
    if (config["session_import"]["browser"]):
        for L in [L_captions, L_no_captions]:
            import_session(config["session_import"]["browser"], L)
    else:
        for L in [L_captions, L_no_captions]:
            L.load_session(config["session_import"]["username"], {
                "csrftoken": config["session_import"]["csrftoken"],
                "sessionid": config["session_import"]["sessionid"],
                "ds_user_id": config["session_import"]["ds_user_id"],
                "mid": config["session_import"]["mid"],
                "ig_did": config["session_import"]["ig_did"]
            })
            L.test_login()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    defaults = Defaults(do_quote = True)
    application = ApplicationBuilder().token(env("TOKEN")).defaults(defaults).read_timeout(30).build()
    # we need to initialize application to fetch the bot's properties
    loop.run_until_complete(application.initialize())
    for L in [L_captions, L_no_captions]:
        L.context.error_catcher = MethodType(error_catcher, L.context)

    active_chat_ids = Preference(os.path.join(ROOT_DIRECTORY, "active_chat_ids.txt"), loop)
    no_captions_chat_ids = Preference(os.path.join(ROOT_DIRECTORY, "no_captions_chat_ids.txt"), loop)
    banned_user_ids = Preference(os.path.join(ROOT_DIRECTORY, "banned_user_ids.txt"), loop)
    
    application.add_handlers([
        CommandHandler('start', start),
        CommandHandler('help', help),
        CommandHandler('enable', enable),
        CommandHandler('disable', disable),
        CommandHandler('disable_captions', disable_captions),
        CommandHandler('enable_captions', enable_captions),
        CommandHandler('uncompressed', uncompressed),
        CommandHandler('audio', audio),
        MessageHandler(filters.Mention(application.bot.name), mentioned),
        MessageHandler((filters.TEXT & (filters.Entity('url') | filters.Entity('text_link'))) |
                       (filters.CAPTION & (filters.CaptionEntity('url') | filters.CaptionEntity('text_link'))),
                       check_message
                       ),
        CommandHandler('admin_commands', admin_commands),
        CommandHandler('enable_chats', enable_chats),
        CommandHandler('disable_chats', disable_chats),
        CommandHandler('ban_users', ban_users),
        CommandHandler('unban_users', unban_users),
    ])  # group = 0 (default)

    application.add_error_handler(application_exception_handler)

    print("Application initialized")
    # ensure logging chats accesibility
    loop.run_until_complete(send_to_logging_chats("Application initialized", application.bot))

    application.run_polling()


if __name__ == '__main__':
    main()
