from celery import Celery
from celery.schedules import crontab
import csv
import os
from datetime import datetime, timedelta

celery_app = Celery(
    "tasks",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0"
)

celery_app.conf.update(
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_always_eager=True
)

def generate_recruitment_report_pdf(dest_path, report_type, company, drives_count, total_apps, placed, apps_list):
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from datetime import datetime
    
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    
    doc = SimpleDocTemplate(dest_path, pagesize=letter,
                            rightMargin=40, leftMargin=40, topMargin=45, bottomMargin=45)
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'RepTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1e1b4b'),
        spaceAfter=5
    )
    
    meta_style = ParagraphStyle(
        'RepMeta',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#4b5563'),
        spaceAfter=15
    )
    
    section_title = ParagraphStyle(
        'RepSecTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=17,
        textColor=colors.HexColor('#1e1b4b'),
        spaceBefore=15,
        spaceAfter=8
    )
    
    body_style = ParagraphStyle(
        'RepBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#1f2937')
    )
    
    body_bold = ParagraphStyle(
        'RepBodyBold',
        parent=body_style,
        fontName='Helvetica-Bold'
    )
    
    story.append(Paragraph(f"{report_type.capitalize()} Recruitment Analytics Report", title_style))
    story.append(Paragraph(f"<b>Recruiter Profile:</b> {company.company_name} | <b>Generated:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC", meta_style))
    story.append(Spacer(1, 10))
    
    stats_data = [
        [Paragraph("<b>Job Drives</b>", body_style), Paragraph("<b>Total Applications</b>", body_style), Paragraph("<b>Offers Awarded</b>", body_style)],
        [Paragraph(f"<b>{drives_count}</b>", title_style), Paragraph(f"<b>{total_apps}</b>", title_style), Paragraph(f"<b>{placed}</b>", title_style)]
    ]
    stats_table = Table(stats_data, colWidths=[180, 180, 180])
    stats_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f3f4f6')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(stats_table)
    story.append(Spacer(1, 20))
    
    story.append(Paragraph("Applicant Tracker", section_title))
    
    header_style = ParagraphStyle('HStyle', parent=body_bold, textColor=colors.white)
    table_data = [
        [Paragraph("<b>Candidate Name</b>", header_style), 
         Paragraph("<b>Target Designation</b>", header_style), 
         Paragraph("<b>CGPA</b>", header_style), 
         Paragraph("<b>Status</b>", header_style), 
         Paragraph("<b>Interview Date</b>", header_style)]
    ]
    
    for a in apps_list:
        interview_str = a.interview_date.strftime("%Y-%m-%d %H:%M") if a.interview_date else "Not Scheduled"
        status_color = '#10b981' if a.status in ['Offer','Placed'] else '#f59e0b' if a.status=='Shortlisted' else '#ef4444' if a.status=='Rejected' else '#6366f1'
        status_style = ParagraphStyle('StatStyle', parent=body_bold, textColor=colors.HexColor(status_color))
        
        table_data.append([
            Paragraph(a.student.full_name, body_style),
            Paragraph(a.placement_drive.job_title, body_style),
            Paragraph(str(a.student.cgpa or '-'), body_style),
            Paragraph(a.status, status_style),
            Paragraph(interview_str, body_style)
        ])
        
    if not apps_list:
        table_data.append([
            Paragraph("No application records currently available.", body_style), "", "", "", ""
        ])
        
    app_table = Table(table_data, colWidths=[120, 140, 50, 90, 130])
    app_table_style = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e1b4b')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]
    
    if not apps_list:
        app_table_style.append(('SPAN', (0,1), (-1,1)))
        app_table_style.append(('ALIGN', (0,1), (-1,1), 'CENTER'))
        
    app_table.setStyle(TableStyle(app_table_style))
    story.append(app_table)
    
    doc.build(story)

