from flask import Flask

from config import Config
from extensions import db

app = Flask(__name__)

app.config.from_object(Config)

db.init_app(app)

with app.app_context():
    from models import (
        User,
        Company,
        Student,
        PlacementDrive,
        Application,
        Placement
    )

    db.create_all()


@app.route("/")
def home():
    return "Placement Portal Backend Running Successfully!"


if __name__ == "__main__":
    app.run(debug=True)