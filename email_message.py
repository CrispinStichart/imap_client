"""
Not sure if this is what I want to do yet.

Was thinking of making a custom email message class,
so I can save the envlope information. However: I don't
know how to copy information from the email.message.EmailMessage
into this one at creation time.

Do I monkey patch it somehow? Seems like a bad idea.
"""
# import email.message
#
#
# class EmailMessage(email.message.EmailMessage):
#     def __init__(self):
#         super().__init__()
#
#     @staticmethod
#     def from_bytes(b):
#
