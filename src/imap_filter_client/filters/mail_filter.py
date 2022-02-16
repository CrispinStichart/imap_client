from email.message import EmailMessage
from ..imap_filter_client import Envelope
from imapclient import IMAPClient


class Filter:
    def __init__(self):
        pass

    def filter(
        self, msg_uid: int, msg: EmailMessage, envelope: Envelope, client: IMAPClient
    ) -> bool:
        pass
