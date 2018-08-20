import asyncio
import json
import ssl
import struct
import sys
import threading
import time
import zlib
from collections import namedtuple

import websockets

from darkPy import helpers

log = helpers.setup_logger()


@asyncio.coroutine
def _ensure_coroutine_connect(gateway, *, loop, klass):
    # In 3.5+ websockets.connect does not return a coroutine, but an awaitable.
    # The problem is that in 3.5.0 and in some cases 3.5.1, asyncio.ensure_future and
    # by proxy, asyncio.wait_for, do not accept awaitables, but rather futures or coroutines.
    # By wrapping it up into this function we ensure that it's in a coroutine and not an awaitable
    # even for 3.5.0 users.
    ws = yield from websockets.connect(gateway, loop=loop, klass=klass)
    return ws


class ResumeWebSocket(Exception):
    """Signals to initialise via RESUME instead of IDETIFY"""
    pass


EventListener = namedtuple('EventListener', 'predicate event result future')


class KeepAliveHandler(threading.Thread):

    def __init__(self, *args, **kwargs):
        ws = kwargs.pop('ws', None)
        interval = kwargs.pop('interval', None)
        threading.Thread.__init__(self, *args, **kwargs)
        self.ws = ws
        self.interval = interval
        self.deamon = True
        self.msg = "Keeping websocket alive with sequence {0[d]}"
        self._stop_ev = threading.Event()
        self._last_ack = time.time()

    def run(self):
        while not self._stop_ev.wait(self.interval):
            if self._last_ack + 2 * self.interval < time.time():
                log.warning("We have stopped responding to the gateway.")
                coro = self.ws.close(1001)
                f = asyncio.run_coroutine_threadsafe(coro, loop=self.ws.loop)

                try:
                    f.result()
                except:
                    pass
                finally:
                    self.stop()
                    return

            data = self.get_payload()
            log.debug(self.msg.format(data))
            coro = self.ws.send_as_json(data)
            f = asyncio.run_coroutine_threadsafe(coro, loop=self.ws.loop)
            try:
                f.result()
            except Exception:
                self.stop()

    def get_payload(self):
        return {
            'op': self.ws.HEARTBEAT,
            'd': self.ws._connection.sequence
        }

    def stop(self):
        self._stop_ev.set()

    def ack(self):
        self._last_ack = time.time()


