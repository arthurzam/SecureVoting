import smtplib
from email.message import EmailMessage
from typing import Iterable

def send_email(to: str, title: str, content: str) -> EmailMessage:
    msg = EmailMessage()
    msg['Subject'] = title
    msg['From'] = 'vmwareavote@gmail.com'
    msg['To'] = to
    msg.set_content(content)
    return msg

def register_email(to: str, name: str, secret_number: int):
    content = f"{name} , welcome to aVote system.\n" \
        f"Your login code is: {secret_number}\n" \
        "Please don't forget it!\n"
    with smtplib.SMTP('mailserver') as s:
        s.send_message(send_email(to, 'Register to aVote', content))

# def start_election(manager_email: str, manager_name: str, voters: Iterable[str]):
#     with smtplib.SMTP('mailserver') as s:
#         s.send_message(send_email(to, 'Register to aVote', content))
