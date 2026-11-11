import html as html_lib
import os
import re
import smtplib
import dotenv

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_URL = re.compile(r"https?://[^\s<]+")


def plain_and_html(marked):
    """A plain-text body and its HTML twin, from one text.

    ``**...**`` marks bold. The plain body drops the markers. The HTML body
    bolds the marked spans and links its URLs; blank lines separate
    paragraphs, a wrapped line joins the one before it so the client reflows
    it, and an indented line (a link, a citation, a signature) keeps a line
    of its own. The two always say the same thing, and a client that shows
    only the plain text loses nothing but the emphasis.
    """
    plain = _BOLD.sub(r"\1", marked)
    body = html_lib.escape(marked.strip("\n"), quote=False)
    paragraphs = []
    for block in re.split(r"\n[ \t]*\n", body):
        lines = []
        for line in block.split("\n"):
            if lines and not line[:1].isspace():
                lines[-1] += " " + line
            else:
                lines.append(line)
        paragraphs.append("<br>\n".join(lines))
    body = "\n".join(f"<p>{p}</p>" for p in paragraphs)
    body = _BOLD.sub(r"<strong>\1</strong>", body)
    body = _URL.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', body)
    body = body.replace("\t", "&nbsp;" * 4)
    body = re.sub(r"(<br>\n|<p>)( +)", lambda m: m.group(1) + "&nbsp;" * len(m.group(2)), body)
    html = (
        "<html><body>"
        '<div style="font-family: Arial, Helvetica, sans-serif; font-size: 14px; line-height: 1.5;">'
        f"{body}</div></body></html>"
    )
    return plain, html


class GeoEmail:
    """used for sending emails within geo framework"""

    def __init__(self):
        # TODO: this should be refactored to use a more secure method of storing email password
        dotenv.load_dotenv()
        self.email_pw = os.getenv("EMAIL_PASSWORD")

        self.defaults = {
            "reply_to": "AidData GeoQuery <geo@aiddata.wm.edu>",
            "sender": "noreply@aiddata.wm.edu",
        }

    def send_email(
        self, receiver, subject, message, sender=None, reply_to=None, passwd=None, html=None
    ):
        """send an email

        Args:
            receiver (str): email address to send to
            subject (str): subject of email
            message (str): body of email (plain text)
            html (str, optional): HTML version of the same body. Sent as a
                multipart/alternative with ``message`` as the fallback for
                clients that do not show HTML.

        Returns:
            (tuple): status, error message, exception
            status is bool
            error message and exception are None on success
        """
        receiver_list = [i.strip() for i in receiver.split(",")]
        receiver_str = ", ".join(receiver_list)

        if sender is None:
            sender = self.defaults["sender"]
        if reply_to is None:
            reply_to = self.defaults["reply_to"]

        try:
            # source:
            # http://stackoverflow.com/questions/64505/
            #   sending-mail-from-python-using-smtp

            msg = self.build_message(receiver_str, subject, message, reply_to, html)

            mailserver = smtplib.SMTP("smtp.gmail.com", 587)
            # identify ourselves to smtp gmail client
            mailserver.ehlo()
            # secure our email with tls encryption
            mailserver.starttls()
            # re-identify ourselves as an encrypted connection
            mailserver.ehlo()

            if not self.email_pw:
                raise ValueError("EMAIL_PASSWORD environment variable is not set")
            mailserver.login(sender, self.email_pw)
            mailserver.sendmail(sender, receiver_list, msg.as_string())
            mailserver.quit()

            return 1, None, None

        except Exception as e:
            return 0, "Error sending email", e

    @staticmethod
    def build_message(receiver_str, subject, message, reply_to, html=None):
        """The MIME message: plain text alone, or plain then HTML as alternatives.

        Clients show the last alternative they can render, so the HTML goes
        last and the plain text is what a text-only client falls back to.
        """
        msg = MIMEMultipart("alternative") if html else MIMEMultipart()
        msg.add_header("reply-to", reply_to)
        msg["From"] = reply_to
        msg["To"] = receiver_str
        msg["Subject"] = subject
        msg.attach(MIMEText(message, "plain", "utf-8") if html else MIMEText(message))
        if html:
            msg.attach(MIMEText(html, "html", "utf-8"))
        return msg

    def send_backup_email(
        self, receiver, subject, message, sender=None, reply_to=None, passwd=None
    ):
        """send an email using alternative method

        Args:
            receiver (str): email address to send to
            subject (str): subject of email
            message (str): body of email

        Returns:
            (tuple): status, error message, exception
            status is bool
            error message and exception are None on success
        """

        if sender is None:
            sender = self.defaults["sender"]
        if reply_to is None:
            reply_to = self.defaults["reply_to"]

        try:
            # source:
            # http://effbot.org/pyfaq/how-do-i-send-mail-from-a-python-script.htm
            FROM = reply_to

            MAIN = [receiver]
            CC = []
            BCC = []
            # who it is going to, main, cc, bcc
            # must be a list
            TO = MAIN + CC + BCC

            # Prepare actual message
            message = """\
            From: %s
            To: %s
            CC: %s
            Subject: %s

            %s
            """ % (FROM, ", ".join(MAIN), ", ".join(CC), subject, message)

            # Send the mail
            SERVER = "localhost"
            server = smtplib.SMTP(SERVER)
            server.sendmail(FROM, TO, message)
            server.quit()

            return 1, None, None

        except Exception as e:
            return 0, "Error sending backup email", e
