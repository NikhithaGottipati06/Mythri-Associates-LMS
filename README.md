# Mythri Associates LMS

A web-based **Loan Management System** built for Mythri Associates, Vijayawada, Andhra Pradesh. Manages the full lifecycle of microfinance operations — from member enrollment to loan disbursement, repayment tracking, savings, and reporting.

---

## Features

- **Dashboard** — at-a-glance stats: active centers, members, applications, disbursements, and savings outstanding
- **Centers & Members** — manage SHG centers and individual member profiles with KYC documents
- **Loan Applications** — create and track loan applications with purpose, guarantor, and KYC details
- **Loan Disbursement** — record and manage loan disbursements
- **Loan Posting** — recovery, prepaid, advance, and moratorium transactions
- **Savings** — deposit and withdrawal tracking per member
- **Reports** — collection sheets, summary sheets, outstanding reports, passbook, loan ledger, insurance, arrears, disbursement, and more
- **User Management** — role-based access (Admin / Staff); admin-only controls
- **Settings** — organization-level configuration

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3, Flask |
| Database | SQLite |
| Frontend | Jinja2 templates, HTML/CSS |
| Production server | Gunicorn |

---

## Getting Started

### Prerequisites

- Python 3.10+
- pip

### Installation

```bash
git clone https://github.com/NikhithaGottipati06/Mythri-Associates-LMS.git
cd Mythri-Associates-LMS
pip install -r requirements.txt
```

### Run (development)

```bash
python app.py
```

The app will be available at `http://localhost:5000`.

### Run (production)

```bash
gunicorn wsgi:app
```

---

## Project Structure

```
├── app.py              # Main Flask application & all routes
├── database.py         # DB connection and schema initialisation
├── wsgi.py             # Gunicorn entry point
├── requirements.txt
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   ├── centers/
│   ├── members/
│   ├── loans/
│   │   ├── applications/
│   │   ├── disbursement/
│   │   ├── posting/
│   │   ├── types/
│   │   └── prepaid_types/
│   ├── savings/
│   ├── reports/
│   └── users/
└── static/
    └── css/
```

---

## Default Login

On first run, the database is initialised with a default admin account:

| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | `admin123` |

> Change the admin password immediately after first login.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `mythri-lms-secret-2024` | Flask session secret — override in production |

---

## License

This project is proprietary software developed for Mythri Associates, Vijayawada, AP.
