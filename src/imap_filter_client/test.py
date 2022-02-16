import configparser
import importlib.util
import logging
import os
import sqlite3 as sql
import sys
from dataclasses import dataclass
from pathlib import Path

from imapclient import IMAPClient

import imap_filter_client as main_class
from filters.political_spam import PoliticalSpam

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

log = logging.getLogger(__name__)


@dataclass
class Envelope:
    date: str
    sender: str
    subject: str


class EmailMessage:
    def __init__(self, id, date, sender, subject, body):
        self.id: int = id
        self.envelope = Envelope(date, sender, subject)
        self.body: str = body

    def get_body(self, *a, **kwargs):
        return self

    def get_content(self):
        return self.body


def get_spam_emails_from_db():
    emails = []
    db = sql.connect("emails.db")
    c = db.cursor()
    c.execute("SELECT * from emails where body like '%paid for by%'")
    for result in c:
        emails.append(EmailMessage(*result))

    db.commit()
    db.close()

    return emails


def load_filter_modules():
    p = Path(os.path.realpath(__file__))

    filter_modules = []

    for file in p.parent.glob("filters/*.py"):
        print(file)
        if file.name not in ["__init__.py", "mail_filter.py"]:
            spec = importlib.util.spec_from_file_location("filters." + file.name, file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[file.name] = module
            filter_modules.append(module)
            spec.loader.exec_module(module)

    return filter_modules


def main():
    log.setLevel(logging.DEBUG)
    main_class.log.setLevel(logging.DEBUG)
    # download_q: Queue = Queue()
    # download_q.put(Response(2432, "EXISTS"))
    #
    # main_class.filter_thread(download_q)

    with main_class.establish_connection() as client:
        print(main_class.get_last_checked_uid(client, catchup=False))


def test_political_spam_filter():
    spam_filter = PoliticalSpam()
    emails = get_spam_emails_from_db()
    should_not_block = [2432, 2437]
    for e in emails:
        processed = spam_filter.filter(e)  # TODO: update this
        if processed and e.id in should_not_block:
            log.warning(
                f"Should NOT have blocked id={e.id}, subj: {e.envelope.subject}"
            )
        if not processed and e.id not in should_not_block:
            log.warning(f"Should have blocked id={e.id}, subj: {e.envelope.subject}")


def fetch_test_email():
    # Read config
    config = configparser.ConfigParser()
    config.read("imap_filter.conf")

    imap_host = config["DEFAULT"]["host"]
    username = config["DEFAULT"]["username"]
    password = config["DEFAULT"]["password"]

    with IMAPClient(host=imap_host) as client:
        client.login(username, password)
        client.enable("UTF8=ACCEPT")
        client.select_folder("INBOX")

        for msg_id, data in client.fetch([2527], ["ENVELOPE", "RFC822"]).items():
            envelope = data[b"ENVELOPE"]
            print(envelope)


if __name__ == "__main__":
    main()