class VoiceKeepAliveHandler(KeepAliveHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.msg = 'Keeping voice websocket alive with timestamp {0[d]}'

    def get_payload(self):
        self.ack()
        return {
            'op': self.ws.HEARTBEAT,
            'd': int(time.time() * 1000)
        }


class MainGateway(websockets.client.WebSocketClientProtocol):

    DISPATCH = 0
    HEARTBEAT = 1
    IDENTIFY = 2
    PRESENCE = 3
    VOICE_STATE = 4
    VOICE_PING = 5
    RESUME = 6
    RECONNECT = 7
    REQUEST_MEMBERS = 8
    INVALIDATE_SESSION = 9
    HELLO = 10
    HEARTBEAT_ACK = 11
    GUILD_SYNC = 12

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_size = None
        # an empty dispatcher to prevent crashes
        self._dispatch = lambda *args: None
        # generic event listeners
        self._dispatch_listeners = []
        # the keep alive
        self._keep_alive = None

    @classmethod
    @asyncio.coroutine
    def from_client(cls, client, *, resume=False):
        gateway = helpers.get_gateway()
        try:
            ws = yield from asyncio.wait_for(_ensure_coroutine_connect(gateway, loop=client.loop, klass=cls),timeout=60, loop=client.loop)
        except asyncio.TimeoutError:
            log.warn('Timeout while waiting for client connect')
            return (yield from cls.from_client(client, resume=resume))
        ws.token = client.token
        ws.gateway = gateway
        ws.loop = client.loop
        ws._connection = client.connection
        ws._dispatch = client.dispatch

        client.connection._update_references(ws)

        log.info('Created websocket connected to {}'.format(gateway))
        try:
            yield from asyncio.wait_for(ws.poll_event(), timeout=60, loop=client.loop)
        except asyncio.TimeoutError:
            log.warning("timed out waiting for HELLO")
            yield from ws.close(1001)

        if not resume:
            yield from ws.identify()
            log.info('sent the identify payload to create the websocket')
            return ws

        yield from ws.resume()
        log.info('sent the resume payload to create the websocket')
        try:
            yield from ws.ensure_open()
        except websockets.exceptions.ConnectionClosed:
            log.warning('RESUME failure')
            return (yield from cls.from_client(client))
        else:
            return ws

    def wait_for(self, event, predicate, result=None):
        """Waits for aDISPATCH'd event that meets the predicate."""

        future = asyncio.Future(loop=self.loop)
        entry = EventListener(event=event, predicate=predicate, result=result, future=future)
        self._dispatch_listeners.append(entry)
        return future

    @asyncio.coroutine
    def poll_event(self):
        try:
            msg = yield from self.recv()
            yield from self.received_message(msg)
        except websockets.exceptions.ConnectionClosed as e:
            if self._can_handle_close(e.code):
                log.info('Wensocket closed with {0.code} ({0.reason}), attempting a reconnect.'.format(e))
                raise ResumeWebSocket(e) from e
            else:
                raise e

    @asyncio.coroutine
    def resume(self):
        state = self._connection
        payload = {
            "op": self.RESUME,
            'd': {
                'seq': state.sequence,
                'session_id': state.session_id,
                'token': self.token
            }
        }

        yield from self.send_as_json(payload)

    @asyncio.coroutine
    def identify(self):
        payload = {
            "op": self.IDENTIFY,
            "d": {
                "token": self.token,
                'properties': {
                    '$os': sys.platform,
                    'browser': 'darkpy',
                    'device': 'darkpy'
                },
                'compress': True,
                'large_threshold': 250,
                'v': 3
            }
        }

        yield from self.send_as_json(payload)

    @asyncio.coroutine
    def received_message(self, msg):
        self._dispatch('socket_raw_receive', msg)

        if isinstance(msg, bytes):
            msg = zlib.decompress(msg, 15, 10490000) # This is 10 MB
            msg = msg.decode('utf-8')

        msg = json.loads(msg)
        state = self._connection

        log.debug("Websocket event {}".format(msg))
        self._dispatch('socket_response', msg)

        op = msg.get('op')
        data = msg.get('d')
        seq = msg.get('s')
        if seq is not None:
            state.sequence = seq

        if op == self.RECONNECT:
            log.info('Received RECONNECT opcode.')
            yield from self.close()
            return

        if op == self.HEARTBEAT_ACK:
            self._keep_alive.ack()
            return

        if op == self.HEARTBEAT:
            beat = self._keep_alive.get_payload()
            yield from self.send_as_json(beat)
            return

        if op == self.HELLO:
            interval = data['heartbeat_interval'] / 1000.0
            self._keep_alive = KeepAliveHandler(ws=self, interval=interval)
            self._keep_alive.start()
            return

        if op == self.INVALIDATE_SESSION:
            if data == True:
                yield from asyncio.sleep(5.0, loop=self.loop)
                yield from self.close()
                raise ResumeWebSocket()

            state.sequence = None
            state.sequence_id = None

            yield from self.identify()
            return

        if op != self.DISPATCH:
            log.info('Unhandled op {}'.format(op))
            return

        event = msg.get('t')
        is_ready = event == 'READY'

        if is_ready:
            state.clear()
            state.sequence = msg['s']
            state.session_id = data['session_id']

        parser = 'parse_' + event.lower()

        try:
            func = getattr(self._connection, parser)
        except AttributeError:
            log.info('Unhandled event {}'.format(event))
        else:
            func(data)

        # remove the dispatched listeners
        removed = []
        for index, entry in enumerate(self._dispatch_listeners):
            if entry.event != event:
                continue

            future = entry.future
            if future.cancelled():
                removed.append(index)
                continue

            try:
                valid = entry.predicate(data)
            except Exception as e:
                future.set_exception(e)
                removed.append(index)
            else:
                if valid:
                    ret = data if entry.result is None else entry.result(data)
                    future.set_result(ret)
                    removed.append(index)

        for index in reversed(removed):
            del self._dispatch_listeners[index]

    @asyncio.coroutine
    def voice_state(self, guild_id, channel_id, self_mute=False, self_deaf=False):
        payload = {
            'op': self.VOICE_STATE,
            'd': {
                'guild_id': guild_id,
                'channel_id': channel_id,
                'self_mute': self_mute,
                'self_deaf': self_deaf
            }
        }

        yield from self.send_as_json(payload)

        # we're leaving a voice channel so remove it from the client list
        if channel_id is None:
            self._connection._remove_voice_client(guild_id)

    @asyncio.coroutine
    def _can_handle_close(self, code):
        return code not in (1000, 4004, 4010, 4011)

    @asyncio.coroutine
    def send_as_json(self, msg):
        try:
            yield from super().send(helpers.to_json(msg))
        except websockets.exceptions.ConnectionClosed as e:
            if not self._can_handle_close(e.code):
                raise

    @asyncio.coroutine
    def close_connection(self):
        if self._keep_alive:
            self._keep_alive.stop()

        yield from super().close_connection()


class VoiceGateway(websockets.client.WebSocketClientProtocol):
    IDENTIFY = 0
    SELECT_PROTOCOL = 1
    READY = 2
    HEARTBEAT = 3
    SESSION_DESCRIPTION = 4
    SPEAKING = 5
    HELLO = 8

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_size = None
        self._keep_alive = None

    @asyncio.coroutine
    def send_as_json(self, data):
        yield from self.send(helpers.to_json(data))

    @classmethod
    @asyncio.coroutine
    def from_client(cls, client):
        """Creates a voice websocket for the :class:`VoiceClient`."""

        gateway = "wss://" + client.endpoint + "?v=3"
        log.debug("Voice websocket gateway is: {}".format(gateway))
        try:
            ws = yield from asyncio.wait_for(
                _ensure_coroutine_connect(gateway, loop=client.loop, klass=cls),
                timeout=60, loop=client.loop)
        except asyncio.TimeoutError:
            log.warning("timed out waiting for voice client connect")
            return (yield from cls.from_client(client))

        ws.gateway =gateway
        ws._connection = client

        # waiting for HELLO packet
        try:
            yield from asyncio.wait_for(ws.poll_event(), timeout=60, loop=client.loop)
        except asyncio.TimeoutError:
            log.warning("timed out waiting for HELLO")
            yield from ws.close(1001)

        identify = {
            'op': cls.IDENTIFY,
            'd': {
                'server_id': client.guild_id,
                'user_id': client.user.id,
                'session_id': client.session_id,
                'token': client.token
            }
        }

        yield from ws.send_as_json(identify)

        return ws

    @asyncio.coroutine
    def received_message(self, msg):
        log.debug('Voice websocket frame received: {}'.format(msg))
        op = msg.get('op')
        data = msg.get('d')

        if op == self.HELLO:
            interval = data['heartbeat_interval'] * 0.75 / 1000.0 # heartbeat information is from HELLO instead of READY. Beacause of bug we multiply by 0.75
            self._keep_alive = VoiceKeepAliveHandler(ws=self, interval=interval)
            self._keep_alive.start()
        elif op == self.READY:
            yield from self.initial_connection(data)
        elif op == self.SESSION_DESCRIPTION:
            yield from self.load_secret_key(data)

    @asyncio.coroutine
    def initial_connection(self, data):
        state = self._connection
        state.ssrc = data.get('ssrc')
        state.voice_port = data.get('port')
        packet = bytearray(70)
        struct.pack_into('>I', packet, 0, state.ssrc)
        state.socket.sendto(packet, (state.endpoint_ip, state.voice_port))
        recv = yield from self.loop.sock_recv(state.socket, 70)
        log.debug('reveived packet in initial_connection: {}'.format(recv))

        # the ip is ascii starting at the 4th byte and ending at the first null
        ip_start = 4
        ip_end = recv.index(0, ip_start)
        state.ip = recv[ip_start:ip_end].decode('ascii')

        # the port is a little endial unsigned short in the last two bytes
        # yes, this is different endianness from everything else
        state.port = struct.unpack_from('<H', recv, len(recv) - 2)[0]

        log.debug('detected ip: {0.ip} port: {0.port}'.format(state))
        yield from self.select_protocol(state.ip, state.port)
        log.info('selected the voice protocol for use')

    @asyncio.coroutine
    def load_secret_key(self, data):
        log.info('received secret key for voice connection')
        self._connection.secret_key = data.get('secret_key')
        yield from self.speak()

    @asyncio.coroutine
    def select_protocol(self, ip, port):
        payload = {
            'op': self.SELECT_PROTOCOL,
            'd': {
                'protocol': 'udp',
                'data': {
                    'address': ip,
                    'port': port,
                    'mode': 'xsalsa20_poly1305'
                }
            }

        }
        yield from self.send_as_json(payload)
        log.debug('Selected protocol as {}'.format(payload))

    @asyncio.coroutine
    def speak(self, is_speaking=True):
        payload = {
            'op': self.SPEAKING,
            'd': {
                'speaking': is_speaking,
                'delay': 0
            }
        }

        yield from self.send_as_json(payload)
        log.debug('Voice speaking now set to {}'.format(is_speaking))

    @asyncio.coroutine
    def poll_event(self):
        try:
            msg = yield from self.recv()
            yield from self.received_message(json.loads(msg))
        except websockets.exceptions.ConnectionClosed as e:
            raise e

    @asyncio.coroutine
    def close_connection(self):
        if self._keep_alive:
            self._keep_alive.stop()

        yield from super().close_connection()
