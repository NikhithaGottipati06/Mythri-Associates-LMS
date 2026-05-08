from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from database import get_db, init_db
from functools import wraps
import os
import json
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'mythri-lms-secret-2024')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

LOAN_PURPOSES = [
    'Agriculture', 'Animal Husbandry', 'Buffalo', 'Cow', 'Goat',
    'Vegetable Business', 'Small Business', 'Trading', 'Tailoring',
    'Cloth Business', 'Grocery', 'Hotel / Tiffin', 'Auto / Vehicle',
    'Education', 'Medical / Health', 'Housing / Repair', 'Other'
]

KYC_TYPES = ['Aadhaar Card', 'PAN Card', 'Voter ID', 'Driving Licence',
             'Ration Card', 'Passport', 'Other']

# ── Auth decorators ────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'Admin':
            flash('Access denied. Admin only.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

def get_current_user():
    return {'id': session.get('user_id'), 'role': session.get('role'),
            'full_name': session.get('full_name'), 'login_name': session.get('login_name')}

app.jinja_env.globals['get_current_user'] = get_current_user

@app.context_processor
def inject_now():
    return {'now': datetime.now().strftime('%A %d-%b-%Y')}

# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    error = None
    if request.method == 'POST':
        login_name = request.form.get('login_name', '').strip()
        password = request.form.get('password', '').strip()
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE login_name=? AND active=1", (login_name,)
        ).fetchone()
        db.close()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            session['login_name'] = user['login_name']
            return redirect(url_for('dashboard'))
        error = 'Invalid username or password.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    stats = {
        'centers': db.execute("SELECT COUNT(*) FROM centers WHERE active=1").fetchone()[0],
        'members': db.execute("SELECT COUNT(*) FROM members WHERE status='ACTIVE'").fetchone()[0],
        'applications': db.execute("SELECT COUNT(*) FROM loan_applications").fetchone()[0],
        'disbursements': db.execute("SELECT COUNT(*) FROM loan_disbursements").fetchone()[0],
        'savings_outstanding': db.execute("SELECT COALESCE(SUM(deposit_amount),0) - COALESCE(SUM(withdraw_amount),0) FROM savings_transactions").fetchone()[0],
    }
    db.close()
    return render_template('dashboard.html', stats=stats)

# ── Users ─────────────────────────────────────────────────────────────────────

@app.route('/users')
@admin_required
def users_list():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    db.close()
    return render_template('users/list.html', users=users)

