import smtplib
from email.message import EmailMessage

def send_email(to: str, title: str, content: str) -> EmailMessage:
    msg = EmailMessage()
    msg['Subject'] = title
    msg['From'] = 'avote@vmware.com'
    msg['To'] = to
    msg.set_content(content)

def register_email(to: str, name: str, secret_number: int):
    content = f"""
        Welcome {name} to aVote system.
        Your login code is: {secret_number}
        Please don't forget it!
    """
    with smtplib.SMTP('mailserver') as s:
        s.send_message(send_email(to, 'Register to aVote', content))
