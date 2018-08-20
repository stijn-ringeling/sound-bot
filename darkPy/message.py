from darkPy.guild import Attachment, Role
from darkPy.user import User


class Message:
    def __init__(self, data):
        for key in data:
            if key == 'author':
                setattr(self, key, User(data[key]))
            elif key == 'mentions':
                mentions = []
                for userData in data[key]:
                    user = User(userData)
                    mentions.append(user)
                setattr(self, key, mentions)
            elif key == 'mention_roles':
                roles = []
                for roleData in data[key]:
                    role = Role(roleData)
                    roles.append(role)
                setattr(self, key, roles)
            elif key == 'attachments':
                attachments = []
                for attachmentData in data[key]:
                    attachments.append(Attachment(attachmentData))
                setattr(self, key, attachments)
            else:
                setattr(self, key, data[key])

    def update(self, data):
        for key in data:
            if key == 'author':
                setattr(self, key, User(data[key]))
            elif key == 'mentions':
                mentions = []
                for userData in data[key]:
                    user = User(userData)
                    mentions.append(user)
                setattr(self, key, mentions)
            elif key == 'mention_roles':
                roles = []
                for roleData in data[key]:
                    role = Role(roleData)
                    roles.append(role)
                setattr(self, key, roles)
            elif key == 'attachments':
                attachments = []
                for attachmentData in data[key]:
                    attachments.append(Attachment(attachmentData))
                setattr(self, key, attachments)
            else:
                setattr(self, key, data[key])
