import os


class Config:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))

    SECRET_KEY = "placement-portal-secret-key"

    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "placement_portal.db")

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECURITY_PASSWORD_SALT = "placement-portal-salt"
    SECURITY_REGISTER_BLUEPRINT = False

    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "True") == "True"
    
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "ssnarayankhedkar@gmail.com")
    
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "YOUR_GMAIL_APP_PASSWORD_HERE")
    
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "ssnarayankhedkar@gmail.com")