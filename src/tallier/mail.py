import os
from smtplib import SMTP
from email.message import EmailMessage
from typing import Iterable

import mytypes

WEBSITE_URL = os.getenv("WEBSITE_URL", "http://localhost")

def build_msg(to: str, title: str, content: str) -> EmailMessage:
    msg = EmailMessage()
    msg['Subject'] = title
    msg['From'] = 'VMWare aVote <vmwareavote@gmail.com>'
    msg['To'] = to
    msg.set_content(content)
    return msg

def register_email(to: str, name: str, secret_number: int):
    content = f"{name} , welcome to aVote system.\n" \
        f"Your login code is: {secret_number}\n" \
        "Please don't forget it!\n" \
        f"To login, enter the URL: {WEBSITE_URL}/login\n"
    with SMTP('mailserver') as s:
        s.send_message(build_msg(to, 'Register to aVote', content))

def start_election(manager_name: str, election: mytypes.Election, voters: Iterable[str]):
    content = f"A new election had opened.\n" \
        f"Election \"{election.election_name}\", by {manager_name} <{election.manager_email}>.\n" \
        "You can vote in it, after logging in, using the following link:\n" \
        f"{WEBSITE_URL}/election/vote?id={election.election_id}\n"
    with SMTP('mailserver') as s:
        for voter in {election.manager_email} | set(voters):
            s.send_message(build_msg(voter, 'Election Started', content))

def stop_election(manager_name: str, election: mytypes.Election, voters: Iterable[str], results: Iterable[str]):
    content = f"An election you were participating in had closed.\n" \
        f"Election \"{election.election_name}\", by {manager_name} <{election.manager_email}>.\n" \
        "The results are the following:\n" \
        + "\n".join((f"    Place #{place} - {name}" for place, name in enumerate(results, start=1)))
    with SMTP('mailserver') as s:
        for voter in {election.manager_email} | set(voters):
            s.send_message(build_msg(voter, 'Election Closed', content))
