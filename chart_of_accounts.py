# Chart of Accounts — all tally_groups and R&P head seeds for microfinance LMS
# Each tally_group entry  : (name, nature, sort_order)
# Each R&P head entry     : (name, type, category, sort_order, is_auto, lms_source)
#   is_auto=1  → amount computed directly from LMS tables; lms_source is the key
#   is_auto=0  → amount entered manually via rp_entries

# ── Tally Groups (P&L / Balance Sheet) ────────────────────────────────────────

INCOME_GROUPS = [
    ('Interest on Loans',             'Income',  1),
    ('PROCESSING FEE',                'Income',  2),
    ('Processing Fee & Insurance',    'Income',  3),
    ('LOAN TO MEMBERS Income',        'Income',  4),
    ('Direct Incomes',                'Income',  5),
    ('Indirect Incomes',              'Income',  6),
    ('Income (Direct)',               'Income',  7),
    ('Income (Indirect)',             'Income',  8),
    ('Sales Accounts',                'Income',  9),
    ('Penalty/Fine Income',           'Income', 10),
    ('Membership Fees',               'Income', 11),
    ('Insurance Commission',          'Income', 12),
    ('Bank Interest Received',        'Income', 13),
    ('Documentation Charges',         'Income', 14),
    ('Service Charges',               'Income', 15),
    ('Recovery of Written Off Loans', 'Income', 16),
    ('Miscellaneous Income',          'Income', 17),
    ('Asset Sale Income',             'Income', 18),
    ('Insurance Premium Recovery',    'Income', 19),
    ('Weekly Collection',             'Income', 20),
]

EXPENSE_GROUPS = [
    ('STAFF SALARIES',               'Expense',  1),
    ('RENT',                         'Expense',  2),
    ('ELECTRICITY BILL',             'Expense',  3),
    ('PRINTING & STATIONARY',        'Expense',  4),
    ('GENERAL & OFFICE MAINTANANCE', 'Expense',  5),
    ('COMPUTER & ACCESSORIES',       'Expense',  6),
    ('FURNITURE AND FIXURES',        'Expense',  7),
    ('HO REMITTANCE',                'Expense',  8),
    ('INTREST PAID ON REMITTANCE',   'Expense',  9),
    ('SPECIAL ALLOWANCES',           'Expense', 10),
    ('Insurance',                    'Expense', 11),
    ('Duties & Taxes',               'Expense', 12),
    ('Provisions',                   'Expense', 13),
    ('Direct Expenses',              'Expense', 14),
    ('Indirect Expenses',            'Expense', 15),
    ('Expenses (Direct)',            'Expense', 16),
    ('Expenses (Indirect)',          'Expense', 17),
    ('Misc. Expenses (ASSET)',       'Expense', 18),
    ('Purchase Accounts',            'Expense', 19),
    ('Internet & Software Charges',  'Expense', 20),
    ('Mobile & Telephone Expenses',  'Expense', 21),
    ('Staff Travel Allowance',       'Expense', 22),
    ('Fuel Expenses',                'Expense', 23),
    ('Vehicle Maintenance',          'Expense', 24),
    ('Bank Charges',                 'Expense', 25),
    ('Interest on Borrowings',       'Expense', 26),
    ('Audit Fees',                   'Expense', 27),
    ('Legal Expenses',               'Expense', 28),
    ('Advertisement Expenses',       'Expense', 29),
    ('Training Expenses',            'Expense', 30),
    ('Generator/Inverter Expenses',  'Expense', 31),
    ('Repairs & Maintenance',        'Expense', 32),
    ('Housekeeping Expenses',        'Expense', 33),
    ('Water Charges',                'Expense', 34),
    ('Security Charges',             'Expense', 35),
    ('Depreciation',                 'Expense', 36),
    ('Provision for Bad Debts',      'Expense', 37),
    ('Loan Write Off',               'Expense', 38),
    ('Center Meeting Expenses',      'Expense', 39),
    ('PAR Provision',                'Expense', 40),
    ('Field Officer Salary',         'Expense', 41),
    ('Software Expenses',            'Expense', 42),
    ('Taxes & Licenses',             'Expense', 43),
    ('Branch Transfer Sent',         'Expense', 44),
]

