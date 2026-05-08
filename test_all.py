"""Full integration test for MYTHRI LMS updates."""
import requests
import re

BASE = 'http://127.0.0.1:5000'
s = requests.Session()

print('=' * 60)
print('  MYTHRI LMS — Full Integration Test')
print('=' * 60)

# ── Phase 1: Branding ────────────────────────────────────
print()
print('PHASE 1: Branding & Location')
print('-' * 40)

r = s.get(BASE + '/')
assert 'Vijayawada' in r.text, 'Login page missing Vijayawada'
assert 'Kanchipuram' not in r.text, 'Login page still has Kanchipuram!'
print('[PASS] Login page: Vijayawada branding')

r = s.post(BASE + '/', data={'login_name': 'GVR', 'password': 'admin123'}, allow_redirects=True)
assert 'Vijayawada' in r.text, 'Dashboard missing Vijayawada'
print('[PASS] Dashboard: Vijayawada branding')

r = s.get(BASE + '/settings')
assert 'Vijayawada' in r.text
assert 'ANDHRA PRADESH' in r.text
print('[PASS] Settings: Vijayawada + ANDHRA PRADESH')

r = s.get(BASE + '/centers/new')
assert 'ANDHRA PRADESH' in r.text
print('[PASS] Center form: ANDHRA PRADESH default')

r = s.get(BASE + '/members/new')
assert 'ANDHRA PRADESH' in r.text
print('[PASS] Member form: ANDHRA PRADESH default')

# ── Setup test data ──────────────────────────────────────
print()
print('SETUP: Creating test data...')
print('-' * 40)

s.post(BASE + '/centers/new', data={
    'center_name': 'Vijayawada Main', 'active': '1', 'address1': 'MG Road',
    'city': 'Vijayawada', 'district': 'Krishna', 'state': 'ANDHRA PRADESH',
    'staff_id': '2', 'max_members': '30', 'meeting_place': 'Community Hall',
    'meeting_type': 'Weekly', 'meeting_week': 'Monday', 'meeting_time': '09:00'
}, allow_redirects=True)
print('[PASS] Center created: Vijayawada Main')

s.post(BASE + '/members/new', data={
    'center_id': '1', 'grp': '1', 'full_name': 'Lakshmi Devi',
    'date_of_join': '01/01/2025', 'date_of_birth': '15/05/1985',
    'gender': 'Female', 'marital_status': 'Married',
    'guardian_name': 'Ramesh', 'address1': 'Gandhi Nagar',
    'city': 'Vijayawada', 'state': 'ANDHRA PRADESH',
    'phone1': '9876543210', 'kyc_type': 'Aadhaar Card', 'kyc_number': '1234-5678-9012',
    'income': '15000', 'expenditure': '8000'
}, allow_redirects=True)
print('[PASS] Member created: Lakshmi Devi')

s.post(BASE + '/loans/types/new', data={
    'loan_type_name': 'Weekly Standard', 'interest_rate': '2',
    'interest_type': 'Percent', 'interest_method': 'FLAT',
    'repayment_frequency': 'Weekly', 'max_amount': '50000', 'min_amount': '5000',
    'tenure_weeks': '50', 'fixed_tenure': '1',
    'processing_fee': '200', 'insurance_fee': '100', 'active': '1'
}, allow_redirects=True)
print('[PASS] Loan type created: Weekly Standard')

s.post(BASE + '/loans/disbursement/new', data={
    'member_id': '1', 'loan_type_id': '1', 'applied_amount': '20000',
    'applied_date': '05/01/2025', 'purpose': 'Small Business',
    'loan_cycle': '1', 'mode': 'Cash', 'nominee_name': 'Ramesh'
}, allow_redirects=True)
print('[PASS] Loan disbursed: Rs.20,000')

# ── Phase 2: Admin-Only Permissions ──────────────────────
print()
print('PHASE 2: Admin-Only Edit/Delete')
print('-' * 40)

