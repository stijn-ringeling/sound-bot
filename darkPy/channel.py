#from message import Message
from enum import Enum

from darkPy import helpers
from darkPy.user import User

log = helpers.setup_logger()

class Channel:
    def __init__(self, data, guild):
        for key in data:
            if key == "recipients":
                recipients = []
                for userData in data[key]:
                    user = User(userData)
                    recipients.append(user)
                setattr(self, key, recipients)
            else:
                setattr(self, key, data[key])
        self.messages = {}
        self.guild = guild
        if self.type == ChannelType.GUILD_VOICE.value:
            self.connected_users = {}

    def add_message(self, message):
        self.messages[message.id] = message

    def get_message(self, message_id):
        return self.messages.get(message_id, None)

    def update_message(self, new_data):
        message = self.get_message(new_data['id'])
        if message:
            message.update(new_data)
        else:
            pass
            from darkPy.message import Message
            self.add_message(Message(new_data))

    def remove_message(self, message_id):
        message = self.get_message(message_id)
        if message:
            self.messages[message_id] = None

    def add_voice_user(self, data):
        if self.type == ChannelType.GUILD_VOICE.value:
            self.connected_users[data['user_id']] = {
                'deaf': data.get('deaf', False),
                'mute': data.get('mute', False),
                'self_deaf': data.get('self_deaf', False),
                'self_mute': data.get('self_mute', False)
            }
            log.info("User {} is now in channel {}".format(data['user_id'], self.id))

    def remove_voice_user(self, user_id):
        if self.type == ChannelType.GUILD_VOICE.value:
            if self.connected_users.get(user_id, None):
                self.connected_users.pop(user_id)
                log.info("User {} is now removed from channel {}".format(user_id, self.id))

    def contains_user(self, user_id):
        if self.type == ChannelType.GUILD_VOICE.value:
            if self.connected_users.get(user_id, None):
                return True

        return False


class ChannelType(Enum):
    GUILD_TEXT = 0
    DM = 1
    GUILD_VOICE = 2
    GROUP_DM = 3
    GROUP_CATEGORY = 4