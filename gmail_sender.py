#!/usr/bin/env python3
"""
Gmail Sender Utility
Provides a reusable class and CLI interface for sending secure emails via Gmail SMTP.
"""

import os
import smtplib
import ssl
import mimetypes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

class GmailSender:
    """
    A utility class to send emails via Gmail SMTP using SSL/TLS.
    Requires a Gmail address and a Gmail App Password.
    """
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 465  # SSL port

    def __init__(self, sender_email: str, app_password: str):
        """
        Initializes the GmailSender with credentials.
        
        :param sender_email: Your Gmail address (e.g., user@gmail.com).
        :param app_password: Your 16-character Gmail App Password.
        """
        if not sender_email or not app_password:
            raise ValueError("Both sender_email and app_password must be provided.")
        
        self.sender_email = sender_email
        self.app_password = app_password

    def send_email(self, 
                   to_emails: list or str, 
                   subject: str, 
                   body: str, 
                   is_html: bool = False, 
                   attachments: list = None) -> bool:
        """
        Sends an email.
        
        :param to_emails: Recipient email address or a list of recipient addresses.
        :param subject: Email subject line.
        :param body: The message content (plain text or HTML).
        :param is_html: Set to True if the body is HTML formatted.
        :param attachments: List of file paths to attach to the email.
        :return: True if the email was sent successfully, False otherwise.
        """
        # Normalize recipients to a list
        if isinstance(to_emails, str):
            recipients = [to_emails]
        else:
            recipients = list(to_emails)

        # Create message container
        msg = MIMEMultipart()
        msg["From"] = self.sender_email
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject

        # Attach text or HTML body
        msg.attach(MIMEText(body, "html" if is_html else "plain"))

        # Process attachments
        if attachments:
            for filepath in attachments:
                if not os.path.exists(filepath):
                    print(f"[-] Attachment not found: {filepath}")
                    continue
                
                filename = os.path.basename(filepath)
                # Guess file mime type
                ctype, encoding = mimetypes.guess_type(filepath)
                if ctype is None or encoding is not None:
                    ctype = "application/octet-stream"
                
                maintype, subtype = ctype.split("/", 1)
                
                try:
                    with open(filepath, "rb") as f:
                        part = MIMEBase(maintype, subtype)
                        part.set_payload(f.read())
                    
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={filename}",
                    )
                    msg.attach(part)
                    print(f"[+] Attached: {filename}")
                except Exception as e:
                    print(f"[-] Failed to attach {filename}: {e}")

        # Send via SMTP SSL
        context = ssl.create_default_context()
        try:
            print(f"[*] Connecting to {self.SMTP_SERVER}:{self.SMTP_PORT}...")
            with smtplib.SMTP_SSL(self.SMTP_SERVER, self.SMTP_PORT, context=context) as server:
                server.login(self.sender_email, self.app_password)
                print("[+] Successfully logged in.")
                print(f"[*] Sending email to {len(recipients)} recipient(s)...")
                server.sendmail(self.sender_email, recipients, msg.as_string())
                print("[+] Email sent successfully!")
                return True
        except smtplib.SMTPAuthenticationError:
            print("[-] Authentication failed. Please verify your Gmail address and App Password.")
            print("    Make sure you are using an 'App Password', NOT your primary Google account password.")
            return False
        except Exception as e:
            print(f"[-] An error occurred while sending the email: {e}")
            return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Send emails using Gmail SMTP.")
    parser.add_argument("--sender", required=True, help="Sender Gmail address")
    parser.add_argument("--password", required=True, help="Gmail App Password")
    parser.add_argument("--to", required=True, nargs="+", help="Recipient email address(es)")
    parser.add_argument("--subject", required=True, help="Email subject")
    parser.add_argument("--body", required=True, help="Email body content")
    parser.add_argument("--html", action="store_true", help="Send email body as HTML")
    parser.add_argument("--attach", nargs="*", help="File path(s) to attach")
    
    args = parser.parse_args()
    
    sender = GmailSender(args.sender, args.password)
    sender.send_email(
        to_emails=args.to,
        subject=args.subject,
        body=args.body,
        is_html=args.html,
        attachments=args.attach
    )