ASSET_GROUPS = [
    ('Cash-in-hand',                 'Asset',  1),
    ('Bank Accounts',                'Asset',  2),
    ('Bank OCC A/c',                 'Asset',  3),
    ('Bank OD A/c',                  'Asset',  4),
    ('LOAN TO MEMBERS',              'Asset',  5),
    ('Current Assets',               'Asset',  6),
    ('Fixed Assets',                 'Asset',  7),
    ('Deposits (Asset)',             'Asset',  8),
    ('Investments',                  'Asset',  9),
    ('Loans & Advances (Asset)',     'Asset', 10),
    ('Sundry Debtors',               'Asset', 11),
    ('Stock-in-hand',                'Asset', 12),
    ('RENT DEPOSTI',                 'Asset', 13),
    ('Loans Outstanding to Members', 'Asset', 14),
    ('Interest Receivable',          'Asset', 15),
    ('Fixed Deposits (Asset)',       'Asset', 16),
    ('Furniture & Fixtures',         'Asset', 17),
    ('Computers & Printers',         'Asset', 18),
    ('Vehicles',                     'Asset', 19),
    ('Office Equipment',             'Asset', 20),
    ('Security Deposits',            'Asset', 21),
    ('Advances to Staff',            'Asset', 22),
    ('Prepaid Expenses',             'Asset', 23),
    ('Accrued Income',               'Asset', 24),
    ('Branch Balances Receivable',   'Asset', 25),
    ('Loan Disbursement to Members', 'Asset', 26),
    ('HO Remittance Received',       'Asset', 27),
    ('Branch Transfer Received',     'Asset', 28),
]

LIABILITY_GROUPS = [
    ('Capital Account',                    'Liability',  1),
    ('Unsecured Loans',                    'Liability',  2),
    ('Secured Loans',                      'Liability',  3),
    ('Current Liabilities',                'Liability',  4),
    ('Loans (Liability)',                  'Liability',  5),
    ('Sundry Creditors',                   'Liability',  6),
    ('Reserves & Surplus',                 'Liability',  7),
    ('Retained Earnings',                  'Liability',  8),
    ('Branch / Divisions',                 'Liability',  9),
    ('Suspense A/c',                       'Liability', 10),
    ('Partner Current Account',            'Liability', 11),
    ('Bank Loan',                          'Liability', 12),
    ('Borrowings',                         'Liability', 13),
    ('Savings Deposits from Members',      'Liability', 14),
    ('Fixed Deposits from Members',        'Liability', 15),
    ('Interest Payable',                   'Liability', 16),
    ('Salaries Payable',                   'Liability', 17),
    ('Rent Payable',                       'Liability', 18),
    ('Audit Fees Payable',                 'Liability', 19),
    ('TDS/GST Payable',                    'Liability', 20),
    ('Security Deposits Received',         'Liability', 21),
    ('Branch Balances Payable',            'Liability', 22),
    ('HO Balance Payable',                 'Liability', 23),
    ('Outstanding Expenses',               'Liability', 24),
    ('Provision for Bad Debts (Liability)','Liability', 25),
    ('Member Savings',                     'Liability', 26),
    ('Group Insurance',                    'Liability', 27),
    ('Partner Capital',                    'Liability', 28),
]

ALL_GROUPS = INCOME_GROUPS + EXPENSE_GROUPS + ASSET_GROUPS + LIABILITY_GROUPS

# Auto-income ledgers — computed from LMS transaction data (used by tally module)
AUTO_LEDGERS = [
    ('Interest Collected',       'Interest on Loans',          'interest'),
    ('Processing Fee Collected', 'PROCESSING FEE',             'processing_fee'),
    ('Insurance Fee Collected',  'Processing Fee & Insurance', 'insurance_fee'),
    ('Membership Joining Fee',   'Direct Incomes',             'membership_fee'),
]


# ── Receipts & Payments Account Heads ─────────────────────────────────────────
# (name, type, category, sort_order, is_auto, lms_source)
#
# Auto sources available from LMS:
#   rp_principal      → recovery_postings.principal
#   rp_interest       → recovery_postings.interest
#   rp_penalty        → recovery_postings.penalty
#   loan_proc_fee     → loan_applications.processing_fee (via disbursement_date)
#   loan_insurance    → loan_applications.insurance_fee + nominee_insurance_fee
#   member_fees       → members.total_fees (by date_of_join)
#   savings_deposit   → savings_transactions.deposit_amount
#   loan_disbursed    → loan_disbursements.disbursed_amount

RECEIPT_HEADS = [
    # ── Opening Balances ──────────────────────────────────────────
    ('Opening Cash Balance',          'Receipt', 'Opening Balances',   1, 0, None),
    ('Opening Bank Balance',          'Receipt', 'Opening Balances',   2, 0, None),

    # ── Loan Operations ───────────────────────────────────────────
    ('Member Loan Recoveries',        'Receipt', 'Loan Operations',   10, 1, 'rp_principal'),
    ('Interest on Loans Collected',   'Receipt', 'Loan Operations',   11, 1, 'rp_interest'),
    ('Processing Fees Received',      'Receipt', 'Loan Operations',   12, 1, 'loan_proc_fee'),
    ('Penalty/Fine Collection',       'Receipt', 'Loan Operations',   13, 1, 'rp_penalty'),
    ('Insurance Collection',          'Receipt', 'Loan Operations',   14, 1, 'loan_insurance'),
    ('Recovery of Written Off Loans', 'Receipt', 'Loan Operations',   15, 0, None),

    # ── Member Deposits ───────────────────────────────────────────
    ('Membership Fees Collected',     'Receipt', 'Member Deposits',   20, 1, 'member_fees'),
    ('Savings Deposits from Members', 'Receipt', 'Member Deposits',   21, 1, 'savings_deposit'),
    ('Fixed Deposit Collections',     'Receipt', 'Member Deposits',   22, 0, None),
    ('Weekly Collection (EMI)',        'Receipt', 'Member Deposits',   23, 0, None),

    # ── Funding & Capital ─────────────────────────────────────────
    ('HO Remittance Received',        'Receipt', 'Funding & Capital', 30, 0, None),
    ('Branch Transfer Received',      'Receipt', 'Funding & Capital', 31, 0, None),
    ('Bank Loan Received',            'Receipt', 'Funding & Capital', 32, 0, None),
    ('Partner Capital Introduced',    'Receipt', 'Funding & Capital', 33, 0, None),

    # ── Other Receipts ────────────────────────────────────────────
    ('Interest from Bank',            'Receipt', 'Other Receipts',    40, 0, None),
    ('Asset Sale Receipts',           'Receipt', 'Other Receipts',    41, 0, None),
    ('Miscellaneous Receipts',        'Receipt', 'Other Receipts',    42, 0, None),
]

