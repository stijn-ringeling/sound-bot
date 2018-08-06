import asyncio
import json
import logging
import ssl
import urllib.parse
from queue import Queue

import websockets

import helpers
from packet import Packet, PacketType


class Gateway:
    def __init__(self, gateway, token):
        self.gateway = gateway
        self.loop = asyncio.get_event_loop()
        self.loop.set_exception_handler(self.handle_exception)
        self.sendQueue = Queue()
        self.token = token
        self.websocket = None
        self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.ssl_context.load_default_certs()
        self.running = True
        self.logger = helpers.setup_logger()
        self.logger.info(self.gateway)
        weblogger = logging.getLogger("websockets")
        weblogger.setLevel(logging.INFO)
        weblogger.addHandler(helpers.ch)
        asynciologger = logging.getLogger('asyncio')
        asynciologger.setLevel(logging.INFO)
        asynciologger.addHandler(helpers.ch)

    def connect(self):
        self.logger.info("Starting connection")
        self.loop.run_until_complete(self.make_connection())

    async def make_connection(self):
        async with websockets.connect(self.gateway, ssl=self.ssl_context) as websocket:
            self.websocket = websocket
            await self.start()

    async def start(self):
        consumer = self.consumer_handler()
        producer = self.producer_handler()
        done, pending = await asyncio.wait([consumer,producer], loop=self.loop, return_when=asyncio.FIRST_EXCEPTION)
        self.logger.info("Connection closed")
        for task in done:
            if task.exception():
                raise task.exception()
        for task in pending:
            task.cancel()
        self.logger.debug("Pending tasks at exit: {}".format(pending) )
        self.logger.info("Cancelling pending tasks.")
        self.stop()
        return

    async def consumer_handler(self):
        while self.websocket.open:
            self.logger.debug("Reading messages")
            message = await self.websocket.recv()
            await self.consume(message)
        return "Done"

    async def consume(self, message):
        jsonMessage = json.loads(message)
        self.logger.debug(jsonMessage)
        packet = Packet().parse(jsonMessage)
        await self.handle_packet(packet)
        self.logger.info("handled packet {}".format(packet))
        return

    async def handle_packet(self, packet):
            pass

    def get_identify(self):
        pass

    def send(self, message):
        if isinstance(message, Packet):
            message = message.enc()
        self.sendQueue.put_nowait(message)

    async def producer_handler(self):
        while self.websocket.open:
            message = self.sendQueue.get()
            await self.websocket.send(message)
            self.logger.info("Message send: " + message)
        return "Done"

    def stop(self):
        self.running = False

    def handle_exception(self, loop, context):
        self.logger.error("We handle an exception with: {}, {}".format(loop, context))


class MainGateway(Gateway):

    def get_identify(self):
        identData = {
            "token": self.token,
            "properties": {
                "$os": "linux",
                "$browser": "disco",
                "$device": "disco"
            },
            "compress": False,
            "large_threshold": 250,
            "shard": [],

        }
        packet = Packet().setData(PacketType.IDENTIFY, identData)
        return packet

    async def handle_packet(self, packet):
        if packet.op == PacketType.HELLO:
            identPacket = self.get_identify()
            self.send(identPacket)
            self.logger.info("send packet {}".format(identPacket))
        else:
            self.logger.info("Got a new packet {}".format(packet))