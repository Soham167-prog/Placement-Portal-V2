from flask import Flask, render_template, request, jsonify, redirect, send_file, send_from_directory
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_security import SQLAlchemyUserDatastore, auth_required, current_user, login_user, logout_user
from flask_cors import CORS
from config import Config
from extensions import db, security, redis_client
from models import User, Role, Company, Student, PlacementDrive, Application, Placement
import json
import os


def get_cached_response(key):
    try:
        data = redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        print(f"[Redis Cache] Read error for key {key}:", e)
    return None

def set_cached_response(key, data, timeout=300):
    try:
        redis_client.setex(key, timeout, json.dumps(data))
    except Exception as e:
        print(f"[Redis Cache] Write error for key {key}:", e)

def invalidate_cache_by_pattern(pattern):
    try:
        keys = redis_client.keys(pattern)
        if keys:
            redis_client.delete(*keys)
            print(f"[Redis Cache] Invalidated keys matching pattern: {pattern}")
    except Exception as e:
        print(f"[Redis Cache] Invalidation error for pattern {pattern}:", e)

def check_and_close_expired_drives():
    from models import PlacementDrive
    from datetime import datetime
    now = datetime.utcnow()
    expired_drives = PlacementDrive.query.filter(
        PlacementDrive.status.in_(["Approved", "Active"]),
        PlacementDrive.application_deadline < now
    ).all()
    if expired_drives:
        for d in expired_drives:
            d.status = "Closed"
        db.session.commit()
        invalidate_cache_by_pattern("student_drives:*")
        invalidate_cache_by_pattern("admin_stats_cache")
        for d in expired_drives:
            invalidate_cache_by_pattern(f"company_stats_cache:{d.company_id}")

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

VIVA_CREDENTIALS = {}
try:
    import viva_secrets
    VIVA_CREDENTIALS = getattr(viva_secrets, "CREDENTIALS", {})
except ImportError:
    pass

def send_email_notification(to_email, subject, body_text, sender_email=None, sender_name=None, attachment_path=None, attachment_filename=None):
    mail_server = app.config.get("MAIL_SERVER", "smtp.gmail.com")
    mail_port = app.config.get("MAIL_PORT", 587)
    
    mail_username = None
    mail_password = None
    
    if sender_email:
        from models import User
        sender_user = User.query.filter_by(email=sender_email).first()
        if sender_user and sender_user.smtp_app_password:
            mail_username = sender_user.email
            mail_password = sender_user.smtp_app_password
            
    if not mail_username or not mail_password:
        mail_username = app.config.get("MAIL_USERNAME", "your-email@gmail.com")
        mail_password = app.config.get("MAIL_PASSWORD", "YOUR_GMAIL_APP_PASSWORD_HERE")
        
    mail_sender = sender_email if sender_email else mail_username
        
    try:
        if attachment_path:
            msg = MIMEMultipart()
            msg['Subject'] = subject
            msg['To'] = to_email
            if sender_name:
                msg['From'] = f"{sender_name} <{mail_sender}>"
            else:
                msg['From'] = mail_sender
            
            msg.attach(MIMEText(body_text, 'plain'))
            
            with open(attachment_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={attachment_filename or 'Offer_Letter.pdf'}",
            )
            msg.attach(part)
        else:
            msg = MIMEText(body_text)
            msg['Subject'] = subject
            if sender_name:
                msg['From'] = f"{sender_name} <{mail_sender}>"
            else:
                msg['From'] = mail_sender
            msg['To'] = to_email
        
        server = smtplib.SMTP(mail_server, mail_port)
        server.starttls()
        server.login(mail_username, mail_password)
        server.sendmail(mail_sender, [to_email], msg.as_string())
        server.quit()
        print(f"[SMTP Email] Email successfully sent to {to_email} (From: {sender_name or 'System'} <{mail_sender}>)")
        return True
    except Exception as e:
        print(f"[SMTP Email] Failed to send email to {to_email}: {e}")
        return False

def generate_offer_letter_pdf(student_name, company_name, position, salary, joining_date_str, benefits, dest_path):
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    import datetime
    
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    
    doc = SimpleDocTemplate(dest_path, pagesize=letter,
                            rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54)
    story = []
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor('#312e81'),
        spaceAfter=15,
        alignment=1
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#4b5563'),
        spaceAfter=30,
        alignment=1
    )
    
    body_style = ParagraphStyle(
        'DocBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10.5,
        leading=16,
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=12
    )
    
    story.append(Paragraph("OFFER OF EMPLOYMENT", title_style))
    story.append(Paragraph(f"Issued by {company_name}", subtitle_style))
    story.append(Spacer(1, 15))
    
    date_today = datetime.date.today().strftime("%B %d, %Y")
    story.append(Paragraph(f"<b>Date:</b> {date_today}", body_style))
    story.append(Paragraph(f"<b>To:</b> {student_name}", body_style))
    story.append(Spacer(1, 10))
    
    story.append(Paragraph(
        f"Dear {student_name},<br/><br/>"
        f"On behalf of <b>{company_name}</b>, we are thrilled to offer you the position of "
        f"<b>{position}</b>. We were exceptionally impressed by your skills, qualifications, "
        f"and performance during our selection process.",
        body_style
    ))
    
    story.append(Paragraph(
        "Please find the summary of your employment terms below:",
        body_style
    ))
    story.append(Spacer(1, 10))
    
    data = [
        [Paragraph("<b>Job Title</b>", body_style), Paragraph(position, body_style)],
        [Paragraph("<b>Company</b>", body_style), Paragraph(company_name, body_style)],
        [Paragraph("<b>Salary Package</b>", body_style), Paragraph(f"{salary} LPA", body_style)],
        [Paragraph("<b>Joining Date</b>", body_style), Paragraph(joining_date_str, body_style)],
        [Paragraph("<b>Perks & Benefits</b>", body_style), Paragraph(benefits or "Standard corporate benefits package", body_style)]
    ]
    
    t = Table(data, colWidths=[130, 370])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f9fafb')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 12),
        ('RIGHTPADDING', (0,0), (-1,-1), 12),
    ]))
    story.append(t)
    story.append(Spacer(1, 20))
    
    story.append(Paragraph(
        "By accepting this offer, you agree to comply with the guidelines, codes of conduct, "
        "and regulations of the company. We look forward to welcoming you to our team and working "
        "together towards achieving great milestones.",
        body_style
    ))
    story.append(Spacer(1, 30))
    
    sig_data = [
        [Paragraph("_____________________________<br/><b>Authorized Signatory</b><br/>HR Department, " + company_name, body_style),
         Paragraph("_____________________________<br/><b>Candidate Acceptance</b><br/>" + student_name, body_style)]
    ]
    sig_table = Table(sig_data, colWidths=[250, 250])
    sig_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(sig_table)
    
    doc.build(story)

