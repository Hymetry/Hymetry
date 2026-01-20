from django.core.mail import EmailMultiAlternatives


def send_postmark_email(to, subject, html_body):
    message = EmailMultiAlternatives(
        subject,
        "",
        to=to,
        from_email='notifications@productpathpro.com',
        reply_to=['support@productpathpro.com'])
    message.attach_alternative(html_body, "text/html")
    message.send()
