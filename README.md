# Examination Management Portal

A Flask and SQLite web application for managing courses, examinations, examiner assignments, examination slots, student bookings, rubrics, and published results.

## Features

### Admin
- Manage courses and examinations
- Define examination types, dates, duration, and maximum marks
- Create rubric criteria and assign examiners
- Approve or deactivate examiner accounts
- Manage slots and booking rescheduling
- Publish or unpublish examination results
- Search users, examinations, and bookings

### Examiner
- View assigned examinations
- Create and manage examination slots
- View students booked into a slot
- Enter rubric marks or direct total marks
- Submit evaluations and remarks

### Student
- Register and maintain a profile
- Browse and search examinations
- Book available examination slots
- Cancel active bookings before the deadline
- View published results and download scorecards

## Technology

- Python 3
- Flask
- SQLite
- Jinja templates
- Werkzeug password hashing
- HTML, CSS, and JavaScript

## Installation

From the project directory:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

Flask debug mode is enabled in `app.py` and is intended for local development only.

## Default Administrator

The database creates this account automatically when no admin account exists:

```text
Email: admin@emp.com
Password: admin123
```

Change or remove the default credentials before deploying the application.

## Database

SQLite creates `emp.db` automatically in the project directory when the application starts.

The database includes:

- `users`
- `courses`
- `exams`
- `rubrics`
- `exam_examiners`
- `slots`
- `bookings`
- `scores`

`emp.db` is runtime data and is excluded from Git by `.gitignore`. Registering users or creating data through the application will modify this local database.

## Main Routes

| Area | Routes |
|---|---|
| Authentication | `/login`, `/logout`, `/register`, `/profile` |
| Admin | `/admin`, `/admin/courses`, `/admin/exams`, `/admin/examiners`, `/admin/students`, `/admin/slots`, `/admin/bookings` |
| Examiner | `/examiner`, `/examiner/slots`, `/examiner/slots/<id>/students`, `/examiner/evaluate/<booking-id>` |
| Student | `/student`, `/student/exams`, `/student/bookings`, `/student/cancel/<booking-id>` |
| Admin JSON API | `/api/courses`, `/api/exams`, `/api/slots`, `/api/bookings`, `/api/examiners`, `/api/students` |

## Project Structure

```text
app.py
emp.db              # Created locally; not committed
requirements.txt
README.md
.gitignore
templates/
  base.html
  form.html
  pending.html
  table.html
```

## Security Notes

This project is designed for learning and local use. Before production deployment:

- Replace the hardcoded Flask secret key with an environment variable
- Remove the default administrator password or force an immediate password reset
- Disable Flask debug mode
- Add stronger database transactions for bookings and slot updates
- Add automated tests and CSRF protection
- Review the application behind a production WSGI server