app = Flask(__name__)
app.config.from_object(Config)

CORS(app, supports_credentials=True)

db.init_app(app)

user_datastore = SQLAlchemyUserDatastore(db, User, Role)
security.init_app(app, user_datastore, register_blueprint=False)

def get_upload_dir(subfolder="resumes"):
    is_vercel = os.environ.get("VERCEL") == "1" or os.environ.get("VERCEL_ENV") is not None
    if is_vercel:
        path = os.path.join("/tmp", "uploads", subfolder)
    else:
        path = os.path.join(app.root_path, "static", "uploads", subfolder)
    os.makedirs(path, exist_ok=True)
    return path

@app.route('/static/uploads/<subfolder>/<filename>')
def serve_uploads(subfolder, filename):
    is_vercel = os.environ.get("VERCEL") == "1" or os.environ.get("VERCEL_ENV") is not None
    if is_vercel:
        tmp_path = os.path.join("/tmp", "uploads", subfolder)
        if os.path.exists(os.path.join(tmp_path, filename)):
            return send_from_directory(tmp_path, filename)
    static_path = os.path.join(app.root_path, "static", "uploads", subfolder)
    return send_from_directory(static_path, filename)

@security.unauthn_handler
def custom_unauth_handler(mechanisms, headers=None):
    return jsonify({"message": "Authentication required."}), 401

with app.app_context():
    try:
        db.create_all()
        if not Role.query.first():
            admin_role = Role(name="Admin", description="Administrator Role")
            student_role = Role(name="Student", description="Student Role")
            company_role = Role(name="Company", description="Company Role")
            db.session.add_all([admin_role, student_role, company_role])
            db.session.commit()
        if not User.query.filter_by(role="Admin").first():
            admin = User(
                email="admin@placement.com",
                password_hash=generate_password_hash("admin123"),
                role="Admin",
                is_active=True
            )
            admin.roles.append(Role.query.filter_by(name="Admin").first())
            db.session.add(admin)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[Database Init Warning] Handled initialization: {e}")

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

    expected_role = data.get("role")
    if expected_role and user.role != expected_role:
        return jsonify({"message": f"This email is not registered as a {expected_role}."}), 403

    password_valid = False
    if user.password_hash.startswith("pbkdf2:") or user.password_hash.startswith("scrypt:"):
        password_valid = check_password_hash(user.password_hash, data["password"])
    else:
        password_valid = (user.password_hash == data["password"])

    if not password_valid:
        return jsonify({"message": "Invalid Password"}), 401

    if not user.is_active:
        return jsonify({"message": "Account is inactive"}), 403

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
    is_multipart = request.content_type and "multipart/form-data" in request.content_type
    if is_multipart:
        email = request.form.get("email")
        password = request.form.get("password")
        full_name = request.form.get("full_name")
        phone = request.form.get("phone")
        branch = request.form.get("branch")
        cgpa_str = request.form.get("cgpa")
        grad_year_str = request.form.get("graduation_year")
        skills = request.form.get("skills")
        experience = request.form.get("experience")
    else:
        data = request.get_json() or {}
        email = data.get("email")
        password = data.get("password")
        full_name = data.get("full_name")
        phone = data.get("phone")
        branch = data.get("branch")
        cgpa_str = data.get("cgpa")
        grad_year_str = data.get("graduation_year")
        skills = data.get("skills")
        experience = data.get("experience")

    if not email or not password or not full_name:
        return jsonify({"message": "Email, password, and full name are required."}), 400

    if not email.lower().endswith("@gmail.com"):
        return jsonify({"message": "Only @gmail.com email addresses are permitted."}), 400

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        student_profile = Student.query.filter_by(user_id=existing_user.id).first()
        if student_profile and student_profile.is_blacklisted:
            return jsonify({"message": "This student account is blacklisted and cannot register again."}), 403
        return jsonify({"message": "Email already registered"}), 400

    cgpa = None
    if cgpa_str:
        try:
            cgpa = float(cgpa_str)
        except ValueError:
            pass
            
    graduation_year = None
    if grad_year_str:
        try:
            graduation_year = int(grad_year_str)
        except ValueError:
            pass

    user = User(
        email=email,
        password_hash=generate_password_hash(password),
        role="Student",
        is_active=True
    )
    
    student_role = Role.query.filter_by(name="Student").first()
    if not student_role:
        student_role = Role(name="Student")
        db.session.add(student_role)
    user.roles.append(student_role)

    db.session.add(user)
    db.session.commit()

    resume_path = "default.pdf"
    if "resume_file" in request.files:
        file = request.files["resume_file"]
        if file and file.filename:
            upload_dir = get_upload_dir("resumes")
            filename = f"resume_{user.id}_{int(datetime.utcnow().timestamp())}_{file.filename}"
            file.save(os.path.join(upload_dir, filename))
            resume_path = f"/static/uploads/resumes/{filename}"

    student = Student(
        user_id=user.id,
        full_name=full_name,
        phone=phone,
        branch=branch,
        cgpa=cgpa,
        graduation_year=graduation_year,
        skills=skills,
        resume=resume_path,
        experience=experience
    )
    db.session.add(student)
    db.session.commit()

    invalidate_cache_by_pattern("admin_students_search:*")
    invalidate_cache_by_pattern("admin_stats_cache")

    return jsonify({"message": "Student Registered Successfully"}), 201

