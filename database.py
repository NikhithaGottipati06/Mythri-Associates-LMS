import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get('DATABASE_PATH', os.path.join(os.path.dirname(__file__), 'lms.db'))

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('Admin','Staff')),
            joining_date TEXT,
            login_name TEXT UNIQUE NOT NULL,
            email TEXT,
            password_hash TEXT NOT NULL,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS centers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            center_code TEXT UNIQUE NOT NULL,
            center_name TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            address1 TEXT,
            address2 TEXT,
            city TEXT,
            mandal TEXT,
            pin_code TEXT,
            district TEXT,
            state TEXT DEFAULT 'ANDHRA PRADESH',
            landmark TEXT,
            notes TEXT,
            staff_id INTEGER REFERENCES users(id),
            max_members INTEGER DEFAULT 30,
            meeting_place TEXT,
            meeting_type TEXT DEFAULT 'Weekly',
            meeting_week TEXT,
            meeting_time TEXT,
            enable_arrears INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_code TEXT UNIQUE NOT NULL,
            center_id INTEGER REFERENCES centers(id),
            grp INTEGER DEFAULT 1,
            full_name TEXT NOT NULL,
            date_of_join TEXT,
            date_of_birth TEXT,
            gender TEXT,
            marital_status TEXT,
            guardian_name TEXT,
            spouse_name TEXT,
            caste TEXT,
            religion TEXT,
            address1 TEXT,
            address2 TEXT,
            city TEXT,
            mandal TEXT,
            pin_code TEXT,
            district TEXT,
            state TEXT DEFAULT 'ANDHRA PRADESH',
            landmark TEXT,
            phone1 TEXT,
            phone2 TEXT,
            email TEXT,
            notes TEXT,
            photo_path TEXT,
            signature_path TEXT,
            income REAL DEFAULT 0,
            expenditure REAL DEFAULT 0,
            total_fees REAL DEFAULT 0,
            fee_mode TEXT DEFAULT 'Cash',
            fee_narration TEXT DEFAULT 'Cash',
            kyc_type TEXT,
            kyc_number TEXT,
            status TEXT DEFAULT 'ACTIVE',
            enable_arrears INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS member_nominees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER REFERENCES members(id),
            nominee_name TEXT,
            relationship TEXT,
            dob TEXT,
            phone TEXT,
            address TEXT
        );

        CREATE TABLE IF NOT EXISTS loan_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_type_code TEXT UNIQUE NOT NULL,
            loan_type_name TEXT NOT NULL,
            interest_rate REAL DEFAULT 0,
            interest_method TEXT DEFAULT 'Flat',
            repayment_frequency TEXT DEFAULT 'Weekly',
            max_amount REAL DEFAULT 0,
            min_amount REAL DEFAULT 0,
            tenure_weeks INTEGER DEFAULT 50,
            processing_fee REAL DEFAULT 0,
            insurance_fee REAL DEFAULT 0,
            active INTEGER DEFAULT 1,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS prepaid_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS loan_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_no TEXT UNIQUE NOT NULL,
            member_id INTEGER REFERENCES members(id),
            center_id INTEGER REFERENCES centers(id),
            loan_type_id INTEGER REFERENCES loan_types(id),
            applied_amount REAL NOT NULL,
            applied_date TEXT,
            purpose TEXT,
            status TEXT DEFAULT 'Pending',
            remarks TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS loan_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER REFERENCES loan_applications(id),
            approved_amount REAL,
            approved_date TEXT,
            approved_by INTEGER REFERENCES users(id),
            status TEXT DEFAULT 'Approved',
            remarks TEXT
        );

        CREATE TABLE IF NOT EXISTS loan_disbursements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER REFERENCES loan_applications(id),
            disbursement_no TEXT UNIQUE NOT NULL,
            disbursed_amount REAL,
            disbursement_date TEXT,
            mode TEXT DEFAULT 'Cash',
            account_no TEXT,
            disbursed_by INTEGER REFERENCES users(id),
            status TEXT DEFAULT 'Disbursed',
            total_installments INTEGER,
            installment_amount REAL,
            remarks TEXT
        );

        CREATE TABLE IF NOT EXISTS recovery_postings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            disbursement_id INTEGER REFERENCES loan_disbursements(id),
            posting_date TEXT,
            installment_no INTEGER,
            due_amount REAL,
            paid_amount REAL,
            principal REAL,
            interest REAL,
            penalty REAL DEFAULT 0,
            mode TEXT DEFAULT 'Cash',
            narration TEXT,
            posted_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS prepaid_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            disbursement_id INTEGER REFERENCES loan_disbursements(id),
            prepaid_type_id INTEGER REFERENCES prepaid_types(id),
            transaction_date TEXT,
            amount REAL,
            mode TEXT DEFAULT 'Cash',
            narration TEXT,
            is_undo INTEGER DEFAULT 0,
            posted_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS advance_recoveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            disbursement_id INTEGER REFERENCES loan_disbursements(id),
            recovery_date TEXT,
            amount REAL,
            mode TEXT DEFAULT 'Cash',
            narration TEXT,
            posted_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS moratoriums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            disbursement_id INTEGER REFERENCES loan_disbursements(id),
            from_date TEXT,
            to_date TEXT,
            reason TEXT,
            applied_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS savings_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER REFERENCES members(id),
            center_id INTEGER REFERENCES centers(id),
            disbursement_id INTEGER REFERENCES loan_disbursements(id),
            recovery_posting_id INTEGER REFERENCES recovery_postings(id),
            transaction_date TEXT,
            deposit_amount REAL DEFAULT 0,
            withdraw_amount REAL DEFAULT 0,
            balance REAL DEFAULT 0,
            posted_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS secure_deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER REFERENCES members(id),
            center_id INTEGER REFERENCES centers(id),
            transaction_date TEXT NOT NULL,
            deposit_amount REAL DEFAULT 0,
            withdraw_amount REAL DEFAULT 0,
            balance REAL DEFAULT 0,
            remarks TEXT,
            posted_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rd_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rd_no TEXT UNIQUE NOT NULL,
            member_id INTEGER REFERENCES members(id),
            center_id INTEGER REFERENCES centers(id),
            start_date TEXT NOT NULL,
            installment_amount REAL NOT NULL,
            total_installments INTEGER NOT NULL,
            frequency TEXT DEFAULT 'Weekly',
            status TEXT DEFAULT 'Active',
            remarks TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rd_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rd_id INTEGER REFERENCES rd_accounts(id),
            transaction_date TEXT NOT NULL,
            installment_no INTEGER NOT NULL,
            amount REAL NOT NULL,
            remarks TEXT,
            posted_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)

    # Seed admin user if no users exist
    existing = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing == 0:
        users = [
            ('G VENKATESWARLU', 'Admin', '01/10/2024', 'GVR', '', generate_password_hash('admin123'), 1),
            ('G SURESH', 'Staff', '01/06/2025', 'Suresh01', '', generate_password_hash('staff123'), 1),
            ('C.Sivaiah', 'Staff', '26/10/2024', 'Siva', '', generate_password_hash('staff123'), 1),
            ('LAYANYA', 'Staff', '01/07/2025', 'Layanya', '', generate_password_hash('staff123'), 1),
            ('KALAIVANI', 'Staff', '22/09/2025', 'KALAIVANI', '', generate_password_hash('staff123'), 0),
            ('Mrs.K Vani', 'Staff', '06/09/2025', 'K Vani', '', generate_password_hash('staff123'), 1),
        ]
        c.executemany(
            "INSERT INTO users (full_name, role, joining_date, login_name, email, password_hash, active) VALUES (?,?,?,?,?,?,?)",
            users
        )

    conn.commit()
    conn.close()
    migrate_db()


