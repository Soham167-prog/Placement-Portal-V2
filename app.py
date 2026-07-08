from flask import Flask, render_template, request, jsonify, redirect
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_security import SQLAlchemyUserDatastore, auth_required, current_user, login_user, logout_user
from flask_cors import CORS
from config import Config
from extensions import db, security
from models import User, Role, Company, Student, PlacementDrive, Application

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

@app.before_request
def handle_inactive_user_session():
    if current_user and current_user.is_authenticated and not current_user.is_active:
        logout_user()

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/admin-login")
def admin_login_page():
    return render_template("admin/login.html")

@app.route("/student-login")
def student_login_page():
    return render_template("student/login.html")

@app.route("/student-register")
def student_register_page():
    return render_template("student/register.html")

@app.route("/company-login")
def company_login_page():
    return render_template("company/login.html")

@app.route("/company-register")
def company_register_page():
    return render_template("company/register.html")

@app.route("/admin/dashboard")
@auth_required()
def admin_dashboard_page():
    if current_user.role != "Admin":
        return redirect("/")
    return render_template("admin/dashboard.html")

@app.route("/student/dashboard")
@auth_required()
def student_dashboard_page():
    if current_user.role != "Student":
        return redirect("/")
    return render_template("student/dashboard.html")

@app.route("/company/dashboard")
@auth_required()
def company_dashboard_page():
    if current_user.role != "Company":
        return redirect("/")
    company = Company.query.filter_by(user_id=current_user.id).first()
    if not company or company.approval_status != "Approved" or company.is_blacklisted:
        logout_user()
        return redirect("/company-login")
    return render_template("company/dashboard.html")

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
    existing_user = User.query.filter_by(email=data["email"]).first()
    if existing_user:
        student_profile = Student.query.filter_by(user_id=existing_user.id).first()
        if student_profile and student_profile.is_blacklisted:
            return jsonify({"message": "This student account is blacklisted and cannot register again."}), 403
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
    existing_user = User.query.filter_by(email=data["email"]).first()
    if existing_user:
        company_profile = Company.query.filter_by(user_id=existing_user.id).first()
        if company_profile and company_profile.is_blacklisted:
            return jsonify({"message": "This company account is blacklisted and cannot register again."}), 403
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

# ================= ADMIN MANAGEMENT APIS =================

@app.route("/api/admin/stats", methods=["GET"])
@auth_required()
def admin_stats():
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
        
    active_students_count = Student.query.filter_by(is_blacklisted=False).count()
    blacklisted_students_count = Student.query.filter_by(is_blacklisted=True).count()
    
    active_companies_count = Company.query.filter_by(is_blacklisted=False, approval_status="Approved").count()
    pending_companies_count = Company.query.filter_by(approval_status="Pending").count()
    blacklisted_companies_count = Company.query.filter_by(is_blacklisted=True).count()
    
    approved_drives_count = PlacementDrive.query.filter_by(status="Approved").count()
    pending_drives_count = PlacementDrive.query.filter_by(status="Pending").count()
    rejected_drives_count = PlacementDrive.query.filter_by(status="Rejected").count()
    
    total_applications_count = Application.query.count()
    rejected_applications_count = Application.query.filter_by(status="Rejected").count()

    return jsonify({
        "active_students_count": active_students_count,
        "blacklisted_students_count": blacklisted_students_count,
        "active_companies_count": active_companies_count,
        "pending_companies_count": pending_companies_count,
        "blacklisted_companies_count": blacklisted_companies_count,
        "approved_drives_count": approved_drives_count,
        "pending_drives_count": pending_drives_count,
        "rejected_drives_count": rejected_drives_count,
        "total_applications_count": total_applications_count,
        "rejected_applications_count": rejected_applications_count
    })

@app.route("/api/admin/students", methods=["GET"])
@auth_required()
def admin_list_students():
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    
    query = Student.query
    search_val = request.args.get("query")
    
    if search_val:
        conditions = [
            Student.full_name.ilike(f"%{search_val}%"),
            Student.phone.ilike(f"%{search_val}%"),
            User.email.ilike(f"%{search_val}%")
        ]
        if search_val.isdigit():
            conditions.append(Student.student_id == int(search_val))
            conditions.append(Student.graduation_year == int(search_val))
        
        query = query.join(User).filter(db.or_(*conditions))
        
    students = query.all()
    res = []
    for s in students:
        res.append({
            "student_id": s.student_id,
            "email": s.user.email,
            "full_name": s.full_name,
            "phone": s.phone,
            "branch": s.branch,
            "cgpa": s.cgpa,
            "graduation_year": s.graduation_year,
            "skills": s.skills,
            "experience": s.experience,
            "is_blacklisted": s.is_blacklisted,
            "is_active": s.user.is_active
        })
    return jsonify(res)