@app.route('/users/new', methods=['GET', 'POST'])
@admin_required
def users_new():
    if request.method == 'POST':
        db = get_db()
        try:
            db.execute(
                "INSERT INTO users (full_name, role, joining_date, login_name, email, password_hash, active) VALUES (?,?,?,?,?,?,?)",
                (request.form['full_name'], request.form['role'], request.form['joining_date'],
                 request.form['login_name'], request.form.get('email',''),
                 generate_password_hash(request.form['password']),
                 1 if request.form.get('active') else 0)
            )
            db.commit()
            flash('User added successfully.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'danger')
        finally:
            db.close()
        return redirect(url_for('users_list'))
    return render_template('users/form.html', user=None)

@app.route('/users/<int:uid>/edit', methods=['GET', 'POST'])
@admin_required
def users_edit(uid):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if request.method == 'POST':
        pw = request.form.get('password', '').strip()
        if pw:
            pw_hash = generate_password_hash(pw)
            db.execute(
                "UPDATE users SET full_name=?,role=?,joining_date=?,login_name=?,email=?,password_hash=?,active=? WHERE id=?",
                (request.form['full_name'], request.form['role'], request.form['joining_date'],
                 request.form['login_name'], request.form.get('email',''), pw_hash,
                 1 if request.form.get('active') else 0, uid)
            )
        else:
            db.execute(
                "UPDATE users SET full_name=?,role=?,joining_date=?,login_name=?,email=?,active=? WHERE id=?",
                (request.form['full_name'], request.form['role'], request.form['joining_date'],
                 request.form['login_name'], request.form.get('email',''),
                 1 if request.form.get('active') else 0, uid)
            )
        db.commit()
        db.close()
        flash('User updated.', 'success')
        return redirect(url_for('users_list'))
    db.close()
    return render_template('users/form.html', user=user)

@app.route('/users/<int:uid>/delete', methods=['POST'])
@admin_required
def users_delete(uid):
    if uid == session['user_id']:
        flash('Cannot delete yourself.', 'danger')
        return redirect(url_for('users_list'))
    db = get_db()
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    db.close()
    flash('User deleted.', 'success')
    return redirect(url_for('users_list'))

# ── Centers ───────────────────────────────────────────────────────────────────

@app.route('/centers')
@login_required
def centers_list():
    db = get_db()
    centers = db.execute("""
        SELECT c.*, u.full_name as staff_name
        FROM centers c LEFT JOIN users u ON c.staff_id=u.id
        ORDER BY c.center_code
    """).fetchall()
    db.close()
    return render_template('centers/list.html', centers=centers)

@app.route('/centers/new', methods=['GET', 'POST'])
@login_required
def centers_new():
    db = get_db()
    if request.method == 'POST':
        last = db.execute("SELECT center_code FROM centers ORDER BY id DESC LIMIT 1").fetchone()
        if last:
            num = int(last['center_code'][1:]) + 1
        else:
            num = 1
        code = f"C{num:03d}"
        try:
            db.execute("""
                INSERT INTO centers (center_code,center_name,active,address1,address2,city,mandal,
                pin_code,district,state,landmark,notes,staff_id,max_members,
                meeting_place,meeting_type,meeting_week,meeting_time)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (code, request.form['center_name'],
                  1 if request.form.get('active') else 0,
                  request.form.get('address1',''), request.form.get('address2',''),
                  request.form.get('city',''), request.form.get('mandal',''),
                  request.form.get('pin_code',''), request.form.get('district',''),
                  request.form.get('state','ANDHRA PRADESH'), request.form.get('landmark',''),
                  request.form.get('notes',''),
                  request.form.get('staff_id') or None,
                  request.form.get('max_members', 30),
                  request.form.get('meeting_place',''), request.form.get('meeting_type','Weekly'),
                  request.form.get('meeting_week',''), request.form.get('meeting_time','')))
            db.commit()
            flash('Center added successfully.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'danger')
        finally:
            db.close()
        return redirect(url_for('centers_list'))
    staff = db.execute("SELECT id, full_name FROM users WHERE active=1").fetchall()
    db.close()
    return render_template('centers/form.html', center=None, staff=staff)

@app.route('/centers/<int:cid>/edit', methods=['GET', 'POST'])
@login_required
def centers_edit(cid):
    db = get_db()
    center = db.execute("SELECT * FROM centers WHERE id=?", (cid,)).fetchone()
    if session['role'] != 'Admin':
        flash('Edit access denied.', 'danger')
        db.close()
        return redirect(url_for('centers_list'))
    if request.method == 'POST':
        db.execute("""
            UPDATE centers SET center_name=?,active=?,address1=?,address2=?,city=?,mandal=?,
            pin_code=?,district=?,state=?,landmark=?,notes=?,staff_id=?,max_members=?,
            meeting_place=?,meeting_type=?,meeting_week=?,meeting_time=? WHERE id=?
        """, (request.form['center_name'], 1 if request.form.get('active') else 0,
              request.form.get('address1',''), request.form.get('address2',''),
              request.form.get('city',''), request.form.get('mandal',''),
              request.form.get('pin_code',''), request.form.get('district',''),
              request.form.get('state','ANDHRA PRADESH'), request.form.get('landmark',''),
              request.form.get('notes',''), request.form.get('staff_id') or None,
              request.form.get('max_members', 30),
              request.form.get('meeting_place',''), request.form.get('meeting_type','Weekly'),
              request.form.get('meeting_week',''), request.form.get('meeting_time',''), cid))
        db.commit()
        db.close()
        flash('Center updated.', 'success')
        return redirect(url_for('centers_list'))
    staff = db.execute("SELECT id, full_name FROM users WHERE active=1").fetchall()
    db.close()
    return render_template('centers/form.html', center=center, staff=staff)

@app.route('/centers/<int:cid>/delete', methods=['POST'])
@admin_required
def centers_delete(cid):
    db = get_db()
    db.execute("DELETE FROM centers WHERE id=?", (cid,))
    db.commit()
    db.close()
    flash('Center deleted.', 'success')
    return redirect(url_for('centers_list'))

# ── Members ───────────────────────────────────────────────────────────────────

@app.route('/members')
@login_required
def members_list():
    db = get_db()
    members = db.execute("""
        SELECT m.*, c.center_name, c.center_code FROM members m
        LEFT JOIN centers c ON m.center_id=c.id ORDER BY m.member_code
    """).fetchall()
    db.close()
    return render_template('members/list.html', members=members)

@app.route('/members/new', methods=['GET', 'POST'])
@login_required
def members_new():
    db = get_db()
    if request.method == 'POST':
        last = db.execute("SELECT member_code FROM members ORDER BY id DESC LIMIT 1").fetchone()
        if last:
            num = int(last['member_code'][1:]) + 1
        else:
            num = 1
        code = f"M{num:04d}"
        try:
            db.execute("""
                INSERT INTO members (member_code,center_id,grp,full_name,date_of_join,date_of_birth,
                gender,marital_status,guardian_name,spouse_name,caste,religion,
                address1,address2,city,mandal,pin_code,district,state,landmark,
                phone1,phone2,email,notes,income,expenditure,total_fees,fee_mode,fee_narration,
                kyc_type,kyc_number,status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (code, request.form.get('center_id') or None,
                  request.form.get('grp', 1), request.form['full_name'],
                  request.form.get('date_of_join',''), request.form.get('date_of_birth',''),
                  request.form.get('gender',''), request.form.get('marital_status',''),
                  request.form.get('guardian_name',''), request.form.get('spouse_name',''),
                  request.form.get('caste',''), request.form.get('religion',''),
                  request.form.get('address1',''), request.form.get('address2',''),
                  request.form.get('city',''), request.form.get('mandal',''),
                  request.form.get('pin_code',''), request.form.get('district',''),
                  request.form.get('state','ANDHRA PRADESH'), request.form.get('landmark',''),
                  request.form.get('phone1',''), request.form.get('phone2',''),
                  request.form.get('email',''), request.form.get('notes',''),
                  request.form.get('income', 0), request.form.get('expenditure', 0),
                  request.form.get('total_fees', 0), request.form.get('fee_mode','Cash'),
                  request.form.get('fee_narration','Cash'),
                  request.form.get('kyc_type',''), request.form.get('kyc_number',''), 'ACTIVE'))
            db.commit()
            flash('Member added successfully.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'danger')
        finally:
            db.close()
        return redirect(url_for('members_list'))
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('members/form.html', member=None, centers=centers)

@app.route('/members/<int:mid>/edit', methods=['GET', 'POST'])
@login_required
def members_edit(mid):
    if session['role'] != 'Admin':
        flash('Edit access denied.', 'danger')
        return redirect(url_for('members_list'))
    db = get_db()
    member = db.execute("SELECT * FROM members WHERE id=?", (mid,)).fetchone()
    if request.method == 'POST':
        db.execute("""
            UPDATE members SET center_id=?,grp=?,full_name=?,date_of_join=?,date_of_birth=?,
            gender=?,marital_status=?,guardian_name=?,spouse_name=?,caste=?,religion=?,
            address1=?,address2=?,city=?,mandal=?,pin_code=?,district=?,state=?,landmark=?,
            phone1=?,phone2=?,email=?,notes=?,income=?,expenditure=?,total_fees=?,
            fee_mode=?,fee_narration=?,kyc_type=?,kyc_number=? WHERE id=?
        """, (request.form.get('center_id') or None, request.form.get('grp',1),
              request.form['full_name'], request.form.get('date_of_join',''),
              request.form.get('date_of_birth',''), request.form.get('gender',''),
              request.form.get('marital_status',''), request.form.get('guardian_name',''),
              request.form.get('spouse_name',''), request.form.get('caste',''),
              request.form.get('religion',''), request.form.get('address1',''),
              request.form.get('address2',''), request.form.get('city',''),
              request.form.get('mandal',''), request.form.get('pin_code',''),
              request.form.get('district',''), request.form.get('state','ANDHRA PRADESH'),
              request.form.get('landmark',''), request.form.get('phone1',''),
              request.form.get('phone2',''), request.form.get('email',''),
              request.form.get('notes',''), request.form.get('income',0),
              request.form.get('expenditure',0), request.form.get('total_fees',0),
              request.form.get('fee_mode','Cash'), request.form.get('fee_narration','Cash'),
              request.form.get('kyc_type',''), request.form.get('kyc_number',''), mid))
        db.commit()
        db.close()
        flash('Member updated.', 'success')
        return redirect(url_for('members_list'))
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('members/form.html', member=member, centers=centers)

@app.route('/members/<int:mid>/delete', methods=['POST'])
@admin_required
def members_delete(mid):
    db = get_db()
    db.execute("DELETE FROM members WHERE id=?", (mid,))
    db.commit()
    db.close()
    flash('Member deleted.', 'success')
    return redirect(url_for('members_list'))

@app.route('/members/<int:mid>/withdraw', methods=['POST'])
@admin_required
def members_withdraw(mid):
    db = get_db()
    db.execute("UPDATE members SET status='WITHDRAWN' WHERE id=?", (mid,))
    db.commit()
    db.close()
    flash('Member withdrawn.', 'warning')
    return redirect(url_for('members_list'))

# ── Member data API (for auto-fill) ──────────────────────────────────────────

@app.route('/api/member/<int:mid>')
@login_required
def api_member(mid):
    db = get_db()
    m = db.execute("SELECT id,center_id,income,kyc_type,kyc_number FROM members WHERE id=?", (mid,)).fetchone()
    db.close()
    if m:
        return jsonify(dict(m))
    return jsonify({})

@app.route('/api/loantype/<int:lid>')
@login_required
def api_loantype(lid):
    db = get_db()
    lt = db.execute("SELECT id,tenure_weeks,processing_fee,insurance_fee,interest_rate FROM loan_types WHERE id=?", (lid,)).fetchone()
    db.close()
    if lt:
        return jsonify(dict(lt))
    return jsonify({})

# ── Loan Types ────────────────────────────────────────────────────────────────

@app.route('/loans/types')
@login_required
def loan_types_list():
    db = get_db()
    types = db.execute("SELECT * FROM loan_types ORDER BY loan_type_code").fetchall()
    db.close()
    return render_template('loans/types/list.html', types=types)

@app.route('/loans/types/new', methods=['GET', 'POST'])
@login_required
def loan_types_new():
    if request.method == 'POST':
        db = get_db()
        last = db.execute("SELECT loan_type_code FROM loan_types ORDER BY id DESC LIMIT 1").fetchone()
        num = int(last['loan_type_code'][2:]) + 1 if last else 1
        code = f"LT{num:03d}"
        try:
            db.execute("""
                INSERT INTO loan_types (loan_type_code,loan_type_name,interest_rate,interest_type,
                interest_method,repayment_frequency,max_amount,min_amount,tenure_weeks,fixed_tenure,
                processing_fee,insurance_fee,active,notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (code, request.form['loan_type_name'],
                  request.form.get('interest_rate', 0),
                  request.form.get('interest_type', 'Percent'),
                  request.form.get('interest_method', 'FLAT'),
                  request.form.get('repayment_frequency', 'Weekly'),
                  request.form.get('max_amount', 0),
                  request.form.get('min_amount', 0),
                  request.form.get('tenure_weeks', 50),
                  1 if request.form.get('fixed_tenure') else 0,
                  request.form.get('processing_fee', 0),
                  request.form.get('insurance_fee', 0),
                  1 if request.form.get('active') else 0,
                  request.form.get('notes', '')))
            db.commit()
            flash('Loan type added.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'danger')
        finally:
            db.close()
        return redirect(url_for('loan_types_list'))
    return render_template('loans/types/form.html', lt=None)

@app.route('/loans/types/<int:lid>/edit', methods=['GET', 'POST'])
@admin_required
def loan_types_edit(lid):
    db = get_db()
    lt = db.execute("SELECT * FROM loan_types WHERE id=?", (lid,)).fetchone()
    if request.method == 'POST':
        db.execute("""
            UPDATE loan_types SET loan_type_name=?,interest_rate=?,interest_type=?,interest_method=?,
            repayment_frequency=?,max_amount=?,min_amount=?,tenure_weeks=?,fixed_tenure=?,
            processing_fee=?,insurance_fee=?,active=?,notes=? WHERE id=?
        """, (request.form['loan_type_name'],
              request.form.get('interest_rate', 0),
              request.form.get('interest_type', 'Percent'),
              request.form.get('interest_method', 'FLAT'),
              request.form.get('repayment_frequency', 'Weekly'),
              request.form.get('max_amount', 0),
              request.form.get('min_amount', 0),
              request.form.get('tenure_weeks', 50),
              1 if request.form.get('fixed_tenure') else 0,
              request.form.get('processing_fee', 0),
              request.form.get('insurance_fee', 0),
              1 if request.form.get('active') else 0,
              request.form.get('notes', ''), lid))
        db.commit()
        db.close()
        flash('Loan type updated.', 'success')
        return redirect(url_for('loan_types_list'))
    db.close()
    return render_template('loans/types/form.html', lt=lt)

@app.route('/loans/types/<int:lid>/delete', methods=['POST'])
@admin_required
def loan_types_delete(lid):
    db = get_db()
    db.execute("DELETE FROM loan_types WHERE id=?", (lid,))
    db.commit()
    db.close()
    flash('Loan type deleted.', 'success')
    return redirect(url_for('loan_types_list'))

# ── Prepaid Types ─────────────────────────────────────────────────────────────

@app.route('/loans/prepaid-types')
@login_required
def prepaid_types_list():
    db = get_db()
    types = db.execute("""
        SELECT pt.*, lt.loan_type_name FROM prepaid_types pt
        LEFT JOIN loan_types lt ON pt.loan_type_id=lt.id
        ORDER BY pt.code
    """).fetchall()
    db.close()
    return render_template('loans/prepaid_types/list.html', types=types)

@app.route('/loans/prepaid-types/new', methods=['GET', 'POST'])
@login_required
def prepaid_types_new():
    db = get_db()
    if request.method == 'POST':
        last = db.execute("SELECT code FROM prepaid_types ORDER BY id DESC LIMIT 1").fetchone()
        num = int(last['code'][2:]) + 1 if last else 1
        code = f"PT{num:03d}"
        try:
            db.execute("""INSERT INTO prepaid_types
                (code,name,type,loan_type_id,active,member_expired,full_interest,has_preclosure_charges)
                VALUES (?,?,?,?,?,?,?,?)""",
                (code, request.form['name'],
                 request.form.get('type', 'Weekly'),
                 request.form.get('loan_type_id') or None,
                 1 if request.form.get('active') else 0,
                 1 if request.form.get('member_expired') else 0,
                 1 if request.form.get('full_interest') else 0,
                 1 if request.form.get('has_preclosure_charges') else 0))
            db.commit()
            flash('Prepaid type added.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'danger')
        finally:
            db.close()
        return redirect(url_for('prepaid_types_list'))
    loan_types = db.execute("SELECT id, loan_type_name FROM loan_types WHERE active=1").fetchall()
    db.close()
    return render_template('loans/prepaid_types/form.html', pt=None, loan_types=loan_types)

@app.route('/loans/prepaid-types/<int:pid>/edit', methods=['GET', 'POST'])
@admin_required
def prepaid_types_edit(pid):
    db = get_db()
    pt = db.execute("SELECT * FROM prepaid_types WHERE id=?", (pid,)).fetchone()
    if request.method == 'POST':
        db.execute("""UPDATE prepaid_types SET name=?,type=?,loan_type_id=?,active=?,
                member_expired=?,full_interest=?,has_preclosure_charges=? WHERE id=?""",
                   (request.form['name'],
                    request.form.get('type', 'Weekly'),
                    request.form.get('loan_type_id') or None,
                    1 if request.form.get('active') else 0,
                    1 if request.form.get('member_expired') else 0,
                    1 if request.form.get('full_interest') else 0,
                    1 if request.form.get('has_preclosure_charges') else 0, pid))
        db.commit()
        db.close()
        flash('Prepaid type updated.', 'success')
        return redirect(url_for('prepaid_types_list'))
    loan_types = db.execute("SELECT id, loan_type_name FROM loan_types WHERE active=1").fetchall()
    db.close()
    return render_template('loans/prepaid_types/form.html', pt=pt, loan_types=loan_types)

@app.route('/loans/prepaid-types/<int:pid>/delete', methods=['POST'])
@admin_required
def prepaid_types_delete(pid):
    db = get_db()
    db.execute("DELETE FROM prepaid_types WHERE id=?", (pid,))
    db.commit()
    db.close()
    flash('Prepaid type deleted.', 'success')
    return redirect(url_for('prepaid_types_list'))

# ── Loan Applications ─────────────────────────────────────────────────────────

@app.route('/loans/applications')
@login_required
def loan_applications_list():
    db = get_db()
    apps = db.execute("""
        SELECT la.*, m.full_name as member_name, m.member_code,
               c.center_name, c.center_code as c_code, c.meeting_type as center_type,
               lt.loan_type_name,
               ld.disbursement_date, ld.loan_id,
               apr.approved_amount, apr.approved_date as approved_on,
               u_cr.full_name as created_by_name,
               u_ap.full_name as approved_by_name
        FROM loan_applications la
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        LEFT JOIN loan_disbursements ld ON ld.application_id=la.id
        LEFT JOIN loan_approvals apr ON apr.application_id=la.id
        LEFT JOIN users u_cr ON la.created_by=u_cr.id
        LEFT JOIN users u_ap ON apr.approved_by=u_ap.id
        ORDER BY la.id DESC
    """).fetchall()
    db.close()
    return render_template('loans/applications/list.html', apps=apps)

@app.route('/loans/applications/new', methods=['GET', 'POST'])
@login_required
def loan_applications_new():
    db = get_db()
    if request.method == 'POST':
        last = db.execute("SELECT application_no FROM loan_applications ORDER BY id DESC LIMIT 1").fetchone()
        num = int(last['application_no'][3:]) + 1 if last else 1
        app_no = f"APP{num:06d}"
        try:
            db.execute("""
                INSERT INTO loan_applications (application_no,member_id,center_id,loan_type_id,
                applied_amount,applied_date,purpose,status,remarks,created_by,
                nominee_name,monthly_net_income,loan_cycle,member_kyc_type,member_kyc_number,
                nominee_kyc_type,nominee_kyc_number,processing_fee,insurance_fee,
                nominee_insurance_fee,other_charges)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (app_no, request.form.get('member_id') or None,
                  request.form.get('center_id') or None,
                  request.form.get('loan_type_id') or None,
                  request.form.get('applied_amount', 0),
                  request.form.get('applied_date', datetime.now().strftime('%d/%m/%Y')),
                  request.form.get('purpose', ''), 'Pending',
                  request.form.get('remarks', ''), session['user_id'],
                  request.form.get('nominee_name', ''),
                  request.form.get('monthly_net_income', 0),
                  request.form.get('loan_cycle', 1),
                  request.form.get('member_kyc_type', ''),
                  request.form.get('member_kyc_number', ''),
                  request.form.get('nominee_kyc_type', ''),
                  request.form.get('nominee_kyc_number', ''),
                  request.form.get('processing_fee', 0),
                  request.form.get('insurance_fee', 0),
                  request.form.get('nominee_insurance_fee', 0),
                  request.form.get('other_charges', 0)))
            db.commit()
            flash('Loan application submitted.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'danger')
        finally:
            db.close()
        return redirect(url_for('loan_applications_list'))
    members = db.execute(
        "SELECT id, member_code, full_name, center_id, income, kyc_type, kyc_number FROM members WHERE status='ACTIVE'"
    ).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    loan_types = db.execute(
        "SELECT id, loan_type_code, loan_type_name, tenure_weeks, processing_fee, insurance_fee FROM loan_types WHERE active=1"
    ).fetchall()
    members_json = json.dumps([dict(m) for m in members])
    loan_types_json = json.dumps([dict(lt) for lt in loan_types])
    db.close()
    return render_template('loans/applications/form.html', app=None,
                           members=members, centers=centers, loan_types=loan_types,
                           members_json=members_json, loan_types_json=loan_types_json,
                           loan_purposes=LOAN_PURPOSES, kyc_types=KYC_TYPES)

@app.route('/loans/applications/<int:aid>/edit', methods=['GET', 'POST'])
@admin_required
def loan_applications_edit(aid):
    db = get_db()
    application = db.execute("SELECT * FROM loan_applications WHERE id=?", (aid,)).fetchone()
    if request.method == 'POST':
        db.execute("""
            UPDATE loan_applications SET member_id=?,center_id=?,loan_type_id=?,
            applied_amount=?,applied_date=?,purpose=?,remarks=?,
            nominee_name=?,monthly_net_income=?,loan_cycle=?,
            member_kyc_type=?,member_kyc_number=?,nominee_kyc_type=?,nominee_kyc_number=?,
            processing_fee=?,insurance_fee=?,nominee_insurance_fee=?,other_charges=? WHERE id=?
        """, (request.form.get('member_id') or None, request.form.get('center_id') or None,
              request.form.get('loan_type_id') or None, request.form.get('applied_amount', 0),
              request.form.get('applied_date', ''), request.form.get('purpose', ''),
              request.form.get('remarks', ''),
              request.form.get('nominee_name', ''),
              request.form.get('monthly_net_income', 0),
              request.form.get('loan_cycle', 1),
              request.form.get('member_kyc_type', ''),
              request.form.get('member_kyc_number', ''),
              request.form.get('nominee_kyc_type', ''),
              request.form.get('nominee_kyc_number', ''),
              request.form.get('processing_fee', 0),
              request.form.get('insurance_fee', 0),
              request.form.get('nominee_insurance_fee', 0),
              request.form.get('other_charges', 0), aid))
        db.commit()
        db.close()
        flash('Application updated.', 'success')
        return redirect(url_for('loan_applications_list'))
    members = db.execute(
        "SELECT id, member_code, full_name, center_id, income, kyc_type, kyc_number FROM members WHERE status='ACTIVE'"
    ).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    loan_types = db.execute(
        "SELECT id, loan_type_code, loan_type_name, tenure_weeks, processing_fee, insurance_fee FROM loan_types WHERE active=1"
    ).fetchall()
    members_json = json.dumps([dict(m) for m in members])
    loan_types_json = json.dumps([dict(lt) for lt in loan_types])
    db.close()
    return render_template('loans/applications/form.html', app=application,
                           members=members, centers=centers, loan_types=loan_types,
                           members_json=members_json, loan_types_json=loan_types_json,
                           loan_purposes=LOAN_PURPOSES, kyc_types=KYC_TYPES)

@app.route('/loans/applications/<int:aid>/delete', methods=['POST'])
@admin_required
def loan_applications_delete(aid):
    db = get_db()
    db.execute("DELETE FROM loan_applications WHERE id=?", (aid,))
    db.commit()
    db.close()
    flash('Application deleted.', 'success')
    return redirect(url_for('loan_applications_list'))

# ── Loan Approvals ────────────────────────────────────────────────────────────

@app.route('/loans/approvals')
@login_required
def loan_approvals_list():
    db = get_db()
    pending = db.execute("""
        SELECT la.*, m.full_name as member_name, m.member_code, lt.loan_type_name
        FROM loan_applications la
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        WHERE la.status='Pending' ORDER BY la.id DESC
    """).fetchall()
    approved = db.execute("""
        SELECT la.*, m.full_name as member_name, m.member_code, lt.loan_type_name,
               u.full_name as approved_by_name, apr.approved_amount, apr.approved_date
        FROM loan_applications la
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        LEFT JOIN loan_approvals apr ON apr.application_id=la.id
        LEFT JOIN users u ON apr.approved_by=u.id
        WHERE la.status IN ('Approved','Rejected') ORDER BY la.id DESC
    """).fetchall()
    db.close()
    return render_template('loans/approvals/list.html', pending=pending, approved=approved)

@app.route('/loans/approvals/<int:aid>/approve', methods=['POST'])
@admin_required
def loan_approve(aid):
    db = get_db()
    db.execute("""
        INSERT INTO loan_approvals (application_id, approved_amount, approved_date, approved_by, status, remarks)
        VALUES (?,?,?,?,?,?)
    """, (aid, request.form.get('approved_amount', 0),
          request.form.get('approved_date', datetime.now().strftime('%d/%m/%Y')),
          session['user_id'], 'Approved', request.form.get('remarks', '')))
    db.execute("UPDATE loan_applications SET status='Approved' WHERE id=?", (aid,))
    db.commit()
    db.close()
    flash('Loan approved.', 'success')
    return redirect(url_for('loan_approvals_list'))

@app.route('/loans/approvals/<int:aid>/reject', methods=['POST'])
@admin_required
def loan_reject(aid):
    db = get_db()
    db.execute("UPDATE loan_applications SET status='Rejected', remarks=? WHERE id=?",
               (request.form.get('remarks', ''), aid))
    db.commit()
    db.close()
    flash('Loan rejected.', 'warning')
    return redirect(url_for('loan_approvals_list'))

# ── Loan Disbursement ─────────────────────────────────────────────────────────

def _next_loan_id(db):
    last = db.execute(
        "SELECT loan_id FROM loan_disbursements WHERE loan_id IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if last and last['loan_id']:
        return f"L{int(last['loan_id'][1:]) + 1:05d}"
    count = db.execute("SELECT COUNT(*) FROM loan_disbursements").fetchone()[0]
    return f"L{count + 1:05d}"

@app.route('/loans/disbursement')
@login_required
def loan_disbursement_list():
    db = get_db()
    approved = db.execute("""
        SELECT la.*, m.full_name as member_name, m.member_code, lt.loan_type_name,
               apr.approved_amount
        FROM loan_applications la
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        LEFT JOIN loan_approvals apr ON apr.application_id=la.id
        WHERE la.status='Approved'
        AND la.id NOT IN (SELECT application_id FROM loan_disbursements)
        ORDER BY la.id DESC
    """).fetchall()
    disbursed = db.execute("""
        SELECT ld.*, la.application_no, m.full_name as member_name, m.member_code,
               lt.loan_type_name, lt.interest_rate, lt.interest_type, la.loan_cycle,
               u.full_name as disbursed_by_name
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        LEFT JOIN users u ON ld.disbursed_by=u.id
        ORDER BY ld.id DESC
    """).fetchall()
    db.close()
    return render_template('loans/disbursement/list.html', approved=approved, disbursed=disbursed)

@app.route('/loans/disbursement/new', methods=['GET', 'POST'])
@admin_required
def loan_disburse_new():
    db = get_db()
    if request.method == 'POST':
        last_app = db.execute("SELECT application_no FROM loan_applications ORDER BY id DESC LIMIT 1").fetchone()
        num_app = int(last_app['application_no'][3:]) + 1 if last_app else 1
        app_no = f"APP{num_app:06d}"

        last_dis = db.execute("SELECT disbursement_no FROM loan_disbursements ORDER BY id DESC LIMIT 1").fetchone()
        num_dis = int(last_dis['disbursement_no'][3:]) + 1 if last_dis else 1
        dis_no = f"DIS{num_dis:06d}"
        loan_id = _next_loan_id(db)

        member = db.execute("SELECT * FROM members WHERE id=?", (request.form.get('member_id'),)).fetchone()
        lt = db.execute("SELECT * FROM loan_types WHERE id=?", (request.form.get('loan_type_id'),)).fetchone()
        amount = float(request.form.get('applied_amount', 0))
        tenure = int(lt['tenure_weeks']) if lt else int(request.form.get('tenure_weeks', 50))
        app_date = request.form.get('applied_date', datetime.now().strftime('%d/%m/%Y'))

        try:
            db.execute("""
                INSERT INTO loan_applications (application_no,member_id,center_id,loan_type_id,
                applied_amount,applied_date,purpose,status,created_by,
                nominee_name,monthly_net_income,loan_cycle,member_kyc_type,member_kyc_number,
                nominee_kyc_type,nominee_kyc_number,processing_fee,insurance_fee,
                nominee_insurance_fee,other_charges)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (app_no,
                  request.form.get('member_id') or None,
                  member['center_id'] if member else None,
                  request.form.get('loan_type_id') or None,
                  amount, app_date,
                  request.form.get('purpose', ''), 'Disbursed',
                  session['user_id'],
                  request.form.get('nominee_name', ''),
                  request.form.get('monthly_net_income', 0),
                  request.form.get('loan_cycle', 1),
                  request.form.get('member_kyc_type', member['kyc_type'] if member else ''),
                  request.form.get('member_kyc_number', member['kyc_number'] if member else ''),
                  request.form.get('nominee_kyc_type', ''),
                  request.form.get('nominee_kyc_number', ''),
                  lt['processing_fee'] if lt else 0,
                  lt['insurance_fee'] if lt else 0,
                  0, 0))
            app_id = db.execute("SELECT id FROM loan_applications WHERE application_no=?", (app_no,)).fetchone()['id']
            db.execute("""
                INSERT INTO loan_approvals (application_id,approved_amount,approved_date,approved_by,status)
                VALUES (?,?,?,?,'Approved')
            """, (app_id, amount, app_date, session['user_id']))
            if lt:
                rate = float(lt['interest_rate'] or 0)
                if lt.get('interest_type') == 'Fixed':
                    total_interest = rate
                else:
                    total_interest = amount * rate / 100
            else:
                total_interest = 0
            inst_amount = round((amount + total_interest) / tenure, 2) if tenure else 0
            db.execute("""
                INSERT INTO loan_disbursements (application_id,disbursement_no,loan_id,disbursed_amount,
                disbursement_date,mode,account_no,disbursed_by,status,total_installments,installment_amount,remarks)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (app_id, dis_no, loan_id, amount, app_date,
                  request.form.get('mode', 'Cash'), request.form.get('account_no', ''),
                  session['user_id'], 'Disbursed', tenure, inst_amount,
                  request.form.get('remarks', '')))
            db.commit()
            flash(f'Loan {loan_id} disbursed successfully.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'danger')
        finally:
            db.close()
        return redirect(url_for('loan_disbursement_list'))

    members = db.execute(
        "SELECT id, member_code, full_name, center_id, income, kyc_type, kyc_number FROM members WHERE status='ACTIVE'"
    ).fetchall()
    loan_types = db.execute(
        "SELECT id, loan_type_code, loan_type_name, tenure_weeks, processing_fee, insurance_fee, interest_rate, interest_type, interest_method FROM loan_types WHERE active=1"
    ).fetchall()
    members_json = json.dumps([dict(m) for m in members])
    loan_types_json = json.dumps([dict(lt) for lt in loan_types])
    db.close()
    return render_template('loans/disbursement/new_form.html',
                           members=members, loan_types=loan_types,
                           members_json=members_json, loan_types_json=loan_types_json,
                           loan_purposes=LOAN_PURPOSES, kyc_types=KYC_TYPES)

@app.route('/loans/disbursement/<int:aid>/disburse', methods=['POST'])
@admin_required
def loan_disburse(aid):
    db = get_db()
    last = db.execute("SELECT disbursement_no FROM loan_disbursements ORDER BY id DESC LIMIT 1").fetchone()
    num = int(last['disbursement_no'][3:]) + 1 if last else 1
    dis_no = f"DIS{num:06d}"
    loan_id = _next_loan_id(db)
    disbursed_amount = float(request.form.get('disbursed_amount', 0))
    total_inst = int(request.form.get('total_installments', 50))
    inst_amount = round(disbursed_amount / total_inst, 2) if total_inst else 0
    db.execute("""
        INSERT INTO loan_disbursements (application_id,disbursement_no,loan_id,disbursed_amount,
        disbursement_date,mode,account_no,disbursed_by,status,total_installments,installment_amount,remarks)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (aid, dis_no, loan_id, disbursed_amount,
          request.form.get('disbursement_date', datetime.now().strftime('%d/%m/%Y')),
          request.form.get('mode', 'Cash'), request.form.get('account_no', ''),
          session['user_id'], 'Disbursed', total_inst, inst_amount,
          request.form.get('remarks', '')))
    db.execute("UPDATE loan_applications SET status='Disbursed' WHERE id=?", (aid,))
    db.commit()
    db.close()
    flash(f'Loan {loan_id} disbursed successfully.', 'success')
    return redirect(url_for('loan_disbursement_list'))

# ── Disbursement Delete ───────────────────────────────────────────────────────

@app.route('/loans/disbursement/<int:did>/delete', methods=['POST'])
@admin_required
def loan_disbursement_delete(did):
    db = get_db()
    dis = db.execute("SELECT * FROM loan_disbursements WHERE id=?", (did,)).fetchone()
    if not dis:
        flash('Disbursement not found.', 'danger')
        db.close()
        return redirect(url_for('loan_disbursement_list'))
    app_id = dis['application_id']
    # Cascade delete: savings_transactions linked to recovery_postings of this disbursement
    db.execute("DELETE FROM savings_transactions WHERE disbursement_id=?", (did,))
    # Delete recovery postings
    db.execute("DELETE FROM recovery_postings WHERE disbursement_id=?", (did,))
    # Delete the disbursement
    db.execute("DELETE FROM loan_disbursements WHERE id=?", (did,))
    # Revert application status to Approved
    db.execute("UPDATE loan_applications SET status='Approved' WHERE id=?", (app_id,))
    db.commit()
    db.close()
    flash('Disbursement deleted and application reverted to Approved.', 'success')
    return redirect(url_for('loan_disbursement_list'))

# ── Recovery Posting ──────────────────────────────────────────────────────────

@app.route('/loans/posting/recovery')
@login_required
def recovery_posting_list():
    db = get_db()
    date_filter = request.args.get('date', datetime.now().strftime('%d/%m/%Y'))
    center_filter = request.args.get('center_id', '')
    try:
        selected_date = datetime.strptime(date_filter, '%d/%m/%Y')
        day_name = selected_date.strftime('%A')
    except Exception:
        selected_date = datetime.now()
        day_name = selected_date.strftime('%A')
        date_filter = selected_date.strftime('%d/%m/%Y')

    params = {'date': date_filter}
    query = """
        SELECT ld.*, la.application_no, la.member_id, la.center_id,
               m.full_name as member_name, m.member_code,
               c.center_name, c.center_code, c.meeting_week, c.meeting_type,
               lt.interest_rate, lt.interest_type,
               (SELECT COUNT(*) FROM recovery_postings rp WHERE rp.disbursement_id=ld.id) as paid_count,
               (SELECT rp2.id FROM recovery_postings rp2
                WHERE rp2.disbursement_id=ld.id AND rp2.posting_date=:date
                ORDER BY rp2.id DESC LIMIT 1) as today_posting_id
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        WHERE ld.status='Disbursed'
        AND (SELECT COUNT(*) FROM recovery_postings rp3 WHERE rp3.disbursement_id=ld.id) < ld.total_installments
    """
    if center_filter:
        query += " AND la.center_id=:center_id"
        params['center_id'] = center_filter
    else:
        query += " AND c.meeting_week=:day"
        params['day'] = day_name
    query += " ORDER BY c.center_code, m.member_code"

    loans = db.execute(query, params).fetchall()
    centers = db.execute(
        "SELECT id, center_code, center_name, meeting_week FROM centers WHERE active=1 ORDER BY center_code"
    ).fetchall()
    db.close()
    return render_template('loans/posting/recovery_list.html',
                           loans=loans, centers=centers,
                           date_filter=date_filter, center_filter=center_filter,
                           day_name=day_name)

@app.route('/loans/posting/recovery/bulk', methods=['POST'])
@login_required
def recovery_bulk_post():
    db = get_db()
    selected_ids = request.form.getlist('selected_loans')
    posting_date = request.form.get('posting_date', datetime.now().strftime('%d/%m/%Y'))
    savings_amount = float(request.form.get('savings_amount', 100))
    posted = 0
    for did in selected_ids:
        did = int(did)
        loan = db.execute("""
            SELECT ld.*, la.member_id, la.center_id, lt.interest_rate, lt.interest_type
            FROM loan_disbursements ld
            LEFT JOIN loan_applications la ON ld.application_id=la.id
            LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
            WHERE ld.id=?
        """, (did,)).fetchone()
        if not loan:
            continue
        paid_count = db.execute(
            "SELECT COUNT(*) FROM recovery_postings WHERE disbursement_id=?", (did,)
        ).fetchone()[0]
        if paid_count >= loan['total_installments']:
            continue
        # Skip if already posted on this date
        already = db.execute(
            "SELECT id FROM recovery_postings WHERE disbursement_id=? AND posting_date=?",
            (did, posting_date)
        ).fetchone()
        if already:
            continue
        amount = float(loan['disbursed_amount'])
        tenure = int(loan['total_installments'])
        rate = float(loan['interest_rate'] or 0)
        interest_type = loan['interest_type'] or 'Percent'
        total_interest = rate if interest_type == 'Fixed' else amount * rate / 100
        principal_inst = round(amount / tenure, 2)
        interest_inst = round(total_interest / tenure, 2)
        inst_amount = principal_inst + interest_inst
        installment_no = paid_count + 1
        db.execute("""
            INSERT INTO recovery_postings
            (disbursement_id,posting_date,installment_no,due_amount,paid_amount,
             principal,interest,penalty,mode,narration,posted_by)
            VALUES (?,?,?,?,?,?,?,0,'Cash','Weekly recovery',?)
        """, (did, posting_date, installment_no, inst_amount, inst_amount,
              principal_inst, interest_inst, session['user_id']))
        recovery_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        if savings_amount > 0 and loan['member_id']:
            prev = db.execute(
                "SELECT COALESCE(SUM(deposit_amount),0)-COALESCE(SUM(withdraw_amount),0) FROM savings_transactions WHERE member_id=?",
                (loan['member_id'],)
            ).fetchone()[0]
            db.execute("""
                INSERT INTO savings_transactions
                (member_id,center_id,disbursement_id,recovery_posting_id,
                 transaction_date,deposit_amount,withdraw_amount,balance,posted_by)
                VALUES (?,?,?,?,?,?,0,?,?)
            """, (loan['member_id'], loan['center_id'], did, recovery_id,
                  posting_date, savings_amount, prev + savings_amount, session['user_id']))
        posted += 1
    db.commit()
    db.close()
    flash(f'{posted} recovery posting(s) saved for {posting_date}.', 'success')
    return redirect(url_for('recovery_posting_list', date=posting_date))

@app.route('/loans/posting/recovery/<int:did>', methods=['GET', 'POST'])
@login_required
def recovery_post(did):
    db = get_db()
    loan = db.execute("""
        SELECT ld.*, la.application_no, la.member_id, la.center_id,
               m.full_name as member_name, m.member_code,
               lt.interest_rate, lt.interest_type, lt.interest_method
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        WHERE ld.id=?
    """, (did,)).fetchone()
    if request.method == 'POST':
        posting_date = request.form.get('posting_date', datetime.now().strftime('%d/%m/%Y'))
        db.execute("""
            INSERT INTO recovery_postings (disbursement_id,posting_date,installment_no,
            due_amount,paid_amount,principal,interest,penalty,mode,narration,posted_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (did, posting_date,
              request.form.get('installment_no', 1), request.form.get('due_amount', 0),
              request.form.get('paid_amount', 0), request.form.get('principal', 0),
              request.form.get('interest', 0), request.form.get('penalty', 0),
              request.form.get('mode', 'Cash'), request.form.get('narration', ''),
              session['user_id']))
        recovery_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        # Auto-create savings transaction
        savings_amount = float(request.form.get('savings_amount', 100))
        if savings_amount > 0 and loan['member_id']:
            # Calculate running balance
            prev_balance = db.execute(
                "SELECT COALESCE(SUM(deposit_amount),0) - COALESCE(SUM(withdraw_amount),0) FROM savings_transactions WHERE member_id=?",
                (loan['member_id'],)
            ).fetchone()[0]
            new_balance = prev_balance + savings_amount
            db.execute("""
                INSERT INTO savings_transactions (member_id,center_id,disbursement_id,recovery_posting_id,
                transaction_date,deposit_amount,withdraw_amount,balance,posted_by)
                VALUES (?,?,?,?,?,?,0,?,?)
            """, (loan['member_id'], loan['center_id'], did, recovery_id,
                  posting_date, savings_amount, new_balance, session['user_id']))
        db.commit()
        flash('Recovery posted with savings.', 'success')
        return redirect(url_for('recovery_posting_list'))
    postings = db.execute(
        "SELECT * FROM recovery_postings WHERE disbursement_id=? ORDER BY installment_no",
        (did,)
    ).fetchall()
    # Savings summary for the member
    savings_summary = None
    if loan['member_id']:
        row = db.execute("""
            SELECT COALESCE(SUM(deposit_amount),0) as total_deposits,
                   COALESCE(SUM(withdraw_amount),0) as total_withdrawals,
                   COALESCE(SUM(deposit_amount),0) - COALESCE(SUM(withdraw_amount),0) as balance
            FROM savings_transactions WHERE member_id=?
        """, (loan['member_id'],)).fetchone()
        savings_summary = {'total_deposits': row['total_deposits'], 'total_withdrawals': row['total_withdrawals'], 'balance': row['balance']}
    db.close()
    return render_template('loans/posting/recovery_form.html', loan=loan, postings=postings, savings_summary=savings_summary)

@app.route('/loans/posting/recovery/<int:rid>/delete', methods=['POST'])
@admin_required
def recovery_posting_delete(rid):
    db = get_db()
    # Delete linked savings transaction
    db.execute("DELETE FROM savings_transactions WHERE recovery_posting_id=?", (rid,))
    # Delete the recovery posting
    db.execute("DELETE FROM recovery_postings WHERE id=?", (rid,))
    db.commit()
    db.close()
    flash('Recovery posting reversed and linked savings transaction deleted.', 'success')
    return redirect(url_for('recovery_posting_list'))

# ── Any Day Prepaid/Undo ──────────────────────────────────────────────────────

@app.route('/loans/posting/prepaid')
@login_required
def prepaid_list():
    db = get_db()
    loans = db.execute("""
        SELECT ld.*, la.application_no, m.full_name as member_name, m.member_code
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        WHERE ld.status='Disbursed' ORDER BY ld.id DESC
    """).fetchall()
    db.close()
    return render_template('loans/posting/prepaid_list.html', loans=loans)

@app.route('/loans/posting/prepaid/<int:did>', methods=['GET', 'POST'])
@login_required
def prepaid_post(did):
    db = get_db()
    loan = db.execute("""
        SELECT ld.*, la.application_no, m.full_name as member_name
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id WHERE ld.id=?
    """, (did,)).fetchone()
    if request.method == 'POST':
        db.execute("""
            INSERT INTO prepaid_transactions (disbursement_id,prepaid_type_id,transaction_date,
            amount,mode,narration,is_undo,posted_by)
            VALUES (?,?,?,?,?,?,?,?)
        """, (did, request.form.get('prepaid_type_id') or None,
              request.form.get('transaction_date', datetime.now().strftime('%d/%m/%Y')),
              request.form.get('amount', 0), request.form.get('mode', 'Cash'),
              request.form.get('narration', ''), 1 if request.form.get('is_undo') else 0,
              session['user_id']))
        db.commit()
        flash('Prepaid transaction posted.', 'success')
        return redirect(url_for('prepaid_list'))
    prepaid_types = db.execute("SELECT * FROM prepaid_types WHERE active=1").fetchall()
    transactions = db.execute(
        """SELECT pt.*, prt.name as type_name FROM prepaid_transactions pt
           LEFT JOIN prepaid_types prt ON pt.prepaid_type_id=prt.id
           WHERE pt.disbursement_id=? ORDER BY pt.id DESC""", (did,)
    ).fetchall()
    db.close()
    return render_template('loans/posting/prepaid_form.html', loan=loan,
                           prepaid_types=prepaid_types, transactions=transactions)

# ── Advance Recovery ──────────────────────────────────────────────────────────

@app.route('/loans/posting/advance-recovery')
@login_required
def advance_recovery_list():
    db = get_db()
    loans = db.execute("""
        SELECT ld.*, la.application_no, m.full_name as member_name, m.member_code
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        WHERE ld.status='Disbursed' ORDER BY ld.id DESC
    """).fetchall()
    db.close()
    return render_template('loans/posting/advance_list.html', loans=loans)

@app.route('/loans/posting/advance-recovery/<int:did>', methods=['GET', 'POST'])
@login_required
def advance_recovery_post(did):
    db = get_db()
    loan = db.execute("""
        SELECT ld.*, la.application_no, m.full_name as member_name
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id WHERE ld.id=?
    """, (did,)).fetchone()
    if request.method == 'POST':
        db.execute("""
            INSERT INTO advance_recoveries (disbursement_id,recovery_date,amount,mode,narration,posted_by)
            VALUES (?,?,?,?,?,?)
        """, (did, request.form.get('recovery_date', datetime.now().strftime('%d/%m/%Y')),
              request.form.get('amount', 0), request.form.get('mode', 'Cash'),
              request.form.get('narration', ''), session['user_id']))
        db.commit()
        flash('Advance recovery posted.', 'success')
        return redirect(url_for('advance_recovery_list'))
    records = db.execute(
        "SELECT * FROM advance_recoveries WHERE disbursement_id=? ORDER BY id DESC", (did,)
    ).fetchall()
    db.close()
    return render_template('loans/posting/advance_form.html', loan=loan, records=records)

# ── Apply Moratorium ──────────────────────────────────────────────────────────

@app.route('/loans/posting/moratorium')
@login_required
def moratorium_list():
    db = get_db()
    loans = db.execute("""
        SELECT ld.*, la.application_no, m.full_name as member_name, m.member_code
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        WHERE ld.status='Disbursed' ORDER BY ld.id DESC
    """).fetchall()
    db.close()
    return render_template('loans/posting/moratorium_list.html', loans=loans)

@app.route('/loans/posting/moratorium/<int:did>', methods=['GET', 'POST'])
@login_required
def moratorium_post(did):
    db = get_db()
    loan = db.execute("""
        SELECT ld.*, la.application_no, m.full_name as member_name
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id WHERE ld.id=?
    """, (did,)).fetchone()
    if request.method == 'POST':
        db.execute("""
            INSERT INTO moratoriums (disbursement_id,from_date,to_date,reason,applied_by)
            VALUES (?,?,?,?,?)
        """, (did, request.form.get('from_date', ''), request.form.get('to_date', ''),
              request.form.get('reason', ''), session['user_id']))
        db.commit()
        flash('Moratorium applied.', 'success')
        return redirect(url_for('moratorium_list'))
    records = db.execute(
        "SELECT * FROM moratoriums WHERE disbursement_id=? ORDER BY id DESC", (did,)
    ).fetchall()
    db.close()
    return render_template('loans/posting/moratorium_form.html', loan=loan, records=records)

# ── Savings ───────────────────────────────────────────────────────────────────

@app.route('/savings')
@login_required
def savings_list():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    query_summary = """
        SELECT m.id as member_id, m.member_code, m.full_name, c.center_code, c.center_name,
               COALESCE(SUM(st.deposit_amount),0) as total_deposits,
               COALESCE(SUM(st.withdraw_amount),0) as total_withdrawals
        FROM members m
        LEFT JOIN centers c ON m.center_id=c.id
        LEFT JOIN savings_transactions st ON st.member_id=m.id
        WHERE m.status='ACTIVE'
    """
    params = []
    if center_filter:
        query_summary += " AND m.center_id=?"
        params.append(center_filter)
    query_summary += " GROUP BY m.id HAVING total_deposits > 0 OR total_withdrawals > 0 ORDER BY c.center_code, m.member_code"
    summary = db.execute(query_summary, params).fetchall()

    query_trans = """
        SELECT st.*, m.member_code, m.full_name, c.center_code, c.center_name, u.full_name as posted_by_name
        FROM savings_transactions st
        LEFT JOIN members m ON st.member_id=m.id
        LEFT JOIN centers c ON st.center_id=c.id
        LEFT JOIN users u ON st.posted_by=u.id
    """
    trans_params = []
    if center_filter:
        query_trans += " WHERE st.center_id=?"
        trans_params.append(center_filter)
    query_trans += " ORDER BY st.id DESC"
    transactions = db.execute(query_trans, trans_params).fetchall()

    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    all_members = db.execute("""
        SELECT m.id, m.member_code, m.full_name, c.center_code, c.center_name
        FROM members m LEFT JOIN centers c ON m.center_id=c.id
        WHERE m.status='ACTIVE' ORDER BY c.center_code, m.member_code
    """).fetchall()

    total_deposits = sum(s['total_deposits'] for s in summary)
    total_withdrawals = sum(s['total_withdrawals'] for s in summary)
    totals = {'deposits': total_deposits, 'withdrawals': total_withdrawals, 'balance': total_deposits - total_withdrawals}

    db.close()
    return render_template('savings/list.html', summary=summary, transactions=transactions,
                           centers=centers, center_filter=center_filter, totals=totals,
                           all_members=all_members)

@app.route('/savings/member-info')
@login_required
def savings_member_info():
    mid = request.args.get('mid', '')
    if not mid:
        return jsonify({})
    db = get_db()
    member = db.execute("""
        SELECT m.id, m.member_code, m.full_name, c.center_name, c.center_code, m.center_id
        FROM members m LEFT JOIN centers c ON m.center_id=c.id WHERE m.id=?
    """, (mid,)).fetchone()
    if not member:
        db.close()
        return jsonify({})
    row = db.execute(
        "SELECT COALESCE(SUM(deposit_amount),0) as d, COALESCE(SUM(withdraw_amount),0) as w FROM savings_transactions WHERE member_id=?",
        (mid,)
    ).fetchone()
    db.close()
    balance = (row['d'] or 0) - (row['w'] or 0)
    return jsonify({
        'member_code': member['member_code'],
        'full_name': member['full_name'],
        'center': f"{member['center_code']} {member['center_name']}",
        'balance': balance
    })

@app.route('/savings/deposit/<int:mid>', methods=['POST'])
@admin_required
def savings_deposit(mid):
    db = get_db()
    deposit_amount = float(request.form.get('deposit_amount', 0))
    transaction_date = request.form.get('transaction_date', datetime.now().strftime('%d/%m/%Y'))
    if deposit_amount <= 0:
        flash('Invalid deposit amount.', 'danger')
        db.close()
        return redirect(url_for('savings_list'))
    member = db.execute("SELECT center_id FROM members WHERE id=?", (mid,)).fetchone()
    prev = db.execute(
        "SELECT COALESCE(SUM(deposit_amount),0) - COALESCE(SUM(withdraw_amount),0) as balance FROM savings_transactions WHERE member_id=?",
        (mid,)
    ).fetchone()
    new_balance = (prev['balance'] or 0) + deposit_amount
    db.execute("""
        INSERT INTO savings_transactions (member_id,center_id,transaction_date,deposit_amount,withdraw_amount,balance,posted_by)
        VALUES (?,?,?,?,0,?,?)
    """, (mid, member['center_id'] if member else None, transaction_date, deposit_amount, new_balance, session['user_id']))
    db.commit()
    db.close()
    flash(f'Deposit of ₹{deposit_amount:,.0f} posted successfully.', 'success')
    return redirect(url_for('savings_list'))

@app.route('/savings/withdraw/<int:mid>', methods=['POST'])
@admin_required
def savings_withdraw(mid):
    db = get_db()
    withdraw_amount = float(request.form.get('withdraw_amount', 0))
    transaction_date = request.form.get('transaction_date', datetime.now().strftime('%d/%m/%Y'))
    # Check available balance
    row = db.execute(
        "SELECT COALESCE(SUM(deposit_amount),0) - COALESCE(SUM(withdraw_amount),0) as balance FROM savings_transactions WHERE member_id=?",
        (mid,)
    ).fetchone()
    available = row['balance'] if row else 0
    if withdraw_amount <= 0 or withdraw_amount > available:
        flash(f'Invalid withdrawal amount. Available balance: ₹{available:,.0f}', 'danger')
        db.close()
        return redirect(url_for('savings_list'))
    member = db.execute("SELECT center_id FROM members WHERE id=?", (mid,)).fetchone()
    new_balance = available - withdraw_amount
    db.execute("""
        INSERT INTO savings_transactions (member_id,center_id,transaction_date,deposit_amount,withdraw_amount,balance,posted_by)
        VALUES (?,?,?,0,?,?,?)
    """, (mid, member['center_id'] if member else None, transaction_date, withdraw_amount, new_balance, session['user_id']))
    db.commit()
    db.close()
    flash(f'Withdrawal of ₹{withdraw_amount:,.0f} posted successfully.', 'success')
    return redirect(url_for('savings_list'))

# ── Loan Schedule ─────────────────────────────────────────────────────────────

@app.route('/loans/disbursement/<int:did>/schedule')
@login_required
def loan_schedule(did):
    db = get_db()
    loan = db.execute("""
        SELECT ld.*, la.application_no, la.member_id, la.center_id,
               m.full_name as member_name, m.member_code, c.center_name, c.center_code,
               lt.interest_rate, lt.interest_type, lt.interest_method, lt.loan_type_name
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        WHERE ld.id=?
    """, (did,)).fetchone()
    postings = db.execute(
        "SELECT * FROM recovery_postings WHERE disbursement_id=? ORDER BY installment_no",
        (did,)
    ).fetchall()
    db.close()

    amount = float(loan['disbursed_amount'])
    tenure = int(loan['total_installments'])
    rate = float(loan['interest_rate'] or 0)
    interest_type = loan['interest_type'] or 'Percent'

    if interest_type == 'Fixed':
        total_interest = rate
    else:
        total_interest = round(amount * rate / 100, 2)

    total_payable = amount + total_interest
    weekly_principal = round(amount / tenure, 2)
    weekly_interest = round(total_interest / tenure, 2)
    weekly_installment = weekly_principal + weekly_interest

    paid_weeks = {p['installment_no'] for p in postings}

    try:
        start_date = datetime.strptime(loan['disbursement_date'], '%d/%m/%Y')
    except Exception:
        start_date = datetime.now()

    schedule = []
    opening = amount
    for week in range(1, tenure + 1):
        date = start_date + timedelta(weeks=week)
        if week == tenure:
            p = round(opening, 2)
            i = round(total_interest - weekly_interest * (tenure - 1), 2)
            inst = round(p + i, 2)
        else:
            p = weekly_principal
            i = weekly_interest
            inst = weekly_installment
        closing = round(max(opening - p, 0), 2)
        schedule.append({
            'week': week,
            'date': date.strftime('%d/%m/%Y'),
            'opening': opening,
            'principal': p,
            'interest': i,
            'installment': inst,
            'closing': closing,
            'paid': week in paid_weeks
        })
        opening = closing

    return render_template('loans/disbursement/schedule.html',
                           loan=loan, schedule=schedule,
                           total_interest=total_interest,
                           total_payable=total_payable,
                           weekly_installment=weekly_installment,
                           weekly_principal=weekly_principal,
                           weekly_interest=weekly_interest,
                           paid_count=len(postings))

# ── Settings ──────────────────────────────────────────────────────────────────

@app.route('/settings')
@admin_required
def settings():
    return render_template('settings.html')

# ── Reports ───────────────────────────────────────────────────────────────────

@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')

@app.route('/reports/masters/centers')
@login_required
def report_masters_centers():
    db = get_db()
    centers = db.execute("""
        SELECT c.*, u.full_name as staff_name,
               (SELECT COUNT(*) FROM members m WHERE m.center_id=c.id AND m.status='ACTIVE') as active_members
        FROM centers c LEFT JOIN users u ON c.staff_id=u.id ORDER BY c.center_code
    """).fetchall()
    db.close()
    return render_template('reports/masters_centers.html', centers=centers)

@app.route('/reports/masters/members')
@login_required
def report_masters_members():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    status_filter = request.args.get('status', 'ACTIVE')
    query = """
        SELECT m.*, c.center_name, c.center_code FROM members m
        LEFT JOIN centers c ON m.center_id=c.id
        WHERE 1=1
    """
    params = []
    if center_filter:
        query += " AND m.center_id=?"
        params.append(center_filter)
    if status_filter:
        query += " AND m.status=?"
        params.append(status_filter)
    query += " ORDER BY m.member_code"
    members = db.execute(query, params).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/masters_members.html', members=members,
                           centers=centers, center_filter=center_filter, status_filter=status_filter)

@app.route('/reports/member-joining')
@login_required
def report_member_joining():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    query = """
        SELECT m.*, c.center_name, c.center_code FROM members m
        LEFT JOIN centers c ON m.center_id=c.id WHERE 1=1
    """
    params = []
    if center_filter:
        query += " AND m.center_id=?"
        params.append(center_filter)
    if from_date:
        query += " AND m.date_of_join >= ?"
        params.append(from_date)
    if to_date:
        query += " AND m.date_of_join <= ?"
        params.append(to_date)
    query += " ORDER BY m.date_of_join, m.member_code"
    members = db.execute(query, params).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/member_joining.html', members=members, centers=centers,
                           center_filter=center_filter, from_date=from_date, to_date=to_date)

@app.route('/reports/member-withdraw')
@login_required
def report_member_withdraw():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    members = db.execute("""
        SELECT m.*, c.center_name, c.center_code FROM members m
        LEFT JOIN centers c ON m.center_id=c.id
        WHERE m.status='WITHDRAWN'
        """ + (" AND m.center_id=?" if center_filter else "") + """
        ORDER BY m.member_code
    """, ([center_filter] if center_filter else [])).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/member_withdraw.html', members=members, centers=centers,
                           center_filter=center_filter)

@app.route('/reports/collection-sheet')
@login_required
def report_collection_sheet():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    report_date = request.args.get('report_date', datetime.now().strftime('%d/%m/%Y'))
    loans = db.execute("""
        SELECT ld.*, la.application_no, la.purpose, la.loan_cycle,
               m.full_name as member_name, m.member_code, m.grp,
               c.center_name, c.center_code,
               lt.loan_type_name,
               (SELECT COALESCE(SUM(rp.paid_amount),0) FROM recovery_postings rp WHERE rp.disbursement_id=ld.id) as total_paid,
               (SELECT COUNT(*) FROM recovery_postings rp WHERE rp.disbursement_id=ld.id) as paid_count
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        WHERE ld.status='Disbursed'
        """ + (" AND la.center_id=?" if center_filter else "") + """
        ORDER BY c.center_code, m.grp, m.member_code
    """, ([center_filter] if center_filter else [])).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/collection_sheet.html', loans=loans, centers=centers,
                           center_filter=center_filter, report_date=report_date)

@app.route('/reports/summary-sheet')
@login_required
def report_summary_sheet():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    report_date = request.args.get('report_date', datetime.now().strftime('%d/%m/%Y'))
    centers_data = db.execute("""
        SELECT c.center_code, c.center_name,
               COUNT(DISTINCT m.id) as total_members,
               COUNT(DISTINCT ld.id) as active_loans,
               COALESCE(SUM(ld.disbursed_amount),0) as total_disbursed,
               COALESCE(SUM(rp.paid_amount),0) as total_collected
        FROM centers c
        LEFT JOIN members m ON m.center_id=c.id AND m.status='ACTIVE'
        LEFT JOIN loan_applications la ON la.center_id=c.id
        LEFT JOIN loan_disbursements ld ON ld.application_id=la.id AND ld.status='Disbursed'
        LEFT JOIN recovery_postings rp ON rp.disbursement_id=ld.id
        """ + (" WHERE c.id=?" if center_filter else "") + """
        GROUP BY c.id ORDER BY c.center_code
    """, ([center_filter] if center_filter else [])).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/summary_sheet.html', centers_data=centers_data,
                           centers=centers, center_filter=center_filter, report_date=report_date)

@app.route('/reports/member-wise-summary')
@login_required
def report_member_wise_summary():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    data = db.execute("""
        SELECT m.member_code, m.full_name, m.grp,
               c.center_name, c.center_code,
               COUNT(ld.id) as loan_count,
               COALESCE(SUM(ld.disbursed_amount),0) as total_disbursed,
               COALESCE(SUM(rp.paid_amount),0) as total_paid,
               COALESCE(SUM(ld.disbursed_amount),0) - COALESCE(SUM(rp.paid_amount),0) as outstanding
        FROM members m
        LEFT JOIN centers c ON m.center_id=c.id
        LEFT JOIN loan_applications la ON la.member_id=m.id
        LEFT JOIN loan_disbursements ld ON ld.application_id=la.id AND ld.status='Disbursed'
        LEFT JOIN recovery_postings rp ON rp.disbursement_id=ld.id
        WHERE m.status='ACTIVE'
        """ + (" AND m.center_id=?" if center_filter else "") + """
        GROUP BY m.id ORDER BY c.center_code, m.grp, m.member_code
    """, ([center_filter] if center_filter else [])).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/member_wise_summary.html', data=data,
                           centers=centers, center_filter=center_filter)

@app.route('/reports/advance/collected')
@login_required
def report_advance_collected():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    query = """
        SELECT ar.*, la.application_no, m.full_name as member_name, m.member_code,
               c.center_name, c.center_code, ld.loan_id
        FROM advance_recoveries ar
        LEFT JOIN loan_disbursements ld ON ar.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        WHERE 1=1
    """
    params = []
    if center_filter:
        query += " AND la.center_id=?"
        params.append(center_filter)
    if from_date:
        query += " AND ar.recovery_date >= ?"
        params.append(from_date)
    if to_date:
        query += " AND ar.recovery_date <= ?"
        params.append(to_date)
    query += " ORDER BY ar.recovery_date"
    records = db.execute(query, params).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/advance_collected.html', records=records, centers=centers,
                           center_filter=center_filter, from_date=from_date, to_date=to_date)

