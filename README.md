Tired of opening every single link sent by your friends? We too.

From now on, you don't need that. **tg-load** sets a Telegram bot for downloading and sending content from the links. Just add the bot to your group, enable it and get all the supported content directly to your chat!

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
7. Create a `.env` file with the following structure:
   ```
   TOKEN=''
   FFMPEG_LOCATION=''
   ```
8. Specify your bot's token and the ffmpeg custom build location in the .env file. The path may be absolute or relative, and must lead to the `bin` folder. Also, make sure to escape `\`. For example, if you placed ffmpeg in your working directory, the location will be `ffmpeg/bin` (or `ffmpeg\\bin` for Windows).


## Usage
- You can specify the texts of the messages sent by the bot in `config.toml`. Make sure to read the comments there.
- You may also want to set a command list for your bot. You can specify it in `commands.txt` (each command must be in a separate line, followed by another line with the description), and then set the commands by running `set_commands.py`.
- To run the bot, simply run `tg_load.py`.
