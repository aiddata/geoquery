import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from gqcore import get_config

class GeoEmail():
    """used for sending emails within geo framework
    """
    def __init__(self):

        self.config = get_config()


    def get_passwd(self, sender):
        try:

            passwd = self.config["email"]["password"]
            return passwd
        except Exception as e:
            raise Exception("Error getting email env var", e)


    def send_email(self, receiver, subject, message, sender=None, reply_to=None, passwd=None):
        """send an email

        Args:
            receiver (str): email address to send to
            subject (str): subject of email
            message (str): body of email

        Returns:
            (tuple): status, error message, exception
            status is bool
            error message and exception are None on success
        """
        receiver_list = [i.strip() for i in receiver.split(",")]
        receiver_str = ", ".join(receiver_list)

        if sender is None:
            sender = self.config["email"]["sender"]
        if reply_to is None:
            reply_to = self.config["email"]["reply_to"]
        if passwd is None:
            passwd = self.get_passwd(sender)
        try:
            # source:
            # http://stackoverflow.com/questions/64505/
            #   sending-mail-from-python-using-smtp

            msg = MIMEMultipart()

            msg.add_header('reply-to', reply_to)
            msg['From'] = reply_to
            msg['To'] = receiver_str
            msg['Subject'] = subject
            msg.attach(MIMEText(message))

            mailserver = smtplib.SMTP(self.config["email"]["server"], self.config["email"]["port"])
            # identify ourselves to smtp gmail client
            mailserver.ehlo()
            # secure our email with tls encryption
            mailserver.starttls()
            # re-identify ourselves as an encrypted connection
            mailserver.ehlo()

            mailserver.login(sender, passwd)
            mailserver.sendmail(sender, receiver_list, msg.as_string())
            mailserver.quit()

            return 1, None, None

        except Exception as e:
            return 0, "Error sending email", e


    def send_backup_email(self, receiver, subject, message, sender=None, reply_to=None, passwd=None):
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
            sender = self.defaults['sender']
        if reply_to is None:
            reply_to = self.defaults['reply_to']

        try:

            # source:
            # http://effbot.org/pyfaq/how-do-i-send-mail-from-a-python-script.htm
            FROM = reply_to

            MAIN = [receiver]
            CC = []
            BCC = []
            # who it is going to, main, cc, bcc
            # must be a list
            TO = MAIN + CC +  BCC

            # Prepare actual message
            message = """\
            From: %s
            To: %s
            CC: %s
            Subject: %s

            %s
            """ % (FROM, ', '.join(MAIN), ', '.join(CC), subject, message)

            # Send the mail
            SERVER = self.config["email"]["backup_server"]
            server = smtplib.SMTP(SERVER)
            server.sendmail(FROM, TO, message)
            server.quit()

            return 1, None, None

        except Exception as e:
            return 0, "Error sending backup email", e