@app.route("/register/company", methods=["POST"])
def register_company():
    data = request.get_json()
    email = data.get("email", "")
    if not email or not email.lower().endswith("@gmail.com"):
        return jsonify({"message": "Only @gmail.com email addresses are permitted."}), 400
        
    existing_user = User.query.filter_by(email=email).first()
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

    invalidate_cache_by_pattern("admin_companies_search:*")
    invalidate_cache_by_pattern("admin_stats_cache")

    return jsonify({"message": "Company Registered Successfully"}), 201

@app.route("/logout", methods=["POST", "GET"])
def logout():
    logout_user()
    return jsonify({"message": "Logout Successful"}), 200

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


@app.route("/api/admin/stats", methods=["GET"])
@auth_required()
def admin_stats():
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
        
    cache_key = "admin_stats_cache"
    cached = get_cached_response(cache_key)
    if cached is not None:
        return jsonify(cached)
        
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

    res = {
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
    }
    set_cached_response(cache_key, res, timeout=300)
    return jsonify(res)

@app.route("/api/admin/students", methods=["GET"])
@auth_required()
def admin_list_students():
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
        
    search_val = request.args.get("query", "").strip()
    cache_key = f"admin_students_search:{search_val}"
    cached = get_cached_response(cache_key)
    if cached is not None:
        return jsonify(cached)
    
    query = Student.query
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
    set_cached_response(cache_key, res, timeout=300)
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
    
    invalidate_cache_by_pattern("admin_students_search:*")
    invalidate_cache_by_pattern("admin_stats_cache")
    invalidate_cache_by_pattern("student_drives:*")
    
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
    
    invalidate_cache_by_pattern("admin_students_search:*")
    invalidate_cache_by_pattern("admin_stats_cache")
    invalidate_cache_by_pattern("student_drives:*")
    
    return jsonify({"message": "Student profile removed successfully."})

@app.route("/api/admin/companies", methods=["GET"])
@auth_required()
def admin_list_companies():
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
        
    search_val = request.args.get("query", "").strip()
    cache_key = f"admin_companies_search:{search_val}"
    cached = get_cached_response(cache_key)
    if cached is not None:
        return jsonify(cached)
        
    query = Company.query
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
    set_cached_response(cache_key, res, timeout=300)
    return jsonify(res)

