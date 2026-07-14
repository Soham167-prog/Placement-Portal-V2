# Campus Placement Portal V2 - Setup and Demo Guide

This system coordinates student placement drives, recruiter job postings, admin approvals, automatic PDF offer letters, and asynchronous status tracking with Redis/Celery.

---

## 1. Setup Instructions

### Pre-requisites
Ensure you have **Python 3.10+**, **Redis**, and **SQLite** installed on your system.

### Installation
1. Install all dependencies from `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```

2. Initialize the database and pre-create the Admin user:
   ```bash
   python create_admin.py
   ```
   *Note: This generates `placement_portal.db` and configures the default admin login credentials.*
   *   **Admin Email**: `admin@placement.com`
   *   **Admin Password**: `admin123`

---

## 2. Running the Application

To run the complete system, you need to start the Redis server, Flask backend, and Celery background workers.

### Step 1: Start Redis
Make sure your Redis server is running locally on port `6379`:
```bash
redis-server
```

### Step 2: Run the Flask Web Application
Start the core Flask backend API:
```bash
python app.py
```
The application will run locally at [http://127.0.0.1:5000/](http://127.0.0.1:5000/).

### Step 3: Run Celery Worker & Beat
In separate terminal windows, start the background tasks worker and the cron task scheduler:

*   **Start the Celery Worker**:
    ```bash
    celery -A tasks.celery_app worker --loglevel=info
    ```
*   **Start the Celery Beat Scheduler**:
    ```bash
    celery -A tasks.celery_app beat --loglevel=info
    ```

---

## 3. End-to-End Demo Workflow (Testing Guide)

Use this step-by-step scenario to verify and demonstrate all functionalities:

### Step A: Setup Users
1. Register a new **Company Recruiter** account using:
   *   **Email**: `recruiter@gmail.com`
   *   **Company Name**: *Google Inc.*
2. Register a new **Student** candidate account using:
   *   **Email**: `student@gmail.com`

### Step B: Admin Approval (Drives & Profiles)
1. Log in to the **Admin Dashboard** (`admin@placement.com` / `admin123`).
2. Go to the **Recruiter Approval** section and click **Approve** next to Google Inc.
3. Log out.

### Step C: Post a Placement Drive
1. Log in as the approved **Company Recruiter** (`recruiter@gmail.com`).
2. Go to the **Post New Job** tab and fill out the details (Title, Salary, Location, Skills, and Eligibility Criteria).
3. Once submitted, the drive requires Admin approval to go active. Log out.
4. Log back in as **Admin**, navigate to the **Job Drives** tab, and click **Approve** to publish the drive.

### Step D: Student Application
1. Log in as the **Student** (`student@gmail.com`).
2. Update your profile by filling in your CGPA, Branch, and uploading a PDF resume.
3. Go to the **Job Postings** tab, search for the Google drive, and click **Apply**.

### Step E: Scheduling the Interview (Recruiter Side)
1. Log in as the **Recruiter**. In the **Applications** tab, click **Schedule Interview** on the student's card.
2. Enter the date/time, a Google Meet link, and instructions. Click **Send Invitation**.
3. The system will dispatch an invitation email to `student@gmail.com`.

### Step F: Checking Scheduled Interview (Student Side)
1. Log in as the **Student**. Go to the **My Interview Schedules** tab.
2. The scheduled interview details and the Join Call button will be visible on your dashboard.

### Step G: Final Selection & PDF Offer Letter
1. Log in as the **Recruiter**. Click **Place Candidate** next to the student's record.
2. Customize the final designation, package, and joining date in the selection details form, then submit.
3. The backend dynamically compiles a formal PDF offer letter and dispatches it as an email attachment to `student@gmail.com`.
4. Log in as the **Student** to download the official PDF confirmation document directly from the dashboard.