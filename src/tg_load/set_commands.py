import asyncio
from environs import env

from telegram import BotCommand
from telegram.ext import ApplicationBuilder


def main():
    env.read_env()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    application = ApplicationBuilder().token(env("TOKEN")).build()

    with open("commands.txt", "r") as file:
        lines = [line.strip() for line in file]

    commands = []
    for i in range(0, len(lines), 2):
        commands.append(BotCommand(lines[i], lines[i + 1]))

    loop.run_until_complete(
        application.bot.set_my_commands(commands)
    )


if __name__ == '__main__':
    main()
