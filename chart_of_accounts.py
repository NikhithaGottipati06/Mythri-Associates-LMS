# Chart of Accounts — all tally_groups seeds for microfinance LMS
# Each entry: (name, nature, sort_order)
# Nature values: 'Income', 'Expense', 'Asset', 'Liability'

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
    # P&L Income
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
    # Receipts & Payments — receipt heads
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
    # P&L Expense
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
    # Microfinance specific expenses
    ('Center Meeting Expenses',      'Expense', 39),
    ('PAR Provision',                'Expense', 40),
    ('Field Officer Salary',         'Expense', 41),
    ('Software Expenses',            'Expense', 42),
    ('Taxes & Licenses',             'Expense', 43),
    # Receipts & Payments — payment heads
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
    # Balance Sheet assets
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
    # Receipts & Payments — asset-side flows
    ('Loan Disbursement to Members', 'Asset', 26),
    ('HO Remittance Received',       'Asset', 27),
    ('Branch Transfer Received',     'Asset', 28),
]

LIABILITY_GROUPS = [
    ('Capital Account',                  'Liability',  1),
    ('Unsecured Loans',                  'Liability',  2),
    ('Secured Loans',                    'Liability',  3),
    ('Current Liabilities',              'Liability',  4),
    ('Loans (Liability)',                'Liability',  5),
    ('Sundry Creditors',                 'Liability',  6),
    ('Reserves & Surplus',               'Liability',  7),
    ('Retained Earnings',                'Liability',  8),
    ('Branch / Divisions',               'Liability',  9),
    ('Suspense A/c',                     'Liability', 10),
    # Balance Sheet liabilities
    ('Partner Current Account',          'Liability', 11),
    ('Bank Loan',                        'Liability', 12),
    ('Borrowings',                       'Liability', 13),
    ('Savings Deposits from Members',    'Liability', 14),
    ('Fixed Deposits from Members',      'Liability', 15),
    ('Interest Payable',                 'Liability', 16),
    ('Salaries Payable',                 'Liability', 17),
    ('Rent Payable',                     'Liability', 18),
    ('Audit Fees Payable',               'Liability', 19),
    ('TDS/GST Payable',                  'Liability', 20),
    ('Security Deposits Received',       'Liability', 21),
    ('Branch Balances Payable',          'Liability', 22),
    ('HO Balance Payable',               'Liability', 23),
    ('Outstanding Expenses',             'Liability', 24),
    ('Provision for Bad Debts (Liability)', 'Liability', 25),
    # Microfinance specific liabilities
    ('Member Savings',                   'Liability', 26),
    ('Group Insurance',                  'Liability', 27),
    ('Partner Capital',                  'Liability', 28),
]

ALL_GROUPS = INCOME_GROUPS + EXPENSE_GROUPS + ASSET_GROUPS + LIABILITY_GROUPS

# Auto-income ledgers — computed from LMS transaction data (not manual entries)
AUTO_LEDGERS = [
    ('Interest Collected',      'Interest on Loans',          'interest'),
    ('Processing Fee Collected','PROCESSING FEE',             'processing_fee'),
    ('Insurance Fee Collected', 'Processing Fee & Insurance', 'insurance_fee'),
    ('Membership Joining Fee',  'Direct Incomes',             'membership_fee'),
]
