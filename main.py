import datetime

import imapclient
from imapclient import IMAPClient
from email.message import EmailMessage
import email
from email import policy
import sqlite3 as sql
import configparser
from contextlib import contextmanager
from typing import cast
import logging
from dataclasses import dataclass
from queue import Queue
from pathlib import Path
import os
import importlib.util
import inspect
import sys
from filters import mail_filter
import threading
import os

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

# from rich import print
logging.basicConfig()
log = logging.getLogger(__name__)

LAST_SEEN_FILENAME = "last_seen_uid.txt"


# Simple storage class so we don't have to index into the server's
# response more than once.
class Response:
    def __init__(self, msg_id: int, action, flags=None):
        self.msg_id: int = msg_id
        self.action: str = action.decode()
        # self.flags: flags[]


class Envelope:
    def __init__(self, envelope):
        self.sender = ",".join(map(str, envelope.from_))
        self.date = envelope.date
        self.subject = envelope.subject.decode()


def load_filter_modules() -> dict:
    p = Path(os.path.realpath(__file__))

    filter_modules = {}

    # Not sure how kosher this all is, I've never done any dynamic
    # loading of modules before.
    for file in p.parent.glob("filters/*.py"):
        if file.name not in ["__init__.py", "mail_filter.py"]:
            log.debug(f"loading module from: {file}")
            spec = importlib.util.spec_from_file_location("filters." + file.name, file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[file.name] = module
            filter_modules[file.name] = module
            spec.loader.exec_module(module)

    return filter_modules


def get_filter_classes_from_modules(filter_modules) -> dict[str, mail_filter.Filter]:
    filter_classes: dict[str, mail_filter.Filter] = {}

    # We go through the modules that we imported and find the class that
    # subclasses our abstract mail_filter.Filter class, then we
    # instantiate it and save it with the module name.
    for module_name, module in filter_modules.items():
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, mail_filter.Filter):
                filter_classes[module_name] = obj()

    return filter_classes


def fetch_email(msg_id: int) -> EmailMessage:
    # We have to establish a new connection because we put the other
    # connection into idle mode, which causes the server to ignore
    # further commands. We establish a new connection for every new
    # message, since in a low-traffic inbox, it may be hours or more
    # between messages, and I'm not sure how IMAPClient/imaplib handles
    # long-lived connections.
    with establish_connection() as client:
        log.debug(f"Fetching message with ID={msg_id}")
        for msg_id, data in client.fetch([msg_id], ["ENVELOPE", "RFC822"]).items():
            # message_from_bytes is typhinted (in the typeshed stubs) as
            # returning Message, but that's only when policy=compat32
            email_message = cast(
                EmailMessage,
                email.message_from_bytes(data[b"RFC822"], policy=policy.default),
            )

            # Monkey patch the envelope into the message. This is
            # probably not the best way to handle this.
            email_message.envelope = Envelope(data[b"ENVELOPE"])

            # Monkey patch the msg_id into the message. Again, probably
            # not the best way to handle this.
            email_message.id = msg_id

    return email_message


def filter_thread(download_q: Queue):
    filter_modules = load_filter_modules()
    filter_classes = get_filter_classes_from_modules(filter_modules)

    while True:
        response: Response = download_q.get()
        msg = fetch_email(response.msg_id)

        for name, filter_c in filter_classes.items():
            log.debug(f"Sending message {response.msg_id} to {name} ")
            processed = filter_c.filter(msg)
            log.debug(f"Processed: {processed}")
            # filters will return true if they deleted or moved
            # the message, such that any other filters may have
            # undefined behavior.
            if processed:
                break


@contextmanager
def establish_connection():
    client = None
    try:
        config = configparser.ConfigParser()
        config.read("imap_filter.conf")

        imap_host = config["DEFAULT"]["host"]
        username = config["DEFAULT"]["username"]
        password = config["DEFAULT"]["password"]

        client = IMAPClient(host=imap_host)
        client.login(username, password)
        client.enable("UTF8=ACCEPT")
        client.select_folder("INBOX")

        yield client
    finally:
        if client:
            client.logout()


