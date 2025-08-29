Tired of opening every single link sent by your friends? We too.

From now on, you don't need that. **tg-load** sets a Telegram bot for downloading and sending content from links. Just add the bot to your group, enable it and get all the supported content directly to your chat!

Currently supported: **Instagram**, **YouTube Music**, **YouTube** (audio and **YouTube Shorts**).

## Required components
- Python (version 3.13 recommended)
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) module
- [environs](https://github.com/sloria/environs) module
- [instaloader](https://github.com/instaloader/instaloader) module with the following PRs merged:
   * [#2577](https://github.com/instaloader/instaloader/pull/2577)
   * [#2578](https://github.com/instaloader/instaloader/pull/2578)
   * [#2581](https://github.com/instaloader/instaloader/pull/2581)
   * [#2583](https://github.com/instaloader/instaloader/pull/2583)
- [browser-cookie3](https://github.com/borisbabic/browser_cookie3) module with the following PRs merged:
   * (optionally) [#225](https://github.com/borisbabic/browser_cookie3/pull/225)
   * (optionally) [#226](https://github.com/borisbabic/browser_cookie3/pull/226)
- [python-youtube-music](https://github.com/tombulled/python-youtube-music) module with YouTubeMusicDL support and the following PRs merged:
  * [#30](https://github.com/tombulled/python-youtube-music/pull/30)
  * [#32](https://github.com/tombulled/python-youtube-music/pull/32)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) module with ffmpeg and ffprobe custom builds

## Recommended installation
1. Install the latest version of Python from the [official website](https://www.python.org/downloads/) with PIP included.
2. [Install Git](https://github.com/git-guides/install-git).
3. In the system command prompt (in your desired directory), run the following as an administrator:<br/>
   ```
   pip install git+https://github.com/denyshon/tg-load
   ```
5. Install https://github.com/denyshon/python-youtube-music/tree/tg-load with YouTubeMusicDL support as described in its README.
6. [Download an ffmpeg custom build](https://github.com/yt-dlp/FFmpeg-Builds) for [yt-dlp](https://github.com/yt-dlp/yt-dlp), that corresponds to your yt-dlp version.
7. In the project root folder, create a `.env` file with the following structure:
   ```
   TOKEN=''
   FFMPEG_LOCATION=''
   ```
8. Specify your bot's token and the ffmpeg custom build location in the .env file. The path may be absolute or relative, and must lead to the `bin` folder. Also, make sure to escape `\`. For example, if you placed ffmpeg in your working directory, the location will be `ffmpeg/bin` (or `ffmpeg\\bin` for Windows).


## Starting
- You can specify the texts of the messages sent by the bot in `src/tg_load/settings/config.toml`. Make sure to read the comments there.
- You may also want to set a command list for your bot. You can specify it in `src/tg_load/settings/commands.txt`, and then set the commands by running `src/tg_load/set_commands.py`.
  - Each of the commands must be in a separate line, followed by another line with the description.
  - If you installed *tg-load* using a package manager, you can also execute
    ```
    tg-load-set-commands
    ```
- To run the bot, simply run `src/tg_load/tg_load.py`.
  - If you installed *tg-load* using a package manager, you can also execute
    ```
    tg-load
    ```


## Usage
### Commands
- `/start`<br/>
  Get started
- `/help`<br/>
  Find out more about the bot
- `/enable` [*admin only*]<br/>
  Enable the bot in the chat
- `/disable` [*admin only*]<br/>
  Disable the bot in the chat
- `/enable_captions`<br/>
  Enable Instagram caption downloading in the chat
- `/disable_captions`<br/>
  Disable Instagram caption downloading in the chat
- `/uncompressed`<br/>
  Get uncompressed media from Instagram (*handles links in your message and in the message you're replying to*)
- `/audio`<br/>
  Get audio from YouTube and YouTube Music (*handles links in your message and in the message you're replying to*)
- `/admin_commands` [*admin only*]<br/>
  Get a list of available admin commands
### Admin commands
It is not recommended to include these commands to the bot's command list, but they are still recognized:
- `/enable_chats [chat_id] [chat_id] … [chat_id]` [*admin only*]<br>
  Enable the bot in the chats with the given IDs
- `/disable_chats [chat_id] [chat_id] … [chat_id]` [*admin only*]<br>
  Disable the bot in the chats with the given IDs
- `/ban_users [user_id] [user_id] … [user_id]` [*admin only*]<br>
  Prevent the users with the given IDs from using the bot
- `/unban_users [user_id] [user_id] … [user_id]` [*admin only*]<br>
  Allow the users with the given IDs using the bot
### Mentions
You can mention the bot to force handling the message you are replying to. Please make sure to reply to the message containing link(s), not a one with downloaded content. Links in your message with the mention will also be handled as usual.
### Limitations
- Make sure to limit Instagram requests according to Instagram limitations.
- Limit the number of videos/audios being downloaded simultaneously. Remember, that for each of them a new process is created, so a too high number may lead to the bot's temporare unavailability and even a crash. The timeouts (*remember to adjusts them*) help dealing with that, but do not solve the problem.
