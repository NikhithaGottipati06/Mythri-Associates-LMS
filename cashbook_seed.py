"""
Run once on the server to import cashbook data from the Maithri PDF.
Usage:
    python cashbook_seed.py                  # auto-detects branch from master.db
    python cashbook_seed.py /path/to/branch.db
"""
import os, sys, sqlite3
from datetime import datetime

# ── Locate branch database ──────────────────────────────────────────────────
def find_branch_db():
    base = os.path.dirname(os.path.abspath(__file__))
    master = os.path.join(base, 'master.db')
    if not os.path.exists(master):
        return None
    conn = sqlite3.connect(master)
    rows = conn.execute("SELECT name, db_path FROM branches WHERE active=1").fetchall()
    conn.close()
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0][1]
    print("Multiple branches found:")
    for idx, (name, path) in enumerate(rows):
        print(f"  [{idx}] {name}  →  {path}")
    choice = input("Enter number: ").strip()
    return rows[int(choice)][1]

db_path = sys.argv[1] if len(sys.argv) > 1 else find_branch_db()
if not db_path or not os.path.exists(db_path):
    print(f"ERROR: database not found: {db_path}")
    sys.exit(1)

print(f"Using database: {db_path}")

# ── All entries from Maithri PDF ────────────────────────────────────────────
# Format: (date DD/MM/YYYY, side DR|CR, particulars, cash_amount, bank_amount)
ENTRIES = [
    # ── 04/05/2026 ──────────────────────────────────────────────────────────
    ('04/05/2026', 'DR', 'Opening Balance',         0,      51000),
    ('04/05/2026', 'DR', 'Ho Remittance',            120000, 0),
    ('04/05/2026', 'DR', 'pf & insurance',           5400,   0),
    ('04/05/2026', 'DR', 'To bank',                  0,      0),
    ('04/05/2026', 'CR', 'By loan to Members',       120000, 51000),
    ('04/05/2026', 'CR', 'printing and stationary',  1850,   0),
    ('04/05/2026', 'CR', 'By bank',                  0,      0),

    # ── 07/05/2026 ──────────────────────────────────────────────────────────
    ('07/05/2026', 'DR', 'Opening Balance',         3550,   51000),
    ('07/05/2026', 'DR', 'Ho Remittance',            120000, 0),
    ('07/05/2026', 'DR', 'pf & insurance',           5400,   0),
    ('07/05/2026', 'DR', 'To bank',                  0,      0),
    ('07/05/2026', 'CR', 'By loan to Members',       120000, 51000),
    ('07/05/2026', 'CR', 'printing and stationary',  135,    0),
    ('07/05/2026', 'CR', 'By bank',                  0,      0),

    # ── 09/05/2026 ──────────────────────────────────────────────────────────
    ('09/05/2026', 'DR', 'Opening Balance',         8815,   11000),
    ('09/05/2026', 'DR', 'Ho Remittance(gv)',        20000,  0),
    ('09/05/2026', 'DR', 'pf & insurance',           900,    0),
    ('09/05/2026', 'DR', 'To bank',                  0,      0),
    ('09/05/2026', 'CR', 'By loan to Members',       20000,  11000),
    ('09/05/2026', 'CR', 'printing and stationary',  1320,   0),

    # ── 11/05/2026 ──────────────────────────────────────────────────────────
    ('11/05/2026', 'DR', 'Opening Balance',                          8395,   11000),
    ('11/05/2026', 'DR', 'Ho Remittance(gv)',                         101000, 0),
    ('11/05/2026', 'DR', 'HO Remittance(vijay)',                      21000,  0),
    ('11/05/2026', 'DR', 'pf & insurance',                            4500,   0),
    ('11/05/2026', 'DR', 'Loan to Members',                           3971,   0),
    ('11/05/2026', 'DR', 'interest on loans',                         629,    0),
    ('11/05/2026', 'DR', 'Savings',                                   600,    0),
    ('11/05/2026', 'DR', 'To bank',                                   0,      0),
    ('11/05/2026', 'CR', 'By loan to Members',                        100000, 11000),
    ('11/05/2026', 'CR', 'Rent Advance for office (Mrs.Padma)',        22000,  0),
    ('11/05/2026', 'CR', 'Furniture & Fixtures',                      8600,   0),
    ('11/05/2026', 'CR', 'General & office maintenance (Furniture transport)', 500, 0),

    # ── 12/05/2026 ──────────────────────────────────────────────────────────
    ('12/05/2026', 'DR', 'Opening Balance',  8995,  11000),
    ('12/05/2026', 'DR', 'To bank',          0,     50000),

    # ── 13/05/2026 ──────────────────────────────────────────────────────────
    ('13/05/2026', 'DR', 'Opening Balance',                               8995,   61000),
    ('13/05/2026', 'DR', 'Ho Remittance(MVK)',                             100000, 0),
    ('13/05/2026', 'DR', 'pf & insurance',                                4500,   0),
    ('13/05/2026', 'DR', 'HO remittance (Rs.15000 MVK and Rs.15000 GV)',  30000,  0),
    ('13/05/2026', 'CR', 'By loan to Members',                            100000, 61000),
    ('13/05/2026', 'CR', 'General & office maintenance (wifi)',           3654,   0),
    ('13/05/2026', 'CR', 'Software expenses (computer & accessories)',    30000,  0),

    # ── 14/05/2026 ──────────────────────────────────────────────────────────
    ('14/05/2026', 'DR', 'Opening Balance',         9841,   61000),
    ('14/05/2026', 'DR', 'Ho Remittance(MVK)',        100000, 0),
    ('14/05/2026', 'DR', 'pf & insurance',            4500,   0),
    ('14/05/2026', 'DR', 'Loan to Members',           0,      0),
    ('14/05/2026', 'DR', 'interest on loans',         0,      0),
    ('14/05/2026', 'DR', 'Savings',                   700,    0),
    ('14/05/2026', 'DR', 'To bank',                   0,      0),
    ('14/05/2026', 'CR', 'By loan to Members',        100000, 61000),
    ('14/05/2026', 'CR', 'General & office maintenance (Ac installation)', 2000, 0),

    # ── 18/05/2026 ──────────────────────────────────────────────────────────
    ('18/05/2026', 'DR', 'Opening Balance',         18291,  61000),
    ('18/05/2026', 'DR', 'pf & insurance',           0,      0),
    ('18/05/2026', 'DR', 'Loan to Members',           0,      0),
    ('18/05/2026', 'DR', 'interest on loans',         0,      0),
    ('18/05/2026', 'DR', 'Savings',                   1100,   0),
    ('18/05/2026', 'DR', 'To bank',                   0,      50000),
    ('18/05/2026', 'CR', 'By loan to Members',        0,      61000),
    ('18/05/2026', 'CR', 'General & office maintenance (cash books)', 1250, 0),

    # ── 20/05/2026 ──────────────────────────────────────────────────────────
    ('20/05/2026', 'DR', 'Opening Balance',         26391,  61000),
    ('20/05/2026', 'DR', 'Ho Remittance(GV)',         120000, 0),
    ('20/05/2026', 'DR', 'pf & insurance',            5400,   0),
    ('20/05/2026', 'DR', 'Loan to Members',           0,      0),
    ('20/05/2026', 'DR', 'interest on loans',         0,      0),
    ('20/05/2026', 'DR', 'Savings',                   0,      0),
    ('20/05/2026', 'CR', 'By loan to Members',        120000, 61000),
]

# ── Insert ──────────────────────────────────────────────────────────────────
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Use first admin user as creator
user = conn.execute("SELECT id FROM users WHERE role='Admin' LIMIT 1").fetchone()
user_id = user['id'] if user else 1

# Check for existing data to avoid duplicates
existing = conn.execute("SELECT COUNT(*) FROM cashbook_entries").fetchone()[0]
if existing > 0:
    ans = input(f"WARNING: {existing} entries already exist. Add anyway? [y/N] ").strip().lower()
    if ans != 'y':
        print("Aborted.")
        conn.close()
        sys.exit(0)

inserted = 0
for (date, side, particulars, cash, bank) in ENTRIES:
    conn.execute(
        "INSERT INTO cashbook_entries (entry_date, side, particulars, cash_amount, bank_amount, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (date, side, particulars, float(cash), float(bank), user_id)
    )
    inserted += 1

conn.commit()
conn.close()
print(f"Done. Inserted {inserted} cashbook entries.")
