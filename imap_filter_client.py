import configparser
import email
import importlib.util
import inspect
import logging
import os
import queue
import sys
import threading
from contextlib import contextmanager
from email import policy
from email.message import EmailMessage
from pathlib import Path
from queue import Queue
from typing import cast

import imapclient
from imapclient import IMAPClient

from filters import mail_filter

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

# from rich import print
logging.basicConfig()
log = logging.getLogger(__name__)

LAST_SEEN_FILENAME = "last_seen_uid.txt"


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
    for file in sorted(p.parent.glob("filters/*.py")):
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


def filter_thread(download_q: Queue, shutdown_event: threading.Event):
    filter_modules = load_filter_modules()
    filter_classes = get_filter_classes_from_modules(filter_modules)

    while True:
        # We check the queue every couple of second, and spend the rest
        # of the time waiting on a shutdown event. so we can join this
        # thread.
        try:
            uid: int = download_q.get_nowait()
            msg = fetch_email(uid)

            for name, filter_c in filter_classes.items():
                log.debug(f"Sending message {uid} to {name} ")
                processed = filter_c.filter(msg)
                log.debug(f"Processed: {processed}")
                # filters will return true if they deleted or moved
                # the message, such that any other filters may have
                # undefined behavior.
                if processed:
                    break
        except queue.Empty:
            if shutdown_event.wait(2.0):
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
    if catchup:
        try:
            with open(LAST_SEEN_FILENAME, "r") as f:
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

        shutdown_event = threading.Event()
        fetcher_thread = threading.Thread(
            target=filter_thread, args=(download_q, shutdown_event)
        )
        fetcher_thread.start()

        # TODO:

        while True:
            try:
                log.debug(f"Searching for messages above UID {last_checked_uid}")
                # Note: UID ranges are inclusive. "*" is the hightest UID in the inbox.
                results = client.search(f"UID {str(last_checked_uid + 1)}:*")
                for uid in results:
                    log.debug(f"Putting UID={uid} into download queue")
                    download_q.put(uid)

                # From what I can tell reading the docs, the search result
                # isn't guaranteed to return the UIDs in order.
                last_checked_uid = max(results)

                # Save the new last_seen
                with open(LAST_SEEN_FILENAME, "w") as f:
                    f.write(str(last_checked_uid))

                # Some notes: 1) when IDLEing, the IMAP server does not
                # return UIDs for emails, it returns the message ID,
                # which don't persist between sessions and may be
                # reassigned by certain operations. So whenver there's
                # activity, we poll the server for messages based on the
                # date of the most recently seen email. 2) Since idle
                # mode prevents the server from responding to any other
                # commands, we have to drop out of idle mode before we
                # can poll the server. 3) There's a timeout on the IDLE
                # because the docs recomend it, because the server will
                # close long-lived socket connections, and IMAPClient
                # doesn't do anything to keep the connection alive.
                client.idle()
                log.info("Client is now in IDLE mode, waiting for response...")
                log.debug("Waiting for IDLE response...")
                response = client.idle_check(60 * 5)
                log.debug(f"Got IDLE response: {response}")
                log.debug("Exiting IDLE mode")
                client.idle_done()
            except KeyboardInterrupt:
                log.debug("Got keyboard inturupt")
                shutdown_event.set()
                break

        log.debug("Waiting for fetch thread to join")
        fetcher_thread.join()


if __name__ == "__main__":
    main()
