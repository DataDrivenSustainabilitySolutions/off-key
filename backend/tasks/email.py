import os
from emails import Message


def send_welcome_email(email: str):
    if os.getenv("ENVIRONMENT") == "production":
        # Real SMTP configuration
        message = Message(
            html="<h1>Welcome to our service!</h1>",
            subject="Registration Successful",
            mail_from=os.getenv("SMTP_FROM"),
        )
        message.send(
            to=email,
            smtp={
                "host": os.getenv("SMTP_HOST"),
                "port": os.getenv("SMTP_PORT"),
                "user": os.getenv("SMTP_USER"),
                "password": os.getenv("SMTP_PASSWORD"),
                "ssl": True,
            },
        )
    else:
        # Just print in development
        print(f"Mock email sent to {email}")