@celery_app.task
def send_interview_reminders():
    """Periodic Job: Sends reminders to students with interviews in the next 24 hours."""
    from app import app
    from models import Application
    
    with app.app_context():
        now = datetime.utcnow()
        tomorrow = now + timedelta(days=1)
        
        upcoming_apps = Application.query.filter(
            Application.status == "Interview",
            Application.interview_date >= now,
            Application.interview_date <= tomorrow
        ).all()
        
        print(f"[Celery: Interview Reminder Job] Running check at {now}. Found {len(upcoming_apps)} scheduled interview(s) in the next 24 hours.")
        for a in upcoming_apps:
            from app import send_email_notification
            subject = f"Interview Reminder: {a.placement_drive.job_title} at {a.placement_drive.company.company_name}"
            body = (
                f"Dear {a.student.full_name},\n\n"
                f"This is a reminder that you have an upcoming interview with '{a.placement_drive.company.company_name}' "
                f"for the '{a.placement_drive.job_title}' role.\n\n"
                f"Scheduled Time: {a.interview_date.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"Please ensure you are prepared and connect on time.\n\n"
                f"Best regards,\nCampus Placement Office"
            )
            send_email_notification(a.student.user.email, subject, body)
        return f"Processed {len(upcoming_apps)} reminders."


@celery_app.task
def generate_daily_reports():
    """Periodic Job: Compile recruitment activity statistics from the last 24 hours."""
    from app import app
    from models import Company, PlacementDrive, Application, Placement
    
    with app.app_context():
        now = datetime.utcnow()
        day_ago = now - timedelta(days=1)
        
        report_dir = os.path.join(app.root_path, "static", "reports", "daily")
        os.makedirs(report_dir, exist_ok=True)
        
        companies = Company.query.filter_by(approval_status="Approved").all()
        print(f"[Celery: Daily Report Job] Compiling daily recruitment statistics since {day_ago}.")
        
        for company in companies:
            drives = PlacementDrive.query.filter(
                PlacementDrive.company_id == company.company_id,
                PlacementDrive.created_at >= day_ago
            ).all()
            
            drive_ids = [d.drive_id for d in company.placement_drives]
            if drive_ids:
                apps = Application.query.filter(
                    Application.drive_id.in_(drive_ids),
                    Application.application_date >= day_ago
                ).all()
                placements = Placement.query.filter(
                    Placement.company_id == company.company_id,
                    Placement.created_at >= day_ago
                ).all()
            else:
                apps = []
                placements = []
                
            clean_company_name = company.company_name.replace(' ', '_').replace('/', '_')
            filename = f"daily_report_company_{company.company_id}_{clean_company_name}_{now.strftime('%Y%m%d')}.pdf"
            filepath = os.path.join(report_dir, filename)
            generate_recruitment_report_pdf(
                dest_path=filepath,
                report_type="Daily",
                company=company,
                drives_count=len(drives),
                total_apps=len(apps),
                placed=len(placements),
                apps_list=apps
            )
        return f"Daily reports generated for {len(companies)} companies."


@celery_app.task
def generate_weekly_reports():
    """Periodic Job: Compile recruitment activity statistics from the last 7 days."""
    from app import app
    from models import Company, PlacementDrive, Application, Placement
    
    with app.app_context():
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        
        report_dir = os.path.join(app.root_path, "static", "reports", "weekly")
        os.makedirs(report_dir, exist_ok=True)
        
        companies = Company.query.filter_by(approval_status="Approved").all()
        print(f"[Celery: Weekly Report Job] Compiling weekly recruitment statistics since {week_ago}.")
        
        for company in companies:
            drives = PlacementDrive.query.filter(
                PlacementDrive.company_id == company.company_id,
                PlacementDrive.created_at >= week_ago
            ).all()
            
            drive_ids = [d.drive_id for d in company.placement_drives]
            if drive_ids:
                apps = Application.query.filter(
                    Application.drive_id.in_(drive_ids),
                    Application.application_date >= week_ago
                ).all()
                placements = Placement.query.filter(
                    Placement.company_id == company.company_id,
                    Placement.created_at >= week_ago
                ).all()
            else:
                apps = []
                placements = []
                
            clean_company_name = company.company_name.replace(' ', '_').replace('/', '_')
            filename = f"weekly_report_company_{company.company_id}_{clean_company_name}_{now.strftime('%Y%m%d')}.pdf"
            filepath = os.path.join(report_dir, filename)
            generate_recruitment_report_pdf(
                dest_path=filepath,
                report_type="Weekly",
                company=company,
                drives_count=len(drives),
                total_apps=len(apps),
                placed=len(placements),
                apps_list=apps
            )
        return f"Weekly reports generated for {len(companies)} companies."


