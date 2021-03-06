from . import mail_filter
from email.message import EmailMessage
import re
from bs4 import BeautifulSoup
import logging
import os
from ..imap_filter_client import log as root_logger
from ..imap_filter_client import Envelope
from imapclient import IMAPClient

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

log = logging.getLogger(__name__)


class PoliticalSpam(mail_filter.Filter):
    # Is this kosher? I just want to inherit the level from the main
    # script's logger.
    log.setLevel(root_logger.level)

    def __init__(self):
        super().__init__()

    def filter(
        self, msg_uid: int, msg: EmailMessage, envelope: Envelope, client: IMAPClient
    ) -> bool:
        """Return true if we did something with the message"""
        soup = BeautifulSoup(
            msg.get_body(preferencelist=("plain", "html")).get_content(), "html.parser"
        )
        plaintext = soup.get_text()

        # These patterns are a good indicator that the message is spam, and will be checked for anywhere.
        patterns = [
            r"paid for by actblue",
            r"paid for by (((\w+\s*){1,4} ((\d\d(\d\d)?)|(for \w+)))|(the ((democratic national (convention|committee))|(dccc)))|((\w+\s*){1,6} PAC))",
        ]

        regexes = [re.compile(p, flags=re.I | re.M) for p in patterns]

        for regex in regexes:
            m = regex.search(plaintext)
            if m:
                # print("SUCESS: ", msg.subject)
                return True

        # This one is more common, and thus more dangerous to filter emails based on it alone.
        # So we only match if it's more than {threshhold}% through the message, and if there's an
        # unsubscribe link.
        regex = re.compile("paid for by", flags=re.I | re.M)
        regex2 = re.compile("unsubscribe", flags=re.I | re.M)
        threshhold = int(len(plaintext) * 0.7)
        if m := regex.search(plaintext, threshhold):
            if m2 := regex2.search(plaintext, threshhold):
                return True

        log.debug(
            f"did not find any matches for email with id={msg_uid} and subject: {envelope.subject}"
        )

        return False
