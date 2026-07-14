from datetime import datetime
import uuid
from flask_security import UserMixin, RoleMixin
from extensions import db

roles_users = db.Table(
    "roles_users",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id")),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"))
)

class Role(db.Model, RoleMixin):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True)
    description = db.Column(db.String(255))

    def __repr__(self):
        return f"<Role {self.name}>"

class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    fs_uniquifier = db.Column(db.String(64), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    smtp_app_password = db.Column(db.String(100), nullable=True)

    company = db.relationship(
        "Company",
        back_populates="user",
        uselist=False
    )

    student = db.relationship(
        "Student",
        back_populates="user",
        uselist=False
    )

    roles = db.relationship(
        "Role",
        secondary=roles_users,
        backref=db.backref("users", lazy="dynamic")
    )

    @property
    def active(self):
        return self.is_active

    @active.setter
    def active(self, value):
        self.is_active = value

    @property
    def password(self):
        return self.password_hash

    @password.setter
    def password(self, value):
        self.password_hash = value

    def __repr__(self):
        return f"<User {self.email}>"
    
class Company(db.Model):
    __tablename__ = "company_profiles"

    company_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        unique=True
    )
    company_name = db.Column(db.String(150), nullable=False)
    hr_contact = db.Column(db.String(100), nullable=False)
    website = db.Column(db.String(200))
    approval_status = db.Column(
        db.String(20),
        default="Pending"
    )
    industry = db.Column(db.String(100))
    location = db.Column(db.String(100))
    description = db.Column(db.Text)
    is_blacklisted = db.Column(
        db.Boolean,
        default=False
    )
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    user = db.relationship(
        "User",
        back_populates="company"
    )
    placement_drives = db.relationship(
        "PlacementDrive",
        back_populates="company",
        cascade="all, delete-orphan"
    )
    placements = db.relationship(
        "Placement",
        back_populates="company"
    )

    def __repr__(self):
        return f"<Company {self.company_name}>"
    
class Student(db.Model):
    __tablename__ = "students"

    student_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        unique=True
    )
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(15))
    branch = db.Column(db.String(100))
    cgpa = db.Column(db.Float)
    graduation_year = db.Column(db.Integer)
    skills = db.Column(db.Text)
    resume = db.Column(db.String(255))
    experience = db.Column(db.Text)
    is_blacklisted = db.Column(
        db.Boolean,
        default=False
    )
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    user = db.relationship(
        "User",
        back_populates="student"
    )
    applications = db.relationship(
        "Application",
        back_populates="student",
        cascade="all, delete-orphan"
    )
    placements = db.relationship(
        "Placement",
        back_populates="student"
    )

    def __repr__(self):
        return f"<Student {self.full_name}>"
    
class PlacementDrive(db.Model):
    __tablename__ = "placement_drives"

    drive_id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company_profiles.company_id"),
        nullable=False
    )
    job_title = db.Column(db.String(150), nullable=False)
    job_description = db.Column(db.Text)
    eligibility_criteria = db.Column(db.Text)
    application_deadline = db.Column(db.DateTime)
    status = db.Column(
        db.String(20),
        default="Pending"
    )
    salary = db.Column(db.Float)
    location = db.Column(db.String(100))
    skills_required = db.Column(db.Text)
    benefits = db.Column(db.Text)
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    company = db.relationship(
        "Company",
        back_populates="placement_drives"
    )
    applications = db.relationship(
        "Application",
        back_populates="placement_drive",
        cascade="all, delete-orphan"
    )
    placements = db.relationship(
        "Placement",
        back_populates="placement_drive"
    )

    def __repr__(self):
        return f"<PlacementDrive {self.job_title}>"
    
class Application(db.Model):
    __tablename__ = "applications"

    __table_args__ = (
        db.UniqueConstraint(
            "student_id",
            "drive_id",
            name="unique_student_drive_application"
        ),
    )

    application_id = db.Column(
        db.Integer,
        primary_key=True
    )
    student_id = db.Column(
        db.Integer,
        db.ForeignKey("students.student_id"),
        nullable=False
    )
    drive_id = db.Column(
        db.Integer,
        db.ForeignKey("placement_drives.drive_id"),
        nullable=False
    )
    application_date = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
    status = db.Column(
        db.String(20),
        default="Applied"
    )
    feedback = db.Column(db.Text)
    interview_date = db.Column(db.DateTime)
    meet_link = db.Column(db.String(255))
    interview_description = db.Column(db.Text)
    interview_confirmed = db.Column(db.Boolean, default=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    student = db.relationship(
        "Student",
        back_populates="applications"
    )
    placement_drive = db.relationship(
        "PlacementDrive",
        back_populates="applications"
    )

    def __repr__(self):
        return f"<Application {self.application_id}>"
    
class Placement(db.Model):
    __tablename__ = "placements"

    placement_id = db.Column(
        db.Integer,
        primary_key=True
    )
    student_id = db.Column(
        db.Integer,
        db.ForeignKey("students.student_id"),
        nullable=False
    )
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company_profiles.company_id"),
        nullable=False
    )
    drive_id = db.Column(
        db.Integer,
        db.ForeignKey("placement_drives.drive_id"),
        nullable=False
    )
    position = db.Column(db.String(150))
    salary = db.Column(db.Float)
    joining_date = db.Column(db.Date)
    offer_letter = db.Column(db.String(255))
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    student = db.relationship(
        "Student",
        back_populates="placements"
    )
    company = db.relationship(
        "Company",
        back_populates="placements"
    )
    placement_drive = db.relationship(
        "PlacementDrive",
        back_populates="placements"
    )

    def __repr__(self):
        return f"<Placement {self.placement_id}>"