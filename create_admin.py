from app import app
from extensions import db
from models import User

with app.app_context():

    admin = User.query.filter_by(role="Admin").first()

    if admin:
        print("Admin user already exists.")
    else:
        admin = User(
            email="admin@placement.com",
            password_hash="admin123",   # Will hash later in Milestone 2
            role="Admin",
            is_active=True
        )

        db.session.add(admin)
        db.session.commit()

        print("Admin user created successfully.")