@app.route('/reports/advance/withdraw')
@login_required
def report_advance_withdraw():
    db = get_db()
    records = db.execute("""
        SELECT ar.*, la.application_no, m.full_name as member_name, m.member_code,
               c.center_name, ld.loan_id
        FROM advance_recoveries ar
        LEFT JOIN loan_disbursements ld ON ar.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        ORDER BY ar.recovery_date DESC
    """).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/advance_withdraw.html', records=records, centers=centers)

@app.route('/reports/advance/consolidated')
@login_required
def report_advance_consolidated():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    data = db.execute("""
        SELECT m.member_code, m.full_name, c.center_name, c.center_code, ld.loan_id,
               la.application_no,
               COALESCE(SUM(ar.amount),0) as total_advance
        FROM advance_recoveries ar
        LEFT JOIN loan_disbursements ld ON ar.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        """ + (" WHERE la.center_id=?" if center_filter else "") + """
        GROUP BY ld.id ORDER BY c.center_code, m.member_code
    """, ([center_filter] if center_filter else [])).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/advance_consolidated.html', data=data,
                           centers=centers, center_filter=center_filter)

@app.route('/reports/voucher-details')
@login_required
def report_voucher_details():
    db = get_db()
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    center_filter = request.args.get('center_id', '')
    query = """
        SELECT rp.*, la.application_no, m.full_name as member_name, m.member_code,
               c.center_name, c.center_code, ld.loan_id, u.full_name as posted_by_name
        FROM recovery_postings rp
        LEFT JOIN loan_disbursements ld ON rp.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN users u ON rp.posted_by=u.id WHERE 1=1
    """
    params = []
    if center_filter:
        query += " AND la.center_id=?"
        params.append(center_filter)
    if from_date:
        query += " AND rp.posting_date >= ?"
        params.append(from_date)
    if to_date:
        query += " AND rp.posting_date <= ?"
        params.append(to_date)
    query += " ORDER BY rp.posting_date, c.center_code"
    records = db.execute(query, params).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/voucher_details.html', records=records, centers=centers,
                           center_filter=center_filter, from_date=from_date, to_date=to_date)