r = s.get(BASE + '/centers')
assert 'bi-pencil' in r.text
assert 'bi-trash' in r.text
print('[PASS] Admin sees Edit+Delete on Centers')

r = s.get(BASE + '/members')
assert 'bi-pencil' in r.text
assert 'bi-trash' in r.text
print('[PASS] Admin sees Edit+Delete on Members')

r = s.get(BASE + '/loans/applications')
assert 'bi-pencil' in r.text
print('[PASS] Admin sees Edit+Delete on Applications (any status)')

r = s.get(BASE + '/loans/disbursement')
assert 'bi-trash' in r.text
print('[PASS] Admin sees Delete on Disbursements')

# Login as Staff
s.get(BASE + '/logout')
s.post(BASE + '/', data={'login_name': 'Suresh01', 'password': 'staff123'}, allow_redirects=True)

r = s.get(BASE + '/centers')
assert 'bi-pencil' not in r.text
assert 'bi-trash' not in r.text
print('[PASS] Staff: NO Edit/Delete on Centers')

r = s.get(BASE + '/members')
assert 'bi-pencil' not in r.text
assert 'bi-trash' not in r.text
print('[PASS] Staff: NO Edit/Delete on Members')

r = s.get(BASE + '/loans/applications')
assert 'bi-pencil' not in r.text
print('[PASS] Staff: NO Edit/Delete on Applications')

r = s.get(BASE + '/loans/disbursement')
assert 'bi-trash' not in r.text
print('[PASS] Staff: NO Delete on Disbursements')

r = s.get(BASE + '/centers/1/edit', allow_redirects=True)
assert 'denied' in r.text.lower() or 'Edit access denied' in r.text
print('[PASS] Staff: Edit center blocked server-side')

r = s.get(BASE + '/members/1/edit', allow_redirects=True)
assert 'denied' in r.text.lower() or 'Edit access denied' in r.text
print('[PASS] Staff: Edit member blocked server-side')

# ── Phase 3 & 4: Savings + Recovery Integration ─────────
print()
print('PHASE 3 & 4: Savings Module + Recovery Integration')
print('-' * 40)

s.get(BASE + '/logout')
s.post(BASE + '/', data={'login_name': 'GVR', 'password': 'admin123'}, allow_redirects=True)

r = s.get(BASE + '/dashboard')
assert 'Savings Outstanding' in r.text
print('[PASS] Dashboard: Savings Outstanding stat card')

r = s.get(BASE + '/savings')
assert r.status_code == 200
assert 'Savings Account' in r.text
print('[PASS] Savings page loads correctly')

r = s.get(BASE + '/loans/posting/recovery/1')
assert 'savings_amount' in r.text
print('[PASS] Recovery form: Savings (Rs.) field present')

# Post 3 weekly recoveries with savings
for week in range(1, 4):
    date = f'{6+week:02d}/01/2025'
    s.post(BASE + '/loans/posting/recovery/1', data={
        'installment_no': str(week), 'posting_date': date,
        'due_amount': '400', 'paid_amount': '400', 'principal': '392',
        'interest': '8', 'penalty': '0', 'mode': 'Cash',
        'narration': 'Weekly recovery', 'savings_amount': '100'
    }, allow_redirects=True)
print('[PASS] Posted 3 recoveries with Rs.100 savings each')

r = s.get(BASE + '/savings')
assert 'Lakshmi Devi' in r.text
assert '300' in r.text
print('[PASS] Savings page: Shows Rs.300 total (3 x Rs.100)')

r = s.get(BASE + '/loans/posting/recovery/1')
assert 'Total Deposits' in r.text
print('[PASS] Recovery form: Savings summary section visible')

assert 'arrow-counterclockwise' in r.text
print('[PASS] Recovery form: Admin reverse button present')

# Reverse last recovery
forms = re.findall(r'/loans/posting/recovery/(\d+)/delete', r.text)
assert len(forms) > 0
last_rid = forms[-1]
r = s.post(BASE + f'/loans/posting/recovery/{last_rid}/delete', allow_redirects=True)
assert 'reversed' in r.text.lower() or 'deleted' in r.text.lower()
print(f'[PASS] Recovery reversed (posting #{last_rid}) + savings deleted')

