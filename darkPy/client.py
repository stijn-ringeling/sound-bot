import asyncio

from websockets import ConnectionClosed

from darkPy import helpers
from darkPy.gateway import MainGateway, ResumeWebSocket
from darkPy.state import ConnectionState
from darkPy.voice_client import VoiceClient
from darkPy.channel import Channel, ChannelType

log = helpers.setup_logger()


class Client:

    def __init__(self, *, loop=None):
        self.ws = None
        self.loop = asyncio.get_event_loop() if loop is None else loop
        self.loop.set_debug(True)
        self.token = ""

        self.command_listeners = {}

        self.connection = ConnectionState(self, loop=self.loop)
        self._closed = asyncio.Event(loop=self.loop)

        if VoiceClient.warn_nacl:
            log.warning("PyNaCl library is not installed. Voice communication will not work")
            VoiceClient.warn_nacl = False

    def run(self, token):
        try:
            self.loop.run_until_complete(self.start(token))
        except KeyboardInterrupt:
            self.loop.run_until_complete(self.logout())
            pending = asyncio.tasks.all_tasks(self.loop)
            gathered = asyncio.gather(*pending, loop=self.loop)
            try:
                gathered.cancel()
                self.loop.run_until_complete(gathered)

                gathered.exception()
            except:
                pass
        finally:
            self.loop.close()

    def add_command(self, name, func):
        self.command_listeners[name] = func

    @asyncio.coroutine
    def start(self, token):
        yield from self.login(token)
        yield from self.connect()

    @asyncio.coroutine
    def login(self, token):
        self.token = token

    @asyncio.coroutine
    def connect(self):
        self.ws = yield from MainGateway.from_client(self)

        while not self._is_closed:
            try:
                yield from self.ws.poll_event()
            except ResumeWebSocket:
                log.info('Got ResumeWebSocket')
                self.ws = yield from MainGateway.from_client(self, resume=True)
            except ConnectionClosed as e:
                yield from self.close()
                if e.code != 1000:
                    raise

    @asyncio.coroutine
    def close(self):
        """
        Close the websocket connection
        :returns:``None``
        """
        if self._closed:
            return
        if self.ws is not None and self.ws.open:
            yield from self.ws.close()

        self._closed.set()

    @property
    def _is_closed(self):
        return self._closed.is_set()

    def dispatch(self, event, data):
        if event == 'message_create':
            if data.content.startswith('!'):
                components = data.content.split(' ')
                command_name = components[0][1:]
                if self.command_listeners.get(command_name, None):
                    self.loop.create_task(self.command_listeners[command_name](components, data))
                else:
                    log.info('Unknown command {}'.format(command_name))

    @asyncio.coroutine
    def join_voice_channel(self, channel):
        """
        Join a voice channel
        :param channel: The channel to join
        :type channel: :class:`Channel`
        :return: return a VoiceClient object
        :rtype: VoiceClient
        """

        if isinstance(channel, object):
            channel = self.get_channel(channel.id)
        if getattr(channel, 'type', ChannelType.GUILD_TEXT.value) != ChannelType.GUILD_VOICE.value:
            raise ValueError('Channel passed must be a voice channel')

        guild = channel.guild

        if self.is_voice_connected(guild):
            raise ValueError('Already connected to a voice channel in this guild')

        log.info('attempting to join voice channel {0.name}'.format(channel))

        def session_id_found(d):
            user_id = d.get('user_id')
            guild_id = d.get('guild_id')
            return user_id == self.user_id and guild_id == guild.id

        # register the futures for waiting
        session_id_future = self.ws.wait_for('VOICE_STATE_UPDATE', session_id_found)
        voice_data_future = self.ws.wait_for('VOICE_SERVER_UPDATE', lambda d: d.get('guild_id') == guild.id)

        yield from self.ws.voice_state(guild.id, channel.id)

        try:
            session_id_data = yield from asyncio.wait_for(session_id_future, timeout=10.0, loop=self.loop)
            data = yield from asyncio.wait_for(voice_data_future, timeout=10.0, loop=self.loop)
        except asyncio.TimeoutError as e:
            yield from self.ws.voice_state(guild.id, None, self_mute=True)
            raise e

        kwargs = {
            'user': self.user,
            'channel': channel,
            'data': data,
            'loop': self.loop,
            'session_id': session_id_data.get('session_id'),
            'main_ws': self.ws
        }

        voice = VoiceClient(**kwargs)
        try:
            yield from voice.connect()
        except asyncio.TimeoutError as e:
            try:
                yield from voice.disconnect()
            except:
                # we don't care if disconnect failed because connection failed
                pass
            raise e

        self.connection._add_voice_client(guild.id, voice)

        return voice

    def is_voice_connected(self, server):
        """
        Returns if the client is connected to a server
        :param server: The server we want to query
        :type server: Guild
        :return: True if we are in the server, False otherwise
        :rtype: bool
        """
        voice = self.voice_client_in(server)
        return voice is not None

    def voice_client_in(self, server):
        """
        Retrieve the voice client for a server
        :param server: The server to receive the voice connection for
        :type server: darkPy.guild.Guild
        :return: the Voice connection or None
        :rtype: VoiceClient
        """
        return self.connection._get_voice_client(server.id)

    def get_channel(self, channel_id):
        return self.connection.get_channel(channel_id)

    def logout(self):
        yield from self.close()

    def get_guild_for_channel(self, channel):
        """

        :param channel: The channel object to retrieve to guild for
        :type channel: Channel
        """
        return self.connection._get_guild_for_channel(channel.id)

