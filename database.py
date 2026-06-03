import sqlite3
import os
import sys
from werkzeug.security import generate_password_hash
from chart_of_accounts import (
    INCOME_GROUPS, EXPENSE_GROUPS, ASSET_GROUPS, LIABILITY_GROUPS,
    AUTO_LEDGERS, ALL_RP_HEADS,
)

def _data_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

_DATA_DIR      = _data_dir()
MASTER_DB_PATH = os.path.join(_DATA_DIR, 'master.db')
BRANCHES_DIR   = os.path.join(_DATA_DIR, 'branches')
os.makedirs(BRANCHES_DIR, exist_ok=True)

# ── Master DB (branch list only) ──────────────────────────────────────────────

def get_master_db():
    conn = sqlite3.connect(MASTER_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_branch_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

# Legacy alias used by wsgi.py / init_db internals
def get_db():
    return get_master_db()

# ── Branch DB schema ──────────────────────────────────────────────────────────

def init_branch_db(db_path):
    conn = get_branch_db(db_path)
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

        CREATE TABLE IF NOT EXISTS sd_accounts (
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
        );

        CREATE TABLE IF NOT EXISTS day_end (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_date TEXT NOT NULL UNIQUE,
            closed_by INTEGER REFERENCES users(id),
            closed_at TEXT DEFAULT (datetime('now')),
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS arrear_entries (
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
        );

        CREATE TABLE IF NOT EXISTS member_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER REFERENCES members(id),
            doc_type TEXT NOT NULL,
            doc_label TEXT,
            filename TEXT NOT NULL,
            original_name TEXT,
            uploaded_at TEXT DEFAULT (datetime('now'))
        );
    """)

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
    migrate_branch_db(db_path)


def migrate_branch_db(db_path):
    conn = get_branch_db(db_path)
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
        # Fix maturity_amount for existing SD accounts
        "UPDATE sd_accounts SET maturity_amount = sd_amount + sd_amount * roi / 100.0 * (tenure_months / 12.0) WHERE sd_amount > 0",
        "ALTER TABLE tally_vouchers ADD COLUMN type TEXT DEFAULT 'Payment'",
        "UPDATE tally_groups SET nature='Liability' WHERE name='HO REMITTANCE' AND nature='Expense'",
        """CREATE TABLE IF NOT EXISTS member_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER REFERENCES members(id),
            doc_type TEXT NOT NULL,
            doc_label TEXT,
            filename TEXT NOT NULL,
            original_name TEXT,
            uploaded_at TEXT DEFAULT (datetime('now'))
        )""",
    ]
    tally_tables = """
        CREATE TABLE IF NOT EXISTS tally_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            nature TEXT NOT NULL,
            sort_order INTEGER DEFAULT 99
        );
        CREATE TABLE IF NOT EXISTS tally_ledgers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            group_id INTEGER REFERENCES tally_groups(id),
            is_auto INTEGER DEFAULT 0,
            lms_source TEXT,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS tally_vouchers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ledger_id INTEGER REFERENCES tally_ledgers(id),
            voucher_date TEXT NOT NULL,
            amount REAL NOT NULL,
            narration TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS rp_heads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL CHECK(type IN ('Receipt','Payment')),
            category TEXT NOT NULL,
            sort_order INTEGER DEFAULT 99,
            is_auto INTEGER DEFAULT 0,
            lms_source TEXT,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS rp_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            head_id INTEGER REFERENCES rp_heads(id),
            entry_date TEXT NOT NULL,
            amount REAL NOT NULL,
            narration TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        );
    """
    for sql in migrations:
        try:
            c.execute(sql)
        except Exception:
            pass
    for stmt in tally_tables.split(';'):
        stmt = stmt.strip()
        if stmt:
            try: c.execute(stmt)
            except Exception: pass

    # Seed Tally groups — defined in chart_of_accounts.py
    for grp_list in [INCOME_GROUPS, EXPENSE_GROUPS, ASSET_GROUPS, LIABILITY_GROUPS]:
        for name, nature, sort in grp_list:
            try:
                c.execute("INSERT OR IGNORE INTO tally_groups (name, nature, sort_order) VALUES (?,?,?)",
                          (name, nature, sort))
            except Exception:
                pass

    # Seed auto-income ledgers (computed from LMS data)
    for lname, gname, src in AUTO_LEDGERS:
        try:
            row = c.execute("SELECT id FROM tally_groups WHERE name=?", (gname,)).fetchone()
            if row:
                existing = c.execute("SELECT id FROM tally_ledgers WHERE lms_source=?", (src,)).fetchone()
                if not existing:
                    c.execute("INSERT INTO tally_ledgers (name, group_id, is_auto, lms_source) VALUES (?,?,1,?)",
                              (lname, row[0], src))
        except Exception:
            pass

    # Seed Receipts & Payments heads — defined in chart_of_accounts.py
    for name, rp_type, category, sort, is_auto, lms_src in ALL_RP_HEADS:
        try:
            c.execute(
                """INSERT OR IGNORE INTO rp_heads
                   (name, type, category, sort_order, is_auto, lms_source)
                   VALUES (?,?,?,?,?,?)""",
                (name, rp_type, category, sort, is_auto, lms_src),
            )
        except Exception:
            pass

    conn.commit()
    conn.close()


# ── Master DB init ─────────────────────────────────────────────────────────────

def init_master_db():
    os.makedirs(BRANCHES_DIR, exist_ok=True)
    conn = get_master_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            db_path TEXT UNIQUE NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS device_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            branch_db TEXT NOT NULL,
            user_login_name TEXT,
            user_full_name TEXT,
            branch_name TEXT,
            device_token TEXT NOT NULL UNIQUE,
            device_label TEXT,
            ip_address TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            approved_at TEXT,
            approved_by_name TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS branch_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_db TEXT UNIQUE NOT NULL,
            branch_name TEXT NOT NULL,
            due_day INTEGER NOT NULL DEFAULT 5,
            monthly_amount REAL DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscription_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_db TEXT NOT NULL,
            branch_name TEXT NOT NULL,
            month_key TEXT NOT NULL,
            due_date TEXT NOT NULL,
            amount REAL DEFAULT 0,
            status TEXT DEFAULT 'Pending',
            paid_at TEXT DEFAULT (datetime('now','localtime')),
            approved_at TEXT,
            approved_by TEXT,
            notes TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS developer_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS master_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            login_name TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS support_queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_db TEXT,
            branch_name TEXT,
            user_id INTEGER,
            user_name TEXT,
            user_role TEXT,
            query TEXT NOT NULL,
            status TEXT DEFAULT 'Open',
            response TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            responded_at TEXT
        )
    """)
    exists = conn.execute("SELECT COUNT(*) FROM master_users WHERE login_name='Sharp'").fetchone()[0]
    if not exists:
        conn.execute(
            "INSERT INTO master_users (full_name, login_name, password_hash) VALUES (?,?,?)",
            ('Sharp Developer', 'Sharp', generate_password_hash('Idontknow8632'))
        )
    conn.commit()

    # Add due_time column if it doesn't exist yet
    try:
        conn.execute("ALTER TABLE branch_subscriptions ADD COLUMN due_time TEXT DEFAULT '23:59'")
        conn.commit()
    except Exception:
        pass

    # Add email_status and user_seen_at to support_queries
    for col_sql in [
        "ALTER TABLE support_queries ADD COLUMN email_status TEXT DEFAULT NULL",
        "ALTER TABLE support_queries ADD COLUMN user_seen_at TEXT DEFAULT NULL",
    ]:
        try:
            conn.execute(col_sql)
            conn.commit()
        except Exception:
            pass

    # Fix stale db_paths (handles reinstall, cross-machine install, or path changes)
    stale = conn.execute("SELECT id, name, db_path FROM branches").fetchall()
    for row in stale:
        if not os.path.exists(row[2]):
            correct = os.path.join(BRANCHES_DIR, os.path.basename(row[2]))
            conn.execute("UPDATE branches SET db_path=? WHERE id=?", (correct, row[0]))
            conn.commit()
            if not os.path.exists(correct):
                init_branch_db(correct)

    conn.close()


def init_db():
    init_master_db()
    # Run migrations on all existing branch databases
    master = get_master_db()
    branches = master.execute("SELECT db_path FROM branches WHERE active=1").fetchall()
    master.close()
    for branch in branches:
        if os.path.exists(branch['db_path']):
            migrate_branch_db(branch['db_path'])
