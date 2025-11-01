import asyncio
import os
import pathlib
import tomllib
from environs import env
from platformdirs import user_state_dir

from .preference import Preference
from .featurestate import FeatureState

import instaloader
from instaloader.__main__ import import_session


PROJECT_NAME = "tg_load"

DIR = pathlib.Path(__file__).resolve().parents[0]
ROOT_DIR = DIR.parents[1] if "src" in str(DIR) else DIR
STATE_DIR = os.path.join(ROOT_DIR, "state") if ROOT_DIR != DIR else user_state_dir(PROJECT_NAME)

FEATURE_NAMES = {
    "inst" : "Instagram",
    "yt_shorts": "YouTube Shorts",
    "ytm": "YouTube Music",
    "yt": "YouTube (audio)"
}

# prepare envs and configs
env.read_env()
config_path = os.path.join(DIR, "settings", "config.toml")
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
    post_metadata_txt_pattern = ""  # don't save captions
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
        if env.bool("TEST_LOGIN", default = True):
            L.test_login()

try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

if env("STATE_BUCKET", default = None):
    from google.cloud import storage
    BUCKET = storage.Client().bucket(env("STATE_BUCKET"))
else:
    BUCKET = None

active_chat_ids = Preference(os.path.join(STATE_DIR, "active_chat_ids.txt"), bucket = BUCKET)
no_captions_chat_ids = Preference(os.path.join(STATE_DIR, "no_captions_chat_ids.txt"), bucket = BUCKET)
banned_user_ids = Preference(os.path.join(STATE_DIR, "banned_user_ids.txt"), bucket = BUCKET)

feature_state = FeatureState(os.path.join(STATE_DIR, "features.json"), bucket = BUCKET)
