from darkPy.guild import Guild
from darkPy.message import Message
from darkPy.user import User


class ConnectionState:
    def __init__(self, client, *, loop=None):
        self.client = client
        self.loop = loop
        self.guilds = {}
        self.channels = {}
        self.clear()

    def clear(self):
        self.user = None
        self.sequence = None
        self.session_id = None
        self.guilds.clear()
        self.voice_clients = {}

    def parse_ready(self, data):
        self.user = User(data['user'])
        self.client.user_id = self.user.id
        self.client.user = self.user

    def parse_resumed(self, data):
        pass

    def parse_guild_create(self, data):
        guild = Guild(data)
        self._add_guild(guild)

    def parse_guild_update(self, data):
        newGuild = Guild(data)
        self._set_guild(newGuild)

    def parse_guild_delete(self, data):
        self._remove_guild(data['id'])

    def parse_emojis_update(self, data):
        guild = self.get_guild(data['guild_id'])
        guild.set_emojis(data['emojis'])

    def parse_guild_member_add(self, data):
        guild = self.get_guild(data['guild_id'])
        data['guild_id'] = None
        guild.add_member(data)

    def parse_guild_member_remove(self, data):
        guild = self.get_guild(data['guild_id'])
        guild.remove_member(data['user']['id'])

    def parse_guild_member_update(self, data):
        guild = self.get_guild(data['guild_id'])
        data['guild_id'] = None
        guild.update_member(data)

    def parse_message_create(self, data):
        message = Message(data)
        guild = self._get_guild_for_channel(message.channel_id)
        guild.channels[message.channel_id].add_message(message)
        self.client.dispatch('message_create', message)

    def parse_message_update(self, data):
        guild = self._get_guild_for_channel(data['channel_id'])
        channel = guild.channels.get(data['channel_id'], None)
        if channel:
            channel.update_message(data)
            self.client.dispatch('message_update', channel.get_message(data['id']))

    def parse_message_delete(self, data):
        guild = self._get_guild_for_channel(data['channel_id'])
        channel = guild.channels.get(data['channel_id'], None)
        if channel:
            channel.remove_message(data['id'])

    def parse_message_delete_bulk(self, data):
        guild = self._get_guild_for_channel(data['channel_id'])
        channel = guild.channels.get(data['channel_id'], None)
        if channel:
            for id in data['ids']:
                channel.remove_message(id)

    def parse_channel_create(self, data):
        guild = self.get_guild(data['guild_id'])
        guild.add_channel(data)

    def parse_channel_update(self, data):
        guild = self.get_guild(data['guild_id'])
        guild.update_channel(data)

    def parse_channel_delete(self, data):
        guild = self.get_guild(data['guild_id'])
        guild.remove_channel(data['guild_id'])

    def parse_voice_state_update(self, data):
        channel = self.get_channel(data.get('channel_id'))
        if channel is None:
            guild = self.get_guild(data.get('guild_id'))
            guild.remove_voice_user(data)
            return
        guild = channel.guild
        guild.remove_voice_user(data)
        channel.add_voice_user(data)
    def _add_guild(self, guild):
        if self.guilds.get(guild.id, None) is None:
            self._set_guild(guild)

    def _set_guild(self, guild):
        self.guilds[guild.id] = guild
        channels = guild.channels
        for channel in channels:
            self.channels[channel] = guild.channels[channel]

    def get_guild(self, guildid):
        """

        :param guildid: The guild ID to retrieve
        :type guildid: str
        :return: The guild object
        :rtype: Guild
        """
        return self.guilds[guildid]

    def _remove_guild(self, guildid):
        channels = self.get_guild(guildid).channels
        for channel in channels:
            self.channels.pop(channel)
        self.guilds.pop(guildid)

    def _get_guild_for_channel(self, channel_id):
        """

        :param channel_id: The channel id we want the guild for
        :type channel_id: str
        :return: The guild corresponding or None if the guild does not exist
        :rtype: Guild
        """
        for guild in self.guilds:
            guild_obj = self.guilds[guild]
            if guild_obj.channels.get(channel_id, None):
                return guild_obj
        return None

    def _get_voice_client(self, guild_id):
        return self.voice_clients.get(guild_id)

    def _add_voice_client(self, guild_id, voice):
        self.voice_clients[guild_id] = voice

    def _remove_voice_client(self, guild_id):
        self.voice_clients.pop(guild_id, None)

    def _update_references(self, ws):
        for vc in self.voice_clients:
            vc.main_ws = ws

    def get_channel(self, channel_id):
        """

        :param channel_id: The channel id to search for
        :type channel_id: str
        :return: The channel object with the specified id
        :rtype: darkPy.channel.Channel
        """
        return self.channels.get(channel_id, None)
