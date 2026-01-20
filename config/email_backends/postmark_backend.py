from django.core.mail.backends.base import BaseEmailBackend
from postmarker.core import PostmarkClient
from django.conf import settings

class PostmarkBackend(BaseEmailBackend):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = PostmarkClient(server_token=settings.POSTMARK_API_TOKEN)

    def send_messages(self, email_messages):
        num_sent = 0
        for message in email_messages:
            try:
                self.client.emails.send(
                    From=message.from_email,
                    To=",".join(message.to),
                    Subject=message.subject,
                    HtmlBody=message.alternatives[0][0] if message.alternatives else "",
                    TextBody=message.body,
                    Cc=",".join(message.cc) if message.cc else None,
                    Bcc=",".join(message.bcc) if message.bcc else None,
                    ReplyTo=message.reply_to[0] if message.reply_to else None,
                    Tag="django-allauth"
                )
                num_sent += 1
            except Exception as e:
                if not self.fail_silently:
                    raise
        return num_sent
