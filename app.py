from flask import Flask, render_template, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_security import SQLAlchemyUserDatastore, auth_required, current_user, login_user, logout_user
from flask_cors import CORS
from config import Config
from extensions import db, security
from models import User, Role, Company, Student

app = Flask(__name__)
app.config.from_object(Config)

# Enable CORS for development flexibility
CORS(app, supports_credentials=True)

db.init_app(app)

user_datastore = SQLAlchemyUserDatastore(db, User, Role)
security.init_app(app, user_datastore, register_blueprint=False)

# Custom unauthenticated handler for API requests
@security.unauthn_handler
def custom_unauth_handler(mechanisms, headers=None):
    return jsonify({"message": "Authentication required."}), 401

# Re-create database if the schema is outdated
with app.app_context():
    try:
        db.create_all()
        Role.query.first()
    except Exception:
        db.session.remove()
        db.drop_all()
        db.create_all()

@app.route("/")
def home():
    return render_template("index.html", start_view="home")

@app.route("/admin-login")
def admin_login_page():
    return render_template("index.html", start_view="admin-login")

@app.route("/api/current-user", methods=["GET"])
def get_current_user():
    if current_user.is_authenticated:
        return jsonify({
            "logged_in": True,
            "user": {
                "id": current_user.id,
                "email": current_user.email,
                "role": current_user.role
            }
        })
    return jsonify({"logged_in": False})

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data or not data.get("email") or not data.get("password"):
        return jsonify({"message": "Email and password are required."}), 400

    user = User.query.filter_by(email=data["email"]).first()
    if not user:
        return jsonify({"message": "Invalid Email"}), 401

    # Verify if the account role matches the portal role being accessed
    expected_role = data.get("role")
    if expected_role and user.role != expected_role:
        return jsonify({"message": f"This email is not registered as a {expected_role}."}), 403

    # Verify password with plain-text fallback (for create_admin.py credentials)
    password_valid = False
    if user.password_hash.startswith("pbkdf2:") or user.password_hash.startswith("scrypt:"):
        password_valid = check_password_hash(user.password_hash, data["password"])
    else:
        password_valid = (user.password_hash == data["password"])

    if not password_valid:
        return jsonify({"message": "Invalid Password"}), 401

    if not user.is_active:
        return jsonify({"message": "Account is inactive"}), 403

    # Check blacklist and approval statuses
    if user.role == "Student":
        student = Student.query.filter_by(user_id=user.id).first()
        if student and student.is_blacklisted:
            return jsonify({"message": "Your account has been blacklisted."}), 403
    elif user.role == "Company":
        company = Company.query.filter_by(user_id=user.id).first()
        if company:
            if company.is_blacklisted:
                return jsonify({"message": "Your company has been blacklisted."}), 403
            if company.approval_status == "Pending":
                return jsonify({"message": "Your company registration is pending approval."}), 403
            if company.approval_status == "Rejected":
                return jsonify({"message": "Your company registration has been rejected."}), 403

    # Sync roles with many-to-many relationship for Flask-Security decorator compatibility
    if user.role and not user.roles:
        r = Role.query.filter_by(name=user.role).first()
        if not r:
            r = Role(name=user.role)
            db.session.add(r)
        user.roles.append(r)
        db.session.commit()

    login_user(user)

    return jsonify({
        "message": "Login Successful",
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role
        }
    }), 200

@app.route("/register/student", methods=["POST"])
def register_student():
    data = request.get_json()
    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"message": "Email already registered"}), 400

    user = User(
        email=data["email"],
        password_hash=generate_password_hash(data["password"]),
        role="Student",
        is_active=True
    )
    
    # Sync Flask-Security role
    student_role = Role.query.filter_by(name="Student").first()
    if not student_role:
        student_role = Role(name="Student")
        db.session.add(student_role)
    user.roles.append(student_role)

    db.session.add(user)
    db.session.commit()

    student = Student(
        user_id=user.id,
        full_name=data["full_name"],
        phone=data.get("phone"),
        branch=data.get("branch"),
        cgpa=data.get("cgpa"),
        graduation_year=data.get("graduation_year"),
        skills=data.get("skills"),
        resume=data.get("resume", "default.pdf"),
        experience=data.get("experience")
    )
    db.session.add(student)
    db.session.commit()

    return jsonify({"message": "Student Registered Successfully"}), 201

@app.route("/register/company", methods=["POST"])
def register_company():
    data = request.get_json()
    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"message": "Email already registered"}), 400

    user = User(
        email=data["email"],
        password_hash=generate_password_hash(data["password"]),
        role="Company",
        is_active=True
    )
    
    # Sync Flask-Security role
    company_role = Role.query.filter_by(name="Company").first()
    if not company_role:
        company_role = Role(name="Company")
        db.session.add(company_role)
    user.roles.append(company_role)

    db.session.add(user)
    db.session.commit()

    company = Company(
        user_id=user.id,
        company_name=data["company_name"],
        hr_contact=data["hr_contact"],
        website=data.get("website"),
        industry=data.get("industry"),
        location=data.get("location"),
        description=data.get("description")
    )
    db.session.add(company)
    db.session.commit()

    return jsonify({"message": "Company Registered Successfully"}), 201

@app.route("/logout", methods=["POST", "GET"])
def logout():
    logout_user()
    return jsonify({"message": "Logout Successful"}), 200

# Dashboard stubs to verify authentication and role access
@app.route("/admin", methods=["GET"])
@auth_required()
def admin_dashboard():
    if current_user.role != "Admin":
        return jsonify({"message": "Unauthorized"}), 403
    return jsonify({"message": "Welcome Admin"})

@app.route("/student", methods=["GET"])
@auth_required()
def student_dashboard():
    if current_user.role != "Student":
        return jsonify({"message": "Unauthorized"}), 403
    return jsonify({"message": "Welcome Student"})

@app.route("/company", methods=["GET"])
@auth_required()
def company_dashboard():
    if current_user.role != "Company":
        return jsonify({"message": "Unauthorized"}), 403
    return jsonify({"message": "Welcome Company"})

if __name__ == "__main__":
    app.run(debug=True)