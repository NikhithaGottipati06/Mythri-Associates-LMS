"""
Financial Statements module — Flask Blueprint
Routes:
  /financial-statements/               → hub / landing page
  /financial-statements/receipts-payments   → Receipts & Payments Account
  /financial-statements/income-expenditure  → Income & Expenditure Account
  /financial-statements/trial-balance       → Trial Balance
"""

from flask import Blueprint, render_template, request, session, redirect, url_for
from database import get_branch_db
from datetime import datetime, date
from collections import OrderedDict

fin_stmt = Blueprint('fin_stmt', __name__, url_prefix='/financial-statements')


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_db():
    branch_db = session.get('branch_db')
    return get_branch_db(branch_db) if branch_db else None

def _parse_date(s):
    """DD/MM/YYYY → YYYY-MM-DD. Returns None on failure."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), '%d/%m/%Y').strftime('%Y-%m-%d')
    except ValueError:
        return None

def _fmt(ymd):
    """YYYY-MM-DD → DD/MM/YYYY for display."""
    if not ymd:
        return ''
    try:
        return datetime.strptime(ymd, '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        return ymd

def _default_range():
    today = date.today()
    d_from = today.replace(day=1).strftime('%Y-%m-%d')
    d_to   = today.strftime('%Y-%m-%d')
    return d_from, d_to

def _scalar(db, sql, params=()):
    row = db.execute(sql, params).fetchone()
    return (row[0] or 0) if row else 0


# ── Auto-computed amounts from LMS tables ──────────────────────────────────────

def _auto_receipts(db, d_from, d_to):
    """Return dict[lms_source] = amount for all auto receipt sources."""
    r = {}
    r['rp_principal']   = _scalar(db,
        "SELECT SUM(principal) FROM recovery_postings WHERE posting_date BETWEEN ? AND ?",
        (d_from, d_to))
    r['rp_interest']    = _scalar(db,
        "SELECT SUM(interest) FROM recovery_postings WHERE posting_date BETWEEN ? AND ?",
        (d_from, d_to))
    r['rp_penalty']     = _scalar(db,
        "SELECT SUM(penalty) FROM recovery_postings WHERE posting_date BETWEEN ? AND ?",
        (d_from, d_to))
    r['loan_proc_fee']  = _scalar(db,
        """SELECT SUM(la.processing_fee)
           FROM loan_applications la
           JOIN loan_disbursements ld ON ld.application_id = la.id
           WHERE ld.disbursement_date BETWEEN ? AND ?""",
        (d_from, d_to))
    r['loan_insurance'] = _scalar(db,
        """SELECT SUM(la.insurance_fee + la.nominee_insurance_fee)
           FROM loan_applications la
           JOIN loan_disbursements ld ON ld.application_id = la.id
           WHERE ld.disbursement_date BETWEEN ? AND ?""",
        (d_from, d_to))
    r['member_fees']    = _scalar(db,
        "SELECT SUM(total_fees) FROM members WHERE date_of_join BETWEEN ? AND ?",
        (d_from, d_to))
    r['savings_deposit']= _scalar(db,
        "SELECT SUM(deposit_amount) FROM savings_transactions WHERE transaction_date BETWEEN ? AND ?",
        (d_from, d_to))
    return r

def _auto_payments(db, d_from, d_to):
    r = {}
    r['loan_disbursed'] = _scalar(db,
        "SELECT SUM(disbursed_amount) FROM loan_disbursements WHERE disbursement_date BETWEEN ? AND ?",
        (d_from, d_to))
    return r

def _manual_amount(db, head_id, d_from, d_to):
    return _scalar(db,
        "SELECT SUM(amount) FROM rp_entries WHERE head_id=? AND entry_date BETWEEN ? AND ?",
        (head_id, d_from, d_to))


# ── R&P Statement ──────────────────────────────────────────────────────────────

def _build_rp(db, d_from, d_to):
    auto_r = _auto_receipts(db, d_from, d_to)
    auto_p = _auto_payments(db, d_from, d_to)

    rows_r = db.execute(
        "SELECT id, name, category, is_auto, lms_source "
        "FROM rp_heads WHERE type='Receipt' AND active=1 ORDER BY sort_order"
    ).fetchall()
    rows_p = db.execute(
        "SELECT id, name, category, is_auto, lms_source "
        "FROM rp_heads WHERE type='Payment' AND active=1 ORDER BY sort_order"
    ).fetchall()

    def resolve(rows, auto_map):
        cats = OrderedDict()
        for hid, name, cat, is_auto, src in rows:
            amt = auto_map.get(src, 0) if (is_auto and src) else _manual_amount(db, hid, d_from, d_to)
            cats.setdefault(cat, []).append({'name': name, 'amount': amt})
        return cats

    receipts = resolve(rows_r, auto_r)
    payments = resolve(rows_p, auto_p)

    total_r = sum(i['amount'] for items in receipts.values() for i in items)
    total_p = sum(i['amount'] for items in payments.values() for i in items)
    return receipts, payments, total_r, total_p


# ── Income & Expenditure (I&E) Account ────────────────────────────────────────

def _build_ie(db, d_from, d_to):
    # Income — auto from LMS + manual rp_entries for income-type heads
    auto_r = _auto_receipts(db, d_from, d_to)

    income = [
        {'name': 'Interest on Loans',      'amount': auto_r['rp_interest']},
        {'name': 'Processing Fees',         'amount': auto_r['loan_proc_fee']},
        {'name': 'Insurance Fees',          'amount': auto_r['loan_insurance']},
        {'name': 'Membership Fees',         'amount': auto_r['member_fees']},
        {'name': 'Penalty / Fine Income',   'amount': auto_r['rp_penalty']},
    ]

    # Manual income heads (from rp_entries whose head belongs to income receipt categories)
    manual_income_heads = db.execute(
        """SELECT rh.id, rh.name FROM rp_heads rh
           WHERE rh.type='Receipt' AND rh.is_auto=0
             AND rh.category IN ('Other Receipts','Funding & Capital')
             AND rh.active=1
           ORDER BY rh.sort_order"""
    ).fetchall()
    for hid, name in manual_income_heads:
        amt = _manual_amount(db, hid, d_from, d_to)
        if amt:
            income.append({'name': name, 'amount': amt})

    total_income = sum(i['amount'] for i in income)

    # Expenditure — from tally_vouchers grouped by tally_group
    exp_rows = db.execute(
        """SELECT tg.name, SUM(tv.amount) AS total
           FROM tally_vouchers tv
           JOIN tally_ledgers tl ON tl.id = tv.ledger_id
           JOIN tally_groups  tg ON tg.id = tl.group_id
           WHERE tg.nature = 'Expense'
             AND tv.voucher_date BETWEEN ? AND ?
           GROUP BY tg.id
           ORDER BY tg.sort_order""",
        (d_from, d_to)
    ).fetchall()

    # Also pull manual payment rp_entries as expenditure
    manual_exp_heads = db.execute(
        """SELECT rh.id, rh.name FROM rp_heads rh
           WHERE rh.type='Payment' AND rh.is_auto=0
             AND rh.category NOT IN ('Loan Disbursements','Closing Balances','Transfers','Capital Expenditure')
             AND rh.active=1
           ORDER BY rh.sort_order"""
    ).fetchall()
    extra_exp = []
    for hid, name in manual_exp_heads:
        amt = _manual_amount(db, hid, d_from, d_to)
        if amt:
            extra_exp.append({'name': name, 'amount': amt})

    total_exp = sum(r[1] for r in exp_rows) + sum(e['amount'] for e in extra_exp)
    surplus = total_income - total_exp

    return income, total_income, exp_rows, extra_exp, total_exp, surplus


# ── Trial Balance ──────────────────────────────────────────────────────────────

def _build_tb(db, d_to):
    d_from = '2000-01-01'  # inception-to-date for balance sheet items

    # ── Debit side ──
    debit = []

    # Loans outstanding = total disbursed − total principal recovered
    disbursed  = _scalar(db, "SELECT SUM(disbursed_amount) FROM loan_disbursements WHERE disbursement_date <= ?", (d_to,))
    recovered  = _scalar(db, "SELECT SUM(principal) FROM recovery_postings WHERE posting_date <= ?", (d_to,))
    loan_os    = disbursed - recovered
    debit.append({'name': 'Loans Outstanding to Members', 'nature': 'Asset',   'amount': loan_os})

    # Interest receivable = accrued interest on active loans (outstanding principal × rate estimate)
    # Simplified: interest billed (via recovery schedule) minus collected
    int_coll   = _scalar(db, "SELECT SUM(interest) FROM recovery_postings WHERE posting_date <= ?", (d_to,))
    debit.append({'name': 'Interest Receivable (approx.)', 'nature': 'Asset',  'amount': 0})  # requires schedule data

    # Member savings balance
    sav_dep    = _scalar(db, "SELECT SUM(deposit_amount) FROM savings_transactions WHERE transaction_date <= ?", (d_to,))
    sav_wit    = _scalar(db, "SELECT SUM(withdraw_amount) FROM savings_transactions WHERE transaction_date <= ?", (d_to,))

    # Cash & Bank from opening balance manual entries
    open_cash  = _manual_amount(db,
        _head_id(db, 'Opening Cash Balance'), '2000-01-01', d_to)
    open_bank  = _manual_amount(db,
        _head_id(db, 'Opening Bank Balance'), '2000-01-01', d_to)
    debit.append({'name': 'Cash in Hand',   'nature': 'Asset', 'amount': open_cash})
    debit.append({'name': 'Bank Balance',   'nature': 'Asset', 'amount': open_bank})

    # All expense groups (inception to date_to from tally_vouchers)
    exp_rows = db.execute(
        """SELECT tg.name, SUM(tv.amount) AS total
           FROM tally_vouchers tv
           JOIN tally_ledgers tl ON tl.id = tv.ledger_id
           JOIN tally_groups  tg ON tg.id = tl.group_id
           WHERE tg.nature = 'Expense' AND tv.voucher_date <= ?
           GROUP BY tg.id ORDER BY tg.sort_order""",
        (d_to,)
    ).fetchall()
    for name, amt in exp_rows:
        debit.append({'name': name, 'nature': 'Expense', 'amount': amt or 0})

    # Manual payment entries (staff, office, etc.) as debit
    manual_pay = db.execute(
        """SELECT rh.name, SUM(re.amount) FROM rp_entries re
           JOIN rp_heads rh ON rh.id = re.head_id
           WHERE rh.type='Payment' AND rh.is_auto=0
             AND rh.category NOT IN ('Loan Disbursements','Closing Balances','Transfers')
             AND re.entry_date <= ?
           GROUP BY rh.id ORDER BY rh.sort_order""",
        (d_to,)
    ).fetchall()
    for name, amt in manual_pay:
        if amt:
            debit.append({'name': name, 'nature': 'Expense', 'amount': amt})

    total_debit = sum(r['amount'] for r in debit)

    # ── Credit side ──
    credit = []

    # Income (inception to date_to)
    auto_r_all = _auto_receipts(db, '2000-01-01', d_to)
    credit.append({'name': 'Interest on Loans',   'nature': 'Income',    'amount': auto_r_all['rp_interest']})
    credit.append({'name': 'Processing Fees',      'nature': 'Income',    'amount': auto_r_all['loan_proc_fee']})
    credit.append({'name': 'Insurance Fees',       'nature': 'Income',    'amount': auto_r_all['loan_insurance']})
    credit.append({'name': 'Membership Fees',      'nature': 'Income',    'amount': auto_r_all['member_fees']})
    credit.append({'name': 'Penalty/Fine Income',  'nature': 'Income',    'amount': auto_r_all['rp_penalty']})

    # Member savings (liability)
    credit.append({'name': 'Savings Deposits from Members', 'nature': 'Liability', 'amount': sav_dep - sav_wit})

    # Capital / Borrowings from manual rp_entries
    capital_heads = db.execute(
        """SELECT rh.name, SUM(re.amount) FROM rp_entries re
           JOIN rp_heads rh ON rh.id = re.head_id
           WHERE rh.type='Receipt'
             AND rh.category = 'Funding & Capital'
             AND re.entry_date <= ?
           GROUP BY rh.id ORDER BY rh.sort_order""",
        (d_to,)
    ).fetchall()
    for name, amt in capital_heads:
        if amt:
            credit.append({'name': name, 'nature': 'Liability', 'amount': amt})

    # Other manual income receipts
    other_inc = db.execute(
        """SELECT rh.name, SUM(re.amount) FROM rp_entries re
           JOIN rp_heads rh ON rh.id = re.head_id
           WHERE rh.type='Receipt' AND rh.is_auto=0
             AND rh.category = 'Other Receipts'
             AND re.entry_date <= ?
           GROUP BY rh.id ORDER BY rh.sort_order""",
        (d_to,)
    ).fetchall()
    for name, amt in other_inc:
        if amt:
            credit.append({'name': name, 'nature': 'Income', 'amount': amt})

    total_credit = sum(r['amount'] for r in credit)

    # Balancing figure
    diff = total_debit - total_credit
    if diff > 0:
        credit.append({'name': 'Surplus (Profit)', 'nature': 'Liability', 'amount': diff})
        total_credit += diff
    elif diff < 0:
        debit.append({'name': 'Deficit (Loss)', 'nature': 'Asset', 'amount': -diff})
        total_debit += -diff

    return debit, credit, total_debit, total_credit


def _head_id(db, name):
    row = db.execute("SELECT id FROM rp_heads WHERE name=?", (name,)).fetchone()
    return row[0] if row else -1


# ── Routes ─────────────────────────────────────────────────────────────────────

@fin_stmt.route('/')
def index():
    if not session.get('branch_db'):
        return redirect(url_for('login'))
    return render_template('fin_statements/index.html')


@fin_stmt.route('/receipts-payments', methods=['GET', 'POST'])
def receipts_payments():
    if not session.get('branch_db'):
        return redirect(url_for('login'))
    db = _get_db()

    # Date range
    d_from_raw = request.args.get('from_date', '')
    d_to_raw   = request.args.get('to_date', '')
    d_from = _parse_date(d_from_raw) or _default_range()[0]
    d_to   = _parse_date(d_to_raw)   or _default_range()[1]

    # POST — add manual entry
    if request.method == 'POST':
        head_id    = request.form.get('head_id', type=int)
        entry_date = request.form.get('entry_date', '').strip()
        amount     = request.form.get('amount', type=float)
        narration  = request.form.get('narration', '').strip()
        if head_id and entry_date and amount:
            db.execute(
                "INSERT INTO rp_entries (head_id, entry_date, amount, narration, created_by) VALUES (?,?,?,?,?)",
                (head_id, entry_date, amount, narration, session.get('user_id'))
            )
            db.commit()
        return redirect(url_for('fin_stmt.receipts_payments',
                                from_date=d_from_raw, to_date=d_to_raw))

    receipts, payments, total_r, total_p = _build_rp(db, d_from, d_to)

    # All heads for the manual-entry form
    all_heads = db.execute(
        "SELECT id, name, type, category FROM rp_heads WHERE active=1 ORDER BY type, sort_order"
    ).fetchall()

    return render_template('fin_statements/receipts_payments.html',
        receipts=receipts, payments=payments,
        total_receipts=total_r, total_payments=total_p,
        from_date=_fmt(d_from), to_date=_fmt(d_to),
        all_heads=all_heads,
    )


@fin_stmt.route('/income-expenditure')
def income_expenditure():
    if not session.get('branch_db'):
        return redirect(url_for('login'))
    db = _get_db()

    d_from_raw = request.args.get('from_date', '')
    d_to_raw   = request.args.get('to_date', '')
    d_from = _parse_date(d_from_raw) or _default_range()[0]
    d_to   = _parse_date(d_to_raw)   or _default_range()[1]

    income, total_income, exp_rows, extra_exp, total_exp, surplus = _build_ie(db, d_from, d_to)

    return render_template('fin_statements/income_expenditure.html',
        income=income, total_income=total_income,
        exp_rows=exp_rows, extra_exp=extra_exp, total_exp=total_exp,
        surplus=surplus,
        from_date=_fmt(d_from), to_date=_fmt(d_to),
    )


@fin_stmt.route('/trial-balance')
def trial_balance():
    if not session.get('branch_db'):
        return redirect(url_for('login'))
    db = _get_db()

    d_to_raw = request.args.get('as_at', '')
    d_to     = _parse_date(d_to_raw) or date.today().strftime('%Y-%m-%d')

    debit, credit, total_debit, total_credit = _build_tb(db, d_to)

    return render_template('fin_statements/trial_balance.html',
        debit=debit, credit=credit,
        total_debit=total_debit, total_credit=total_credit,
        as_at=_fmt(d_to),
    )