def migrate_db():
    conn = get_db()
    c = conn.cursor()
    migrations = [
        "ALTER TABLE loan_types ADD COLUMN interest_type TEXT DEFAULT 'Percent'",
        "ALTER TABLE loan_types ADD COLUMN fixed_tenure INTEGER DEFAULT 1",
        "ALTER TABLE prepaid_types ADD COLUMN type TEXT DEFAULT 'Weekly'",
        "ALTER TABLE prepaid_types ADD COLUMN loan_type_id INTEGER",
        "ALTER TABLE prepaid_types ADD COLUMN member_expired INTEGER DEFAULT 0",
        "ALTER TABLE prepaid_types ADD COLUMN full_interest INTEGER DEFAULT 1",
        "ALTER TABLE prepaid_types ADD COLUMN has_preclosure_charges INTEGER DEFAULT 0",
        "ALTER TABLE loan_applications ADD COLUMN nominee_name TEXT DEFAULT ''",
        "ALTER TABLE loan_applications ADD COLUMN monthly_net_income REAL DEFAULT 0",
        "ALTER TABLE loan_applications ADD COLUMN loan_cycle INTEGER DEFAULT 1",
        "ALTER TABLE loan_applications ADD COLUMN member_kyc_type TEXT DEFAULT ''",
        "ALTER TABLE loan_applications ADD COLUMN member_kyc_number TEXT DEFAULT ''",
        "ALTER TABLE loan_applications ADD COLUMN nominee_kyc_type TEXT DEFAULT ''",
        "ALTER TABLE loan_applications ADD COLUMN nominee_kyc_number TEXT DEFAULT ''",
        "ALTER TABLE loan_applications ADD COLUMN processing_fee REAL DEFAULT 0",
        "ALTER TABLE loan_applications ADD COLUMN insurance_fee REAL DEFAULT 0",
        "ALTER TABLE loan_applications ADD COLUMN nominee_insurance_fee REAL DEFAULT 0",
        "ALTER TABLE loan_applications ADD COLUMN other_charges REAL DEFAULT 0",
        "ALTER TABLE loan_disbursements ADD COLUMN loan_id TEXT",
        "ALTER TABLE secure_deposits ADD COLUMN percentage REAL DEFAULT 0",
        "ALTER TABLE secure_deposits ADD COLUMN interest_rate REAL DEFAULT 0",
        "ALTER TABLE rd_accounts ADD COLUMN percentage REAL DEFAULT 0",
        "ALTER TABLE rd_accounts ADD COLUMN interest_rate REAL DEFAULT 0",
        "ALTER TABLE rd_transactions ADD COLUMN transaction_type TEXT DEFAULT 'Payment'",
        "ALTER TABLE rd_accounts ADD COLUMN maturity_amount REAL DEFAULT 0",
        "ALTER TABLE rd_accounts ADD COLUMN tenure_unit TEXT DEFAULT 'Months'",
        """CREATE TABLE IF NOT EXISTS sd_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sd_no TEXT UNIQUE NOT NULL,
            member_id INTEGER REFERENCES members(id),
            center_id INTEGER REFERENCES centers(id),
            loan_amount REAL DEFAULT 0,
            percentage REAL DEFAULT 0,
            sd_amount REAL DEFAULT 0,
            roi REAL DEFAULT 0,
            tenure_months INTEGER DEFAULT 12,
            tenure_unit TEXT DEFAULT 'Months',
            maturity_amount REAL DEFAULT 0,
            start_date TEXT,
            status TEXT DEFAULT 'Active',
            remarks TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        """CREATE TABLE IF NOT EXISTS day_end (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_date TEXT NOT NULL UNIQUE,
            closed_by INTEGER REFERENCES users(id),
            closed_at TEXT DEFAULT (datetime('now')),
            notes TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS arrear_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            disbursement_id INTEGER REFERENCES loan_disbursements(id),
            arrear_date TEXT NOT NULL,
            installment_no INTEGER,
            due_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'Pending',
            collected_date TEXT,
            collected_amount REAL DEFAULT 0,
            marked_by INTEGER REFERENCES users(id),
            cleared_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        # Fix maturity_amount for existing SD accounts: interest on SD amount, not loan amount
        "UPDATE sd_accounts SET maturity_amount = sd_amount + sd_amount * roi / 100.0 * (tenure_months / 12.0) WHERE sd_amount > 0",
    ]
    for sql in migrations:
        try:
            c.execute(sql)
        except Exception:
            pass
    conn.commit()
    conn.close()
