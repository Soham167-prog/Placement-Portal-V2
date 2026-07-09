from celery import Celery
from celery.schedules import crontab
from app import app
from extensions import db
from models import Student, Company, Application, Placement
import csv
import os
from datetime import datetime, timedelta

# Initialize Celery app tied to Redis broker
celery_app = Celery(
    "tasks",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0"
)

celery_app.conf.update(
    timezone="Asia/Kolkata",
    enable_utc=True,
)

# ================= BACKGROUND JOBS =================

@celery_app.task
def send_interview_reminders():
    """Periodic Job: Sends reminders to students with interviews in the next 24 hours."""
    with app.app_context():
        now = datetime.utcnow()
        tomorrow = now + timedelta(days=1)
        
        # Find applications with an Interview scheduled within the next 24 hours
        upcoming_apps = Application.query.filter(
            Application.status == "Interview",
            Application.interview_date >= now,
            Application.interview_date <= tomorrow
        ).all()
        
        print(f"[Celery: Interview Reminder Job] Running check at {now}. Found {len(upcoming_apps)} scheduled interview(s) in the next 24 hours.")
        for a in upcoming_apps:
            # Simulate sending communication channels
            print(f"--- SIMULATED NOTIFICATION (EMAIL/SMS/GCHAT) SENT ---")
            print(f"Recipient: {a.student.full_name} <{a.student.user.email}>")
            print(f"Scheduled Time: {a.interview_date.strftime('%Y-%m-%d %H:%M')}")
            print(f"Details: You have a scheduled interview with '{a.placement_drive.company.company_name}' for the '{a.placement_drive.job_title}' role.")
            print(f"------------------------------------------------------")
        return f"Processed {len(upcoming_apps)} reminders."