@app.route('/reports/disbursement')
@login_required
def report_disbursement():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    query = """
        SELECT ld.*, la.application_no, la.purpose, la.loan_cycle, la.processing_fee, la.insurance_fee,
               m.full_name as member_name, m.member_code,
               c.center_name, c.center_code,
               lt.loan_type_name,
               u.full_name as disbursed_by_name
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        LEFT JOIN users u ON ld.disbursed_by=u.id WHERE 1=1
    """
    params = []
    if center_filter:
        query += " AND la.center_id=?"
        params.append(center_filter)
    if from_date:
        query += " AND ld.disbursement_date >= ?"
        params.append(from_date)
    if to_date:
        query += " AND ld.disbursement_date <= ?"
        params.append(to_date)
    query += " ORDER BY ld.disbursement_date, c.center_code"
    records = db.execute(query, params).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/disbursement_report.html', records=records, centers=centers,
                           center_filter=center_filter, from_date=from_date, to_date=to_date)

@app.route('/reports/prepaid')
@login_required
def report_prepaid():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    query = """
        SELECT pt.*, la.application_no, m.full_name as member_name, m.member_code,
               c.center_name, c.center_code, ld.loan_id, prt.name as prepaid_type_name
        FROM prepaid_transactions pt
        LEFT JOIN loan_disbursements ld ON pt.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN prepaid_types prt ON pt.prepaid_type_id=prt.id
        WHERE 1=1
    """
    params = []
    if center_filter:
        query += " AND la.center_id=?"
        params.append(center_filter)
    if from_date:
        query += " AND pt.transaction_date >= ?"
        params.append(from_date)
    if to_date:
        query += " AND pt.transaction_date <= ?"
        params.append(to_date)
    query += " ORDER BY pt.transaction_date"
    records = db.execute(query, params).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/prepaid_report.html', records=records, centers=centers,
                           center_filter=center_filter, from_date=from_date, to_date=to_date)

