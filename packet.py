import logging
from enum import Enum
import json

import helpers


class Packet:

    def __init__(self):
        self.logger = helpers.setup_logger()
        self.s = 0
        self.t = ""

    def parse(self, json):
        self.op = PacketType(json['op'])
        self.data = json['d']
        if self.op == PacketType.DISPATCH:
            self.seq = json['s']
            self.type = json['t']
        else:
            self.seq = None
            self.type = None
        self.logger.debug("Opcode is: " + self.op.name)
        return self

    def setData(self, op, data=None, s=0, t=""):
        self.op = op
        self.data = data
        self.s = s
        self.t = t
        return self

    def enc(self):
        jsonData = {}
        if isinstance(self.op, PacketType):
            jsonData = {'op': self.op.value}
            if self.data is not None:
                jsonData['d'] = self.data
            jsonData['s'] = self.s
            jsonData['t'] = self.t
        else:
            self.logger.warning("Invalid opcode: " + self.op)
        return json.dumps(jsonData)

    def __str__(self):
        return self.enc()


class PacketType(Enum):
    DISPATCH = 0
    HEARTBEAT = 1
    IDENTIFY = 2
    STATUS_UPDATE = 3
    VOICE_STATE_UPDATE = 4
    VOICE_SERVER_PING = 5
    RESUME = 6
    RECONNECT = 7
    REQUEST_GUILD_MEMBERS = 8
    INVALID_SESSION = 9
    HELLO = 10
    HEARTBEAT_ACK = 11