@celery_app.task
def generate_monthly_reports():
    """Periodic Job: Generates recruitment statistics and placement history report for companies."""
    with app.app_context():
        companies = Company.query.filter_by(approval_status="Approved").all()
        report_dir = os.path.join(app.root_path, "static", "reports")
        os.makedirs(report_dir, exist_ok=True)
        
        print(f"[Celery: Monthly Report Job] Commencing monthly reporting for {len(companies)} approved recruiter profiles.")
        for company in companies:
            drive_ids = [d.drive_id for d in company.placement_drives]
            if not drive_ids:
                total_apps = 0
                shortlisted = 0
                placed = 0
                apps_list = []
            else:
                apps_list = Application.query.filter(Application.drive_id.in_(drive_ids)).all()
                total_apps = len(apps_list)
                shortlisted = sum(1 for a in apps_list if a.status == "Shortlisted")
                placed = sum(1 for a in apps_list if a.status in ["Offer", "Placed"])

            html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Placement Analytics Report - {company.company_name}</title>
    <style>
        body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; margin: 40px; background-color: #0f172a; color: #cbd5e1; }}
        .report-card {{ background: #1e293b; padding: 40px; border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.08); max-width: 850px; margin: 0 auto; }}
        h1 {{ color: #ffffff; border-bottom: 2px solid #334155; padding-bottom: 15px; margin-top: 0; }}
        .metrics-container {{ display: flex; justify-content: space-between; margin: 30px 0; gap: 20px; }}
        .metric-box {{ flex: 1; background: #0f172a; padding: 20px; border-radius: 8px; text-align: center; border: 1px solid rgba(255, 255, 255, 0.05); }}
        .metric-val {{ font-size: 28px; font-weight: bold; color: #818cf8; margin-bottom: 5px; }}
        .metric-lbl {{ font-size: 13px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 30px; }}
        th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background-color: #0f172a; color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 12px; }}
        tr:hover {{ background-color: rgba(255, 255, 255, 0.02); }}
    </style>
</head>
<body>
    <div class="report-card">
        <h1>Monthly Recruitment Analytics Report</h1>
        <p style="color: #94a3b8; margin-top: 5px;">Recruiter Profile: <strong style="color: #fff;">{company.company_name}</strong></p>
        <p style="color: #94a3b8;">Generated On: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
        
        <div class="metrics-container">
            <div class="metric-box">
                <div class="metric-val">{len(company.placement_drives)}</div>
                <div class="metric-lbl">Active/Approved Job Drives</div>
            </div>
            <div class="metric-box">
                <div class="metric-val">{total_apps}</div>
                <div class="metric-lbl">Total Job Applications</div>
            </div>
            <div class="metric-box">
                <div class="metric-val">{placed}</div>
                <div class="metric-lbl">Offers Awarded / Hired</div>
            </div>
        </div>
        
        <h3 style="color: #fff; margin-top: 40px; border-bottom: 1px solid #334155; padding-bottom: 8px;">Applicant Tracker</h3>
        <table>
            <thead>
                <tr>
                    <th>Candidate Name</th>
                    <th>Target Designation</th>
                    <th>CGPA</th>
                    <th>Application Status</th>
                    <th>Interview Date</th>
                </tr>
            </thead>
            <tbody>
"""
            for a in apps_list:
                interview_str = a.interview_date.strftime("%Y-%m-%d %H:%M") if a.interview_date else "Not Scheduled"
                html_content += f"""
                <tr>
                    <td style="color: #fff; font-weight: 500;">{a.student.full_name}</td>
                    <td>{a.placement_drive.job_title}</td>
                    <td>{a.student.cgpa or '-'}</td>
                    <td><span style="font-weight: 600; color: {'#34d399' if a.status in ['Offer','Placed'] else '#fbbf24' if a.status=='Shortlisted' else '#f87171' if a.status=='Rejected' else '#a5b4fc'};">{a.status}</span></td>
                    <td style="font-family: monospace;">{interview_str}</td>
                </tr>"""

            if not apps_list:
                html_content += """
                <tr>
                    <td colspan="5" style="text-align: center; color: #94a3b8; py: 20px;">No application records currently available for your postings.</td>
                </tr>"""

            html_content += """
            </tbody>
        </table>
    </div>
</body>
</html>
"""
            # Save file
            filename = f"report_company_{company.company_id}_{datetime.utcnow().strftime('%m_%Y')}.html"
            filepath = os.path.join(report_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"[Celery: Report Generated] Output report written: {filepath}")
        return f"Report batch generated for {len(companies)} companies."


@celery_app.task
def export_applications_csv(user_id, role):
    """Triggered Job: Asynchronously writes application history CSV for download."""
    with app.app_context():
        export_dir = os.path.join(app.root_path, "static", "exports")
        os.makedirs(export_dir, exist_ok=True)
        
        timestamp = int(datetime.utcnow().timestamp())
        filename = f"export_{role.lower()}_{user_id}_{timestamp}.csv"
        filepath = os.path.join(export_dir, filename)
        
        # Write CSV contents
        with open(filepath, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Application ID", "Student Name", "Student Email", 
                "Company Name", "Job Title", "Salary (LPA)", 
                "Application Date", "Status", "Interview Date", "Feedback"
            ])
            
            if role == "Student":
                student = Student.query.filter_by(user_id=user_id).first()
                apps = Application.query.filter_by(student_id=student.student_id).all() if student else []
            elif role == "Company":
                company = Company.query.filter_by(user_id=user_id).first()
                drive_ids = [d.drive_id for d in company.placement_drives] if company else []
                apps = Application.query.filter(Application.drive_id.in_(drive_ids)).all() if drive_ids else []
            else:
                apps = []
                
            for a in apps:
                writer.writerow([
                    a.application_id,
                    a.student.full_name,
                    a.student.user.email,
                    a.placement_drive.company.company_name,
                    a.placement_drive.job_title,
                    a.placement_drive.salary,
                    a.application_date.strftime("%Y-%m-%d %H:%M") if a.application_date else "",
                    a.status,
                    a.interview_date.strftime("%Y-%m-%d %H:%M") if a.interview_date else "",
                    a.feedback or ""
                ])
                
        print(f"[Celery: CSV Export Job] Saved exported CSV for user {user_id} ({role}) to {filepath}")
        return f"/static/exports/{filename}"


# ================= CELERY BEAT SCHEDULE =================

celery_app.conf.beat_schedule = {
    # Check for upcoming interview schedules every 30 seconds (simulation friendly)
    "trigger-upcoming-interview-reminders": {
        "task": "tasks.send_interview_reminders",
        "schedule": 30.0,
    },
    # Trigger report compilation at midnight on the 1st of every month
    "trigger-monthly-reports": {
        "task": "tasks.generate_monthly_reports",
        "schedule": crontab(day_of_month="1", hour="0", minute="0"),
    }
}
