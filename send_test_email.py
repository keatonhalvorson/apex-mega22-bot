#!/usr/bin/env python3
"""
Example Script
Demonstrates how to use the GmailSender class to send a beautiful HTML email.
"""

import os
from gmail_sender import GmailSender

def main():
    # 1. Retrieve credentials from environment variables (recommended) or replace placeholders
    # In practice, you can run: export SENDER_EMAIL="your_email@gmail.com" GMAIL_APP_PASSWORD="your_16_char_password"
    sender_email = os.environ.get("SENDER_EMAIL")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient_email = os.environ.get("RECIPIENT_EMAIL")

    if not sender_email or not app_password or not recipient_email:
        print("[!] Missing environment variables.")
        print("Please enter them manually to run this test:")
        sender_email = input("Your Gmail address: ").strip()
        app_password = input("Your Gmail App Password (16 chars): ").strip()
        recipient_email = input("Recipient email address: ").strip()

    if not sender_email or not app_password or not recipient_email:
        print("[-] Verification failed: All inputs are required.")
        return

    # 2. Instantiate the GmailSender
    sender = GmailSender(sender_email, app_password)

    # 3. Define a beautiful HTML email body
    html_body = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: #f4f6f9;
                margin: 0;
                padding: 0;
            }
            .container {
                max-width: 600px;
                margin: 40px auto;
                background: #ffffff;
                border-radius: 12px;
                box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
                overflow: hidden;
                border: 1px solid #e1e8ed;
            }
            .header {
                background: linear-gradient(135deg, #4f46e5, #06b6d4);
                color: #ffffff;
                padding: 40px 20px;
                text-align: center;
            }
            .header h1 {
                margin: 0;
                font-size: 26px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            .content {
                padding: 30px 40px;
                color: #334155;
                line-height: 1.6;
            }
            .content p {
                font-size: 16px;
                margin-bottom: 20px;
            }
            .btn-container {
                text-align: center;
                margin: 30px 0;
            }
            .btn {
                background-color: #4f46e5;
                color: #ffffff !important;
                text-decoration: none;
                padding: 12px 30px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 16px;
                display: inline-block;
                box-shadow: 0 4px 6px -1px rgba(79, 70, 229, 0.2);
            }
            .footer {
                background-color: #f8fafc;
                text-align: center;
                padding: 20px;
                font-size: 13px;
                color: #64748b;
                border-top: 1px solid #f1f5f9;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>تم إرسال بريد بنجاح! 🎉</h1>
            </div>
            <div class="content">
                <p>مرحباً بك،</p>
                <p>تم إرسال هذه الرسالة الجميلة والمنسقة باستخدام كود بايثون عبر خادم Gmail SMTP بنجاح.</p>
                <p>يمكنك استخدام هذا النموذج لإرسال تقارير، إشعارات، أو ملفات كمرفقات بسهولة.</p>
                <div class="btn-container">
                    <a href="https://github.com" class="btn">زيارة GitHub</a>
                </div>
            </div>
            <div class="footer">
                هذه الرسالة تم إنشاؤها تلقائياً بواسطة أداة Gmail Sender Utility.
            </div>
        </div>
    </body>
    </html>
    """

    # 4. Send the email
    print("\n[*] Sending test HTML email...")
    success = sender.send_email(
        to_emails=recipient_email,
        subject="تجربة إرسال بريد إلكتروني جميل من Python 💌",
        body=html_body,
        is_html=True
    )

    if success:
        print("[+] Test completed successfully!")
    else:
        print("[-] Test failed.")

if __name__ == "__main__":
    main()
