import smtplib
from email.message import EmailMessage

class NotificationService:
    def __init__(self, bot_client, smtp_config):
        self.bot = bot_client
        self.smtp = smtp_config

    def send_daily_telegram_digest(self, user_id: str, markdown_content: str):
        # Pushes lightweight Markdown directly to Telegram chat
        self.bot.send_message(chat_id=user_id, text=markdown_content, parse_mode="MarkdownV2")

    def send_periodic_email_statement(self, user_email: str, subject: str, pdf_path: str):
        # Routes heavy static documents via SMTP Email
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['To'] = user_email

        with open(pdf_path, 'rb') as f:
            file_data = f.read()
            msg.add_attachment(file_data, maintype='application', subtype='pdf', filename='PocketMunim_Statement.pdf')

        with smtplib.SMTP_SSL(self.smtp.host, self.smtp.port) as server:
            server.login(self.smtp.user, self.smtp.password)
            server.send_message(msg)