@app.route("/api/admin/students/<int:student_id>/toggle-blacklist", methods=["POST"])
@auth_required()
def admin_toggle_student_blacklist(student_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    student = Student.query.get_or_404(student_id)
    if student.is_blacklisted:
        return jsonify({"message": "Blacklist status is permanent and cannot be undone."}), 400
    student.is_blacklisted = True
    student.user.is_active = False
    db.session.commit()
    return jsonify({
        "message": "Student blacklisted permanently.",
        "is_blacklisted": True,
        "is_active": False
    })

@app.route("/api/admin/students/<int:student_id>", methods=["DELETE"])
@auth_required()
def admin_remove_student(student_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    student = Student.query.get_or_404(student_id)
    user = student.user
    db.session.delete(student)
    db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "Student profile removed successfully."})

@app.route("/api/admin/companies", methods=["GET"])
@auth_required()
def admin_list_companies():
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
        
    query = Company.query
    search_val = request.args.get("query")
    
    if search_val:
        conditions = [
            Company.company_name.ilike(f"%{search_val}%"),
            Company.industry.ilike(f"%{search_val}%")
        ]
        query = query.filter(db.or_(*conditions))
        
    companies = query.all()
    res = []
    for c in companies:
        res.append({
            "company_id": c.company_id,
            "email": c.user.email,
            "company_name": c.company_name,
            "hr_contact": c.hr_contact,
            "website": c.website,
            "approval_status": c.approval_status,
            "industry": c.industry,
            "location": c.location,
            "description": c.description,
            "is_blacklisted": c.is_blacklisted,
            "is_active": c.user.is_active
        })
    return jsonify(res)