@app.route('/reports/outstanding')
@login_required
def report_outstanding():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    data = db.execute("""
        SELECT ld.loan_id, ld.disbursed_amount, ld.total_installments, ld.installment_amount,
               ld.disbursement_date,
               la.application_no, la.purpose, la.loan_cycle,
               m.full_name as member_name, m.member_code, m.grp,
               c.center_name, c.center_code,
               lt.loan_type_name,
               COALESCE(SUM(rp.paid_amount),0) as total_paid,
               COALESCE(SUM(rp.principal),0) as principal_paid,
               COALESCE(SUM(rp.interest),0) as interest_paid,
               COUNT(rp.id) as installments_paid,
               ld.disbursed_amount - COALESCE(SUM(rp.paid_amount),0) as outstanding
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        LEFT JOIN recovery_postings rp ON rp.disbursement_id=ld.id
        WHERE ld.status='Disbursed'
        """ + (" AND la.center_id=?" if center_filter else "") + """
        GROUP BY ld.id ORDER BY c.center_code, m.grp, m.member_code
    """, ([center_filter] if center_filter else [])).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/outstanding_report.html', data=data,
                           centers=centers, center_filter=center_filter)

@app.route('/reports/arrears/member-wise')
@login_required
def report_arrears_member_wise():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    data = db.execute("""
        SELECT ld.loan_id, ld.disbursed_amount, ld.installment_amount, ld.total_installments,
               ld.disbursement_date,
               la.application_no, la.loan_cycle,
               m.full_name as member_name, m.member_code, m.grp,
               c.center_name, c.center_code,
               lt.loan_type_name,
               COUNT(rp.id) as paid_count,
               COALESCE(SUM(rp.paid_amount),0) as total_paid,
               ld.disbursed_amount - COALESCE(SUM(rp.paid_amount),0) as outstanding,
               ld.total_installments - COUNT(rp.id) as pending_installments
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        LEFT JOIN recovery_postings rp ON rp.disbursement_id=ld.id
        WHERE ld.status='Disbursed'
        """ + (" AND la.center_id=?" if center_filter else "") + """
        GROUP BY ld.id HAVING pending_installments > 0
        ORDER BY c.center_code, m.grp, m.member_code
    """, ([center_filter] if center_filter else [])).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/arrears_member_wise.html', data=data,
                           centers=centers, center_filter=center_filter)

