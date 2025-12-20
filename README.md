Tired of opening every single link sent by your friends? We too.

From now on, you don't need that. **tg-load** sets a Telegram bot for downloading and sending content from links. Just add the bot to your group, enable it and get all the supported content directly to your chat!

Currently supported: **Instagram**, **YouTube Music**, **YouTube** (audio and **YouTube Shorts**).

## Required components
- Python (version 3.13 recommended)
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) module
- [environs](https://github.com/sloria/environs) module
- [instaloader](https://github.com/instaloader/instaloader) module with the following PRs merged:
   * [#2577](https://github.com/instaloader/instaloader/pull/2577)
   * [#2583](https://github.com/instaloader/instaloader/pull/2583)
- [browser-cookie3](https://github.com/borisbabic/browser_cookie3) module with the following PRs merged:
   * (optionally) [#225](https://github.com/borisbabic/browser_cookie3/pull/225)
   * (optionally) [#226](https://github.com/borisbabic/browser_cookie3/pull/226)
- [python-youtube-music](https://github.com/tombulled/python-youtube-music) module with YouTubeMusicDL support and the following PRs merged:
  * [#30](https://github.com/tombulled/python-youtube-music/pull/30)
  * [#32](https://github.com/tombulled/python-youtube-music/pull/32)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) module with ffmpeg and ffprobe custom builds

## Recommended installation and setup
1. Install the latest version of Python from the [official website](https://www.python.org/downloads/) with PIP included.
2. [Install Git](https://github.com/git-guides/install-git).
3. In the system command prompt, run the following as an administrator:<br/>
   ```
   pip install git+https://github.com/denyshon/tg-load
   ```
4. Install https://github.com/denyshon/python-youtube-music/tree/tg-load with YouTubeMusicDL support as described in its README.
5. [Download an ffmpeg custom build](https://github.com/yt-dlp/FFmpeg-Builds) for [yt-dlp](https://github.com/yt-dlp/yt-dlp), that corresponds to your yt-dlp version.
6. In the project root folder, create a `.env` file with the following structure:
   ```
   TOKEN=''
   FFMPEG_LOCATION=''
   ```
7. Specify your bot's token and the ffmpeg custom build location in the .env file. The path may be absolute or relative, and must lead to the `bin` folder. Also, make sure to escape `\`. For example, if you placed ffmpeg in your working directory, the location will be `ffmpeg/bin` (or `ffmpeg\\bin` for Windows). **Warning:** for the console application, it is recommended to use an absolute path only.
8. Optionally, add
   ```
   TEST_LOGIN=False
   ```
   This has effect only if browser is not set in config.toml, and means that exactly one test login will be performed after loading the session. Default is true.
9. In `src/tg_load/settings/`, create `config.toml`. Values specified there will override values from `src/tg_load/settings/config.default.toml`. You must specify:
   - `admin_ids`
   - Either `browser` or `username`, `csrftoken`, `sessionid`, `ds_user_id`, `mid` and `ig_did`.
   It is also recommended to specify `logging_chat_ids`.
10. In `src/tg_load/settings/config.toml`, you can also specify the texts of the messages sent by the bot. Make sure to follow the structure of `src/tg_load/settings/config.default.toml` and read the comments there.
11. You can pass YouTube cookies to login via `src/tg_load/settings/youtube_cookies.txt`. See https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies
12. You may also want to set a command list for your bot. You can specify it in `src/tg_load/settings/commands.txt` (or stick to `src/tg_load/settings/commands.default.txt`) and then set the commands by running `src/tg_load/set_commands.py`.
    - If `src/tg_load/settings/commands.txt` doesn't exist, `src/tg_load/settings/commands.default.txt` will be used. Otherwise, `src/tg_load/settings/commands.default.txt` will be ignored!
    - Each of the commands must be in a separate line, followed by another line with the description.
    - If you installed *tg-load* using a package manager, you can also execute
      ```
      tg-load-set-commands
      ```

## Starting
To run the bot:
- If you installed *tg-load* via pip, simply execute
  ```
  tg-load
  ```
- If you haven't installed *tg-load*, in the project directory execute:
  ```
  set PYTHONPATH=src
  ```
  on Windows, or
  ```
  PYTHONPATH=src
  ```
  on Unix, and then
  ```
  python -m tg_load
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
- `/uncompressed`<br/>
  Get uncompressed media from Instagram (*handles links in your message and in the message you're replying to*)
- `/audio`<br/>
  Get audio from YouTube and YouTube Music (*handles links in your message and in the message you're replying to*)
- `/enable_captions`<br/>
  Enable Instagram caption downloading in the chat
- `/disable_captions`<br/>
  Disable Instagram caption downloading in the chat
- `/enable_notifications`<br/>
  Enable notifications (e.g., when a feature is enabled/disabled) in the chat
- `/disable_notifications`<br/>
  Disable notifications (e.g., when a feature is enabled/disabled) in the chat
- `/admin_commands` [*admin only*]<br/>
  Get a list of available admin commands
### Admin commands
It is not recommended to include these commands in the bot's command list, but they are still recognized:
- `/enable_chats [chat_id] [chat_id] … [chat_id]` [*admin only*]<br>
  Enable the bot in the chats with the given IDs
- `/disable_chats [chat_id] [chat_id] … [chat_id]` [*admin only*]<br>
  Disable the bot in the chats with the given IDs
- `/ban_users [user_id] [user_id] … [user_id]` [*admin only*]<br>
  Prevent the users with the given IDs from using the bot
- `/unban_users [user_id] [user_id] … [user_id]` [*admin only*]<br>
  Allow the users with the given IDs to use the bot
- `/enable_features [feature_shortname] [feature_shortname] … [feature_shortname]` [*admin only*]<br>
  Enable features with shortnames from the args (`inst` | `yt_shorts` | `ytm` | `yt`)
- `/disable_features [feature_shortname] [feature_shortname] … [feature_shortname]` [*admin only*]<br>
  Disable features with shortnames from the args (`inst` | `yt_shorts` | `ytm` | `yt`)
- `/send_notification [Notification content]` [*admin only*]<br>
  Send a notification to the chats with notifications enabled
- `/send_forced_notification [Notification content]` [*admin only*]<br>
  Send a notification to all the active chats
### Mentions
You can mention the bot to force handling of the message you are replying to. Please make sure to reply to the message containing link(s), not the one with downloaded content. Links in your message with the mention will also be handled as usual.
### Limitations
- Make sure to limit Instagram requests according to Instagram's limitations for a single account.
- Limit the number of videos/audios being downloaded simultaneously. Remember that for each of them a new process is created, so too high a number may lead to the bot's temporary unavailability and even a crash. The timeouts (*remember to adjust them if needed*) help deal with that, but do not solve the problem.


## Supported link types
- **Instagram**:
  - `p`: links to Instagram posts, e.g., `https://www.instagram.com/instagram/p/DN8-GjPkgjS/`
  - `reel`: links to Instagram reels from profiles, e.g., `https://www.instagram.com/instagram/reel/DN8JgNMgFE8/`
  - `reels`: links to Instagram reels from the general tab, e.g., `https://www.instagram.com/reels/DLVVFcppzdR/`
  - `stories`: links to Instagram profile stories, e.g., `https://www.instagram.com/stories/instagram/`, or links to certain Instagram stories, e.g., `https://www.instagram.com/stories/instagram/3711483840431921893/`
- **YouTube Music**:
  - `watch`: links to YouTube Music songs, e.g., `https://music.youtube.com/watch?v=lYBUbBu4W08`
  - `playlist`: links to YouTube Music albums and singles, e.g., `https://music.youtube.com/playlist?list=OLAK5uy_kRPA8ySVXwGMFk2DcJjEzCTE4yjJqiOrY`<br>
    **Note**: user playlists are not supported, see [#4](https://github.com/denyshon/tg-load/issues/4)
  - `browse`: *browse* links to YouTube Music albums and singles (redirected to *playlist* links), e.g., `https://music.youtube.com/browse/MPREb_WrO8DjG6YIZ`
- **YouTube**:
  - `watch`: links to YouTube videos, e.g., `https://www.youtube.com/watch?v=lYBUbBu4W08`
  - `youtu.be`: shortened links to YouTube videos (redirected to *watch* links), e.g., `https://youtu.be/xvFZjo5PgG0`
  - `playlist`: links to YouTube albums and singles, e.g., `https://www.youtube.com/playlist?list=OLAK5uy_kRPA8ySVXwGMFk2DcJjEzCTE4yjJqiOrY`
    **Note**: user playlists are not supported, see [#4](https://github.com/denyshon/tg-load/issues/4)
  - `shorts`: links to YouTube shorts, e.g., `https://www.youtube.com/shorts/ei_2rfHyqCU`


## Google Cloud Run deployment
Install gcloud. On Windows:
```
winget install --id Google.CloudSDK
```
Create a project, and then login:
```
gcloud auth login
gcloud auth application-default login
gcloud config set project ${PROJECT_ID}

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com
```
Create a bucket (or use your project's one) and give ${PROJECT_ID}-compute@developer.gserviceaccount.com the Storage Object User role.
In the project directory, deploy from source:
```
gcloud run deploy tg-load --source . --region ${REGION} --allow-unauthenticated --clear-base-image --set-env-vars TOKEN=${TOKEN} --set-env-vars STATE_BUCKET=${BUCKET} --min-instances 1
```
Set webhook updates:
```
curl -s -X POST "https://api.telegram.org/bot${TOKEN}/setWebhook" \
  -d "url=${SERVICE_URL}/webhook" \
  -d "secret_token=${SECRET}" \
  -d "drop_pending_updates=true"
```


## Plans for future releases
- Track a request count for each user
- Add more download options for the users
- Provide YouTube video downloading (limited per user)
- Add Instagram highlights / profile downloading (with warnings and limited per user)
- Provide support for LinkedIn links
- Provide support for TikTok links
- Provide support for SoundCloud links
- Provide support for X links