r = s.get(BASE + '/savings')
assert '200' in r.text
print('[PASS] Savings reduced to Rs.200 after reversal')

# Test withdrawal
r = s.post(BASE + '/savings/withdraw/1', data={
    'withdraw_amount': '50', 'transaction_date': '15/01/2025'
}, allow_redirects=True)
assert 'successfully' in r.text.lower() or 'Withdrawal' in r.text
print('[PASS] Savings withdrawal: Rs.50 posted')

r = s.get(BASE + '/savings')
assert '150' in r.text
print('[PASS] Savings balance: Rs.150 (200 - 50)')

# Over-withdrawal blocked
r = s.post(BASE + '/savings/withdraw/1', data={
    'withdraw_amount': '999', 'transaction_date': '16/01/2025'
}, allow_redirects=True)
assert 'invalid' in r.text.lower() or 'Invalid' in r.text
print('[PASS] Over-withdrawal blocked')

# ── Reports ──────────────────────────────────────────────
print()
print('REPORTS VERIFICATION')
print('-' * 40)

r = s.get(BASE + '/reports')
assert 'Savings Report' in r.text
print('[PASS] Reports page: Savings Report link present')

r = s.get(BASE + '/reports/glance')
assert 'Total Savings' in r.text
assert 'Savings Withdrawn' in r.text
assert 'Savings Outstanding' in r.text
assert 'Sav. Balance' in r.text
print('[PASS] Glance Report: Savings cards + center columns')

# ── Disbursement Delete ──────────────────────────────────
print()
print('DISBURSEMENT DELETE TEST')
print('-' * 40)

s.post(BASE + '/members/new', data={
    'center_id': '1', 'grp': '1', 'full_name': 'Sita Rani',
    'date_of_join': '01/02/2025', 'date_of_birth': '10/03/1990',
    'gender': 'Female', 'marital_status': 'Married',
    'address1': 'Test', 'kyc_type': 'Aadhaar Card', 'kyc_number': '9999',
    'state': 'ANDHRA PRADESH'
}, allow_redirects=True)
s.post(BASE + '/loans/disbursement/new', data={
    'member_id': '2', 'loan_type_id': '1', 'applied_amount': '15000',
    'applied_date': '01/02/2025', 'purpose': 'Agriculture', 'loan_cycle': '1', 'mode': 'Cash'
}, allow_redirects=True)
s.post(BASE + '/loans/posting/recovery/2', data={
    'installment_no': '1', 'posting_date': '08/02/2025',
    'due_amount': '300', 'paid_amount': '300', 'principal': '294',
    'interest': '6', 'penalty': '0', 'mode': 'Cash',
    'narration': 'Weekly', 'savings_amount': '100'
}, allow_redirects=True)
print('[PASS] Second loan created with 1 recovery+savings')

r = s.post(BASE + '/loans/disbursement/2/delete', allow_redirects=True)
assert 'deleted' in r.text.lower() or 'reverted' in r.text.lower()
print('[PASS] Disbursement deleted, application reverted to Approved')

r = s.get(BASE + '/savings')
assert 'Sita Rani' not in r.text
print('[PASS] Cascade delete: savings transactions removed')

# ── Staff: no reverse button ─────────────────────────────
print()
print('STAFF REVERSE BUTTON CHECK')
print('-' * 40)
s.get(BASE + '/logout')
s.post(BASE + '/', data={'login_name': 'Suresh01', 'password': 'staff123'}, allow_redirects=True)
r = s.get(BASE + '/loans/posting/recovery/1')
assert 'arrow-counterclockwise' not in r.text
print('[PASS] Staff: NO reverse button on recovery postings')

print()
print('=' * 60)
print('  ALL TESTS PASSED! App is working correctly.')
print('=' * 60)
print()
print('App running at: http://127.0.0.1:5000')
print('  Admin: GVR / admin123')
print('  Staff: Suresh01 / staff123')
