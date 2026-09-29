import os


class Config:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))

    SECRET_KEY = os.environ.get("SECRET_KEY", "placement-portal-secret-key")

    # Detect Vercel / serverless environment (read-only filesystem)
    IS_VERCEL = os.environ.get("VERCEL") == "1" or os.environ.get("VERCEL_ENV") is not None
    if IS_VERCEL:
        DB_PATH = "/tmp/placement_portal.db"
    else:
        DB_PATH = os.path.join(BASE_DIR, "placement_portal.db")

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECURITY_PASSWORD_SALT = os.environ.get("SECURITY_PASSWORD_SALT", "placement-portal-salt")
    SECURITY_REGISTER_BLUEPRINT = False

    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "True") == "True"

    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "ssnarayankhedkar@gmail.com")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "YOUR_GMAIL_APP_PASSWORD_HERE")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "ssnarayankhedkar@gmail.com")