@app.route('/reports/arrears/new')
@login_required
def report_arrears_new():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    data = db.execute("""
        SELECT ld.loan_id, ld.disbursed_amount, ld.installment_amount,
               la.application_no, la.loan_cycle,
               m.full_name as member_name, m.member_code,
               c.center_name, c.center_code,
               lt.loan_type_name,
               ld.disbursed_amount - COALESCE(SUM(rp.paid_amount),0) as outstanding
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        LEFT JOIN recovery_postings rp ON rp.disbursement_id=ld.id
        WHERE ld.status='Disbursed'
        """ + (" AND la.center_id=?" if center_filter else "") + """
        GROUP BY ld.id HAVING outstanding > 0
        ORDER BY c.center_code
    """, ([center_filter] if center_filter else [])).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/arrears_new.html', data=data, centers=centers,
                           center_filter=center_filter, from_date=from_date, to_date=to_date)

@app.route('/reports/arrears/collected')
@login_required
def report_arrears_collected():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    query = """
        SELECT rp.posting_date, rp.paid_amount, rp.installment_no, rp.penalty,
               la.application_no, la.loan_cycle,
               m.full_name as member_name, m.member_code,
               c.center_name, c.center_code, ld.loan_id
        FROM recovery_postings rp
        LEFT JOIN loan_disbursements ld ON rp.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        WHERE 1=1
    """
    params = []
    if center_filter:
        query += " AND la.center_id=?"
        params.append(center_filter)
    if from_date:
        query += " AND rp.posting_date >= ?"
        params.append(from_date)
    if to_date:
        query += " AND rp.posting_date <= ?"
        params.append(to_date)
    query += " ORDER BY rp.posting_date, c.center_code"
    records = db.execute(query, params).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/arrears_collected.html', records=records, centers=centers,
                           center_filter=center_filter, from_date=from_date, to_date=to_date)

