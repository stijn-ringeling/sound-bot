class User:
    def __init__(self, data):
        self.id = data['id']
        self.username = data['username']
        self.discriminator = data['discriminator']
        self.avatar = data.get('avatar', None)
        self.bot = data.get('bot', False)
        self.mfa_enabled = data.get('mfa_enabled', False)
        self.verified = data.get('verified', False)
        self.email = data.get('email', "")