import asyncio
import os
import pathlib
from environs import env

from telegram import BotCommand
from telegram.ext import ApplicationBuilder


def main():
    DIRECTORY = pathlib.Path(__file__).resolve().parents[0]
    
    env.read_env()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    application = ApplicationBuilder().token(env("TOKEN")).build()

    commands_default_path = os.path.join(DIRECTORY, "settings", "commands.default.txt")
    commands_override_path = os.path.join(DIRECTORY, "settings", "commands.txt")
    commands_path = commands_override_path if os.path.isfile(commands_override_path) else commands_default_path
    with open(commands_path, "r") as file:
        lines = [line.strip() for line in file]

    commands = []
    for i in range(0, len(lines), 2):
        commands.append(BotCommand(lines[i], lines[i + 1]))

    loop.run_until_complete(
        application.bot.set_my_commands(commands)
    )

    input("Press Enter to close this window: ")


if __name__ == '__main__':
    main()
