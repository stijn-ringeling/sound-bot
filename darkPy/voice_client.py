import asyncio
import audioop
import datetime
import functools
import inspect
import shlex
import socket
import struct
import subprocess
import threading
import time

from websockets import ConnectionClosed

from darkPy import opus, helpers
from darkPy.channel import ChannelType
from darkPy.gateway import VoiceGateway

log = helpers.setup_logger()

try:
    import nacl.secret
    has_nacl = True
except ImportError:
    has_nacl = False


class StreamPlayer(threading.Thread):
    def __init__(self, stream, encoder, connected, player, after, **kwargs):
        threading.Thread.__init__(self, **kwargs)
        self.daemon = True
        self.buff = stream
        self.frame_size = encoder.frame_size
        self.player = player
        self._end = threading.Event()
        self._resumed = threading.Event()
        self._resumed.set()
        self._connected = connected
        self.after = after
        self._delay = encoder.frame_length / 1000.0
        self._volume = 1.0
        self._current_error = None

        if after is not None and not callable(after):
            raise TypeError('Expected a callable of for the after parameter.')

    def _do_run(self):
        self.loops = 0
        self._start = time.time()
        while not self._end.is_set():
            # Are we paused
            if not self._resumed.is_set():
                # Wait until we resume
                self._resumed.wait()

            if not self._connected.is_set():
                self.stop()
                break

            self.loops += 1
            data = self.buff.read(self.frame_size)

            if self._volume != 1.0:
                data = audioop.mul(data, 2, min(self.volume, 2.0))

            if len(data) != self.frame_size:
                self.stop()
                break

            self.player(data)
            next_time = self._start + self._delay * self.loops
            delay = max(0, self._delay + (next_time - time.time()))
            time.sleep(delay)

    def run(self):
        try:
            self._do_run()
        except Exception as e:
            self._current_error = e
            self.stop()
            raise e
        finally:
            self._call_after()

    def _call_after(self):
        if self.after is not None:
            try:
                arg_count = len(inspect.signature(self.after).parameters)
            except:
                # if this ended up happening a mistake was made
                log.error("Could not parse argument count from self.after")
                arg_count = 0

            try:
                if arg_count == 0:
                    self.after()
                else:
                    self.after(self)
            except Exception as e:
                log.error('Error while parsing self.after.')
                log.error(e.with_traceback())
                raise e

    def stop(self):
        self._end.set()

    @property
    def error(self):
        return self._current_error

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value):
        self._volume = map(value, 0.0)

    def pause(self):
        self._resumed.clear()

    def resume(self):
        self.loops = 0
        self._start = time.time()
        self._resumed.set()

    def is_playing(self):
        return self._resumed.is_set() and not self.is_done()

    def is_done(self):
        return not self._connected.is_set() or self._end.is_set()

class ProcessPlayer(StreamPlayer):
    def __init__(self, process, client, after, **kwargs):
        super().__init__(process.stdout, client.encoder, client._connected,
                         client.play_audio, after, **kwargs)
        self.process = process

    def run(self):
        super().run()

        self.process.kill()
        if self.process.poll() is None:
            self.process.communicate()