@app.route("/api/admin/companies/<int:company_id>/approve", methods=["POST"])
@auth_required()
def admin_approve_company(company_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    company = Company.query.get_or_404(company_id)
    company.approval_status = "Approved"
    db.session.commit()
    
    invalidate_cache_by_pattern("admin_companies_search:*")
    invalidate_cache_by_pattern("admin_stats_cache")
    invalidate_cache_by_pattern("student_drives:*")
    
    return jsonify({"message": "Company approved.", "approval_status": "Approved"})

@app.route("/api/admin/companies/<int:company_id>/reject", methods=["POST"])
@auth_required()
def admin_reject_company(company_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    company = Company.query.get_or_404(company_id)
    company.approval_status = "Rejected"
    db.session.commit()
    
    invalidate_cache_by_pattern("admin_companies_search:*")
    invalidate_cache_by_pattern("admin_stats_cache")
    invalidate_cache_by_pattern("student_drives:*")
    
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
    
    invalidate_cache_by_pattern("admin_companies_search:*")
    invalidate_cache_by_pattern("admin_stats_cache")
    invalidate_cache_by_pattern("student_drives:*")
    
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
    
    invalidate_cache_by_pattern("admin_companies_search:*")
    invalidate_cache_by_pattern("admin_stats_cache")
    invalidate_cache_by_pattern("student_drives:*")
    
    return jsonify({"message": "Company removed successfully."})

@app.route("/api/admin/companies/<int:company_id>/profile", methods=["GET"])
@auth_required()
def get_company_profile_details(company_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
        
    company = Company.query.get_or_404(company_id)
    
    drives = []
    for d in company.placement_drives:
        apps = []
        for a in d.applications:
            apps.append({
                "application_id": a.application_id,
                "student_id": a.student_id,
                "student_name": a.student.full_name,
                "student_email": a.student.user.email,
                "student_cgpa": a.student.cgpa,
                "status": a.status,
                "interview_date": a.interview_date.strftime("%Y-%m-%d %H:%M") if a.interview_date else None,
                "feedback": a.feedback,
                "application_date": a.application_date.strftime("%Y-%m-%d %H:%M") if a.application_date else None,
                "meet_link": a.meet_link,
                "interview_description": a.interview_description,
                "interview_confirmed": a.interview_confirmed
            })
        drives.append({
            "drive_id": d.drive_id,
            "job_title": d.job_title,
            "salary": d.salary,
            "location": d.location,
            "status": d.status,
            "created_at": d.created_at.strftime("%Y-%m-%d") if d.created_at else None,
            "applications": apps
        })
        
    placements = []
    for p in company.placements:
        placements.append({
            "placement_id": p.placement_id,
            "student_name": p.student.full_name,
            "position": p.position,
            "salary": p.salary,
            "joining_date": p.joining_date.strftime("%Y-%m-%d") if p.joining_date else None
        })
        
    return jsonify({
        "company_id": company.company_id,
        "company_name": company.company_name,
        "email": company.user.email,
        "sector": company.industry,
        "website": company.website,
        "location": company.location,
        "description": company.description,
        "approval_status": company.approval_status,
        "is_blacklisted": company.is_blacklisted,
        "placement_drives": drives,
        "placements": placements
    })

@app.route("/api/admin/drives", methods=["GET"])
@auth_required()
def admin_list_drives():
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    check_and_close_expired_drives()
    drives = PlacementDrive.query.all()
    res = []
    for d in drives:
        res.append({
            "drive_id": d.drive_id,
            "company_id": d.company_id,
            "company_name": d.company.company_name,
            "job_title": d.job_title,
            "job_description": d.job_description,
            "eligibility_criteria": d.eligibility_criteria,
            "min_cgpa": d.min_cgpa,
            "application_deadline": d.application_deadline.strftime("%Y-%m-%d %H:%M") if d.application_deadline else None,
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
    
    invalidate_cache_by_pattern("student_drives:*")
    invalidate_cache_by_pattern("admin_stats_cache")
    invalidate_cache_by_pattern(f"company_stats_cache:{drive.company_id}")
    
    return jsonify({"message": "Placement drive approved.", "status": "Approved"})

@app.route("/api/admin/drives/<int:drive_id>/reject", methods=["POST"])
@auth_required()
def admin_reject_drive(drive_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    drive = PlacementDrive.query.get_or_404(drive_id)
    drive.status = "Rejected"
    db.session.commit()
    
    invalidate_cache_by_pattern("student_drives:*")
    invalidate_cache_by_pattern("admin_stats_cache")
    invalidate_cache_by_pattern(f"company_stats_cache:{drive.company_id}")
    
    return jsonify({"message": "Placement drive rejected.", "status": "Rejected"})

@app.route("/api/admin/drives/<int:drive_id>", methods=["DELETE"])
@auth_required()
def admin_remove_drive(drive_id):
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
    drive = PlacementDrive.query.get_or_404(drive_id)
    company_id = drive.company_id
    db.session.delete(drive)
    db.session.commit()
    
    invalidate_cache_by_pattern("student_drives:*")
    invalidate_cache_by_pattern("admin_stats_cache")
    invalidate_cache_by_pattern(f"company_stats_cache:{company_id}")
    
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
            "student_id": a.student_id,
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
    company_id = appln.placement_drive.company_id
    db.session.delete(appln)
    db.session.commit()
    
    invalidate_cache_by_pattern("admin_stats_cache")
    invalidate_cache_by_pattern(f"company_stats_cache:{company_id}")
    invalidate_cache_by_pattern("student_drives:*")
    
    return jsonify({"message": "Application removed successfully."})


@app.route("/api/company/stats", methods=["GET"])
@auth_required()
def company_stats():
    if current_user.role != "Company":
        return jsonify({"message": "Unauthorized"}), 403
    
    company = Company.query.filter_by(user_id=current_user.id).first()
    if not company or company.approval_status != "Approved" or company.is_blacklisted:
        return jsonify({"message": "Access denied. Company profile not approved or blacklisted."}), 403
        
    cache_key = f"company_stats_cache:{company.company_id}"
    cached = get_cached_response(cache_key)
    if cached is not None:
        return jsonify(cached)
        
    drives_count = PlacementDrive.query.filter_by(company_id=company.company_id).count()
    
    drive_ids = [d.drive_id for d in PlacementDrive.query.filter_by(company_id=company.company_id).all()]
    applications_count = Application.query.filter(Application.drive_id.in_(drive_ids)).count() if drive_ids else 0
    
    shortlisted_count = Application.query.filter(
        Application.drive_id.in_(drive_ids),
        Application.status == "Shortlisted"
    ).count() if drive_ids else 0
    
    res = {
        "drives_count": drives_count,
        "applications_count": applications_count,
        "shortlisted_count": shortlisted_count
    }
    set_cached_response(cache_key, res, timeout=300)
    return jsonify(res)

@app.route("/api/company/drives", methods=["GET", "POST"])
@auth_required()
def company_drives():
    if current_user.role != "Company":
        return jsonify({"message": "Unauthorized"}), 403
        
    check_and_close_expired_drives()
    company = Company.query.filter_by(user_id=current_user.id).first()
    if not company or company.approval_status != "Approved" or company.is_blacklisted:
        return jsonify({"message": "Access denied. Company profile not approved or blacklisted."}), 403

    if request.method == "POST":
        data = request.get_json()
        job_title = data.get("job_title")
        if not job_title:
            return jsonify({"message": "Job title is required."}), 400
            
        deadline = None
        if data.get("application_deadline"):
            val = data.get("application_deadline")
            try:
                deadline = datetime.strptime(val, "%Y-%m-%dT%H:%M")
            except ValueError:
                try:
                    deadline = datetime.strptime(val, "%Y-%m-%d %H:%M")
                except ValueError:
                    try:
                        deadline = datetime.strptime(val, "%Y-%m-%d")
                        deadline = deadline.replace(hour=23, minute=59)
                    except ValueError:
                        return jsonify({"message": "Invalid format for deadline. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM"}), 400
            
            if deadline < datetime.utcnow():
                return jsonify({"message": "Application deadline must be a future date/time."}), 400

        min_cgpa_val = data.get("min_cgpa")
        try:
            min_cgpa = float(min_cgpa_val) if min_cgpa_val is not None and min_cgpa_val != "" else 0.0
        except (ValueError, TypeError):
            min_cgpa = 0.0

        drive = PlacementDrive(
            company_id=company.company_id,
            job_title=job_title,
            job_description=data.get("job_description"),
            eligibility_criteria=data.get("eligibility_criteria"),
            min_cgpa=min_cgpa,
            application_deadline=deadline,
            salary=data.get("salary"),
            location=data.get("location"),
            skills_required=data.get("skills_required"),
            benefits=data.get("benefits"),
            status="Pending"
        )
        db.session.add(drive)
        db.session.commit()
        
        invalidate_cache_by_pattern("student_drives:*")
        invalidate_cache_by_pattern(f"company_stats_cache:{company.company_id}")
        invalidate_cache_by_pattern("admin_stats_cache")
        
        return jsonify({"message": "Placement drive posted successfully. Awaiting Admin approval.", "drive_id": drive.drive_id}), 201

    drives = PlacementDrive.query.filter_by(company_id=company.company_id).all()
    res = []
    for d in drives:
        res.append({
            "drive_id": d.drive_id,
            "job_title": d.job_title,
            "job_description": d.job_description,
            "eligibility_criteria": d.eligibility_criteria,
            "min_cgpa": d.min_cgpa,
            "application_deadline": d.application_deadline.strftime("%Y-%m-%d %H:%M") if d.application_deadline else None,
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
    if not company or company.approval_status != "Approved" or company.is_blacklisted:
        return jsonify({"message": "Access denied. Company profile not approved or blacklisted."}), 403
        
    drive = PlacementDrive.query.filter_by(drive_id=drive_id, company_id=company.company_id).first_or_404()
    
    if drive.status == "Closed":
        return jsonify({"message": "This drive has been closed and cannot be reopened."}), 400
        
    if drive.status in ["Approved", "Active"]:
        drive.status = "Closed"
    else:
        return jsonify({"message": "Drive status cannot be toggled because it is not active or approved."}), 400
        
    db.session.commit()
    
    invalidate_cache_by_pattern("student_drives:*")
    invalidate_cache_by_pattern(f"company_stats_cache:{company.company_id}")
    invalidate_cache_by_pattern("admin_stats_cache")
    
    return jsonify({"message": f"Drive status updated to {drive.status}.", "status": drive.status})

@app.route("/api/company/applications", methods=["GET"])
@auth_required()
def company_applications():
    if current_user.role != "Company":
        return jsonify({"message": "Unauthorized"}), 403
        
    company = Company.query.filter_by(user_id=current_user.id).first()
    if not company or company.approval_status != "Approved" or company.is_blacklisted:
        return jsonify({"message": "Access denied. Company profile not approved or blacklisted."}), 403
        
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
            "application_date": a.application_date.strftime("%Y-%m-%d %H:%M") if a.application_date else None,
            "meet_link": a.meet_link,
            "interview_description": a.interview_description,
            "interview_confirmed": a.interview_confirmed,
            "drive_salary": a.placement_drive.salary,
            "drive_benefits": a.placement_drive.benefits
        })
    return jsonify(res)

@app.route("/api/company/applications/<int:app_id>/status", methods=["POST"])
@auth_required()
def company_update_application_status(app_id):
    if current_user.role != "Company":
        return jsonify({"message": "Unauthorized"}), 403
        
    company = Company.query.filter_by(user_id=current_user.id).first()
    if not company or company.approval_status != "Approved" or company.is_blacklisted:
        return jsonify({"message": "Access denied. Company profile not approved or blacklisted."}), 403
        
    appln = Application.query.get_or_404(app_id)
    if appln.placement_drive.company_id != company.company_id:
        return jsonify({"message": "Access denied"}), 403
        
    data = request.get_json()
    new_status = data.get("status")
    if new_status not in ["Applied", "Shortlisted", "Interview", "Offer", "Rejected", "Placed"]:
        return jsonify({"message": "Invalid application status. Use Applied, Shortlisted, Interview, Offer, Rejected, or Placed."}), 400
        
    appln.status = new_status
    if "feedback" in data:
        appln.feedback = data.get("feedback")
        
    if new_status == "Placed":
        import datetime
        custom_pos = data.get("position") or appln.placement_drive.job_title
        custom_sal = data.get("salary")
        if custom_sal is not None:
            try:
                custom_sal = float(custom_sal)
            except ValueError:
                custom_sal = appln.placement_drive.salary
        else:
            custom_sal = appln.placement_drive.salary
            
        custom_joining_date = None
        if data.get("joining_date"):
            try:
                custom_joining_date = datetime.datetime.strptime(data.get("joining_date"), "%Y-%m-%d").date()
            except ValueError:
                custom_joining_date = datetime.date.today() + datetime.timedelta(days=90)
        else:
            custom_joining_date = datetime.date.today() + datetime.timedelta(days=90)
            
        custom_benefits = data.get("benefits") or appln.placement_drive.benefits
        
        pdf_filename = f"offer_{appln.application_id}.pdf"
        upload_dir = get_upload_dir("offers")
        pdf_path = os.path.join(upload_dir, pdf_filename)
        generate_offer_letter_pdf(
            student_name=appln.student.full_name,
            company_name=company.company_name,
            position=custom_pos,
            salary=custom_sal,
            joining_date_str=custom_joining_date.strftime("%Y-%m-%d"),
            benefits=custom_benefits,
            dest_path=pdf_path
        )
        
        existing_placement = Placement.query.filter_by(
            student_id=appln.student_id,
            company_id=company.company_id,
            drive_id=appln.drive_id
        ).first()
        if not existing_placement:
            new_placement = Placement(
                student_id=appln.student_id,
                company_id=company.company_id,
                drive_id=appln.drive_id,
                position=custom_pos,
                salary=custom_sal,
                joining_date=custom_joining_date,
                offer_letter=f"/static/uploads/offers/{pdf_filename}"
            )
            db.session.add(new_placement)
        else:
            existing_placement.position = custom_pos
            existing_placement.salary = custom_sal
            existing_placement.joining_date = custom_joining_date
            existing_placement.offer_letter = f"/static/uploads/offers/{pdf_filename}"
            
    db.session.commit()
    
    if new_status == "Shortlisted":
        subject = f"Application Update: Shortlisted for {appln.placement_drive.job_title}"
        body = f"Dear {appln.student.full_name},\n\nWe are pleased to inform you that you have been shortlisted by '{company.company_name}' for the position of '{appln.placement_drive.job_title}'.\n\nPlease check your student dashboard for updates regarding scheduling your placement interview.\n\nBest regards,\nCampus Placement Office"
        send_email_notification(appln.student.user.email, subject, body, sender_email=company.user.email, sender_name=f"{company.company_name} Recruitment")
    elif new_status == "Placed":
        pdf_filename = f"offer_{appln.application_id}.pdf"
        pdf_path = os.path.join(app.root_path, "static", "uploads", "offers", pdf_filename)
        subject = f"Congratulations! Placement Offer from {company.company_name}"
        body = (
            f"Dear {appln.student.full_name},\n\n"
            f"We are thrilled to inform you that you have been selected for the position of '{custom_pos}' "
            f"at '{company.company_name}' with a salary package of {custom_sal} LPA!\n\n"
            f"Please find your official employment offer letter attached to this email as a PDF file.\n\n"
            f"We wish you all the best and look forward to having you on board!\n\n"
            f"Best regards,\n"
            f"{company.company_name} HR Team"
        )
        send_email_notification(
            to_email=appln.student.user.email,
            subject=subject,
            body_text=body,
            sender_email=company.user.email,
            sender_name=f"{company.company_name} HR",
            attachment_path=pdf_path,
            attachment_filename=pdf_filename
        )
    elif new_status == "Rejected":
        subject = f"Application Update: {appln.placement_drive.job_title} at {company.company_name}"
        body = f"Dear {appln.student.full_name},\n\nThank you for your interest and for taking the time to apply for the position of '{appln.placement_drive.job_title}' with '{company.company_name}'.\n\nUnfortunately, we will not be moving forward with your application at this time.\n\nWe wish you all the best in your career pursuits.\n\nBest regards,\nCampus Placement Office"
        send_email_notification(appln.student.user.email, subject, body, sender_email=company.user.email, sender_name=f"{company.company_name} HR")
        
    invalidate_cache_by_pattern(f"company_stats_cache:{company.company_id}")
    invalidate_cache_by_pattern("admin_stats_cache")
    invalidate_cache_by_pattern("student_drives:*")
    
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
    if not company or company.approval_status != "Approved" or company.is_blacklisted:
        return jsonify({"message": "Access denied. Company profile not approved or blacklisted."}), 403
        
    appln = Application.query.get_or_404(app_id)
    if appln.placement_drive.company_id != company.company_id:
        return jsonify({"message": "Access denied"}), 403
        
    data = request.get_json()
    date_str = data.get("interview_date")
    meet_link = data.get("meet_link")
    description = data.get("interview_description")
    
    if not date_str:
        return jsonify({"message": "Interview date is required."}), 400
        
    try:
        interview_dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M")
    except ValueError:
        try:
            interview_dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        except ValueError:
            return jsonify({"message": "Invalid date format. Use YYYY-MM-DD HH:MM"}), 400
            
    appln.interview_date = interview_dt
    appln.meet_link = meet_link
    appln.interview_description = description
    appln.interview_confirmed = True
    appln.status = "Interview"
    db.session.commit()
    
    subject = f"Interview Scheduled: {appln.placement_drive.job_title} at {company.company_name}"
    body = (
        f"Dear {appln.student.full_name},\n\n"
        f"An interview has been scheduled for you with '{company.company_name}' for the position of '{appln.placement_drive.job_title}'.\n\n"
        f"Interview Date & Time: {interview_dt.strftime('%Y-%m-%d %H:%M')}\n"
        f"Google Meet / Meeting Link: {meet_link or 'Will be shared soon'}\n"
        f"Details / Instructions: {description or 'N/A'}\n\n"
        f"Please log in to your student dashboard to view details and join the meeting link at the scheduled time.\n\n"
        f"Best regards,\n"
        f"{company.company_name} Recruitment Team"
    )
    send_email_notification(appln.student.user.email, subject, body, sender_email=company.user.email, sender_name=f"{company.company_name} Recruitment")
    
    invalidate_cache_by_pattern(f"company_stats_cache:{company.company_id}")
    invalidate_cache_by_pattern("admin_stats_cache")
    invalidate_cache_by_pattern("student_drives:*")
    
    return jsonify({
        "message": "Interview invitation sent to student.",
        "status": appln.status,
        "interview_date": date_str,
        "meet_link": meet_link,
        "interview_description": description,
        "interview_confirmed": True
    })


@app.route("/api/user/smtp-password", methods=["GET", "POST"])
@auth_required()
def user_smtp_password():
    if request.method == "POST":
        data = request.get_json() or {}
        password = data.get("smtp_app_password", "")
        password = password.replace(" ", "")
        current_user.smtp_app_password = password
        db.session.commit()
        return jsonify({"message": "SMTP App Password updated successfully."})
    return jsonify({"smtp_app_password": current_user.smtp_app_password or ""})

@app.route("/api/student/profile", methods=["GET", "POST"])
@auth_required()
def student_profile():
    if current_user.role != "Student":
        return jsonify({"message": "Unauthorized"}), 403
        
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        return jsonify({"message": "Student profile not found"}), 404
        
    if request.method == "POST":
        if request.content_type and "multipart/form-data" in request.content_type:
            student.full_name = request.form.get("full_name", student.full_name)
            student.phone = request.form.get("phone", student.phone)
            student.branch = request.form.get("branch", student.branch)
            try:
                student.cgpa = float(request.form.get("cgpa")) if request.form.get("cgpa") else student.cgpa
            except ValueError:
                pass
            try:
                student.graduation_year = int(request.form.get("graduation_year")) if request.form.get("graduation_year") else student.graduation_year
            except ValueError:
                pass
            student.skills = request.form.get("skills", student.skills)
            student.experience = request.form.get("experience", student.experience)
            
            if "resume_file" in request.files:
                file = request.files["resume_file"]
                if file and file.filename:
                    upload_dir = get_upload_dir("resumes")
                    filename = f"resume_{student.student_id}_{int(datetime.utcnow().timestamp())}_{file.filename}"
                    file.save(os.path.join(upload_dir, filename))
                    student.resume = f"/static/uploads/resumes/{filename}"
        else:
            data = request.get_json()
            student.full_name = data.get("full_name", student.full_name)
            student.phone = data.get("phone", student.phone)
            student.branch = data.get("branch", student.branch)
            student.cgpa = data.get("cgpa", student.cgpa)
            student.graduation_year = data.get("graduation_year", student.graduation_year)
            student.skills = data.get("skills", student.skills)
            student.experience = data.get("experience", student.experience)
            if "resume" in data:
                student.resume = data.get("resume")
                
        db.session.commit()
        
        invalidate_cache_by_pattern("admin_students_search:*")
        invalidate_cache_by_pattern("admin_stats_cache")
        invalidate_cache_by_pattern(f"student_drives:{student.student_id}:*")
        
        return jsonify({"message": "Profile updated successfully.", "resume_url": student.resume})
        
    return jsonify({
        "student_id": student.student_id,
        "full_name": student.full_name,
        "phone": student.phone,
        "branch": student.branch,
        "cgpa": student.cgpa,
        "graduation_year": student.graduation_year,
        "skills": student.skills,
        "resume": student.resume,
        "experience": student.experience,
        "is_blacklisted": student.is_blacklisted
    })

@app.route("/api/student/drives", methods=["GET"])
@auth_required()
def student_list_drives():
    if current_user.role != "Student":
        return jsonify({"message": "Unauthorized"}), 403
        
    check_and_close_expired_drives()
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        return jsonify({"message": "Student profile not found"}), 404
        
    query_str = request.args.get("query", "").strip()
    cache_key = f"student_drives:{student.student_id}:{query_str}"
    cached = get_cached_response(cache_key)
    if cached is not None:
        return jsonify(cached)
    
    drives_query = PlacementDrive.query.filter(PlacementDrive.status.in_(["Approved", "Active"]))
    
    if query_str:
        from models import Company
        drives_query = drives_query.join(Company).filter(
            db.or_(
                Company.company_name.ilike(f"%{query_str}%"),
                PlacementDrive.job_title.ilike(f"%{query_str}%"),
                PlacementDrive.skills_required.ilike(f"%{query_str}%")
            )
        )
        
    drives = drives_query.all()
    applied_drive_ids = [a.drive_id for a in student.applications]
    
    res = []
    for d in drives:
        res.append({
            "drive_id": d.drive_id,
            "company_name": d.company.company_name,
            "job_title": d.job_title,
            "job_description": d.job_description,
            "eligibility_criteria": d.eligibility_criteria,
            "min_cgpa": d.min_cgpa,
            "application_deadline": d.application_deadline.strftime("%Y-%m-%d %H:%M") if d.application_deadline else None,
            "salary": d.salary,
            "location": d.location,
            "skills_required": d.skills_required,
            "benefits": d.benefits,
            "has_applied": d.drive_id in applied_drive_ids
        })
    set_cached_response(cache_key, res, timeout=300)
    return jsonify(res)

@app.route("/api/student/drives/<int:drive_id>/apply", methods=["POST"])
@auth_required()
def student_apply_drive(drive_id):
    if current_user.role != "Student":
        return jsonify({"message": "Unauthorized"}), 403
        
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        return jsonify({"message": "Student profile not found"}), 404
        
    if student.is_blacklisted:
        return jsonify({"message": "You are blacklisted and cannot apply to placement drives."}), 403
        
    drive = PlacementDrive.query.get_or_404(drive_id)
    if drive.status not in ["Approved", "Active"]:
        return jsonify({"message": "This placement drive is closed or inactive."}), 400
        
    if drive.min_cgpa and student.cgpa is not None:
        if student.cgpa < drive.min_cgpa:
            return jsonify({"message": f"You do not meet the minimum CGPA requirement ({drive.min_cgpa}) for this drive."}), 400

    existing = Application.query.filter_by(student_id=student.student_id, drive_id=drive_id).first()
    if existing:
        return jsonify({"message": "You have already applied to this drive."}), 400
        
    appln = Application(
        student_id=student.student_id,
        drive_id=drive_id,
        status="Applied"
    )
    db.session.add(appln)
    db.session.commit()
    
    invalidate_cache_by_pattern(f"student_drives:{student.student_id}:*")
    invalidate_cache_by_pattern(f"company_stats_cache:{drive.company_id}")
    invalidate_cache_by_pattern("admin_stats_cache")
    
    return jsonify({"message": "Applied successfully!", "application_id": appln.application_id})

@app.route("/api/student/applications", methods=["GET"])
@auth_required()
def student_applications():
    if current_user.role != "Student":
        return jsonify({"message": "Unauthorized"}), 403
        
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        return jsonify({"message": "Student profile not found"}), 404
        
    apps = Application.query.filter_by(student_id=student.student_id).all()
    res = []
    for a in apps:
        res.append({
            "application_id": a.application_id,
            "drive_id": a.drive_id,
            "job_title": a.placement_drive.job_title,
            "company_name": a.placement_drive.company.company_name,
            "application_date": a.application_date.strftime("%Y-%m-%d %H:%M") if a.application_date else None,
            "status": a.status,
            "feedback": a.feedback,
            "interview_date": a.interview_date.strftime("%Y-%m-%d %H:%M") if a.interview_date else None,
            "meet_link": a.meet_link,
            "interview_description": a.interview_description,
            "interview_confirmed": a.interview_confirmed
        })
    return jsonify(res)

@app.route("/api/student/placements", methods=["GET"])
@auth_required()
def student_placements():
    if current_user.role != "Student":
        return jsonify({"message": "Unauthorized"}), 403
        
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        return jsonify({"message": "Student profile not found"}), 404
        
    placements = Placement.query.filter_by(student_id=student.student_id).all()
    res = []
    for p in placements:
        res.append({
            "placement_id": p.placement_id,
            "company_name": p.company.company_name,
            "position": p.position,
            "salary": p.salary,
            "joining_date": p.joining_date.strftime("%Y-%m-%d") if p.joining_date else None,
            "offer_letter": p.offer_letter
        })
    return jsonify(res)

@app.route("/api/student/placements/<int:placement_id>/download-offer", methods=["GET"])
@auth_required()
def student_download_offer(placement_id):
    if current_user.role != "Student":
        return jsonify({"message": "Unauthorized"}), 403
        
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        return jsonify({"message": "Student profile not found"}), 404
        
    placement = Placement.query.get_or_404(placement_id)
    if placement.student_id != student.student_id:
        return jsonify({"message": "Access denied"}), 403
        
    pdf_filename = f"offer_ref_{placement.placement_id}.pdf"
    upload_dir = get_upload_dir("offers")
    pdf_path = os.path.join(upload_dir, pdf_filename)
    if not os.path.exists(pdf_path):
        import datetime
        joining_date_str = placement.joining_date.strftime("%Y-%m-%d") if placement.joining_date else datetime.date.today().strftime("%Y-%m-%d")
        benefits = placement.placement_drive.benefits if placement.placement_drive else "Standard corporate benefits package"
        generate_offer_letter_pdf(
            student_name=student.full_name,
            company_name=placement.company.company_name,
            position=placement.position or "Graduate Trainee",
            salary=placement.salary or 0.0,
            joining_date_str=joining_date_str,
            benefits=benefits,
            dest_path=pdf_path
        )
        placement.offer_letter = f"/static/uploads/offers/{pdf_filename}"
        db.session.commit()
        
    filename = f"OfferLetter_{placement.company.company_name.replace(' ', '_')}_{student.full_name.replace(' ', '_')}.pdf"
    return send_file(
        pdf_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
    )


@app.route("/api/common/export-csv", methods=["POST"])
@auth_required()
def trigger_csv_export():
    if current_user.role not in ["Student", "Company"]:
        return jsonify({"message": "Access denied"}), 403
        
    import uuid
    task_id = str(uuid.uuid4())
    
    try:
        redis_client.setex(f"export_status:{task_id}", 600, json.dumps({"status": "PENDING"}))
    except Exception as e:
        print("[Redis] Error setting initial task status:", e)
        
    from tasks import export_applications_csv
    export_applications_csv.delay(current_user.id, current_user.role, task_id)
    
    return jsonify({
        "message": "Export task started.",
        "task_id": task_id
    }), 202

@app.route("/api/common/export-status/<task_id>", methods=["GET"])
@auth_required()
def check_export_status(task_id):
    if current_user.role not in ["Student", "Company"]:
        return jsonify({"message": "Access denied"}), 403
        
    try:
        data_str = redis_client.get(f"export_status:{task_id}")
        if data_str:
            return jsonify(json.loads(data_str))
    except Exception as e:
        print("[Redis] Error reading task status:", e)
        
    return jsonify({"status": "PENDING"})


@app.route("/api/common/students/<int:student_id>/profile", methods=["GET"])
@auth_required()
def get_student_profile_details(student_id):
    if current_user.role not in ["Admin", "Company"]:
        return jsonify({"message": "Access denied"}), 403
        
    student = Student.query.get_or_404(student_id)
    
    if current_user.role == "Company":
        company = Company.query.filter_by(user_id=current_user.id).first()
        if not company:
            return jsonify({"message": "Access denied"}), 403
        drive_ids = [d.drive_id for d in company.placement_drives]
        has_applied = Application.query.filter(
            Application.student_id == student_id,
            Application.drive_id.in_(drive_ids)
        ).first() is not None
        if not has_applied:
            return jsonify({"message": "Access denied. Candidate has not applied to your postings."}), 403
            
    apps = []
    for a in student.applications:
        apps.append({
            "application_id": a.application_id,
            "company_name": a.placement_drive.company.company_name,
            "job_title": a.placement_drive.job_title,
            "application_date": a.application_date.strftime("%Y-%m-%d %H:%M") if a.application_date else None,
            "status": a.status,
            "interview_date": a.interview_date.strftime("%Y-%m-%d %H:%M") if a.interview_date else None,
            "feedback": a.feedback,
            "meet_link": a.meet_link,
            "interview_description": a.interview_description,
            "interview_confirmed": a.interview_confirmed
        })
        
    placements = []
    for p in student.placements:
        placements.append({
            "placement_id": p.placement_id,
            "company_name": p.company.company_name,
            "position": p.position,
            "salary": p.salary,
            "joining_date": p.joining_date.strftime("%Y-%m-%d") if p.joining_date else None,
            "offer_letter": f"/download-offer/{p.placement_id}"
        })
        
    return jsonify({
        "student_id": student.student_id,
        "full_name": student.full_name,
        "email": student.user.email,
        "phone": student.phone,
        "branch": student.branch,
        "cgpa": student.cgpa,
        "graduation_year": student.graduation_year,
        "skills": student.skills,
        "experience": student.experience,
        "resume": student.resume,
        "applications": apps,
        "placements": placements
    })


@app.route("/api/admin/reports", methods=["GET"])
@auth_required()
def admin_list_generated_reports():
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
        
    report_types = ["daily", "weekly", "monthly"]
    reports = []
    
    for rt in report_types:
        directory = os.path.join(app.root_path, "static", "reports", rt)
        if os.path.exists(directory):
            for filename in os.listdir(directory):
                if filename.endswith(".pdf"):
                    parts = filename.split("_")
                    company_name = "Unknown"
                    try:
                        idx = parts.index("company")
                        co_id = int(parts[idx+1])
                        from models import Company
                        co = Company.query.get(co_id)
                        if co:
                            company_name = co.company_name
                    except Exception:
                        pass
                    
                    reports.append({
                        "type": rt.capitalize(),
                        "company_name": company_name,
                        "filename": filename,
                        "url": f"/static/reports/{rt}/{filename}"
                    })
                    
    return jsonify(reports)

@app.route("/api/admin/trigger-monthly-reports", methods=["POST"])
@auth_required()
def admin_trigger_reports():
    if current_user.role != "Admin":
        return jsonify({"message": "Access denied"}), 403
        
    from tasks import generate_monthly_reports
    generate_monthly_reports.delay()
    return jsonify({"message": "Monthly placement report generation job triggered successfully."})

if __name__ == "__main__":
    app.run(debug=True)