@app.route("/api/admin/companies/<int:company_id>/approve", methods=["POST"])
@auth_required()
def admin_approve_company(company_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    company = Company.query.get_or_404(company_id)
    company.approval_status = "Approved"
    db.session.commit()
    return jsonify({"message": "Company approved.", "approval_status": "Approved"})

@app.route("/api/admin/companies/<int:company_id>/reject", methods=["POST"])
@auth_required()
def admin_reject_company(company_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    company = Company.query.get_or_404(company_id)
    company.approval_status = "Rejected"
    db.session.commit()
    return jsonify({"message": "Company rejected.", "approval_status": "Rejected"})

@app.route("/api/admin/companies/<int:company_id>/toggle-blacklist", methods=["POST"])
@auth_required()
def admin_toggle_company_blacklist(company_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    company = Company.query.get_or_404(company_id)
    if company.is_blacklisted:
        return jsonify({"message": "Blacklist status is permanent and cannot be undone."}), 400
    company.is_blacklisted = True
    company.user.is_active = False
    db.session.commit()
    return jsonify({
        "message": "Company blacklisted permanently.",
        "is_blacklisted": True,
        "is_active": False
    })

@app.route("/api/admin/companies/<int:company_id>", methods=["DELETE"])
@auth_required()
def admin_remove_company(company_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    company = Company.query.get_or_404(company_id)
    user = company.user
    db.session.delete(company)
    db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "Company removed successfully."})

@app.route("/api/admin/drives", methods=["GET"])
@auth_required()
def admin_list_drives():
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    drives = PlacementDrive.query.all()
    res = []
    for d in drives:
        res.append({
            "drive_id": d.drive_id,
            "company_name": d.company.company_name,
            "job_title": d.job_title,
            "job_description": d.job_description,
            "eligibility_criteria": d.eligibility_criteria,
            "application_deadline": d.application_deadline.strftime("%Y-%m-%d") if d.application_deadline else None,
            "status": d.status,
            "salary": d.salary,
            "location": d.location,
            "skills_required": d.skills_required,
            "benefits": d.benefits,
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M:%S")
        })
    return jsonify(res)

@app.route("/api/admin/drives/<int:drive_id>/approve", methods=["POST"])
@auth_required()
def admin_approve_drive(drive_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    drive = PlacementDrive.query.get_or_404(drive_id)
    drive.status = "Approved"
    db.session.commit()
    return jsonify({"message": "Placement drive approved.", "status": "Approved"})

@app.route("/api/admin/drives/<int:drive_id>/reject", methods=["POST"])
@auth_required()
def admin_reject_drive(drive_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    drive = PlacementDrive.query.get_or_404(drive_id)
    drive.status = "Rejected"
    db.session.commit()
    return jsonify({"message": "Placement drive rejected.", "status": "Rejected"})

@app.route("/api/admin/drives/<int:drive_id>", methods=["DELETE"])
@auth_required()
def admin_remove_drive(drive_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    drive = PlacementDrive.query.get_or_404(drive_id)
    db.session.delete(drive)
    db.session.commit()
    return jsonify({"message": "Placement drive removed successfully."})

@app.route("/api/admin/applications", methods=["GET"])
@auth_required()
def admin_list_applications():
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    apps = Application.query.all()
    res = []
    for a in apps:
        res.append({
            "application_id": a.application_id,
            "student_name": a.student.full_name,
            "student_email": a.student.user.email,
            "company_name": a.placement_drive.company.company_name,
            "job_title": a.placement_drive.job_title,
            "drive_id": a.drive_id,
            "application_date": a.application_date.strftime("%Y-%m-%d %H:%M:%S") if a.application_date else None,
            "status": a.status,
            "feedback": a.feedback,
            "interview_date": a.interview_date.strftime("%Y-%m-%d %H:%M:%S") if a.interview_date else None
        })
    return jsonify(res)

@app.route("/api/admin/applications/<int:app_id>", methods=["DELETE"])
@auth_required()
def admin_remove_application(app_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    appln = Application.query.get_or_404(app_id)
    db.session.delete(appln)
    db.session.commit()
    return jsonify({"message": "Application removed successfully."})

# ================= COMPANY PORTAL APIS =================

@app.route("/api/company/stats", methods=["GET"])
@auth_required()
def company_stats():
    if current_user.role != "Company":
        return jsonify({"message": "Unauthorized"}), 403
    
    company = Company.query.filter_by(user_id=current_user.id).first()
    if not company:
        return jsonify({"message": "Company profile not found"}), 404
        
    drives_count = PlacementDrive.query.filter_by(company_id=company.company_id).count()
    
    # Received applications count across all company drives
    drive_ids = [d.drive_id for d in PlacementDrive.query.filter_by(company_id=company.company_id).all()]
    applications_count = Application.query.filter(Application.drive_id.in_(drive_ids)).count() if drive_ids else 0
    
    # Shortlisted candidates count across all company drives
    shortlisted_count = Application.query.filter(
        Application.drive_id.in_(drive_ids),
        Application.status == "Shortlisted"
    ).count() if drive_ids else 0
    
    return jsonify({
        "drives_count": drives_count,
        "applications_count": applications_count,
        "shortlisted_count": shortlisted_count
    })

@app.route("/api/company/drives", methods=["GET", "POST"])
@auth_required()
def company_drives():
    if current_user.role != "Company":
        return jsonify({"message": "Unauthorized"}), 403
        
    company = Company.query.filter_by(user_id=current_user.id).first()
    if not company:
        return jsonify({"message": "Company profile not found"}), 404

    if request.method == "POST":
        data = request.get_json()
        job_title = data.get("job_title")
        if not job_title:
            return jsonify({"message": "Job title is required."}), 400
            
        deadline = None
        if data.get("application_deadline"):
            try:
                deadline = datetime.strptime(data.get("application_deadline"), "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"message": "Invalid date format for deadline. Use YYYY-MM-DD"}), 400

        drive = PlacementDrive(
            company_id=company.company_id,
            job_title=job_title,
            job_description=data.get("job_description"),
            eligibility_criteria=data.get("eligibility_criteria"),
            application_deadline=deadline,
            salary=data.get("salary"),
            location=data.get("location"),
            skills_required=data.get("skills_required"),
            benefits=data.get("benefits"),
            status="Pending"  # Requires Admin Approval
        )
        db.session.add(drive)
        db.session.commit()
        return jsonify({"message": "Placement drive posted successfully. Awaiting Admin approval.", "drive_id": drive.drive_id}), 201

    # GET method
    drives = PlacementDrive.query.filter_by(company_id=company.company_id).all()
    res = []
    for d in drives:
        res.append({
            "drive_id": d.drive_id,
            "job_title": d.job_title,
            "job_description": d.job_description,
            "eligibility_criteria": d.eligibility_criteria,
            "application_deadline": d.application_deadline.strftime("%Y-%m-%d") if d.application_deadline else None,
            "status": d.status,
            "salary": d.salary,
            "location": d.location,
            "skills_required": d.skills_required,
            "benefits": d.benefits
        })
    return jsonify(res)

@app.route("/api/company/drives/<int:drive_id>/toggle-status", methods=["POST"])
@auth_required()
def company_toggle_drive_status(drive_id):
    if current_user.role != "Company":
        return jsonify({"message": "Unauthorized"}), 403
        
    company = Company.query.filter_by(user_id=current_user.id).first()
    if not company:
        return jsonify({"message": "Company profile not found"}), 404
        
    drive = PlacementDrive.query.filter_by(drive_id=drive_id, company_id=company.company_id).first_or_404()
    
    # Can only manage if approved/active/closed
    if drive.status not in ["Approved", "Active", "Closed"]:
        return jsonify({"message": "Drive status cannot be toggled because it is not approved by the administrator."}), 400
        
    if drive.status == "Closed":
        drive.status = "Active"
    else:
        drive.status = "Closed"
        
    db.session.commit()
    return jsonify({"message": f"Drive status updated to {drive.status}.", "status": drive.status})

@app.route("/api/company/applications", methods=["GET"])
@auth_required()
def company_applications():
    if current_user.role != "Company":
        return jsonify({"message": "Unauthorized"}), 403
        
    company = Company.query.filter_by(user_id=current_user.id).first()
    if not company:
        return jsonify({"message": "Company profile not found"}), 404
        
    drive_ids = [d.drive_id for d in PlacementDrive.query.filter_by(company_id=company.company_id).all()]
    if not drive_ids:
        return jsonify([])
        
    apps = Application.query.filter(Application.drive_id.in_(drive_ids)).all()
    res = []
    for a in apps:
        res.append({
            "application_id": a.application_id,
            "job_title": a.placement_drive.job_title,
            "drive_id": a.drive_id,
            "student_id": a.student_id,
            "student_name": a.student.full_name,
            "student_email": a.student.user.email,
            "student_phone": a.student.phone,
            "student_branch": a.student.branch,
            "student_cgpa": a.student.cgpa,
            "student_skills": a.student.skills,
            "student_experience": a.student.experience,
            "status": a.status,
            "feedback": a.feedback,
            "interview_date": a.interview_date.strftime("%Y-%m-%d %H:%M") if a.interview_date else None,
            "application_date": a.application_date.strftime("%Y-%m-%d %H:%M") if a.application_date else None
        })
    return jsonify(res)

@app.route("/api/company/applications/<int:app_id>/status", methods=["POST"])
@auth_required()
def company_update_application_status(app_id):
    if current_user.role != "Company":
        return jsonify({"message": "Unauthorized"}), 403
        
    company = Company.query.filter_by(user_id=current_user.id).first()
    if not company:
        return jsonify({"message": "Company profile not found"}), 404
        
    appln = Application.query.get_or_404(app_id)
    if appln.placement_drive.company_id != company.company_id:
        return jsonify({"message": "Access denied"}), 403
        
    data = request.get_json()
    new_status = data.get("status")
    if new_status not in ["Shortlisted", "Selected", "Rejected"]:
        return jsonify({"message": "Invalid application status. Use Shortlisted, Selected, or Rejected."}), 400
        
    appln.status = new_status
    if "feedback" in data:
        appln.feedback = data.get("feedback")
        
    db.session.commit()
    return jsonify({
        "message": f"Application status updated to {new_status}.",
        "status": new_status,
        "feedback": appln.feedback
    })

@app.route("/api/company/applications/<int:app_id>/schedule-interview", methods=["POST"])
@auth_required()
def company_schedule_interview(app_id):
    if current_user.role != "Company":
        return jsonify({"message": "Unauthorized"}), 403
        
    company = Company.query.filter_by(user_id=current_user.id).first()
    if not company:
        return jsonify({"message": "Company profile not found"}), 404
        
    appln = Application.query.get_or_404(app_id)
    if appln.placement_drive.company_id != company.company_id:
        return jsonify({"message": "Access denied"}), 403
        
    data = request.get_json()
    date_str = data.get("interview_date")
    if not date_str:
        return jsonify({"message": "Interview date is required."}), 400
        
    try:
        # Expected format YYYY-MM-DDTHH:MM or YYYY-MM-DD HH:MM
        interview_dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M")
    except ValueError:
        try:
            interview_dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        except ValueError:
            return jsonify({"message": "Invalid date format. Use YYYY-MM-DD HH:MM"}), 400
            
    appln.interview_date = interview_dt
    db.session.commit()
    return jsonify({
        "message": "Interview scheduled successfully.",
        "interview_date": appln.interview_date.strftime("%Y-%m-%d %H:%M")
    })

if __name__ == "__main__":
    app.run(debug=True)