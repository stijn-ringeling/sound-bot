import asyncio
import importlib
import command_handlers.command_handlers as command_handlers

from darkPy import helpers
from darkPy.client import Client

client = Client()

log = helpers.setup_logger()


def main():
    token = ""
    with open("token.txt") as token_file:
        token = token_file.read()
    if token != "":
        client.add_command('play', handle_play)
        client.add_command('stop', handle_stop)
        client.run(token)


@asyncio.coroutine
def handle_play(args, message):
    importlib.reload(command_handlers)
    yield from command_handlers.handle_play(args, message, client)


@asyncio.coroutine
def handle_stop(args, message):
    importlib.reload(command_handlers)
    yield from command_handlers.handle_stop(args, message, client)


if __name__ == "__main__":
    main()
