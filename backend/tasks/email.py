# backend/tasks/email.py
from emails import Message

def send_welcome_email(email: str):
    message = Message(
        html="<h1>Welcome to our service!</h1>",
        subject="Registration Successful",
        mail_from="noreply@example.com"
    )
    # Configure with real SMTP in production
    message.send(to=email, smtp={"host": "localhost", "port": 1025})