@app.route('/reports/glance')
@login_required
def report_glance():
    db = get_db()
    stats = {
        'total_centers': db.execute("SELECT COUNT(*) FROM centers WHERE active=1").fetchone()[0],
        'total_members': db.execute("SELECT COUNT(*) FROM members WHERE status='ACTIVE'").fetchone()[0],
        'withdrawn_members': db.execute("SELECT COUNT(*) FROM members WHERE status='WITHDRAWN'").fetchone()[0],
        'total_applications': db.execute("SELECT COUNT(*) FROM loan_applications").fetchone()[0],
        'pending_applications': db.execute("SELECT COUNT(*) FROM loan_applications WHERE status='Pending'").fetchone()[0],
        'approved_applications': db.execute("SELECT COUNT(*) FROM loan_applications WHERE status='Approved'").fetchone()[0],
        'total_disbursements': db.execute("SELECT COUNT(*) FROM loan_disbursements").fetchone()[0],
        'total_disbursed_amount': db.execute("SELECT COALESCE(SUM(disbursed_amount),0) FROM loan_disbursements").fetchone()[0],
        'total_collected': db.execute("SELECT COALESCE(SUM(paid_amount),0) FROM recovery_postings").fetchone()[0],
    }
    stats['outstanding'] = stats['total_disbursed_amount'] - stats['total_collected']
    stats['total_savings'] = db.execute("SELECT COALESCE(SUM(deposit_amount),0) FROM savings_transactions").fetchone()[0]
    stats['savings_withdrawn'] = db.execute("SELECT COALESCE(SUM(withdraw_amount),0) FROM savings_transactions").fetchone()[0]
    stats['savings_outstanding'] = stats['total_savings'] - stats['savings_withdrawn']
    center_stats = db.execute("""
        SELECT c.center_code, c.center_name,
               COUNT(DISTINCT m.id) as members,
               COUNT(DISTINCT ld.id) as loans,
               COALESCE(SUM(ld.disbursed_amount),0) as disbursed,
               COALESCE(SUM(rp.paid_amount),0) as collected,
               COALESCE((SELECT SUM(st.deposit_amount) FROM savings_transactions st WHERE st.center_id=c.id),0) as savings_deposits,
               COALESCE((SELECT SUM(st.withdraw_amount) FROM savings_transactions st WHERE st.center_id=c.id),0) as savings_withdrawals
        FROM centers c
        LEFT JOIN members m ON m.center_id=c.id AND m.status='ACTIVE'
        LEFT JOIN loan_applications la ON la.center_id=c.id
        LEFT JOIN loan_disbursements ld ON ld.application_id=la.id
        LEFT JOIN recovery_postings rp ON rp.disbursement_id=ld.id
        GROUP BY c.id ORDER BY c.center_code
    """).fetchall()
    db.close()
    return render_template('reports/glance_report.html', stats=stats, center_stats=center_stats)

