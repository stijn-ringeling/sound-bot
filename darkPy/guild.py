from darkPy.channel import Channel
from darkPy.user import User


class Role:
    def __init__(self, data):
        for key in data:
            setattr(self, key, data[key])


class Attachment:
    def __init__(self, data):
        for key in data:
            setattr(self, key, data[key])


class Emoji:
    def __init__(self, data):
        for key in data:
            setattr(self, key, data[key])


class Member:
    def __init__(self, data):
        self.user = User(data['user'])
        self.nick = data.get('nick', self.user.username)
        self.roles = data['roles']  # Array of snowflakes. Exact role data is stored in the guild object
        self.joined_at = data['joined_at']
        self.deaf = data['deaf']
        self.mute = data['mute']

    def update(self, data):
        userData = data.get('user', None)
        if userData is not None:
            self.user = User(userData)
        self.nick = data.get('nick', self.user.username)
        self.roles = data.get('roles', self.roles)


class Guild:
    def __init__(self, data):
        self.id = data['id']
        self.unavailable = data.get('unavailable', False)
        if self.unavailable:
            return
        self.name = data['name']
        self.icon = data['icon']
        self.splash = data['splash']
        self.owner = data.get('owner', False)
        self.owner_id = data['owner_id']
        self.permissions = data.get('permissions', 0)
        self.region = data['region']
        self.afk_channel_id = data['afk_channel_id']
        self.afk_timeout = data['afk_timeout']
        self.embed_enabled = data.get('embed_enabled', False)
        self.embed_channel_id = data.get('embed_channel_id', None)
        self.verification_level = data['verification_level']
        self.default_message_notifications = data['default_message_notifications']
        self.explicit_content_filter = data['explicit_content_filter']
        self.roles = {}
        for roleData in data['roles']:
            role = Role(roleData)
            self.roles[role.id] = role
        self.emojis = {}
        for emojiData in data.get('emojis', []):
            emoji = Emoji(emojiData)
            self.emojis[emoji.id] = emoji
        self.features = data['features']
        self.mfa_level = data['mfa_level']
        self.application_id = data['application_id']
        self.widget_enabled = data.get('widget_enabled', False)
        self.widget_channel_id = data.get('widget_channel_id', None)
        self.system_channel_id = data['system_channel_id']
        self.joined_at = data.get('joined_at', None)
        self.large = data.get('large', False)
        self.member_count = data.get('member_count', 0)
        # TODO parse partial voice states
        self.members = {}
        for memberData in data.get('members', []):
            member = Member(memberData)
            self.members[member.user.id] = member
        self.channels = {}
        for channelData in data.get('channels', []):
            channel = Channel(channelData, self)
            self.channels[channel.id] = channel
        # TODO parse presences data

    def set_emojis(self, emojis):
        self.emojis = {}
        for emojiData in emojis:
            emoji = Emoji(emojiData)
            self.emojis[emoji.id] = emoji

    def add_member(self, user):
        member = Member(user)
        self.members[member.user.id] = member

    def remove_member(self, user_id):
        self.members[user_id] = None

    def update_member(self, data):
        member = self.members.get(data['user']['id'])
        member.update(data)

    def add_channel(self, data):
        channel = Channel(data, self)
        self.channels[channel.id] = channel

    def update_channel(self, data):
        oldChannel = self.channels.get(data['id'])
        if oldChannel:
            messages = oldChannel.messages
            channel = Channel(data)
            for key in messages:
                channel.add_message(messages[key])
            self.channels[channel.id] = channel

    def remove_channel(self, channel_id):
        if self.channels.get(channel_id, None):
            self.channels[channel_id] = None

    def remove_voice_user(self, data):
        for key, channel in self.channels.items():
            channel.remove_voice_user(data['user_id'])

    def get_voice_channel_for_user(self, user_id):
        for key, channel in self.channels.items():
            if channel.contains_user(user_id):
                return channel
