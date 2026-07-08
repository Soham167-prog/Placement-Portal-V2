import os


class Config:
    # Base directory of the project
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))

    # Secret key (used later for sessions/JWT)
    SECRET_KEY = "placement-portal-secret-key"

    # SQLite Database
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "placement_portal.db")

    # Disable modification tracking
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECURITY_PASSWORD_SALT = "placement-portal-salt"
    SECURITY_REGISTER_BLUEPRINT = False