def get_last_checked_uid(client: imapclient.IMAPClient, catchup=False):
    date_filename = "last_seen_date.txt"
    if catchup:
        try:
            with open(date_filename, "r") as f:
                uid = int(f.readline().strip())
                log.debug(f"Read UID from {LAST_SEEN_FILENAME}: {str(uid)}")
                return uid
        except FileNotFoundError:
            catchup = False

    if not catchup:
        log.debug("Searching for most recent email")
        # The "*" stands for the highest numbered (most recent) UID
        uid = client.search(["UID", "*"])[0]
        with open(LAST_SEEN_FILENAME, "w") as f:
            f.write(str(uid))
        return uid


def main():
    log.setLevel(logging.DEBUG)
    with establish_connection() as client:
        client: imapclient.IMAPClient

        last_checked_uid = get_last_checked_uid(client)

        download_q: Queue = Queue()

        fetcher_thread = threading.Thread(target=filter_thread, args=(download_q,))
        fetcher_thread.start()

        while True:
            log.debug(f"Searching for messages above UID {last_checked_uid}")
            # Note: UID ranges are inclusive. "*" is the hightest UID in the inbox.
            results = client.search(["UID", last_checked_uid + 1, ":*"])
            for uid in results:
                log.debug(f"Putting UID={uid} into download queue")
                download_q.put(Response(uid, b"EXISTS"))

            # From what I can tell reading the docs, the search result
            # isn't guaranteed to return the UIDs in order.
            last_checked_uid = max(results)

            # Save the new last_seen
            with open(LAST_SEEN_FILENAME, "w") as f:
                f.write(str(last_checked_uid))

            # Note: when IDLEing, the IMAP server does not return UIDs
            # for emails, it returns the message ID, which don't persist
            # between sessions and may be reassigned by certain
            # operations. So whenver there's activity, we poll the
            # server for messages based on the date of the most recently
            # seen email.
            client.idle()
            log.info("Client is now in IDLE mode, waiting for response...")
            log.debug("Waiting for IDLE response...")
            response = client.idle_check(60 * 5)
            log.debug(f"Got IDLE response: {response}")
            log.debug("Exiting IDLE mode")
            client.idle_done()

    # date = "1-Jan-2020"
    #
    # db = sql.connect("emails.db")
    # c = db.cursor()
    # c.execute("DROP TABLE IF EXISTS emails")
    # c.execute("""CREATE TABLE IF NOT EXISTS emails (id, date, sender, subject, body)""")
    # c.execute("""CREATE UNIQUE INDEX id ON emails (id)""")
    # with IMAPClient(host=imap_host) as client:
    #     client.login(imap_user, imap_pass)
    #     client.enable("UTF8=ACCEPT")
    #     client.select_folder("INBOX")
    #     messages = client.search(["SINCE", date])
    #     for msg_id, data in client.fetch(messages, ["ENVELOPE", "RFC822"]).items():
    #         envelope = data[b"ENVELOPE"]
    #         # noinspection PyTypeChecker
    #         email_message: email.message.EmailMessage = email.message_from_bytes(
    #             data[b"RFC822"], policy=policy.default
    #         )
    #
    #         body = email_message.get_body(
    #             preferencelist=("plain", "html")
    #         ).get_content()
    #
    #         print(
    #             'ID #%d: "%s" received %s'
    #             % (msg_id, envelope.subject.decode(), envelope.date)
    #         )
    #         sender = ",".join(map(str, envelope.from_))
    #
    #         c.execute(
    #             "INSERT INTO emails VALUES (:id, :date, :sender, :subject, :body)",
    #             (msg_id, envelope.date, sender, envelope.subject.decode(), body),
    #         )
    #
    # db.commit()
    # db.close()


if __name__ == "__main__":
    main()
