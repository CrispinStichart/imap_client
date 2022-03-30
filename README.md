# Abandoned

So yeah, after spending a lot of time on this, the dismal state of Python packaging annoyed me *so much* I went and learned Rust and rewrote it. Check it out here:

https://github.com/CrispinStichart/email-liberator


# Filter Your Mail However You Want

Have you ever tried to set up automatic filtering in Gmail, only to be disappointed by the lack of features? Then this program *might* be for you!

In a nutshell, this is a bare-bones mail client that supports IMAP. It's intended to run 24/7 on a server or a pi or whatever. Whenever someone sends you an email, this program immediately downloads it and runs it through whatever filters you have set up.

These filters are python scripts written by yourself, so they can do whatever you can imagine.

## Current State

You could use this, I guess. It's technically functional.

It's a bit hacky, and there aren't any tests yet. *I'm* not using it yet, so I can't imagine anyone else would want to...

## How To Install

Packaging python apps is a pain. Honestly, I haven't done it enough times to know what the absolute best way is. For now, if for some reason you actually want to run this, you should...

* Make sure you have Python 3.8 or later installed
  * 3.8 is required, because I love me some [walrus operators](https://www.python.org/dev/peps/pep-0572/)
* Download this repo
* Set up a `venv`
  * not strictly necessary, but `venv`s help keep things tidy
  * `python3 -m venv env`
    * `env` is the name of the folder to be created in the current working directory
    * run `source env/bin/activate` under Linux, or `.\env\Scripts\activate` if you're using Windows
* run `pip install -r requirements.txt`
* run `python -m imap_filter_client.imap_filter_client`

That'll all probably work. I haven't double-checked any of those commands because let's be honest, no one is reading this README, and anyone who is probably doesn't need my help.

## How To Configure

In `src/imap_filter_client/`, you'll find `imap_filter.conf.template`. Rename it to remove the `.template` and edit it with your login info. If you don't like the idea of saving your password to a text file, comment out the `password` line, and you'll be prompted at runtime to enter your password.

You can also use the `--host`, `--username`, and `--password` options on the command line to specify those parameters.

Fun fact: Google lets you create "app passwords" that are randomly generated, can be restricted to only accessing one service (e.g. Gmail), and can be revoked at any time. Pretty neat.

https://support.google.com/accounts/answer/185833?hl=en

## How To Write Filters

Create python file under `src/imap_filter_client/filters/`. At minimum, you need the following:

```python
from . import mail_filter
from email.message import EmailMessage
from ..imap_filter_client import Envelope
from imapclient import IMAPClient

class MyFilter(mail_filter.Filter):
    def filter(self, msg_uid: int, msg: EmailMessage, envelope: Envelope, client: IMAPClient) -> bool:
        pass
```

If a filter returns `True`, no further filters will be run on that message. 

`client` is an authenticated client; see the `imapclient` documentation for how to use it.

There's an example filter included (`political_spam.py`, but at the time of the writing it doesn't actually do anything.


# What's Next

After spending five hours trying to figure why relative imports weren't working, and the answer turning out to be related to the magical way python loads packages, I have developed a strong urge to redo this whole program in Rust.
  
Assuming I don't rewrite it in rust, I need to:

* ~~make it easier for the filters to talk to the server~~
* ~~make a custom class for the email message object~~
  * ~~or just pass the envelope data as a separate object, I somehow only thought of that as I'm writing this <_<~~
* package this program better
  * maybe try out Flit or Poetry
* write tests or something