@app.route('/reports/passbook')
@login_required
def report_passbook():
    db = get_db()
    member_filter = request.args.get('member_id', '')
    loan_filter = request.args.get('loan_id', '')
    member = None
    loan = None
    postings = []
    if loan_filter:
        loan = db.execute("""
            SELECT ld.*, la.application_no, la.purpose, la.loan_cycle, la.processing_fee,
                   la.insurance_fee, la.nominee_insurance_fee, la.other_charges,
                   m.full_name as member_name, m.member_code,
                   c.center_name, lt.loan_type_name, lt.interest_rate
            FROM loan_disbursements ld
            LEFT JOIN loan_applications la ON ld.application_id=la.id
            LEFT JOIN members m ON la.member_id=m.id
            LEFT JOIN centers c ON la.center_id=c.id
            LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
            WHERE ld.loan_id=?
        """, (loan_filter,)).fetchone()
        if loan:
            postings = db.execute(
                "SELECT * FROM recovery_postings WHERE disbursement_id=? ORDER BY installment_no",
                (loan['id'],)
            ).fetchall()
    members = db.execute("SELECT id, member_code, full_name FROM members ORDER BY member_code").fetchall()
    loans = db.execute(
        "SELECT ld.loan_id, m.member_code, m.full_name FROM loan_disbursements ld "
        "LEFT JOIN loan_applications la ON ld.application_id=la.id "
        "LEFT JOIN members m ON la.member_id=m.id ORDER BY ld.id DESC"
    ).fetchall()
    db.close()
    return render_template('reports/passbook_report.html', loan=loan, postings=postings,
                           members=members, loans=loans,
                           member_filter=member_filter, loan_filter=loan_filter)

@app.route('/reports/loan-ledger')
@login_required
def report_loan_ledger():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    member_filter = request.args.get('member_id', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    query = """
        SELECT ld.loan_id, ld.disbursement_date, ld.disbursed_amount, ld.total_installments,
               ld.installment_amount,
               la.application_no, la.purpose, la.loan_cycle,
               m.full_name as member_name, m.member_code, m.grp,
               c.center_name, c.center_code,
               lt.loan_type_name, lt.interest_rate,
               COALESCE(SUM(rp.paid_amount),0) as total_paid,
               ld.disbursed_amount - COALESCE(SUM(rp.paid_amount),0) as outstanding,
               COUNT(rp.id) as paid_count
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        LEFT JOIN recovery_postings rp ON rp.disbursement_id=ld.id
        WHERE 1=1
    """
    params = []
    if center_filter:
        query += " AND la.center_id=?"
        params.append(center_filter)
    if member_filter:
        query += " AND la.member_id=?"
        params.append(member_filter)
    query += " GROUP BY ld.id ORDER BY c.center_code, m.member_code, ld.id"
    records = db.execute(query, params).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    members = db.execute("SELECT id, member_code, full_name FROM members WHERE status='ACTIVE' ORDER BY member_code").fetchall()
    db.close()
    return render_template('reports/loan_ledger.html', records=records, centers=centers,
                           members=members, center_filter=center_filter,
                           member_filter=member_filter, from_date=from_date, to_date=to_date)

@app.route('/reports/insurance')
@login_required
def report_insurance():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    data = db.execute("""
        SELECT m.member_code, m.full_name, m.date_of_birth, m.spouse_name,
               la.nominee_name, la.nominee_kyc_type, la.nominee_kyc_number,
               la.insurance_fee, la.nominee_insurance_fee,
               ld.loan_id, ld.disbursement_date, ld.disbursed_amount,
               c.center_name, c.center_code,
               lt.loan_type_name
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        WHERE ld.status='Disbursed'
        """ + (" AND la.center_id=?" if center_filter else "") + """
        ORDER BY c.center_code, m.member_code
    """, ([center_filter] if center_filter else [])).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/insurance_report.html', data=data,
                           centers=centers, center_filter=center_filter)

@app.route('/help')
@login_required
def help_page():
    return render_template('help.html')

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