@celery_app.task
def generate_monthly_reports():
    """Periodic Job: Generates recruitment statistics and placement history report for companies."""
    from app import app
    from models import Company, Application
    
    with app.app_context():
        companies = Company.query.filter_by(approval_status="Approved").all()
        report_dir = os.path.join(app.root_path, "static", "reports", "monthly")
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

            clean_company_name = company.company_name.replace(' ', '_').replace('/', '_')
            filename = f"report_company_{company.company_id}_{clean_company_name}_{datetime.utcnow().strftime('%m_%Y')}.pdf"
            filepath = os.path.join(report_dir, filename)
            generate_recruitment_report_pdf(
                dest_path=filepath,
                report_type="Monthly",
                company=company,
                drives_count=len(company.placement_drives),
                total_apps=total_apps,
                placed=placed,
                apps_list=apps_list
            )
            print(f"[Celery: Report Generated] Output report written: {filepath}")
        return f"Report batch generated for {len(companies)} companies."


@celery_app.task
def export_applications_csv(user_id, role, task_id=None):
    """Triggered Job: Asynchronously writes application history CSV for download."""
    from app import app
    from models import Student, Company, Application
    from extensions import redis_client
    import json
    
    try:
        with app.app_context():
            export_dir = os.path.join(app.root_path, "static", "exports")
            os.makedirs(export_dir, exist_ok=True)
            
            timestamp = int(datetime.utcnow().timestamp())
            filename = f"export_{role.lower()}_{user_id}_{timestamp}.csv"
            filepath = os.path.join(export_dir, filename)
            
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
                    
            download_url = f"/static/exports/{filename}"
            print(f"[Celery: CSV Export Job] Saved exported CSV for user {user_id} ({role}) to {filepath}")
            
            if task_id:
                try:
                    redis_client.setex(
                        f"export_status:{task_id}", 
                        600, 
                        json.dumps({"status": "SUCCESS", "download_url": download_url})
                    )
                except Exception as re:
                    print("[Redis] Error updating task status to SUCCESS:", re)
                    
            return download_url
            
    except Exception as e:
        print("[Celery: CSV Export Job] Failed:", e)
        if task_id:
            try:
                redis_client.setex(
                    f"export_status:{task_id}", 
                    600, 
                    json.dumps({"status": "FAILURE", "message": str(e)})
                )
            except Exception as re:
                print("[Redis] Error updating task status to FAILURE:", re)
        raise e



celery_app.conf.beat_schedule = {
    "trigger-upcoming-interview-reminders": {
        "task": "tasks.send_interview_reminders",
        "schedule": 30.0,
    },
    "trigger-daily-reports": {
        "task": "tasks.generate_daily_reports",
        "schedule": crontab(hour="0", minute="0"),
    },
    "trigger-weekly-reports": {
        "task": "tasks.generate_weekly_reports",
        "schedule": crontab(day_of_week="0", hour="0", minute="0"),
    },
    "trigger-monthly-reports": {
        "task": "tasks.generate_monthly_reports",
        "schedule": crontab(day_of_month="1", hour="0", minute="0"),
    }
}