class VoiceClient:
    def __init__(self, user, main_ws, session_id, channel, data, loop):
        if not has_nacl:
            raise RuntimeError("PyNaCl library needed in order to use voice")

        self.user = user
        self.main_ws = main_ws
        self.channel = channel
        self.session_id = session_id
        self.loop = loop
        self._connected = asyncio.Event(loop=self.loop)
        self.token = data.get('token')
        self.guild_id = data.get('guild_id')
        self.endpoint = data.get('endpoint')
        self.sequence = 0
        self.timestamp = 0
        self.encoder = opus.Encoder(48000, 2)
        self.player = None
        log.info('created opus encoder with {0.__dict__}'.format(self.encoder))

    warn_nacl = not has_nacl

    @property
    def server(self):
        return self.channel.server

    def checked_add(self, attr, value, limit):
        val = getattr(self, attr)
        if val + value > limit:
            setattr(self, attr, 0)
        else:
            setattr(self, attr, val+ value)

    # connection related

    @asyncio.coroutine
    def connect(self):
        log.info('voice connection is connecting...')
        self.endpoint = self.endpoint.replace(':80', '')
        self.endpoint_ip = socket.gethostbyname(self.endpoint)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setblocking(False)

        log.info('Voice endpoint found {0.endpoint} (IP: {0.endpoint_ip})'.format(self))

        self.ws = yield from VoiceGateway.from_client(self)
        while not self._connected.is_set():
            yield from self.ws.poll_event()
            if hasattr(self, 'secret_key'):
                # we have a secret , so we don't need to poll
                # websocket events anymore
                self._connected.set()
                break

        self.loop.create_task(self.poll_voice_ws())

    @asyncio.coroutine
    def poll_voice_ws(self):
        while self._connected.is_set():
            try:
                yield from self.ws.poll_event()
            except ConnectionClosed as e:
                if e.code == 1000:
                    break
                else:
                    raise e

    @asyncio.coroutine
    def disconnect(self):
        if not self._connected.is_set():
            return
        self._connected.clear()
        try:
            yield from self.ws.close()
            yield from self.main_ws.voice_state(self.guild_id, None, self_mute=True)
        finally:
            self.socket.close()

    @asyncio.coroutine
    def move_to(self, channel):
        if getattr(channel, 'type', ChannelType.GUILD_TEXT.value) != ChannelType.GUILD_VOICE.value:
            raise ValueError('Must be a voice channel.')

        yield from self.main_ws.voice_state(self.guild_id, channel.id)

    def is_connected(self):
        """bool: Indicates if the voice client is connected to voice."""
        return self._connected.is_set()

    # audio related

    def _get_voice_packet(self, data):
        header = bytearray(12)
        nonce = bytearray(24)
        box = nacl.secret.SecretBox(bytes(self.secret_key))

        # Formulate header
        header[0] = 0x80
        header[1] = 0x78
        struct.pack_into('>H', header, 2, self.sequence)
        struct.pack_into('>I', header, 4, self.timestamp)
        struct.pack_into('>I', header, 8, self.ssrc)

        # Copy header to nonce's first 12 bytes
        nonce[:12] = header

        # Encrypt and return the data
        return header + box.encrypt(bytes(data), bytes(nonce)).ciphertext

    def create_ffmpeg_player(self, filename, *, use_avconv=False, pipe=False, stderr=None, options=None, before_options=None, headers=None, after=None):
        """
        Creates a stream player for ffmpeg that launches in a separate thread to play audio.

        The ffmpeg player launches a subprocess of ``fmpeg`` to a specific
        filename and then plays that file.

        You must have ffmpeg or avconv executable in your path environment variable
        in forder for this to work.

        The operations that can be done on the player are the same as those in
        :meth:`create_stream_player`
        :param filename: The filename that ffmpeg will take and convert to PCM bytes.
        If ``pipe`` is True then this is a file like object that is passed to the stdin of ``fmpeg``.
        :type filename: str
        :param use_avconv: Use ``avconv`` instead of ``fmpeg``.
        :type use_avconv: bool
        :param pipe: If true, denotes that filename parameter will be passed to stdin of ffmpeg.
        :type pipe: bool
        :param stderr: A gile-like object or ``subprocess.PIPE`` to pass to the Popen constructor.
        :type stderr: Any
        :param options: Extra command line flags to pass to ``fmpeg`` after
        :type options: str
        :param before_options: Command line flags to pass to ``fmpeg`` before the ``-i`` flag
        :type before_options: str
        :param headers: HTTP headers dictionary to pass to ``-headers`` command line option
        :type headers: dict
        :param after: The finalizer that is called after the stream is doe being played.
        all exceptions the finalizer throws are silently discarded.
        :type after: callable
        :return: A stream player with specific operations
        :rtype: StreamPlayer
        """

        command = 'ffmpeg' if not use_avconv else 'avconv'
        input_name = '-' if pipe else shlex.quote(filename)
        before_args = ""
        if isinstance(headers, dict):
            for key, value in headers.items():
                before_args += "{}: {}\r\n".format(key,value)
            before_args = ' -headers ' + shlex.quote(before_args)

        if isinstance(before_options, str):
            before_args += ' ' + before_options

        cmd = command + '{} -i {} -f s16le -ar {} -ac {} -loglevel warning'
        cmd = cmd.format(before_args, input_name, self.encoder.sampling_rate, self.encoder.channels)

        if isinstance(options, str):
            cmd = cmd + ' ' + options

        cmd += ' pipe:1'

        stdin = None if not pipe else filename
        args = shlex.split(cmd)
        try:
            p = subprocess.Popen(args, stdin=stdin, stdout=subprocess.PIPE, stderr=stderr)
            self.player = ProcessPlayer(p, self, after)
            return self.player
        except FileNotFoundError as e:
            raise Exception('ffmpeg/avconv was not found in your PATH environment variable') from e
        except subprocess.SubprocessError as e:
            raise Exception('Popen failed: {0.__name__} {1}'.format(type(e), str(e))) from e

    @asyncio.coroutine
    def create_ytdl_player(self, url, *, ytdl_options=None, **kwargs):

        import youtube_dl

        use_avconv = kwargs.get('use_avconv', False)
        opts = {
            'format': 'webm[abr>0]/bestaudio/best',
            'prefer_ffmpeg': not use_avconv
        }

        if ytdl_options is not None and isinstance(ytdl_options, dict):
            opts.update(ytdl_options)

        ydl = youtube_dl.YoutubeDL(opts)
        func = functools.partial(ydl.extract_info, url, download=False)
        info = yield from self.loop.run_in_executor(None, func)
        if "entries" in info:
            info = info['entries'][0]

        log.info('playing URL {}'.format(url))
        download_url = info['url']
        player = self.create_ffmpeg_player(download_url, **kwargs)

        player.download_url = download_url
        player.url = url
        player.yt = ydl
        player.views = info.get('view_count')
        player.is_live = bool(info.get('is_live'))
        player.likes = info.get('like_count')
        player.dislikes = info.get('dislike_count')
        player.duration = info.get('duration')
        player.uploader = info.get('uploader')

        is_twitch = 'twitch' in  url
        if is_twitch:
            # twitch has 'title' and 'description' sor of mixed up.
            player.title = info.get('desciption')
            player.description = None
        else:
            player.title = info.get('title')
            player.description = None

        date = info.get('upload_date')
        if date:
            try:
                date = datetime.datetime.strptime(date, "%Y%M%d").date()
            except ValueError:
                date = None

        player.upload_date = date
        return player

    def play_audio(self, data, *, encode=True):
        """Sends an audio packet composed of the data.

        You must be connected to play audio.

        data : bytes
            The *bytes-like-object* denoting PCM or Opus voice data.
        encode : bool
            Indicates if ``data`` should be encoded into Opus."""
        self.checked_add('sequence', 1, 65535)
        if encode:
            encoded_data = self.encoder.encode(data, self.encoder.samples_per_frame)
        else:
            encoded_data = data
        packet = self._get_voice_packet(encoded_data)
        try:
            sent = self.socket.sendto(packet, (self.endpoint_ip, self.voice_port))
        except BlockingIOError:
            log.warning('A packet has been dropped (seq: {0.sequence}, timestamp: ({0.timestamp})'.format(self))

        self.checked_add('timestamp', self.encoder.samples_per_frame, 4294967295)