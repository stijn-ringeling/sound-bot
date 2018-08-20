import asyncio
import os

from darkPy import helpers
from darkPy.channel import ChannelType

log = helpers.setup_logger()


def close_connection(voice, loop):
    def closer():
        asyncio.run_coroutine_threadsafe(voice.disconnect(), loop)

    return closer


@asyncio.coroutine
def handle_play(args, message, client):
    """
    Handle any command
    :param args: Arguments passed to the command
    :type args: array.Array
    :param message: The message object send by the user
    :type message: darkPy.message.Message
    :param client: The client from which te command originated
    :type client: darkPy.client.Client
    """
    log.info("Handling command")
    if len(args) > 1:
        path = "audio/" + args[1] + ".wav"
        channel = client.get_channel(message.channel_id)
        guild = client.get_guild_for_channel(channel)
        log.info(guild.channels[message.channel_id])
        user_channel = guild.get_voice_channel_for_user(message.author.id)
        if user_channel is None:
            channels = []
            for key in guild.channels:
                if guild.channels[key].type == ChannelType.GUILD_VOICE.value:
                    log.info("Adding channel to voice channels")
                    channels.append(guild.channels[key])

            if len(channels) > 0:
                user_channel = channels[0]
        log.info("Starring voice connection")
        log.info(user_channel.guild)
        voice = client.voice_client_in(guild)
        if voice is None:
            voice = yield from client.join_voice_channel(user_channel)
            if voice.channel.id != user_channel.id:
                yield from voice.move_to(channels[0])
        log.info("playing some audio")
        if voice.player is not None:
            voice.player.after = None
            voice.player.stop()
        if os.path.exists(path):
            player = voice.create_ffmpeg_player(path, after=close_connection(voice, client.loop))
            player.start()
        else:
            player = yield from voice.create_ytdl_player(args[1], after=close_connection(voice,client.loop))
            player.start()
    else:
        log.info("Please specify a file to play")


@asyncio.coroutine
def handle_stop(args, message, client):
    channel = client.get_channel(message.channel_id)
    guild = client.get_guild_for_channel(channel)
    voice = client.voice_client_in(guild)
    log.info(voice)
    if voice is not None:
        yield from voice.disconnect()