PAYMENT_HEADS = [
    # ── Loan Disbursements ────────────────────────────────────────
    ('Loan Disbursement to Members',  'Payment', 'Loan Disbursements',  1, 1, 'loan_disbursed'),
    ('Insurance Premium Paid',        'Payment', 'Loan Disbursements',  2, 0, None),
    ('Group Insurance Premium',       'Payment', 'Loan Disbursements',  3, 0, None),

    # ── Staff Costs ───────────────────────────────────────────────
    ('Salaries & Wages',              'Payment', 'Staff Costs',        10, 0, None),
    ('Field Officer Salary',          'Payment', 'Staff Costs',        11, 0, None),
    ('Special Allowances',            'Payment', 'Staff Costs',        12, 0, None),
    ('Staff Travel Allowance',        'Payment', 'Staff Costs',        13, 0, None),

    # ── Office Expenses ───────────────────────────────────────────
    ('Office Rent',                   'Payment', 'Office Expenses',    20, 0, None),
    ('Printing & Stationery',         'Payment', 'Office Expenses',    21, 0, None),
    ('Electricity Charges',           'Payment', 'Office Expenses',    22, 0, None),
    ('Internet & Software Charges',   'Payment', 'Office Expenses',    23, 0, None),
    ('Mobile & Telephone Expenses',   'Payment', 'Office Expenses',    24, 0, None),
    ('Water Charges',                 'Payment', 'Office Expenses',    25, 0, None),
    ('Housekeeping Expenses',         'Payment', 'Office Expenses',    26, 0, None),
    ('Repairs & Maintenance',         'Payment', 'Office Expenses',    27, 0, None),
    ('Security Charges',              'Payment', 'Office Expenses',    28, 0, None),
    ('Center Meeting Expenses',       'Payment', 'Office Expenses',    29, 0, None),

    # ── Vehicle & Transport ───────────────────────────────────────
    ('Fuel Expenses',                 'Payment', 'Vehicle & Transport',30, 0, None),
    ('Vehicle Maintenance',           'Payment', 'Vehicle & Transport',31, 0, None),

    # ── Capital Expenditure ───────────────────────────────────────
    ('Computer & Software Purchase',  'Payment', 'Capital Expenditure',40, 0, None),
    ('Furniture Purchase',            'Payment', 'Capital Expenditure',41, 0, None),
    ('Generator/Inverter Purchase',   'Payment', 'Capital Expenditure',42, 0, None),
    ('Office Equipment Purchase',     'Payment', 'Capital Expenditure',43, 0, None),

    # ── Financial Charges ─────────────────────────────────────────
    ('Bank Charges',                  'Payment', 'Financial Charges',  50, 0, None),
    ('Interest Paid on Bank Loans',   'Payment', 'Financial Charges',  51, 0, None),
    ('Audit Fees',                    'Payment', 'Financial Charges',  52, 0, None),
    ('Legal Expenses',                'Payment', 'Financial Charges',  53, 0, None),
    ('Taxes & Licenses',              'Payment', 'Financial Charges',  54, 0, None),

    # ── Transfers ─────────────────────────────────────────────────
    ('HO Remittance Sent',            'Payment', 'Transfers',          60, 0, None),
    ('Branch Transfer Sent',          'Payment', 'Transfers',          61, 0, None),

    # ── Other Payments ────────────────────────────────────────────
    ('Advertisement Expenses',        'Payment', 'Other Payments',     70, 0, None),
    ('Training Expenses',             'Payment', 'Other Payments',     71, 0, None),
    ('Miscellaneous Expenses',        'Payment', 'Other Payments',     72, 0, None),

    # ── Closing Balances ──────────────────────────────────────────
    ('Closing Cash Balance',          'Payment', 'Closing Balances',   80, 0, None),
    ('Closing Bank Balance',          'Payment', 'Closing Balances',   81, 0, None),
]

ALL_RP_HEADS = RECEIPT_HEADS + PAYMENT_HEADS
