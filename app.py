from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response, g
from werkzeug.security import check_password_hash, generate_password_hash
from database import get_master_db, get_branch_db, init_db, init_branch_db, BRANCHES_DIR
from functools import wraps
import os
import json
import sqlite3
import secrets
from datetime import datetime, timedelta

def get_db():
    """Return a connection to the current branch database."""
    branch_db = session.get('branch_db')
    if not branch_db:
        return None
    return get_branch_db(branch_db)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'mythri-lms-secret-2024')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.context_processor
def inject_helpers():
    return dict(_number_to_words=_number_to_words)

@app.context_processor
def inject_subscription_ctx():
    return {
        'sub_warning_days': getattr(g, 'sub_warning_days', None),
        'sub_due_date_str': getattr(g, 'sub_due_date_str', ''),
        'sub_amount':       getattr(g, 'sub_amount', 0),
        'sub_scanner':      getattr(g, 'sub_scanner', None),
        'sub_paid_pending': getattr(g, 'sub_paid_pending', False),
    }

_SUBSCRIPTION_EXEMPT = frozenset([
    'login', 'logout', 'static',
    'device_pending', 'device_check_status',
    'developer_panel', 'developer_logout', 'developer_device_action', 'developer_purge_duplicates',
    'developer_subscription_settings', 'developer_subscription_approve',
    'developer_subscription_undo', 'developer_subscription_delete',
    'developer_scanner_upload',
    'subscription_blocked', 'subscription_submit_payment',
])

@app.before_request
def check_subscription():
    ep = request.endpoint
    if not ep or ep in _SUBSCRIPTION_EXEMPT or ep.startswith('static'):
        return None
    if 'user_id' not in session or 'branch_db' not in session:
        return None
    import calendar as _cal
    branch_db = session['branch_db']
    master = get_master_db()
    sub = master.execute(
        "SELECT * FROM branch_subscriptions WHERE branch_db=? AND enabled=1", (branch_db,)
    ).fetchone()
    if not sub:
        master.close()
        return None
    from datetime import timezone, timedelta
    _IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(_IST).replace(tzinfo=None)
    today = now.date()
    last_day = _cal.monthrange(today.year, today.month)[1]
    due_day = min(int(sub['due_day']), last_day)
    from datetime import date as _date
    due_date = _date(today.year, today.month, due_day)
    # Parse due_time (HH:MM), default 23:59
    due_time_str = (sub['due_time'] if 'due_time' in sub.keys() else None) or '23:59'
    try:
        dh, dm = int(due_time_str.split(':')[0]), int(due_time_str.split(':')[1])
    except Exception:
        dh, dm = 23, 59
    due_datetime = datetime(due_date.year, due_date.month, due_date.day, dh, dm)
    month_key = today.strftime('%Y-%m')
    payment = master.execute(
        "SELECT * FROM subscription_payments WHERE branch_db=? AND month_key=?",
        (branch_db, month_key)
    ).fetchone()
    scanner_row = master.execute(
        "SELECT value FROM developer_settings WHERE key='scanner_image'"
    ).fetchone()
    master.close()
    if payment and payment['status'] == 'Approved':
        return None
    g.sub_amount = sub['monthly_amount'] if sub else 0
    g.sub_scanner = scanner_row['value'] if scanner_row else None
    g.sub_paid_pending = (payment is not None)
    days_left = (due_date - today).days
    _h12 = dh % 12 or 12
    _ampm = 'AM' if dh < 12 else 'PM'
    g.sub_due_date_str = f"{due_date.strftime('%d/%m/%Y')} by {_h12}:{dm:02d} {_ampm}"
    if now >= due_datetime:
        g.sub_blocked = True
        g.sub_payment_pending = (payment is not None)
        if ep not in ('subscription_blocked', 'subscription_submit_payment'):
            return redirect(url_for('subscription_blocked'))
    else:
        g.sub_warning_days = days_left
    return None

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
        if 'user_id' not in session or 'branch_db' not in session:
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

# ── Device helpers ────────────────────────────────────────────────────────────

def _parse_device_label(ua):
    ua = ua or ''
    if 'Edg' in ua:
        browser = 'Edge'
    elif 'OPR' in ua or 'Opera' in ua:
        browser = 'Opera'
    elif 'Chrome' in ua:
        browser = 'Chrome'
    elif 'Firefox' in ua:
        browser = 'Firefox'
    elif 'Safari' in ua:
        browser = 'Safari'
    else:
        browser = 'Browser'
    if 'Android' in ua:
        os_name = 'Android'
    elif 'iPhone' in ua or 'iPad' in ua:
        os_name = 'iOS'
    elif 'Windows' in ua:
        os_name = 'Windows'
    elif 'Mac OS' in ua:
        os_name = 'Mac'
    elif 'Linux' in ua:
        os_name = 'Linux'
    else:
        os_name = 'Unknown'
    device = 'Mobile' if ('Mobile' in ua or 'Android' in ua or 'iPhone' in ua) else 'Desktop'
    return f"{browser} on {os_name} ({device})"

# ── Auth routes ───────────────────────────────────────────────────────────────

def developer_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_developer'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_id' in session and 'branch_db' in session:
        return redirect(url_for('dashboard'))
    if session.get('is_developer'):
        return redirect(url_for('developer_panel'))
    master = get_master_db()
    branches = master.execute("SELECT id, name FROM branches WHERE active=1 ORDER BY name").fetchall()
    master.close()
    error = None
    if request.method == 'POST':
        login_name  = request.form.get('login_name', '').strip()
        password    = request.form.get('password', '').strip()

        # Check master/developer account first (no branch required)
        master_check = get_master_db()
        dev_user = master_check.execute(
            "SELECT * FROM master_users WHERE login_name=? AND active=1", (login_name,)
        ).fetchone()
        master_check.close()
        if dev_user and check_password_hash(dev_user['password_hash'], password):
            session['is_developer'] = True
            session['dev_name']     = dev_user['full_name']
            session['dev_login']    = dev_user['login_name']
            return redirect(url_for('developer_panel'))

        branch_id   = request.form.get('branch_id', '').strip()
        if not branch_id:
            error = 'Please select a branch.'
        else:
            master = get_master_db()
            branch = master.execute(
                "SELECT * FROM branches WHERE id=? AND active=1", (branch_id,)
            ).fetchone()
            master.close()
            if not branch:
                error = 'Invalid branch selected.'
            else:
                db   = get_branch_db(branch['db_path'])
                user = db.execute(
                    "SELECT * FROM users WHERE login_name=? AND active=1", (login_name,)
                ).fetchone()
                db.close()
                if user and check_password_hash(user['password_hash'], password):
                    master2 = get_master_db()
                    token_cookie = request.cookies.get('device_token')
                    device = None
                    if token_cookie:
                        device = master2.execute(
                            "SELECT * FROM device_approvals WHERE device_token=? AND user_id=? AND branch_db=?",
                            (token_cookie, user['id'], branch['db_path'])
                        ).fetchone()
                    if device:
                        if device['status'] == 'Approved':
                            master2.close()
                            session['user_id']    = user['id']
                            session['role']       = user['role']
                            session['full_name']  = user['full_name']
                            session['login_name'] = user['login_name']
                            session['branch_id']  = branch['id']
                            session['branch_name']= branch['name']
                            session['branch_db']  = branch['db_path']
                            return redirect(url_for('dashboard'))
                        elif device['status'] == 'Blocked':
                            master2.close()
                            error = 'This device has been blocked by the admin. Contact your administrator.'
                        else:
                            master2.close()
                            return redirect(url_for('device_pending'))
                    else:
                        label = _parse_device_label(request.headers.get('User-Agent', ''))
                        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
                        new_token = secrets.token_hex(32)
                        # Check for existing record with same user + branch + device_label (cookie cleared)
                        existing_label = master2.execute(
                            "SELECT * FROM device_approvals WHERE user_id=? AND branch_db=? AND device_label=? "
                            "ORDER BY id DESC LIMIT 1",
                            (user['id'], branch['db_path'], label)
                        ).fetchone()
                        if existing_label:
                            # Reuse existing record — just refresh the token and IP
                            device = existing_label
                            master2.execute(
                                "UPDATE device_approvals SET device_token=?, ip_address=? WHERE id=?",
                                (new_token, ip, device['id'])
                            )
                            master2.commit()
                            master2.close()
                            if device['status'] == 'Approved':
                                session['user_id']    = user['id']
                                session['role']       = user['role']
                                session['full_name']  = user['full_name']
                                session['login_name'] = user['login_name']
                                session['branch_id']  = branch['id']
                                session['branch_name']= branch['name']
                                session['branch_db']  = branch['db_path']
                                resp = make_response(redirect(url_for('dashboard')))
                            elif device['status'] == 'Blocked':
                                return render_template('login.html',
                                    branches=get_master_db().execute("SELECT * FROM branches WHERE active=1").fetchall(),
                                    error='This device has been blocked. Contact your administrator.')
                            else:
                                resp = make_response(redirect(url_for('device_pending')))
                            resp.set_cookie('device_token', new_token,
                                            max_age=365*24*3600, httponly=True, samesite='Lax')
                            return resp
                        # Truly new device — bootstrap only if user has NO approved device across ANY branch
                        global_approved = master2.execute(
                            "SELECT COUNT(*) FROM device_approvals WHERE user_id=? AND status='Approved'",
                            (user['id'],)
                        ).fetchone()[0]
                        initial_status = 'Approved' if global_approved == 0 else 'Pending'
                        master2.execute("""
                            INSERT INTO device_approvals
                            (user_id, branch_db, user_login_name, user_full_name, branch_name,
                             device_token, device_label, ip_address, status)
                            VALUES (?,?,?,?,?,?,?,?,?)
                        """, (user['id'], branch['db_path'], user['login_name'], user['full_name'],
                              branch['name'], new_token, label, ip, initial_status))
                        master2.commit()
                        master2.close()
                        if initial_status == 'Approved':
                            session['user_id']    = user['id']
                            session['role']       = user['role']
                            session['full_name']  = user['full_name']
                            session['login_name'] = user['login_name']
                            session['branch_id']  = branch['id']
                            session['branch_name']= branch['name']
                            session['branch_db']  = branch['db_path']
                            resp = make_response(redirect(url_for('dashboard')))
                        else:
                            resp = make_response(redirect(url_for('device_pending')))
                        resp.set_cookie('device_token', new_token,
                                        max_age=365*24*3600, httponly=True, samesite='Lax')
                        return resp
                else:
                    error = 'Invalid username or password.'
    return render_template('login.html', error=error, branches=branches)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/developer')
@developer_required
def developer_panel():
    master = get_master_db()
    devices = master.execute(
        "SELECT * FROM device_approvals ORDER BY CASE status WHEN 'Pending' THEN 0 WHEN 'Approved' THEN 1 ELSE 2 END, created_at DESC"
    ).fetchall()
    branches_raw = master.execute("SELECT * FROM branches ORDER BY name").fetchall()
    branches_list = [dict(b) for b in branches_raw]
    branches_stats = []
    for br in branches_raw:
        stat = {
            'name': br['name'], 'active': br['active'],
            'members': 0, 'active_loans': 0, 'closed_loans': 0,
            'outstanding': 0.0, 'approved_devices': 0, 'pending_devices': 0
        }
        stat['approved_devices'] = master.execute(
            "SELECT COUNT(*) FROM device_approvals WHERE branch_db=? AND status='Approved'", (br['db_path'],)
        ).fetchone()[0]
        stat['pending_devices'] = master.execute(
            "SELECT COUNT(*) FROM device_approvals WHERE branch_db=? AND status='Pending'", (br['db_path'],)
        ).fetchone()[0]
        if os.path.exists(br['db_path']):
            try:
                bdb = get_branch_db(br['db_path'])
                stat['members'] = bdb.execute(
                    "SELECT COUNT(*) FROM members WHERE status='ACTIVE'"
                ).fetchone()[0]
                stat['active_loans'] = bdb.execute(
                    "SELECT COUNT(*) FROM loan_disbursements WHERE status='Disbursed'"
                ).fetchone()[0]
                stat['closed_loans'] = bdb.execute(
                    "SELECT COUNT(*) FROM loan_disbursements WHERE status='Closed'"
                ).fetchone()[0]
                row = bdb.execute("""
                    SELECT COALESCE(SUM(ld.disbursed_amount),0) -
                           COALESCE((SELECT SUM(rp.principal) FROM recovery_postings rp
                                     WHERE rp.disbursement_id=ld.id AND rp.installment_no>0),0)
                    FROM loan_disbursements ld WHERE ld.status='Disbursed'
                """).fetchone()
                stat['outstanding'] = round(row[0] or 0, 2)
                bdb.close()
            except Exception:
                pass
        branches_stats.append(stat)
    # Subscription data
    sub_rows = master.execute(
        "SELECT * FROM branch_subscriptions"
    ).fetchall()
    sub_map = {r['branch_db']: dict(r) for r in sub_rows}

    pending_payments = master.execute("""
        SELECT * FROM subscription_payments
        WHERE status='Pending' ORDER BY paid_at DESC
    """).fetchall()

    approved_payments = master.execute("""
        SELECT * FROM subscription_payments
        WHERE status='Approved' ORDER BY approved_at DESC LIMIT 50
    """).fetchall()

    scanner_row = master.execute(
        "SELECT value FROM developer_settings WHERE key='scanner_image'"
    ).fetchone()
    scanner_image = scanner_row['value'] if scanner_row else None

    master.close()
    return render_template('developer.html',
        devices=devices, branches_stats=branches_stats,
        branches_list=branches_list,
        sub_map=sub_map, pending_payments=pending_payments,
        approved_payments=approved_payments,
        scanner_image=scanner_image)

@app.route('/developer/devices/<int:did>/action', methods=['POST'])
@developer_required
def developer_device_action(did):
    action = request.form.get('action')
    master = get_master_db()
    if action == 'approve':
        master.execute(
            "UPDATE device_approvals SET status='Approved', approved_at=datetime('now','localtime'), approved_by_name=? WHERE id=?",
            (session.get('dev_name'), did)
        )
        flash('Device approved.', 'success')
    elif action == 'block':
        master.execute("UPDATE device_approvals SET status='Blocked' WHERE id=?", (did,))
        flash('Device blocked.', 'warning')
    elif action == 'delete':
        master.execute("DELETE FROM device_approvals WHERE id=?", (did,))
        flash('Device record removed.', 'info')
    master.commit()
    master.close()
    return redirect(url_for('developer_panel'))

@app.route('/developer/devices/purge-duplicates', methods=['POST'])
@developer_required
def developer_purge_duplicates():
    master = get_master_db()
    # Keep only the most recent record per (user_id, branch_db, device_label); delete the rest
    master.execute("""
        DELETE FROM device_approvals
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM device_approvals
            GROUP BY user_id, branch_db, device_label
        )
    """)
    deleted = master.execute("SELECT changes()").fetchone()[0]
    master.commit()
    master.close()
    flash(f'Removed {deleted} duplicate device record(s).', 'success')
    return redirect(url_for('developer_panel'))


@app.route('/developer/logout')
def developer_logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/device-pending')
def device_pending():
    token = request.cookies.get('device_token')
    if not token:
        return redirect(url_for('login'))
    master = get_master_db()
    device = master.execute("SELECT * FROM device_approvals WHERE device_token=?", (token,)).fetchone()
    master.close()
    if not device:
        return redirect(url_for('login'))
    if device['status'] == 'Approved':
        return redirect(url_for('login'))
    return render_template('device_pending.html', device=device)

@app.route('/device-status')
def device_status():
    token = request.cookies.get('device_token')
    if not token:
        return jsonify({'status': 'unknown'})
    master = get_master_db()
    device = master.execute("SELECT status FROM device_approvals WHERE device_token=?", (token,)).fetchone()
    master.close()
    return jsonify({'status': device['status'] if device else 'unknown'})

@app.route('/admin/devices')
@admin_required
def admin_devices():
    master = get_master_db()
    devices = master.execute(
        "SELECT * FROM device_approvals ORDER BY CASE status WHEN 'Pending' THEN 0 WHEN 'Approved' THEN 1 ELSE 2 END, created_at DESC"
    ).fetchall()
    master.close()
    return render_template('admin/devices.html', devices=devices)

@app.route('/admin/devices/<int:did>/action', methods=['POST'])
@admin_required
def admin_device_action(did):
    action = request.form.get('action')
    master = get_master_db()
    if action == 'approve':
        master.execute(
            "UPDATE device_approvals SET status='Approved', approved_at=datetime('now','localtime'), approved_by_name=? WHERE id=?",
            (session.get('full_name'), did)
        )
        flash('Device approved successfully.', 'success')
    elif action == 'block':
        master.execute("UPDATE device_approvals SET status='Blocked' WHERE id=?", (did,))
        flash('Device blocked.', 'warning')
    elif action == 'delete':
        master.execute("DELETE FROM device_approvals WHERE id=?", (did,))
        flash('Device record removed.', 'info')
    master.commit()
    master.close()
    return redirect(url_for('admin_devices'))

# ── Branch management (Admin only) ────────────────────────────────────────────

@app.route('/branches')
@admin_required
def branches_list():
    master = get_master_db()
    branches = master.execute("SELECT * FROM branches ORDER BY name").fetchall()
    master.close()
    return render_template('branches/list.html', branches=branches)

@app.route('/branches/new', methods=['GET', 'POST'])
@admin_required
def branch_new():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Branch name is required.', 'danger')
            return render_template('branches/form.html', branch=None)
        db_path = os.path.join(BRANCHES_DIR, f"{name.lower().replace(' ', '_')}.db")
        master  = get_master_db()
        try:
            master.execute("INSERT INTO branches (name, db_path) VALUES (?, ?)", (name, db_path))
            master.commit()
            if not os.path.exists(db_path):
                init_branch_db(db_path)
            flash(f'Branch "{name}" created successfully.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'danger')
        finally:
            master.close()
        return redirect(url_for('branches_list'))
    return render_template('branches/form.html', branch=None)

@app.route('/branches/<int:bid>/edit', methods=['GET', 'POST'])
@admin_required
def branch_edit(bid):
    master = get_master_db()
    branch = master.execute("SELECT * FROM branches WHERE id=?", (bid,)).fetchone()
    if not branch:
        master.close()
        flash('Branch not found.', 'danger')
        return redirect(url_for('branches_list'))
    if request.method == 'POST':
        name   = request.form.get('name', '').strip()
        active = 1 if request.form.get('active') else 0
        master.execute("UPDATE branches SET name=?, active=? WHERE id=?", (name, active, bid))
        master.commit()
        master.close()
        flash('Branch updated.', 'success')
        return redirect(url_for('branches_list'))
    master.close()
    return render_template('branches/form.html', branch=branch)

@app.route('/branches/<int:bid>/delete', methods=['POST'])
@admin_required
def branch_delete(bid):
    master = get_master_db()
    master.execute("DELETE FROM branches WHERE id=?", (bid,))
    master.commit()
    master.close()
    flash('Branch deleted.', 'success')
    return redirect(url_for('branches_list'))

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

def _save_member_file(file, member_code, prefix):
    import uuid
    branch_name = os.path.basename(session.get('branch_db', 'default')).replace('.db', '')
    upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], branch_name, member_code)
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(file.filename)[1].lower() or '.jpg'
    fname = f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"
    file.save(os.path.join(upload_dir, fname))
    return f"{branch_name}/{member_code}/{fname}"

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
            member_id = db.execute("SELECT id FROM members WHERE member_code=?", (code,)).fetchone()['id']
            # Handle file uploads
            photo = request.files.get('member_photo')
            if photo and photo.filename:
                path = _save_member_file(photo, code, 'photo')
                db.execute("UPDATE members SET photo_path=? WHERE id=?", (path, member_id))
                db.commit()
            kyc_doc = request.files.get('kyc_doc')
            if kyc_doc and kyc_doc.filename:
                path = _save_member_file(kyc_doc, code, 'kyc')
                label = request.form.get('kyc_type', 'KYC Document')
                db.execute("INSERT INTO member_documents (member_id,doc_type,doc_label,filename,original_name) VALUES (?,?,?,?,?)",
                           (member_id, 'kyc', label, path, kyc_doc.filename))
                db.commit()
            for other in request.files.getlist('other_docs'):
                if other and other.filename:
                    path = _save_member_file(other, code, 'doc')
                    db.execute("INSERT INTO member_documents (member_id,doc_type,doc_label,filename,original_name) VALUES (?,?,?,?,?)",
                               (member_id, 'other', 'Document', path, other.filename))
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
        try:
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
            code = db.execute("SELECT member_code FROM members WHERE id=?", (mid,)).fetchone()['member_code']
            photo = request.files.get('member_photo')
            if photo and photo.filename:
                path = _save_member_file(photo, code, 'photo')
                db.execute("UPDATE members SET photo_path=? WHERE id=?", (path, mid))
                db.commit()
            kyc_doc = request.files.get('kyc_doc')
            if kyc_doc and kyc_doc.filename:
                path = _save_member_file(kyc_doc, code, 'kyc')
                label = request.form.get('kyc_type', 'KYC Document')
                db.execute("INSERT INTO member_documents (member_id,doc_type,doc_label,filename,original_name) VALUES (?,?,?,?,?)",
                           (mid, 'kyc', label, path, kyc_doc.filename))
                db.commit()
            for other in request.files.getlist('other_docs'):
                if other and other.filename:
                    path = _save_member_file(other, code, 'doc')
                    db.execute("INSERT INTO member_documents (member_id,doc_type,doc_label,filename,original_name) VALUES (?,?,?,?,?)",
                               (mid, 'other', 'Document', path, other.filename))
                    db.commit()
            flash('Member updated.', 'success')
        except Exception as e:
            flash(f'Error updating member: {e}', 'danger')
        finally:
            db.close()
        return redirect(url_for('members_edit', mid=mid))
    docs = db.execute("SELECT * FROM member_documents WHERE member_id=? ORDER BY uploaded_at DESC", (mid,)).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('members/form.html', member=member, centers=centers, docs=docs)

@app.route('/members/<int:mid>/delete', methods=['POST'])
@admin_required
def members_delete(mid):
    db = get_db()
    db.execute("DELETE FROM members WHERE id=?", (mid,))
    db.commit()
    db.close()
    flash('Member deleted.', 'success')
    return redirect(url_for('members_list'))

@app.route('/members/<int:mid>/documents/<int:doc_id>/delete', methods=['POST'])
@login_required
def member_doc_delete(mid, doc_id):
    db = get_db()
    row = db.execute("SELECT filename FROM member_documents WHERE id=? AND member_id=?", (doc_id, mid)).fetchone()
    if row:
        full_path = os.path.join(app.config['UPLOAD_FOLDER'], row['filename'])
        if os.path.exists(full_path):
            os.remove(full_path)
        db.execute("DELETE FROM member_documents WHERE id=?", (doc_id,))
        db.commit()
    db.close()
    return redirect(url_for('members_edit', mid=mid))

# ── Member Applications ───────────────────────────────────────────────────────

@app.route('/member-applications')
@login_required
def member_applications():
    db = get_db()
    members = db.execute("""
        SELECT m.*, c.center_name FROM members m
        LEFT JOIN centers c ON m.center_id = c.id
        WHERE m.photo_path IS NOT NULL AND m.photo_path != ''
        ORDER BY m.id DESC
    """).fetchall()
    db.close()
    return render_template('members/applications.html', members=members)

# ── KYC Documents ─────────────────────────────────────────────────────────────

@app.route('/documents')
@login_required
def documents_list():
    db = get_db()
    q = request.args.get('q', '').strip()
    if q:
        members = db.execute("""
            SELECT m.*, c.center_name FROM members m
            LEFT JOIN centers c ON m.center_id = c.id
            WHERE m.full_name LIKE ? OR m.member_code LIKE ?
            ORDER BY m.full_name
        """, (f'%{q}%', f'%{q}%')).fetchall()
    else:
        members = db.execute("""
            SELECT m.*, c.center_name FROM members m
            LEFT JOIN centers c ON m.center_id = c.id
            ORDER BY m.full_name
        """).fetchall()
    db.close()
    return render_template('documents/index.html', members=members, q=q)

@app.route('/documents/<int:mid>')
@login_required
def documents_view(mid):
    db = get_db()
    member = db.execute("""
        SELECT m.*, c.center_name, c.center_code FROM members m
        LEFT JOIN centers c ON m.center_id = c.id
        WHERE m.id=?
    """, (mid,)).fetchone()
    docs = db.execute("SELECT * FROM member_documents WHERE member_id=? ORDER BY doc_type, uploaded_at", (mid,)).fetchall()
    loans = db.execute("""
        SELECT la.application_no, la.applied_amount, la.applied_date, la.purpose, la.status,
               ld.disbursement_no, ld.disbursed_amount, ld.disbursement_date,
               COALESCE((SELECT SUM(rp.principal) FROM recovery_postings rp WHERE rp.disbursement_id=ld.id),0) as paid_principal
        FROM loan_applications la
        LEFT JOIN loan_disbursements ld ON ld.application_id = la.id
        WHERE la.member_id=?
        ORDER BY la.id DESC
    """, (mid,)).fetchall()
    db.close()
    return render_template('documents/view.html', member=member, docs=docs, loans=loans)

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
    members = db.execute("""
        SELECT m.id, m.member_code, m.full_name, m.center_id, m.income, m.kyc_type, m.kyc_number
        FROM members m
        LEFT JOIN (SELECT member_id, MAX(id) as last_app_id FROM loan_applications GROUP BY member_id) la ON m.id = la.member_id
        WHERE m.status='ACTIVE'
        ORDER BY CASE WHEN la.last_app_id IS NULL THEN 1 ELSE 0 END, la.last_app_id DESC, m.member_code
    """).fetchall()
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
    members = db.execute("""
        SELECT m.id, m.member_code, m.full_name, m.center_id, m.income, m.kyc_type, m.kyc_number
        FROM members m
        LEFT JOIN (SELECT member_id, MAX(id) as last_app_id FROM loan_applications GROUP BY member_id) la ON m.id = la.member_id
        WHERE m.status='ACTIVE'
        ORDER BY CASE WHEN la.last_app_id IS NULL THEN 1 ELSE 0 END, la.last_app_id DESC, m.member_code
    """).fetchall()
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

    members = db.execute("""
        SELECT m.id, m.member_code, m.full_name, m.center_id, m.income, m.kyc_type, m.kyc_number
        FROM members m
        LEFT JOIN (SELECT member_id, MAX(id) as last_app_id FROM loan_applications GROUP BY member_id) la ON m.id = la.member_id
        WHERE m.status='ACTIVE'
        ORDER BY CASE WHEN la.last_app_id IS NULL THEN 1 ELSE 0 END, la.last_app_id DESC, m.member_code
    """).fetchall()
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

@app.route('/loans/disbursement/bulk-disburse', methods=['POST'])
@admin_required
def loan_bulk_disburse():
    db = get_db()
    selected_ids = request.form.getlist('selected_ids')
    if not selected_ids:
        flash('No loans selected.', 'warning')
        db.close()
        return redirect(url_for('loan_disbursement_list'))
    disbursement_date = request.form.get('disbursement_date', datetime.now().strftime('%d/%m/%Y'))
    total_inst = int(request.form.get('total_installments', 50))
    mode = request.form.get('mode', 'Cash')
    account_no = request.form.get('account_no', '')
    remarks = request.form.get('remarks', '')
    count = 0
    for aid in selected_ids:
        aid = int(aid)
        app_rec = db.execute("""
            SELECT la.*, COALESCE(apr.approved_amount, la.applied_amount) as disburse_amount
            FROM loan_applications la
            LEFT JOIN loan_approvals apr ON apr.application_id=la.id
            WHERE la.id=? AND la.status='Approved'
        """, (aid,)).fetchone()
        if not app_rec:
            continue
        last = db.execute("SELECT disbursement_no FROM loan_disbursements ORDER BY id DESC LIMIT 1").fetchone()
        num = int(last['disbursement_no'][3:]) + 1 if last else 1
        dis_no = f"DIS{num:06d}"
        loan_id = _next_loan_id(db)
        disbursed_amount = float(app_rec['disburse_amount'] or 0)
        inst_amount = round(disbursed_amount / total_inst, 2) if total_inst else 0
        db.execute("""
            INSERT INTO loan_disbursements (application_id,disbursement_no,loan_id,disbursed_amount,
            disbursement_date,mode,account_no,disbursed_by,status,total_installments,installment_amount,remarks)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (aid, dis_no, loan_id, disbursed_amount, disbursement_date,
              mode, account_no, session['user_id'], 'Disbursed', total_inst, inst_amount, remarks))
        db.execute("UPDATE loan_applications SET status='Disbursed' WHERE id=?", (aid,))
        db.commit()
        count += 1
    db.close()
    flash(f'{count} loan(s) disbursed successfully.', 'success')
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
               (SELECT COUNT(*) FROM recovery_postings rp WHERE rp.disbursement_id=ld.id AND rp.installment_no > 0) as paid_count,
               (SELECT rp2.id FROM recovery_postings rp2
                WHERE rp2.disbursement_id=ld.id AND rp2.posting_date=:date
                ORDER BY rp2.id DESC LIMIT 1) as today_posting_id,
               (SELECT COUNT(*) FROM arrear_entries ae WHERE ae.disbursement_id=ld.id AND ae.status='Pending') as pending_arrears
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        WHERE ld.status='Disbursed'
        AND (SELECT COUNT(*) FROM recovery_postings rp3 WHERE rp3.disbursement_id=ld.id AND rp3.installment_no > 0) < ld.total_installments
        AND substr(ld.disbursement_date,7,4)||'-'||substr(ld.disbursement_date,4,2)||'-'||substr(ld.disbursement_date,1,2)
            < substr(:date,7,4)||'-'||substr(:date,4,2)||'-'||substr(:date,1,2)
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
    if _is_day_locked(db, posting_date):
        flash(f'Day {posting_date} is closed. Undo Day End first to make changes.', 'danger')
        db.close()
        return redirect(url_for('recovery_posting_list', date=posting_date))
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
            "SELECT COUNT(*) FROM recovery_postings WHERE disbursement_id=? AND installment_no > 0", (did,)
        ).fetchone()[0]
        if paid_count >= loan['total_installments']:
            continue
        # Skip if already posted on this date
        already = db.execute(
            "SELECT id FROM recovery_postings WHERE disbursement_id=? AND posting_date=? AND installment_no > 0",
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
        if _is_day_locked(db, posting_date):
            flash(f'Day {posting_date} is closed. Undo Day End first to make changes.', 'danger')
            db.close()
            return redirect(url_for('recovery_post', did=did))
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
    rp = db.execute("SELECT posting_date FROM recovery_postings WHERE id=?", (rid,)).fetchone()
    posting_date = rp['posting_date'] if rp else ''
    db.execute("DELETE FROM savings_transactions WHERE recovery_posting_id=?", (rid,))
    db.execute("DELETE FROM recovery_postings WHERE id=?", (rid,))
    db.commit()
    db.close()
    flash('Recovery posting reversed and linked savings transaction deleted.', 'success')
    back = request.form.get('back', '')
    if back == 'undo':
        return redirect(url_for('recovery_undo_list', date=posting_date))
    return redirect(url_for('recovery_posting_list', date=posting_date))

# ── Any Day Prepaid/Undo ──────────────────────────────────────────────────────

def _is_day_locked(db, date_str):
    return db.execute("SELECT id FROM day_end WHERE day_date=?", (date_str,)).fetchone() is not None

def _to_iso(date_str):
    """Convert DD/MM/YYYY to YYYY-MM-DD for SQLite string comparison."""
    try:
        p = date_str.split('/')
        return f"{p[2]}-{p[1]}-{p[0]}"
    except Exception:
        return date_str

def _days_since(date_str):
    """Days from DD/MM/YYYY date to today."""
    try:
        d = datetime.strptime(date_str, '%d/%m/%Y')
        return max((datetime.today() - d).days, 0)
    except Exception:
        return 0

def _days_between(d1_str, d2_str):
    """Days between two DD/MM/YYYY dates."""
    try:
        d1 = datetime.strptime(d1_str, '%d/%m/%Y')
        d2 = datetime.strptime(d2_str, '%d/%m/%Y')
        return max((d2 - d1).days, 0)
    except Exception:
        return 0

def _add_months(date_str, months):
    """Add whole months to a DD/MM/YYYY string, return DD/MM/YYYY."""
    import calendar as _cal
    try:
        dt = datetime.strptime(date_str, '%d/%m/%Y')
        m = dt.month - 1 + months
        year = dt.year + m // 12
        month = m % 12 + 1
        day = min(dt.day, _cal.monthrange(year, month)[1])
        return datetime(year, month, day).strftime('%d/%m/%Y')
    except Exception:
        return ''

def _calc_interest(principal, roi, days):
    """Simple interest = principal × roi/100 × days/365."""
    if principal <= 0 or not roi or days <= 0:
        return 0.0
    return round(principal * (roi / 100) * (days / 365), 2)

def _number_to_words(n):
    """Convert a number to Indian rupee words (e.g. 31250.00 → 'Thirty One Thousand Two Hundred Fifty Only')."""
    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
            'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
            'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def below_100(n):
        if n < 20: return ones[n]
        return tens[n // 10] + (' ' + ones[n % 10] if n % 10 else '')

    def below_1000(n):
        if n < 100: return below_100(n)
        return ones[n // 100] + ' Hundred' + (' ' + below_100(n % 100) if n % 100 else '')

    def to_words(n):
        if n == 0: return ''
        if n < 1000: return below_1000(n)
        if n < 100000: return below_1000(n // 1000) + ' Thousand' + (' ' + below_1000(n % 1000) if n % 1000 else '')
        if n < 10000000: return below_1000(n // 100000) + ' Lakh' + (' ' + to_words(n % 100000) if n % 100000 else '')
        return below_1000(n // 10000000) + ' Crore' + (' ' + to_words(n % 10000000) if n % 10000000 else '')

    try:
        n = float(n or 0)
        rupees = int(n)
        paise = round((n - rupees) * 100)
        result = to_words(rupees) or 'Zero'
        if paise:
            result += ' and ' + below_100(paise) + ' Paise'
        return 'Rupees ' + result + ' Only'
    except Exception:
        return ''

def _posting_loans(db, date_filter, center_filter):
    """Loans with ≥1 recovery posting, filtered by center meeting day or specific center."""
    try:
        day_name = datetime.strptime(date_filter, '%d/%m/%Y').strftime('%A')
    except Exception:
        day_name = datetime.now().strftime('%A')
    params = {'date': date_filter}
    query = """
        SELECT ld.*, la.application_no, la.center_id,
               m.full_name as member_name, m.member_code,
               c.center_name, c.center_code, c.meeting_week,
               (SELECT COUNT(*) FROM recovery_postings rp WHERE rp.disbursement_id=ld.id AND rp.installment_no > 0) as paid_count
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        WHERE ld.status='Disbursed'
        AND (SELECT COUNT(*) FROM recovery_postings rp2 WHERE rp2.disbursement_id=ld.id AND rp2.installment_no > 0) > 0
        AND substr(ld.disbursement_date,7,4)||'-'||substr(ld.disbursement_date,4,2)||'-'||substr(ld.disbursement_date,1,2)
            < substr(:date,7,4)||'-'||substr(:date,4,2)||'-'||substr(:date,1,2)
    """
    if center_filter:
        query += " AND la.center_id=:center_id"
        params['center_id'] = center_filter
    else:
        query += " AND c.meeting_week=:day"
        params['day'] = day_name
    query += " ORDER BY c.center_code, m.member_code"
    return db.execute(query, params).fetchall(), day_name

@app.route('/loans/posting/prepaid')
@login_required
def prepaid_list():
    db = get_db()
    date_filter = request.args.get('date', datetime.now().strftime('%d/%m/%Y'))
    center_filter = request.args.get('center_id', '')
    loans, day_name = _posting_loans(db, date_filter, center_filter)
    centers = db.execute("SELECT id, center_code, center_name, meeting_week FROM centers WHERE active=1 ORDER BY center_code").fetchall()
    locked = _is_day_locked(db, date_filter)
    db.close()
    return render_template('loans/posting/prepaid_list.html', loans=loans, centers=centers,
                           date_filter=date_filter, center_filter=center_filter,
                           day_name=day_name, locked=locked)

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
        txn_date = request.form.get('transaction_date', datetime.now().strftime('%d/%m/%Y'))
        if _is_day_locked(db, txn_date):
            flash(f'Day {txn_date} is closed. Undo Day End first to make changes.', 'danger')
            db.close()
            return redirect(url_for('prepaid_list'))
        db.execute("""
            INSERT INTO prepaid_transactions (disbursement_id,prepaid_type_id,transaction_date,
            amount,mode,narration,is_undo,posted_by)
            VALUES (?,?,?,?,?,?,?,?)
        """, (did, request.form.get('prepaid_type_id') or None, txn_date,
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
    date_filter = request.args.get('date', datetime.now().strftime('%d/%m/%Y'))
    center_filter = request.args.get('center_id', '')
    loans, day_name = _posting_loans(db, date_filter, center_filter)
    centers = db.execute("SELECT id, center_code, center_name, meeting_week FROM centers WHERE active=1 ORDER BY center_code").fetchall()
    locked = _is_day_locked(db, date_filter)
    db.close()
    return render_template('loans/posting/advance_list.html', loans=loans, centers=centers,
                           date_filter=date_filter, center_filter=center_filter,
                           day_name=day_name, locked=locked)

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
        rec_date = request.form.get('recovery_date', datetime.now().strftime('%d/%m/%Y'))
        if _is_day_locked(db, rec_date):
            flash(f'Day {rec_date} is closed. Undo Day End first to make changes.', 'danger')
            db.close()
            return redirect(url_for('advance_recovery_list'))
        db.execute("""
            INSERT INTO advance_recoveries (disbursement_id,recovery_date,amount,mode,narration,posted_by)
            VALUES (?,?,?,?,?,?)
        """, (did, rec_date, request.form.get('amount', 0), request.form.get('mode', 'Cash'),
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
    date_filter = request.args.get('date', datetime.now().strftime('%d/%m/%Y'))
    center_filter = request.args.get('center_id', '')
    loans, day_name = _posting_loans(db, date_filter, center_filter)
    centers = db.execute("SELECT id, center_code, center_name, meeting_week FROM centers WHERE active=1 ORDER BY center_code").fetchall()
    locked = _is_day_locked(db, date_filter)
    db.close()
    return render_template('loans/posting/moratorium_list.html', loans=loans, centers=centers,
                           date_filter=date_filter, center_filter=center_filter,
                           day_name=day_name, locked=locked)

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
        from_date = request.form.get('from_date', '')
        if from_date and _is_day_locked(db, from_date):
            flash(f'Day {from_date} is closed. Undo Day End first to make changes.', 'danger')
            db.close()
            return redirect(url_for('moratorium_list'))
        db.execute("""
            INSERT INTO moratoriums (disbursement_id,from_date,to_date,reason,applied_by)
            VALUES (?,?,?,?,?)
        """, (did, from_date, request.form.get('to_date', ''),
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

@app.route('/savings/passbook/<int:mid>')
@login_required
def savings_passbook(mid):
    db = get_db()
    member = db.execute("""
        SELECT m.*, c.center_code, c.center_name FROM members m
        LEFT JOIN centers c ON m.center_id=c.id WHERE m.id=?
    """, (mid,)).fetchone()
    transactions = db.execute("""
        SELECT st.*, u.full_name as posted_by_name
        FROM savings_transactions st
        LEFT JOIN users u ON st.posted_by=u.id
        WHERE st.member_id=? ORDER BY st.id
    """, (mid,)).fetchall()
    db.close()
    return render_template('savings/passbook.html', member=member, transactions=transactions)

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
@login_required
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
@login_required
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

@app.route('/savings/transaction/<int:tid>/delete', methods=['POST'])
@admin_required
def savings_transaction_delete(tid):
    db = get_db()
    db.execute("DELETE FROM savings_transactions WHERE id=?", (tid,))
    db.commit()
    db.close()
    flash('Savings transaction deleted.', 'success')
    return redirect(url_for('savings_list'))

@app.route('/savings/undo/<int:mid>', methods=['POST'])
@admin_required
def savings_undo(mid):
    db = get_db()
    last = db.execute(
        "SELECT id FROM savings_transactions WHERE member_id=? ORDER BY id DESC LIMIT 1", (mid,)
    ).fetchone()
    if last:
        db.execute("DELETE FROM savings_transactions WHERE id=?", (last['id'],))
        db.commit()
        flash('Last savings transaction undone.', 'success')
    else:
        flash('No savings transactions to undo.', 'warning')
    db.close()
    return redirect(url_for('savings_list'))

# ── Secure Deposits ───────────────────────────────────────────────────────────

@app.route('/secure-deposits')
@login_required
def secure_deposits_list():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    all_members = db.execute("""
        SELECT m.id, m.member_code, m.full_name, c.center_code, c.center_name, m.center_id
        FROM members m LEFT JOIN centers c ON m.center_id=c.id
        WHERE m.status='ACTIVE' ORDER BY m.member_code
    """).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    where = "WHERE 1=1"
    params = []
    if center_filter:
        where += " AND sa.center_id=?"; params.append(center_filter)
    accounts = db.execute(f"""
        SELECT sa.*, m.member_code, m.full_name, m.phone1, c.center_code, c.center_name,
               u.full_name as created_by_name
        FROM sd_accounts sa
        LEFT JOIN members m ON sa.member_id=m.id
        LEFT JOIN centers c ON sa.center_id=c.id
        LEFT JOIN users u ON sa.created_by=u.id
        {where} ORDER BY sa.sd_no DESC
    """, params).fetchall()
    totals = {
        'count': len(accounts),
        'total_sd': sum(a['sd_amount'] or 0 for a in accounts),
        'total_maturity': sum(a['maturity_amount'] or 0 for a in accounts),
    }
    db.close()
    return render_template('secure_deposits/list.html', accounts=accounts, all_members=all_members,
                           centers=centers, center_filter=center_filter, totals=totals)

@app.route('/secure-deposits/member-info')
@login_required
def secure_deposits_member_info():
    db = get_db()
    mid = request.args.get('mid', '')
    if not mid:
        return jsonify({'center': '', 'loan_amount': 0})
    member = db.execute("""
        SELECT m.*, c.center_code, c.center_name FROM members m
        LEFT JOIN centers c ON m.center_id=c.id WHERE m.id=?
    """, (mid,)).fetchone()
    loan_amt = db.execute("""
        SELECT COALESCE(SUM(ld.disbursed_amount),0) as la
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        WHERE la.member_id=? AND ld.status='Disbursed'
    """, (mid,)).fetchone()['la']
    db.close()
    if not member:
        return jsonify({'center': '', 'loan_amount': 0})
    return jsonify({'center': f"{member['center_code']} {member['center_name']}",
                    'loan_amount': loan_amt or 0})

@app.route('/secure-deposits/new', methods=['POST'])
@login_required
def secure_deposit_new():
    db = get_db()
    mid = int(request.form.get('member_id', 0) or 0)
    loan_amount = float(request.form.get('loan_amount', 0) or 0)
    percentage = float(request.form.get('percentage', 0) or 0)
    roi = float(request.form.get('roi', 0) or 0)
    tenure = int(request.form.get('tenure', 0) or 0)
    tenure_unit = request.form.get('tenure_unit', 'Months')
    start_date = request.form.get('start_date', '').strip()
    remarks = request.form.get('remarks', '').strip()
    if not mid or tenure <= 0 or not start_date:
        flash('All required fields must be filled.', 'danger')
        db.close()
        return redirect(url_for('secure_deposits_list'))
    tenure_months = tenure if tenure_unit == 'Months' else tenure * 12
    sd_amount = loan_amount * percentage / 100
    maturity_amount = sd_amount + sd_amount * roi / 100 * (tenure_months / 12)
    member = db.execute("SELECT center_id FROM members WHERE id=?", (mid,)).fetchone()
    last = db.execute("SELECT sd_no FROM sd_accounts ORDER BY id DESC LIMIT 1").fetchone()
    if last:
        try:
            num = int(last['sd_no'].split('-')[1]) + 1
        except Exception:
            num = 1
    else:
        num = 1
    sd_no = f"SD-{num:04d}"
    db.execute("""
        INSERT INTO sd_accounts (sd_no, member_id, center_id, loan_amount, percentage, sd_amount,
                                 roi, tenure_months, tenure_unit, maturity_amount, start_date,
                                 status, remarks, created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (sd_no, mid, member['center_id'], loan_amount, percentage, sd_amount,
          roi, tenure_months, tenure_unit, maturity_amount, start_date,
          'Active', remarks, session['user_id']))
    db.commit()
    db.close()
    flash(f'Secure Deposit Account {sd_no} opened successfully.', 'success')
    return redirect(url_for('secure_deposits_list'))

@app.route('/secure-deposits/<int:sdid>')
@login_required
def secure_deposit_detail(sdid):
    db = get_db()
    account = db.execute("""
        SELECT sa.*, m.member_code, m.full_name, m.phone1, c.center_code, c.center_name,
               u.full_name as created_by_name
        FROM sd_accounts sa
        LEFT JOIN members m ON sa.member_id=m.id
        LEFT JOIN centers c ON sa.center_id=c.id
        LEFT JOIN users u ON sa.created_by=u.id
        WHERE sa.id=?
    """, (sdid,)).fetchone()
    if not account:
        flash('SD account not found.', 'danger')
        db.close()
        return redirect(url_for('secure_deposits_list'))
    interest_earned = (account['sd_amount'] or 0) * (account['roi'] or 0) / 100 * ((account['tenure_months'] or 0) / 12)
    maturity_date = _add_months(account['start_date'] or '', account['tenure_months'] or 0)
    db.close()
    return render_template('secure_deposits/detail.html', account=account,
                           interest_earned=interest_earned, maturity_date=maturity_date)

@app.route('/secure-deposits/<int:sdid>/delete', methods=['POST'])
@admin_required
def secure_deposit_account_delete(sdid):
    db = get_db()
    db.execute("DELETE FROM sd_accounts WHERE id=?", (sdid,))
    db.commit()
    db.close()
    flash('SD Account deleted.', 'success')
    return redirect(url_for('secure_deposits_list'))

@app.route('/secure-deposits/deposit/<int:mid>', methods=['POST'])
@login_required
def secure_deposit_add(mid):
    db = get_db()
    amount = float(request.form.get('deposit_amount', 0))
    date = request.form.get('transaction_date', '').strip()
    remarks = request.form.get('remarks', '').strip()
    percentage = float(request.form.get('percentage', 0) or 0)
    interest_rate = float(request.form.get('interest_rate', 0) or 0)
    if amount <= 0 or not date:
        flash('Invalid amount or date.', 'danger')
        return redirect(url_for('secure_deposits_list'))
    member = db.execute("SELECT center_id FROM members WHERE id=?", (mid,)).fetchone()
    prev = db.execute(
        "SELECT COALESCE(SUM(deposit_amount),0)-COALESCE(SUM(withdraw_amount),0) FROM secure_deposits WHERE member_id=?",
        (mid,)).fetchone()[0] or 0
    db.execute("""
        INSERT INTO secure_deposits (member_id,center_id,transaction_date,deposit_amount,withdraw_amount,balance,percentage,interest_rate,remarks,posted_by)
        VALUES (?,?,?,?,0,?,?,?,?,?)
    """, (mid, member['center_id'], date, amount, prev + amount, percentage, interest_rate, remarks, session['user_id']))
    db.commit()
    db.close()
    flash(f'Secure deposit of ₹{amount:,.0f} recorded.', 'success')
    return redirect(url_for('secure_deposits_list'))

@app.route('/secure-deposits/withdraw/<int:mid>', methods=['POST'])
@login_required
def secure_deposit_withdraw(mid):
    db = get_db()
    amount = float(request.form.get('withdraw_amount', 0))
    date = request.form.get('transaction_date', '').strip()
    remarks = request.form.get('remarks', '').strip()
    prev = db.execute(
        "SELECT COALESCE(SUM(deposit_amount),0)-COALESCE(SUM(withdraw_amount),0) FROM secure_deposits WHERE member_id=?",
        (mid,)).fetchone()[0] or 0
    if amount <= 0 or not date:
        flash('Invalid amount or date.', 'danger')
        return redirect(url_for('secure_deposits_list'))
    if amount > prev:
        flash(f'Insufficient balance. Available: ₹{prev:,.0f}', 'danger')
        return redirect(url_for('secure_deposits_list'))
    member = db.execute("SELECT center_id FROM members WHERE id=?", (mid,)).fetchone()
    db.execute("""
        INSERT INTO secure_deposits (member_id,center_id,transaction_date,deposit_amount,withdraw_amount,balance,remarks,posted_by)
        VALUES (?,?,?,0,?,?,?,?)
    """, (mid, member['center_id'], date, amount, prev - amount, remarks, session['user_id']))
    db.commit()
    db.close()
    flash(f'Withdrawal of ₹{amount:,.0f} recorded.', 'success')
    return redirect(url_for('secure_deposits_list'))

@app.route('/secure-deposits/transaction/<int:tid>/delete', methods=['POST'])
@admin_required
def secure_deposit_transaction_delete(tid):
    db = get_db()
    db.execute("DELETE FROM secure_deposits WHERE id=?", (tid,))
    db.commit()
    db.close()
    flash('Secure deposit transaction deleted.', 'success')
    return redirect(url_for('secure_deposits_list'))

@app.route('/secure-deposits/undo/<int:mid>', methods=['POST'])
@admin_required
def secure_deposit_undo(mid):
    db = get_db()
    last = db.execute(
        "SELECT id FROM secure_deposits WHERE member_id=? ORDER BY id DESC LIMIT 1", (mid,)
    ).fetchone()
    if last:
        db.execute("DELETE FROM secure_deposits WHERE id=?", (last['id'],))
        db.commit()
        flash('Last secure deposit transaction undone.', 'success')
    else:
        flash('No transactions to undo.', 'warning')
    db.close()
    return redirect(url_for('secure_deposits_list'))

@app.route('/reports/secure-deposits')
@login_required
def report_secure_deposits():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    where = "WHERE 1=1"
    params = []
    if center_filter:
        where += " AND sd.center_id=?"; params.append(center_filter)
    if from_date:
        where += " AND substr(sd.transaction_date,7,4)||'-'||substr(sd.transaction_date,4,2)||'-'||substr(sd.transaction_date,1,2) >= ?"; params.append(_to_iso(from_date))
    if to_date:
        where += " AND substr(sd.transaction_date,7,4)||'-'||substr(sd.transaction_date,4,2)||'-'||substr(sd.transaction_date,1,2) <= ?"; params.append(_to_iso(to_date))
    raw = db.execute(f"""
        SELECT sd.*, m.member_code, m.full_name, c.center_code, c.center_name,
               u.full_name as posted_by_name
        FROM secure_deposits sd
        LEFT JOIN members m ON sd.member_id=m.id
        LEFT JOIN centers c ON sd.center_id=c.id
        LEFT JOIN users u ON sd.posted_by=u.id
        {where} ORDER BY sd.transaction_date, m.member_code
    """, params).fetchall()
    db.close()
    today_str = datetime.today().strftime('%d/%m/%Y')
    transactions = []
    for t in raw:
        days = _days_between(t['transaction_date'], today_str)
        interest = _calc_interest(t['deposit_amount'] or 0, t['interest_rate'] or 0, days) if t['deposit_amount'] else 0
        transactions.append({**dict(t), 'days': days, 'interest': interest})
    return render_template('reports/secure_deposit_report.html', transactions=transactions, centers=centers,
                           center_filter=center_filter, from_date=from_date, to_date=to_date)

# ── Recurring Deposits ────────────────────────────────────────────────────────

@app.route('/rd')
@login_required
def rd_list():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    all_members = db.execute("""
        SELECT m.id, m.member_code, m.full_name, c.center_code, c.center_name, m.center_id
        FROM members m LEFT JOIN centers c ON m.center_id=c.id
        WHERE m.status='ACTIVE' ORDER BY m.member_code
    """).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    where = "WHERE 1=1"
    params = []
    if center_filter:
        where += " AND rd.center_id=?"; params.append(center_filter)
    rows = db.execute(f"""
        SELECT rd.*, m.member_code, m.full_name, m.phone1, c.center_code, c.center_name,
               u.full_name as created_by_name
        FROM rd_accounts rd
        LEFT JOIN members m ON rd.member_id=m.id
        LEFT JOIN centers c ON rd.center_id=c.id
        LEFT JOIN users u ON rd.created_by=u.id
        {where} ORDER BY rd.rd_no DESC
    """, params).fetchall()
    accounts = []
    for a in rows:
        tenure_months = a['total_installments'] or 0
        monthly = a['installment_amount'] or 0
        roi = a['interest_rate'] or 0
        corpus = monthly * tenure_months
        interest_earned = corpus * roi / 100
        keys = a.keys()
        mat = (a['maturity_amount'] if 'maturity_amount' in keys and a['maturity_amount'] else (corpus + interest_earned))
        tu = (a['tenure_unit'] if 'tenure_unit' in keys and a['tenure_unit'] else 'Months')
        maturity_date = _add_months(a['start_date'] or '', tenure_months)
        accounts.append({**dict(a), 'corpus': corpus, 'interest_earned': interest_earned,
                         'calc_maturity': mat, 'tenure_unit': tu, 'maturity_date': maturity_date})
    db.close()
    return render_template('rd/list.html', accounts=accounts, all_members=all_members,
                           centers=centers, center_filter=center_filter)

@app.route('/rd/member-info')
@login_required
def rd_member_info():
    db = get_db()
    mid = request.args.get('mid', '')
    if not mid:
        return {'center': '', 'loan_amount': 0}
    member = db.execute("""
        SELECT m.*, c.center_code, c.center_name FROM members m
        LEFT JOIN centers c ON m.center_id=c.id WHERE m.id=?
    """, (mid,)).fetchone()
    loan_amt = db.execute("""
        SELECT COALESCE(SUM(ld.disbursed_amount),0) as la
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        WHERE la.member_id=? AND ld.status='Disbursed'
    """, (mid,)).fetchone()['la']
    db.close()
    if not member:
        return {'center': '', 'loan_amount': 0}
    return {'center': f"{member['center_code']} {member['center_name']}", 'loan_amount': loan_amt or 0}

@app.route('/rd/new', methods=['POST'])
@login_required
def rd_new():
    db = get_db()
    mid = int(request.form.get('member_id', 0) or 0)
    start_date = request.form.get('start_date', '').strip()
    monthly_amount = float(request.form.get('monthly_amount', 0) or 0)
    tenure = int(request.form.get('tenure', 0) or 0)
    tenure_unit = request.form.get('tenure_unit', 'Months')
    roi = float(request.form.get('roi', 0) or 0)
    remarks = request.form.get('remarks', '').strip()
    if not mid or not start_date or monthly_amount <= 0 or tenure <= 0:
        flash('All required fields must be filled.', 'danger')
        db.close()
        return redirect(url_for('rd_list'))
    tenure_months = tenure if tenure_unit == 'Months' else tenure * 12
    corpus = monthly_amount * tenure_months
    maturity_amount = corpus + corpus * roi / 100
    member = db.execute("SELECT center_id FROM members WHERE id=?", (mid,)).fetchone()
    last = db.execute("SELECT rd_no FROM rd_accounts ORDER BY id DESC LIMIT 1").fetchone()
    if last:
        try:
            num = int(last['rd_no'].split('-')[1]) + 1
        except Exception:
            num = 1
    else:
        num = 1
    rd_no = f"RD-{num:04d}"
    db.execute("""
        INSERT INTO rd_accounts (rd_no, member_id, center_id, start_date, installment_amount,
                                 total_installments, frequency, interest_rate, maturity_amount,
                                 tenure_unit, status, remarks, created_by)
        VALUES (?,?,?,?,?,?,'Monthly',?,?,?,?,?,?)
    """, (rd_no, mid, member['center_id'], start_date, monthly_amount, tenure_months,
          roi, maturity_amount, tenure_unit, 'Active', remarks, session['user_id']))
    db.commit()
    db.close()
    flash(f'RD Account {rd_no} opened successfully.', 'success')
    return redirect(url_for('rd_list'))

@app.route('/rd/<int:rdid>')
@login_required
def rd_detail(rdid):
    db = get_db()
    account = db.execute("""
        SELECT rd.*, m.member_code, m.full_name, m.phone1, c.center_code, c.center_name,
               u.full_name as created_by_name
        FROM rd_accounts rd
        LEFT JOIN members m ON rd.member_id=m.id
        LEFT JOIN centers c ON rd.center_id=c.id
        LEFT JOIN users u ON rd.created_by=u.id
        WHERE rd.id=?
    """, (rdid,)).fetchone()
    if not account:
        flash('RD account not found.', 'danger')
        return redirect(url_for('rd_list'))
    payments = db.execute("""
        SELECT rdt.*, u.full_name as posted_by_name
        FROM rd_transactions rdt LEFT JOIN users u ON rdt.posted_by=u.id
        WHERE rdt.rd_id=? AND (rdt.transaction_type='Payment' OR rdt.transaction_type IS NULL)
        ORDER BY rdt.installment_no
    """, (rdid,)).fetchall()
    withdrawals = db.execute("""
        SELECT rdt.*, u.full_name as posted_by_name
        FROM rd_transactions rdt LEFT JOIN users u ON rdt.posted_by=u.id
        WHERE rdt.rd_id=? AND rdt.transaction_type='Withdrawal'
        ORDER BY rdt.id
    """, (rdid,)).fetchall()
    tenure_months = account['total_installments'] or 0
    monthly = account['installment_amount'] or 0
    roi = account['interest_rate'] or 0
    corpus = monthly * tenure_months
    interest_earned = corpus * roi / 100
    keys = account.keys()
    calc_maturity = (account['maturity_amount'] if 'maturity_amount' in keys and account['maturity_amount']
                     else corpus + interest_earned)
    tenure_unit = (account['tenure_unit'] if 'tenure_unit' in keys and account['tenure_unit'] else 'Months')
    maturity_date = _add_months(account['start_date'] or '', tenure_months)
    db.close()
    return render_template('rd/detail.html', account=account, transactions=payments,
                           withdrawals=withdrawals, corpus=corpus, interest_earned=interest_earned,
                           calc_maturity=calc_maturity, tenure_unit=tenure_unit,
                           maturity_date=maturity_date)

@app.route('/rd/<int:rdid>/pay', methods=['POST'])
@login_required
def rd_pay(rdid):
    db = get_db()
    account = db.execute("SELECT * FROM rd_accounts WHERE id=?", (rdid,)).fetchone()
    if not account or account['status'] == 'Closed':
        flash('RD account not found or already closed.', 'danger')
        return redirect(url_for('rd_list'))
    paid_count = db.execute("SELECT COUNT(*) FROM rd_transactions WHERE rd_id=? AND (transaction_type='Payment' OR transaction_type IS NULL)", (rdid,)).fetchone()[0]
    if paid_count >= account['total_installments']:
        db.execute("UPDATE rd_accounts SET status='Closed' WHERE id=?", (rdid,))
        db.commit()
        db.close()
        flash('All installments already paid. RD marked as Closed.', 'warning')
        return redirect(url_for('rd_detail', rdid=rdid))
    transaction_date = request.form.get('transaction_date', '').strip()
    amount = float(request.form.get('amount', account['installment_amount']))
    remarks = request.form.get('remarks', '').strip()
    if not transaction_date or amount <= 0:
        flash('Invalid date or amount.', 'danger')
        return redirect(url_for('rd_detail', rdid=rdid))
    next_inst = paid_count + 1
    db.execute("""
        INSERT INTO rd_transactions (rd_id, transaction_date, installment_no, amount, remarks, transaction_type, posted_by)
        VALUES (?,?,?,?,?,'Payment',?)
    """, (rdid, transaction_date, next_inst, amount, remarks, session['user_id']))
    if next_inst >= account['total_installments']:
        db.execute("UPDATE rd_accounts SET status='Closed' WHERE id=?", (rdid,))
    db.commit()
    db.close()
    flash(f'Installment {next_inst}/{account["total_installments"]} recorded.', 'success')
    return redirect(url_for('rd_detail', rdid=rdid))

@app.route('/rd/<int:rdid>/withdraw', methods=['POST'])
@login_required
def rd_withdraw(rdid):
    db = get_db()
    account = db.execute("SELECT * FROM rd_accounts WHERE id=?", (rdid,)).fetchone()
    if not account or account['status'] == 'Closed':
        flash('RD account not found or already closed.', 'danger')
        db.close()
        return redirect(url_for('rd_list'))
    amount = float(request.form.get('amount', 0))
    transaction_date = request.form.get('transaction_date', '').strip()
    remarks = request.form.get('remarks', '').strip()
    if amount <= 0 or not transaction_date:
        flash('Invalid amount or date.', 'danger')
        db.close()
        return redirect(url_for('rd_detail', rdid=rdid))
    total_paid = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM rd_transactions WHERE rd_id=? AND (transaction_type='Payment' OR transaction_type IS NULL)",
        (rdid,)).fetchone()[0]
    total_withdrawn = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM rd_transactions WHERE rd_id=? AND transaction_type='Withdrawal'",
        (rdid,)).fetchone()[0]
    available = total_paid - total_withdrawn
    if amount > available:
        flash(f'Insufficient balance. Available: ₹{available:,.0f}', 'danger')
        db.close()
        return redirect(url_for('rd_detail', rdid=rdid))
    db.execute("""
        INSERT INTO rd_transactions (rd_id, transaction_date, installment_no, amount, remarks, transaction_type, posted_by)
        VALUES (?,?,0,?,?,'Withdrawal',?)
    """, (rdid, transaction_date, amount, remarks, session['user_id']))
    db.commit()
    db.close()
    flash(f'Withdrawal of ₹{amount:,.0f} recorded for {account["rd_no"]}.', 'success')
    return redirect(url_for('rd_detail', rdid=rdid))

@app.route('/rd/transaction/<int:tid>/delete', methods=['POST'])
@admin_required
def rd_transaction_delete(tid):
    db = get_db()
    txn = db.execute("SELECT rd_id, transaction_type FROM rd_transactions WHERE id=?", (tid,)).fetchone()
    if not txn:
        flash('Transaction not found.', 'danger')
        db.close()
        return redirect(url_for('rd_list'))
    rdid = txn['rd_id']
    db.execute("DELETE FROM rd_transactions WHERE id=?", (tid,))
    paid = db.execute(
        "SELECT COUNT(*) FROM rd_transactions WHERE rd_id=? AND (transaction_type='Payment' OR transaction_type IS NULL)",
        (rdid,)).fetchone()[0]
    total = db.execute("SELECT total_installments FROM rd_accounts WHERE id=?", (rdid,)).fetchone()[0]
    if paid < total:
        db.execute("UPDATE rd_accounts SET status='Active' WHERE id=?", (rdid,))
    db.commit()
    db.close()
    flash('RD transaction deleted.', 'success')
    return redirect(url_for('rd_detail', rdid=rdid))

@app.route('/rd/<int:rdid>/undo', methods=['POST'])
@admin_required
def rd_undo(rdid):
    db = get_db()
    last = db.execute(
        "SELECT id, transaction_type FROM rd_transactions WHERE rd_id=? ORDER BY id DESC LIMIT 1", (rdid,)
    ).fetchone()
    if last:
        db.execute("DELETE FROM rd_transactions WHERE id=?", (last['id'],))
        paid = db.execute(
            "SELECT COUNT(*) FROM rd_transactions WHERE rd_id=? AND (transaction_type='Payment' OR transaction_type IS NULL)",
            (rdid,)).fetchone()[0]
        total = db.execute("SELECT total_installments FROM rd_accounts WHERE id=?", (rdid,)).fetchone()[0]
        if paid < total:
            db.execute("UPDATE rd_accounts SET status='Active' WHERE id=?", (rdid,))
        db.commit()
        flash('Last RD transaction undone.', 'success')
    else:
        flash('No transactions to undo.', 'warning')
    db.close()
    return redirect(url_for('rd_detail', rdid=rdid))

@app.route('/rd/<int:rdid>/delete', methods=['POST'])
@admin_required
def rd_account_delete(rdid):
    db = get_db()
    db.execute("DELETE FROM rd_transactions WHERE rd_id=?", (rdid,))
    db.execute("DELETE FROM rd_accounts WHERE id=?", (rdid,))
    db.commit()
    db.close()
    flash('RD account deleted.', 'success')
    return redirect(url_for('rd_list'))

@app.route('/reports/rd')
@login_required
def report_rd():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    status_filter = request.args.get('status', '')
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    where = "WHERE 1=1"
    params = []
    if center_filter:
        where += " AND rd.center_id=?"; params.append(center_filter)
    if status_filter:
        where += " AND rd.status=?"; params.append(status_filter)
    accounts = db.execute(f"""
        SELECT rd.*, m.member_code, m.full_name, c.center_code, c.center_name,
               COALESCE(SUM(rdt.amount),0) as total_collected,
               COUNT(rdt.id) as paid_count
        FROM rd_accounts rd
        LEFT JOIN members m ON rd.member_id=m.id
        LEFT JOIN centers c ON rd.center_id=c.id
        LEFT JOIN rd_transactions rdt ON rdt.rd_id=rd.id
        {where} GROUP BY rd.id ORDER BY rd.rd_no
    """, params).fetchall()
    # transactions filtered by date
    twhere = "WHERE 1=1"
    tparams = []
    if center_filter:
        twhere += " AND rd.center_id=?"; tparams.append(center_filter)
    if from_date:
        twhere += " AND substr(rdt.transaction_date,7,4)||'-'||substr(rdt.transaction_date,4,2)||'-'||substr(rdt.transaction_date,1,2) >= ?"; tparams.append(_to_iso(from_date))
    if to_date:
        twhere += " AND substr(rdt.transaction_date,7,4)||'-'||substr(rdt.transaction_date,4,2)||'-'||substr(rdt.transaction_date,1,2) <= ?"; tparams.append(_to_iso(to_date))
    transactions = db.execute(f"""
        SELECT rdt.*, rd.rd_no, rd.installment_amount, rd.total_installments,
               m.member_code, m.full_name, c.center_code, c.center_name,
               u.full_name as posted_by_name
        FROM rd_transactions rdt
        LEFT JOIN rd_accounts rd ON rdt.rd_id=rd.id
        LEFT JOIN members m ON rd.member_id=m.id
        LEFT JOIN centers c ON rd.center_id=c.id
        LEFT JOIN users u ON rdt.posted_by=u.id
        {twhere} ORDER BY rdt.transaction_date, rd.rd_no
    """, tparams).fetchall()
    db.close()
    return render_template('reports/rd_report.html', accounts=accounts, transactions=transactions,
                           centers=centers, center_filter=center_filter, from_date=from_date,
                           to_date=to_date, status_filter=status_filter)

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

# ── Arrears Collection ────────────────────────────────────────────────────────

@app.route('/loans/posting/arrears')
@login_required
def arrears_collection_list():
    db = get_db()
    date_filter = request.args.get('date', datetime.now().strftime('%d/%m/%Y'))
    center_filter = request.args.get('center_id', '')
    try:
        day_name = datetime.strptime(date_filter, '%d/%m/%Y').strftime('%A')
    except Exception:
        day_name = datetime.now().strftime('%A')
    locked = _is_day_locked(db, date_filter)
    date_iso = _to_iso(date_filter)

    # Loans that had no recovery posted on this date → eligible to mark as arrear
    p = {'date': date_filter, 'date_iso': date_iso}
    q = """
        SELECT ld.*, la.application_no, la.center_id, la.member_id,
               m.full_name as member_name, m.member_code,
               c.center_name, c.center_code, c.meeting_week,
               lt.interest_rate, lt.interest_type,
               (SELECT COUNT(*) FROM recovery_postings rp WHERE rp.disbursement_id=ld.id AND rp.installment_no > 0) as paid_count
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        WHERE ld.status='Disbursed'
        AND (SELECT COUNT(*) FROM recovery_postings rp2 WHERE rp2.disbursement_id=ld.id AND rp2.installment_no > 0) < ld.total_installments
        AND substr(ld.disbursement_date,7,4)||'-'||substr(ld.disbursement_date,4,2)||'-'||substr(ld.disbursement_date,1,2) < :date_iso
        AND (SELECT COUNT(*) FROM recovery_postings rp3 WHERE rp3.disbursement_id=ld.id AND rp3.posting_date=:date AND rp3.installment_no > 0) = 0
        AND (SELECT COUNT(*) FROM arrear_entries ae WHERE ae.disbursement_id=ld.id AND ae.arrear_date=:date) = 0
    """
    if center_filter:
        q += " AND la.center_id=:center_id"
        p['center_id'] = center_filter
    else:
        q += " AND c.meeting_week=:day"
        p['day'] = day_name
    q += " ORDER BY c.center_code, m.member_code"
    to_mark = db.execute(q, p).fetchall()

    # Pending arrear entries for this center/day
    p2 = {}
    pq = """
        SELECT ae.*,
               m.full_name as member_name, m.member_code,
               c.center_code, c.center_name, c.meeting_week,
               ld.disbursed_amount, ld.loan_id, ld.disbursement_no, ld.total_installments,
               lt.interest_rate, lt.interest_type,
               (SELECT COUNT(*) FROM recovery_postings rp WHERE rp.disbursement_id=ae.disbursement_id AND rp.installment_no > 0) as paid_count
        FROM arrear_entries ae
        LEFT JOIN loan_disbursements ld ON ae.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        WHERE ae.status='Pending'
    """
    if center_filter:
        pq += " AND la.center_id=:center_id"
        p2['center_id'] = center_filter
    else:
        pq += " AND c.meeting_week=:day"
        p2['day'] = day_name
    pq += " ORDER BY ae.arrear_date, c.center_code, m.member_code"
    pending_arrears = db.execute(pq, p2).fetchall()

    centers = db.execute(
        "SELECT id, center_code, center_name, meeting_week FROM centers WHERE active=1 ORDER BY center_code"
    ).fetchall()
    db.close()
    return render_template('loans/posting/arrears_list.html',
                           to_mark=to_mark, pending_arrears=pending_arrears,
                           centers=centers, date_filter=date_filter,
                           center_filter=center_filter, day_name=day_name, locked=locked)


@app.route('/loans/posting/arrears/mark/<int:did>', methods=['POST'])
@login_required
def arrears_mark(did):
    db = get_db()
    arrear_date = request.form.get('arrear_date', datetime.now().strftime('%d/%m/%Y'))
    if _is_day_locked(db, arrear_date):
        flash(f'Day {arrear_date} is closed. Undo Day End first.', 'danger')
        db.close()
        return redirect(url_for('arrears_collection_list', date=arrear_date))
    if db.execute("SELECT id FROM arrear_entries WHERE disbursement_id=? AND arrear_date=?", (did, arrear_date)).fetchone():
        flash('Arrear already marked for this date.', 'warning')
        db.close()
        return redirect(url_for('arrears_collection_list', date=arrear_date))
    loan = db.execute("""
        SELECT ld.*, lt.interest_rate, lt.interest_type
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id WHERE ld.id=?
    """, (did,)).fetchone()
    if not loan:
        flash('Loan not found.', 'danger')
        db.close()
        return redirect(url_for('arrears_collection_list', date=arrear_date))
    paid_count = db.execute("SELECT COUNT(*) FROM recovery_postings WHERE disbursement_id=? AND installment_no > 0", (did,)).fetchone()[0]
    amount = float(loan['disbursed_amount'])
    tenure = int(loan['total_installments'])
    rate = float(loan['interest_rate'] or 0)
    total_interest = rate if (loan['interest_type'] or 'Percent') == 'Fixed' else amount * rate / 100
    inst_amount = round((amount + total_interest) / tenure, 2) if tenure else 0
    db.execute("""
        INSERT INTO arrear_entries (disbursement_id, arrear_date, installment_no, due_amount, status, marked_by)
        VALUES (?,?,?,?,'Pending',?)
    """, (did, arrear_date, paid_count + 1, inst_amount, session['user_id']))
    db.commit()
    db.close()
    flash(f'Marked as arrear for {arrear_date}.', 'warning')
    return redirect(url_for('arrears_collection_list', date=arrear_date))


@app.route('/loans/posting/arrears/collect/<int:aeid>', methods=['POST'])
@login_required
def arrears_collect(aeid):
    db = get_db()
    ae = db.execute("""
        SELECT ae.*, ld.disbursed_amount, ld.total_installments, la.member_id, la.center_id,
               lt.interest_rate, lt.interest_type
        FROM arrear_entries ae
        LEFT JOIN loan_disbursements ld ON ae.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        WHERE ae.id=?
    """, (aeid,)).fetchone()
    if not ae:
        flash('Arrear entry not found.', 'danger')
        db.close()
        return redirect(url_for('arrears_collection_list'))
    collected_date = request.form.get('collected_date', datetime.now().strftime('%d/%m/%Y'))
    if _is_day_locked(db, collected_date):
        flash(f'Day {collected_date} is closed. Undo Day End first.', 'danger')
        db.close()
        return redirect(url_for('arrears_collection_list'))
    amount = float(ae['disbursed_amount'])
    tenure = int(ae['total_installments'])
    rate = float(ae['interest_rate'] or 0)
    total_interest = rate if (ae['interest_type'] or 'Percent') == 'Fixed' else amount * rate / 100
    principal_inst = round(amount / tenure, 2)
    interest_inst = round(total_interest / tenure, 2)
    inst_amount = principal_inst + interest_inst
    paid_count = db.execute("SELECT COUNT(*) FROM recovery_postings WHERE disbursement_id=? AND installment_no > 0", (ae['disbursement_id'],)).fetchone()[0]
    db.execute("""
        INSERT INTO recovery_postings
        (disbursement_id,posting_date,installment_no,due_amount,paid_amount,
         principal,interest,penalty,mode,narration,posted_by)
        VALUES (?,?,?,?,?,?,?,0,'Cash',?,?)
    """, (ae['disbursement_id'], collected_date, paid_count + 1, inst_amount, inst_amount,
          principal_inst, interest_inst, f'Arrear (due {ae["arrear_date"]})', session['user_id']))
    db.execute("""
        UPDATE arrear_entries SET status='Collected', collected_date=?, collected_amount=?, cleared_by=?
        WHERE id=?
    """, (collected_date, inst_amount, session['user_id'], aeid))
    db.commit()
    db.close()
    flash(f'Arrear collected and recovery posted for {collected_date}.', 'success')
    return redirect(url_for('arrears_collection_list'))


@app.route('/loans/posting/arrears/undo/<int:aeid>', methods=['POST'])
@admin_required
def arrears_mark_undo(aeid):
    db = get_db()
    ae = db.execute("SELECT * FROM arrear_entries WHERE id=?", (aeid,)).fetchone()
    if ae:
        db.execute("DELETE FROM arrear_entries WHERE id=?", (aeid,))
        db.commit()
        flash(f'Arrear entry for {ae["arrear_date"]} removed.', 'success')
    else:
        flash('Arrear entry not found.', 'danger')
    db.close()
    return redirect(url_for('arrears_collection_list'))


# ── Undo Recovery Posting (Admin) ──────────────────────────────────────────────

@app.route('/admin/recovery-undo')
@admin_required
def recovery_undo_list():
    db = get_db()
    date_filter = request.args.get('date', datetime.now().strftime('%d/%m/%Y'))
    center_filter = request.args.get('center_id', '')
    params = [date_filter]
    query = """
        SELECT rp.*,
               m.full_name as member_name, m.member_code,
               c.center_code, c.center_name,
               ld.disbursed_amount, ld.loan_id, ld.disbursement_no,
               u.full_name as posted_by_name
        FROM recovery_postings rp
        LEFT JOIN loan_disbursements ld ON rp.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN users u ON rp.posted_by=u.id
        WHERE rp.posting_date=?
    """
    if center_filter:
        query += " AND la.center_id=?"
        params.append(center_filter)
    query += " ORDER BY c.center_code, m.member_code, rp.installment_no"
    postings = db.execute(query, params).fetchall()
    centers = db.execute(
        "SELECT id, center_code, center_name FROM centers WHERE active=1 ORDER BY center_code"
    ).fetchall()
    locked = _is_day_locked(db, date_filter)
    total_collected = sum(p['paid_amount'] or 0 for p in postings)
    db.close()
    return render_template('loans/posting/recovery_undo.html',
                           postings=postings, centers=centers,
                           date_filter=date_filter, center_filter=center_filter,
                           locked=locked, total_collected=total_collected)


# ── Day End ───────────────────────────────────────────────────────────────────

@app.route('/day-end', methods=['GET', 'POST'])
@login_required
def day_end():
    db = get_db()
    if request.method == 'POST':
        day_date = request.form.get('day_date', '').strip()
        notes = request.form.get('notes', '').strip()
        if not day_date:
            flash('Please select a date.', 'danger')
            db.close()
            return redirect(url_for('day_end'))
        existing = db.execute("SELECT id FROM day_end WHERE day_date=?", (day_date,)).fetchone()
        if existing:
            flash(f'{day_date} is already closed.', 'warning')
            db.close()
            return redirect(url_for('day_end'))
        db.execute("INSERT INTO day_end (day_date, closed_by, notes) VALUES (?,?,?)",
                   (day_date, session['user_id'], notes))
        db.commit()
        flash(f'Day End completed for {day_date}. No further changes allowed for this date.', 'success')
        db.close()
        return redirect(url_for('day_end'))

    date_filter = request.args.get('date', datetime.now().strftime('%d/%m/%Y'))
    # Summary for selected date
    recovery_summary = db.execute("""
        SELECT c.center_code, c.center_name,
               COUNT(rp.id) as postings,
               COALESCE(SUM(rp.paid_amount),0) as total_collected,
               COALESCE(SUM(rp.principal),0) as total_principal,
               COALESCE(SUM(rp.interest),0) as total_interest
        FROM recovery_postings rp
        LEFT JOIN loan_disbursements ld ON rp.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN centers c ON la.center_id=c.id
        WHERE rp.posting_date=?
        GROUP BY la.center_id ORDER BY c.center_code
    """, (date_filter,)).fetchall()
    savings_summary = db.execute("""
        SELECT COALESCE(SUM(deposit_amount),0) as deposits,
               COALESCE(SUM(withdraw_amount),0) as withdrawals
        FROM savings_transactions WHERE transaction_date=?
    """, (date_filter,)).fetchone()
    closed_days = db.execute("""
        SELECT de.*, u.full_name as closed_by_name
        FROM day_end de LEFT JOIN users u ON de.closed_by=u.id
        ORDER BY de.day_date DESC LIMIT 30
    """).fetchall()
    locked = _is_day_locked(db, date_filter)
    db.close()
    return render_template('day_end.html', date_filter=date_filter,
                           recovery_summary=recovery_summary,
                           savings_summary=savings_summary,
                           closed_days=closed_days, locked=locked)

@app.route('/day-end/<int:did>/undo', methods=['POST'])
@admin_required
def day_end_undo(did):
    db = get_db()
    rec = db.execute("SELECT * FROM day_end WHERE id=?", (did,)).fetchone()
    if rec:
        db.execute("DELETE FROM day_end WHERE id=?", (did,))
        db.commit()
        flash(f'Day End for {rec["day_date"]} has been reversed. Changes are now allowed.', 'success')
    else:
        flash('Record not found.', 'danger')
    db.close()
    return redirect(url_for('day_end'))

# ── Settings ──────────────────────────────────────────────────────────────────

@app.route('/settings')
@admin_required
def settings():
    return render_template('settings.html')

# ── Reports ───────────────────────────────────────────────────────────────────

@app.route('/reports')
@login_required
def reports():
    db = get_db()
    today = datetime.now().strftime('%d/%m/%Y')
    today_locked = _is_day_locked(db, today)
    any_day_end = db.execute("SELECT id FROM day_end LIMIT 1").fetchone() is not None
    db.close()
    return render_template('reports.html', today_locked=today_locked, any_day_end=any_day_end, today=today)

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
    rows = db.execute("""
        SELECT ld.*, la.application_no, la.purpose, la.loan_cycle,
               m.full_name as member_name, m.member_code, m.grp, m.phone1,
               c.center_name, c.center_code, c.meeting_week,
               lt.loan_type_name, lt.interest_rate, lt.interest_type,
               u.full_name as staff_name,
               (SELECT COALESCE(SUM(rp.paid_amount),0) FROM recovery_postings rp WHERE rp.disbursement_id=ld.id AND rp.installment_no > 0) as total_paid,
               (SELECT COALESCE(SUM(rp.principal),0) FROM recovery_postings rp WHERE rp.disbursement_id=ld.id AND rp.installment_no > 0) as principal_paid,
               (SELECT COUNT(*) FROM recovery_postings rp WHERE rp.disbursement_id=ld.id AND rp.installment_no > 0) as paid_count,
               (SELECT COALESCE(SUM(ar.amount),0) FROM advance_recoveries ar WHERE ar.disbursement_id=ld.id) as advance_total
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        LEFT JOIN users u ON c.staff_id=u.id
        WHERE ld.status='Disbursed'
        """ + (" AND la.center_id=?" if center_filter else "") + """
        ORDER BY c.center_code, m.grp, m.member_code
    """, ([center_filter] if center_filter else [])).fetchall()
    # compute interest per installment for each loan
    loans = []
    for r in rows:
        d = dict(r)
        amt = float(d['disbursed_amount'] or 0)
        tenure = int(d['total_installments'] or 1)
        rate = float(d['interest_rate'] or 0)
        itype = d['interest_type'] or 'Percent'
        total_int = rate if itype == 'Fixed' else amt * rate / 100
        d['int_per_inst'] = round(total_int / tenure, 2) if tenure else 0
        loans.append(d)
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
    date_param = [report_date]
    cond = " AND rp.posting_date=?" if not center_filter else " AND rp.posting_date=? AND la.center_id=?"
    cond_params = date_param if not center_filter else date_param + [center_filter]

    credit = db.execute("""
        SELECT
          COALESCE(SUM(m.total_fees),0) as joining_fee,
          COALESCE(SUM(la.insurance_fee + la.nominee_insurance_fee),0) as insurance_premium,
          COALESCE(SUM(la.processing_fee),0) as processing_fee,
          COALESCE(SUM(rp.principal),0) as prin_recovery,
          COALESCE(SUM(rp.interest),0) as int_recovery
        FROM recovery_postings rp
        LEFT JOIN loan_disbursements ld ON rp.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        WHERE rp.posting_date=? AND rp.installment_no > 0
    """ + (" AND la.center_id=?" if center_filter else ""),
    cond_params).fetchone()

    prepaid_amt = db.execute("""
        SELECT COALESCE(SUM(pt.amount),0) FROM prepaid_transactions pt
        LEFT JOIN loan_disbursements ld ON pt.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        WHERE pt.transaction_date=? AND pt.is_undo=0
    """ + (" AND la.center_id=?" if center_filter else ""),
    cond_params).fetchone()[0]

    advance_collected = db.execute("""
        SELECT COALESCE(SUM(ar.amount),0) FROM advance_recoveries ar
        LEFT JOIN loan_disbursements ld ON ar.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        WHERE ar.recovery_date=?
    """ + (" AND la.center_id=?" if center_filter else ""),
    cond_params).fetchone()[0]

    disbursed_amt = db.execute("""
        SELECT COALESCE(SUM(ld.disbursed_amount),0) FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        WHERE ld.disbursement_date=?
    """ + (" AND la.center_id=?" if center_filter else ""),
    cond_params).fetchone()[0]

    credit_data = {
        'joining_fee': credit['joining_fee'] if credit else 0,
        'insurance_premium': credit['insurance_premium'] if credit else 0,
        'processing_fee': credit['processing_fee'] if credit else 0,
        'prin_recovery': credit['prin_recovery'] if credit else 0,
        'int_recovery': credit['int_recovery'] if credit else 0,
        'prepaid_amount': prepaid_amt,
        'preclosure_charges': 0,
        'advance_collected': advance_collected,
    }
    credit_data['credit_total'] = sum(credit_data.values())
    debit_data = {
        'disbursed_amount': disbursed_amt,
        'advance_withdraw': 0,
    }
    debit_data['debit_total'] = sum(debit_data.values())

    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/summary_sheet.html',
                           credit_data=credit_data, debit_data=debit_data,
                           centers=centers, center_filter=center_filter, report_date=report_date)

@app.route('/reports/member-wise-summary')
@login_required
def report_member_wise_summary():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    report_date = request.args.get('report_date', datetime.now().strftime('%d/%m/%Y'))
    data = db.execute("""
        SELECT m.member_code, m.full_name, m.grp, m.total_fees as join_fee,
               c.center_name, c.center_code,
               COALESCE(SUM(rp.principal),0) as prin_recovery,
               COALESCE(SUM(rp.interest),0) as int_recovery,
               COALESCE((SELECT SUM(pt.amount) FROM prepaid_transactions pt
                         LEFT JOIN loan_disbursements ld2 ON pt.disbursement_id=ld2.id
                         LEFT JOIN loan_applications la2 ON ld2.application_id=la2.id
                         WHERE la2.member_id=m.id AND pt.is_undo=0),0) as prepaid_amount,
               COALESCE((SELECT SUM(ar.amount) FROM advance_recoveries ar
                         LEFT JOIN loan_disbursements ld3 ON ar.disbursement_id=ld3.id
                         LEFT JOIN loan_applications la3 ON ld3.application_id=la3.id
                         WHERE la3.member_id=m.id),0) as advance_collected,
               COALESCE(SUM(la.insurance_fee + la.nominee_insurance_fee),0) as insurance_collected,
               COALESCE(SUM(la.processing_fee),0) as process_fee,
               COALESCE(SUM(ld.disbursed_amount),0) as disb_amount
        FROM members m
        LEFT JOIN centers c ON m.center_id=c.id
        LEFT JOIN loan_applications la ON la.member_id=m.id
        LEFT JOIN loan_disbursements ld ON ld.application_id=la.id AND ld.status='Disbursed'
        LEFT JOIN recovery_postings rp ON rp.disbursement_id=ld.id AND rp.installment_no > 0
        WHERE m.status='ACTIVE'
        """ + (" AND m.center_id=?" if center_filter else "") + """
        GROUP BY m.id ORDER BY c.center_code, m.grp, m.member_code
    """, ([center_filter] if center_filter else [])).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/member_wise_summary.html', data=data,
                           centers=centers, center_filter=center_filter, report_date=report_date)

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
        LEFT JOIN users u ON rp.posted_by=u.id WHERE rp.installment_no > 0
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
               la.nominee_name,
               m.full_name as member_name, m.member_code,
               c.center_name, c.center_code,
               lt.loan_type_name,
               u.full_name as disbursed_by_name,
               COALESCE(mn.relationship, '') as nominee_relation
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN member_nominees mn ON mn.member_id=m.id
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
               ld.disbursed_amount - COALESCE(SUM(rp.principal),0) as outstanding
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        LEFT JOIN recovery_postings rp ON rp.disbursement_id=ld.id AND rp.installment_no > 0
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
    query = """
        SELECT m.member_code, m.full_name,
               c.center_code, c.center_name,
               ld.loan_id, ld.disbursed_amount, ld.total_installments,
               COUNT(ae.id) as total_arrears,
               SUM(CASE WHEN ae.status='Pending' THEN 1 ELSE 0 END) as pending_count,
               SUM(CASE WHEN ae.status='Pending' THEN ae.due_amount ELSE 0 END) as pending_amount,
               SUM(CASE WHEN ae.status='Collected' THEN 1 ELSE 0 END) as collected_count,
               MIN(CASE WHEN ae.status='Pending' THEN ae.arrear_date END) as oldest_arrear
        FROM arrear_entries ae
        LEFT JOIN loan_disbursements ld ON ae.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        WHERE 1=1
    """ + (" AND la.center_id=?" if center_filter else "") + """
        GROUP BY ae.disbursement_id ORDER BY c.center_code, m.member_code
    """
    data = db.execute(query, ([center_filter] if center_filter else [])).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/arrears_member_wise.html', data=data,
                           centers=centers, center_filter=center_filter)

@app.route('/reports/arrears/new')
@login_required
def report_arrears_new():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    query = """
        SELECT ae.id, ae.arrear_date, ae.installment_no, ae.due_amount,
               m.full_name as member_name, m.member_code,
               c.center_code, c.center_name,
               ld.loan_id, ld.disbursed_amount, ld.disbursement_no
        FROM arrear_entries ae
        LEFT JOIN loan_disbursements ld ON ae.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        WHERE ae.status='Pending'
    """ + (" AND la.center_id=?" if center_filter else "") + """
        ORDER BY ae.arrear_date, c.center_code, m.member_code
    """
    data = db.execute(query, ([center_filter] if center_filter else [])).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/arrears_new.html', data=data, centers=centers,
                           center_filter=center_filter)

@app.route('/reports/arrears/collected')
@login_required
def report_arrears_collected():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    query = """
        SELECT ae.arrear_date, ae.collected_date, ae.due_amount, ae.collected_amount,
               ae.installment_no,
               m.full_name as member_name, m.member_code,
               c.center_code, c.center_name,
               ld.loan_id, ld.disbursed_amount
        FROM arrear_entries ae
        LEFT JOIN loan_disbursements ld ON ae.disbursement_id=ld.id
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        WHERE ae.status='Collected'
    """
    params = []
    if center_filter:
        query += " AND la.center_id=?"
        params.append(center_filter)
    if from_date:
        query += " AND substr(ae.collected_date,7,4)||'-'||substr(ae.collected_date,4,2)||'-'||substr(ae.collected_date,1,2) >= ?"
        params.append(_to_iso(from_date))
    if to_date:
        query += " AND substr(ae.collected_date,7,4)||'-'||substr(ae.collected_date,4,2)||'-'||substr(ae.collected_date,1,2) <= ?"
        params.append(_to_iso(to_date))
    query += " ORDER BY ae.collected_date, c.center_code, m.member_code"
    records = db.execute(query, params).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/arrears_collected.html', records=records, centers=centers,
                           center_filter=center_filter, from_date=from_date, to_date=to_date)

@app.route('/reports/voucher/debit')
@login_required
def report_voucher_debit():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    report_date = request.args.get('report_date', datetime.today().strftime('%Y-%m-%d'))
    try:
        p = report_date.split('-')
        report_date_display = f"{p[2]}/{p[1]}/{p[0]}"
    except Exception:
        report_date_display = report_date
    query = """
        SELECT ld.loan_id, ld.disbursement_no, ld.disbursement_date, ld.disbursed_amount, ld.mode,
               la.processing_fee, la.insurance_fee, la.nominee_insurance_fee, la.other_charges,
               m.full_name as member_name, m.member_code,
               c.center_code, c.center_name,
               lt.loan_type_name,
               u.full_name as disbursed_by_name
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        LEFT JOIN users u ON ld.disbursed_by=u.id
        WHERE substr(ld.disbursement_date,7,4)||'-'||substr(ld.disbursement_date,4,2)||'-'||substr(ld.disbursement_date,1,2) = ?
    """
    params = [report_date]
    if center_filter:
        query += " AND la.center_id=?"
        params.append(center_filter)
    query += " ORDER BY c.center_code, m.member_code"
    records = db.execute(query, params).fetchall()
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/voucher_debit.html', records=records, centers=centers,
                           center_filter=center_filter, report_date=report_date, report_date_display=report_date_display)

@app.route('/reports/voucher/credit')
@login_required
def report_voucher_credit():
    db = get_db()
    center_filter = request.args.get('center_id', '')
    report_date = request.args.get('report_date', datetime.today().strftime('%Y-%m-%d'))
    try:
        p = report_date.split('-')
        report_date_display = f"{p[2]}/{p[1]}/{p[0]}"
    except Exception:
        report_date_display = report_date

    def _rp_sum(field):
        q = f"SELECT COALESCE(SUM(rp.{field}),0) FROM recovery_postings rp LEFT JOIN loan_disbursements ld ON rp.disbursement_id=ld.id LEFT JOIN loan_applications la ON ld.application_id=la.id WHERE rp.installment_no > 0 AND substr(rp.posting_date,7,4)||'-'||substr(rp.posting_date,4,2)||'-'||substr(rp.posting_date,1,2) = ?"
        p = [report_date]
        if center_filter:
            q += " AND la.center_id=?"; p.append(center_filter)
        return db.execute(q, p).fetchone()[0] or 0

    def _disb_sum(field):
        q = f"SELECT COALESCE(SUM(la.{field}),0) FROM loan_applications la LEFT JOIN loan_disbursements ld ON ld.application_id=la.id WHERE substr(ld.disbursement_date,7,4)||'-'||substr(ld.disbursement_date,4,2)||'-'||substr(ld.disbursement_date,1,2) = ?"
        p = [report_date]
        if center_filter:
            q += " AND la.center_id=?"; p.append(center_filter)
        return db.execute(q, p).fetchone()[0] or 0

    prepaid_q = "SELECT COALESCE(SUM(pt.amount),0) FROM prepaid_transactions pt LEFT JOIN loan_disbursements ld ON pt.disbursement_id=ld.id LEFT JOIN loan_applications la ON ld.application_id=la.id WHERE pt.is_undo=0 AND substr(pt.transaction_date,7,4)||'-'||substr(pt.transaction_date,4,2)||'-'||substr(pt.transaction_date,1,2) = ?"
    prepaid_p = [report_date]
    if center_filter:
        prepaid_q += " AND la.center_id=?"; prepaid_p.append(center_filter)
    prepaid_total = db.execute(prepaid_q, prepaid_p).fetchone()[0] or 0

    member_fee_q = "SELECT COALESCE(SUM(m.total_fees),0) FROM members m WHERE substr(m.date_of_join,7,4)||'-'||substr(m.date_of_join,4,2)||'-'||substr(m.date_of_join,1,2) = ?"
    member_fee_p = [report_date]
    if center_filter:
        member_fee_q += " AND m.center_id=?"; member_fee_p.append(center_filter)
    member_fee_total = db.execute(member_fee_q, member_fee_p).fetchone()[0] or 0

    totals = {
        'loan_recovery': _rp_sum('principal'),
        'interest_on_loans': _rp_sum('interest'),
        'processing_fee': _disb_sum('processing_fee'),
        'insurance': _disb_sum('insurance_fee') + _disb_sum('nominee_insurance_fee'),
        'prepaid': prepaid_total,
        'member_fee': member_fee_total,
    }
    totals['grand_total'] = sum(totals.values())
    centers = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()
    db.close()
    return render_template('reports/voucher_credit.html', totals=totals, centers=centers,
                           center_filter=center_filter, report_date=report_date, report_date_display=report_date_display)

@app.route('/reports/glance')
@login_required
def report_glance():
    db = get_db()
    from_date = request.args.get('from_date', '')
    to_date   = request.args.get('to_date', '')
    from_iso  = _to_iso(from_date) if from_date else ''
    to_iso    = _to_iso(to_date)   if to_date   else ''
    centers   = db.execute("SELECT id, center_code, center_name FROM centers WHERE active=1").fetchall()

    def ic(col):
        return f"substr({col},7,4)||'-'||substr({col},4,2)||'-'||substr({col},1,2)"

    def scalar(sql, params=()):
        row = db.execute(sql, params).fetchone()
        return (row[0] or 0) if row else 0

    def dc(col, period):
        expr = ic(col)
        if period == 'open':
            if not from_iso: return '1=0', ()
            return f'{expr} < ?', (from_iso,)
        if period == 'during':
            parts, ps = [], []
            if from_iso: parts.append(f'{expr} >= ?'); ps.append(from_iso)
            if to_iso:   parts.append(f'{expr} <= ?'); ps.append(to_iso)
            return (' AND '.join(parts) if parts else '1=1'), tuple(ps)
        # 'close'
        if not to_iso: return '1=1', ()
        return f'{expr} <= ?', (to_iso,)

    def mem_count(period):
        c, p = dc('m.date_of_join', period)
        return scalar(f'SELECT COUNT(*) FROM members m WHERE {c}', p)

    def borrowers(period):
        c, p = dc('ld.disbursement_date', period)
        return scalar(
            f'SELECT COUNT(DISTINCT la.member_id) FROM loan_disbursements ld '
            f'LEFT JOIN loan_applications la ON ld.application_id=la.id WHERE {c}', p)

    def mem_fee(period):
        c, p = dc('m.date_of_join', period)
        return scalar(f'SELECT COALESCE(SUM(m.total_fees),0) FROM members m WHERE {c}', p)

    def disb_count(period):
        c, p = dc('ld.disbursement_date', period)
        return scalar(f'SELECT COUNT(*) FROM loan_disbursements ld WHERE {c}', p)

    def disb_amt(period):
        c, p = dc('ld.disbursement_date', period)
        return scalar(f'SELECT COALESCE(SUM(ld.disbursed_amount),0) FROM loan_disbursements ld WHERE {c}', p)

    def la_sum(field, period):
        c, p = dc('ld.disbursement_date', period)
        return scalar(
            f'SELECT COALESCE(SUM(la.{field}),0) FROM loan_disbursements ld '
            f'LEFT JOIN loan_applications la ON ld.application_id=la.id WHERE {c}', p)

    def rp_sum(field, period):
        c, p = dc('rp.posting_date', period)
        return scalar(
            f'SELECT COALESCE(SUM(rp.{field}),0) FROM recovery_postings rp '
            f'WHERE rp.installment_no>0 AND {c}', p)

    def save_dep(period):
        c, p = dc('st.transaction_date', period)
        return scalar(f'SELECT COALESCE(SUM(st.deposit_amount),0) FROM savings_transactions st WHERE {c}', p)

    def save_with(period):
        c, p = dc('st.transaction_date', period)
        return scalar(f'SELECT COALESCE(SUM(st.withdraw_amount),0) FROM savings_transactions st WHERE {c}', p)

    def arrear_count(period):
        c, p = dc('ae.arrear_date', period)
        return scalar(
            f'SELECT COUNT(DISTINCT ae.disbursement_id) FROM arrear_entries ae WHERE ae.status="Pending" AND {c}', p)

    def arrear_amt(period):
        c, p = dc('ae.arrear_date', period)
        return scalar(
            f'SELECT COALESCE(SUM(ae.due_amount),0) FROM arrear_entries ae WHERE ae.status="Pending" AND {c}', p)

    def prepaid_count(period):
        c, p = dc('pt.transaction_date', period)
        return scalar(
            f'SELECT COUNT(DISTINCT pt.disbursement_id) FROM prepaid_transactions pt WHERE pt.is_undo=0 AND {c}', p)

    def prepaid_amt(period):
        c, p = dc('pt.transaction_date', period)
        return scalar(
            f'SELECT COALESCE(SUM(pt.amount),0) FROM prepaid_transactions pt WHERE pt.is_undo=0 AND {c}', p)

    def adv_collected(period):
        c, p = dc('ar.recovery_date', period)
        return scalar(f'SELECT COALESCE(SUM(ar.amount),0) FROM advance_recoveries ar WHERE {c}', p)

    total_centers   = scalar("SELECT COUNT(*) FROM centers WHERE active=1")
    total_withdrawn = scalar("SELECT COUNT(*) FROM members WHERE status='WITHDRAWN'")
    loans_closed    = scalar("SELECT COUNT(*) FROM loan_disbursements WHERE status='Closed'")

    rows = []
    def R(sno, name, o, d, cl=None):
        if cl is None: cl = o + d
        rows.append({'sno': sno, 'name': name, 'opening': o, 'during': d, 'closing': cl})

    # ── 1 No. Of Centers ──────────────────────────────────────────────────────
    R(1, 'No. Of Centers', 0, total_centers, total_centers)
    # ── 2 Members Enrolled ────────────────────────────────────────────────────
    mo = mem_count('open'); md = mem_count('during'); mc = mem_count('close')
    R(2, 'Members Enrolled', mo, md, mc)
    # ── 3 Members Withdrawn ───────────────────────────────────────────────────
    R(3, 'Members Withdrawn', 0, total_withdrawn, total_withdrawn)
    # ── 4 Net Members ─────────────────────────────────────────────────────────
    R(4, 'Net Members', mo, md, mc - total_withdrawn)
    # ── 5 Borrowers ───────────────────────────────────────────────────────────
    R(5, 'Borrowers', borrowers('open'), borrowers('during'), borrowers('close'))
    # ── 6 Member Joining Fee ──────────────────────────────────────────────────
    R(6, 'Member Joining Fee', mem_fee('open'), mem_fee('during'), mem_fee('close'))
    # ── 7 Processing Fee ──────────────────────────────────────────────────────
    R(7, 'Processing Fee', la_sum('processing_fee','open'), la_sum('processing_fee','during'), la_sum('processing_fee','close'))
    # ── 8 Insurance Premium ───────────────────────────────────────────────────
    ins_o = la_sum('insurance_fee','open') + la_sum('nominee_insurance_fee','open')
    ins_d = la_sum('insurance_fee','during') + la_sum('nominee_insurance_fee','during')
    ins_c = la_sum('insurance_fee','close') + la_sum('nominee_insurance_fee','close')
    R(8, 'Insurance Premium', ins_o, ins_d, ins_c)
    # ── 9 Loans Closed ────────────────────────────────────────────────────────
    R(9, 'Loans Closed', 0, loans_closed, loans_closed)
    # ── 10 Loans Disbursed ────────────────────────────────────────────────────
    R(10, 'Loans Disbursed', disb_count('open'), disb_count('during'), disb_count('close'))
    # ── 11 Loan Amount ────────────────────────────────────────────────────────
    R(11, 'Loan Amount', disb_amt('open'), disb_amt('during'), disb_amt('close'))
    # ── 12 Prin Recovery ──────────────────────────────────────────────────────
    R(12, 'Prin Recovery', rp_sum('principal','open'), rp_sum('principal','during'), rp_sum('principal','close'))
    # ── 13 Outstanding ────────────────────────────────────────────────────────
    out_o = disb_amt('open') - rp_sum('principal','open')
    out_d = disb_amt('during') - rp_sum('principal','during')
    out_c = disb_amt('close') - rp_sum('principal','close')
    R(13, 'Outstanding', out_o, out_d, out_c)
    # ── 14 Interest Recovery ──────────────────────────────────────────────────
    R(14, 'Interest Recovery', rp_sum('interest','open'), rp_sum('interest','during'), rp_sum('interest','close'))
    # ── 15 Prin Due Current Period ────────────────────────────────────────────
    R(15, 'Prin Due Current Period', 0, 0, 0)
    # ── 16 Int Due Current Period ─────────────────────────────────────────────
    R(16, 'Int Due Current Period', 0, 0, 0)
    # ── 17 Savings Current Period ─────────────────────────────────────────────
    R(17, 'Savings Current Period', save_dep('open'), save_dep('during'), save_dep('close'))
    # ── 18 Prin Due Next Period ───────────────────────────────────────────────
    R(18, 'Prin Due Next Period', 0, 0, 0)
    # ── 19 Int Due Next Period ────────────────────────────────────────────────
    R(19, 'Int Due Next Period', 0, 0, 0)
    # ── 20 Arrear Loans ───────────────────────────────────────────────────────
    R(20, 'Arrear Loans', arrear_count('open'), arrear_count('during'), arrear_count('close'))
    # ── 21 Arrear Prin ────────────────────────────────────────────────────────
    R(21, 'Arrear Prin', arrear_amt('open'), arrear_amt('during'), arrear_amt('close'))
    # ── 22 Arrear Int ─────────────────────────────────────────────────────────
    R(22, 'Arrear Int', 0, 0, 0)
    # ── 23 Prepaid Loans ──────────────────────────────────────────────────────
    R(23, 'Prepaid Loans', prepaid_count('open'), prepaid_count('during'), prepaid_count('close'))
    # ── 24 Prepaid Amount ─────────────────────────────────────────────────────
    R(24, 'Prepaid Amount', prepaid_amt('open'), prepaid_amt('during'), prepaid_amt('close'))
    # ── 25 Death Loans ────────────────────────────────────────────────────────
    R(25, 'Death Loans', 0, 0, 0)
    # ── 26 Prepaid on Death ───────────────────────────────────────────────────
    R(26, 'Prepaid on Death', 0, 0, 0)
    # ── 27 Prepaid Charges ────────────────────────────────────────────────────
    R(27, 'Prepaid Charges', 0, 0, 0)
    # ── 28 Advance Collected ──────────────────────────────────────────────────
    ac_o = adv_collected('open'); ac_d = adv_collected('during'); ac_c = adv_collected('close')
    R(28, 'Advance Collected', ac_o, ac_d, ac_c)
    # ── 29 Advance Withdrawn ──────────────────────────────────────────────────
    R(29, 'Advance Withdrawn', 0, 0, 0)
    # ── 30 Net Advance Recovery ───────────────────────────────────────────────
    R(30, 'Net Advance Recovery', ac_o, ac_d, ac_c)

    db.close()
    return render_template('reports/glance_report.html', rows=rows, centers=centers,
                           from_date=from_date, to_date=to_date)

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
               COALESCE(SUM(rp.principal),0) as principal_paid,
               ld.disbursed_amount - COALESCE(SUM(rp.principal),0) as outstanding,
               COUNT(rp.id) as paid_count
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        LEFT JOIN members m ON la.member_id=m.id
        LEFT JOIN centers c ON la.center_id=c.id
        LEFT JOIN loan_types lt ON la.loan_type_id=lt.id
        LEFT JOIN recovery_postings rp ON rp.disbursement_id=ld.id AND rp.installment_no > 0
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
        SELECT m.member_code, m.full_name, m.date_of_birth, m.spouse_name, m.kyc_type, m.gender,
               la.nominee_name, la.nominee_kyc_type, la.nominee_kyc_number,
               la.insurance_fee, la.nominee_insurance_fee, la.loan_cycle,
               ld.loan_id, ld.disbursement_date, ld.disbursed_amount, ld.total_installments,
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

# ── Subscription / Billing ────────────────────────────────────────────────────

@app.route('/subscription/blocked')
@login_required
def subscription_blocked():
    import calendar as _cal
    from datetime import timezone, timedelta
    branch_db = session['branch_db']
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).replace(tzinfo=None)
    month_key = today.strftime('%Y-%m')
    master = get_master_db()
    payment = master.execute(
        "SELECT * FROM subscription_payments WHERE branch_db=? AND month_key=?",
        (branch_db, month_key)
    ).fetchone()
    sub = master.execute(
        "SELECT * FROM branch_subscriptions WHERE branch_db=?", (branch_db,)
    ).fetchone()
    scanner_row = master.execute(
        "SELECT value FROM developer_settings WHERE key='scanner_image'"
    ).fetchone()
    scanner_image = scanner_row['value'] if scanner_row else None
    last_day = _cal.monthrange(today.year, today.month)[1]
    due_day = min(int(sub['due_day']), last_day) if sub else today.day
    due_date = today.replace(day=due_day).strftime('%d/%m/%Y')
    amount = sub['monthly_amount'] if sub else 0
    master.close()
    return render_template('subscription_blocked.html',
        payment=payment, scanner_image=scanner_image,
        due_date=due_date, amount=amount)


@app.route('/subscription/pay', methods=['POST'])
@login_required
def subscription_submit_payment():
    import calendar as _cal
    branch_db = session['branch_db']
    branch_name = session.get('branch_name', '')
    today = datetime.now()
    month_key = today.strftime('%Y-%m')
    master = get_master_db()
    sub = master.execute(
        "SELECT * FROM branch_subscriptions WHERE branch_db=?", (branch_db,)
    ).fetchone()
    last_day = _cal.monthrange(today.year, today.month)[1]
    due_day = min(int(sub['due_day']), last_day) if sub else today.day
    due_date_str = today.replace(day=due_day).strftime('%Y-%m-%d')
    amount = sub['monthly_amount'] if sub else 0
    existing = master.execute(
        "SELECT id FROM subscription_payments WHERE branch_db=? AND month_key=?",
        (branch_db, month_key)
    ).fetchone()
    if not existing:
        master.execute("""
            INSERT INTO subscription_payments
            (branch_db, branch_name, month_key, due_date, amount, status)
            VALUES (?,?,?,?,?,'Pending')
        """, (branch_db, branch_name, month_key, due_date_str, amount))
        master.commit()
    master.close()
    flash('Payment submitted. Access will be confirmed once the developer approves.', 'success')
    # If already blocked redirect to blocked page; otherwise back to dashboard
    if getattr(g, 'sub_blocked', False):
        return redirect(url_for('subscription_blocked'))
    return redirect(url_for('dashboard'))


# ── Developer – Subscription Management ──────────────────────────────────────

@app.route('/developer/subscriptions', methods=['POST'])
@developer_required
def developer_subscription_settings():
    master = get_master_db()
    branches = master.execute("SELECT * FROM branches ORDER BY name").fetchall()
    for br in branches:
        bid     = br['id']
        due_day  = request.form.get(f'due_day_{bid}', '5')
        due_time = request.form.get(f'due_time_{bid}', '23:59') or '23:59'
        amount   = request.form.get(f'amount_{bid}', '0')
        enabled  = 1 if request.form.get(f'enabled_{bid}') else 0
        existing = master.execute(
            "SELECT id FROM branch_subscriptions WHERE branch_db=?", (br['db_path'],)
        ).fetchone()
        if existing:
            master.execute("""
                UPDATE branch_subscriptions
                SET due_day=?, due_time=?, monthly_amount=?, enabled=?, branch_name=?,
                    updated_at=datetime('now')
                WHERE branch_db=?
            """, (due_day, due_time, amount, enabled, br['name'], br['db_path']))
        else:
            master.execute("""
                INSERT INTO branch_subscriptions
                (branch_db, branch_name, due_day, due_time, monthly_amount, enabled)
                VALUES (?,?,?,?,?,?)
            """, (br['db_path'], br['name'], due_day, due_time, amount, enabled))
    master.commit()
    master.close()
    flash('Subscription settings saved.', 'success')
    return redirect(url_for('developer_panel'))


@app.route('/developer/subscriptions/<int:pid>/approve', methods=['POST'])
@developer_required
def developer_subscription_approve(pid):
    master = get_master_db()
    master.execute("""
        UPDATE subscription_payments
        SET status='Approved', approved_at=datetime('now','localtime'), approved_by=?
        WHERE id=?
    """, (session.get('dev_name', 'Developer'), pid))
    master.commit()
    master.close()
    flash('Payment approved. Branch access restored.', 'success')
    return redirect(url_for('developer_panel'))


@app.route('/developer/subscriptions/<int:pid>/undo', methods=['POST'])
@developer_required
def developer_subscription_undo(pid):
    master = get_master_db()
    master.execute("""
        UPDATE subscription_payments
        SET status='Pending', approved_at=NULL, approved_by=NULL
        WHERE id=?
    """, (pid,))
    master.commit()
    master.close()
    flash('Payment approval undone. Branch will be blocked again.', 'warning')
    return redirect(url_for('developer_panel'))


@app.route('/developer/subscriptions/<int:pid>/delete', methods=['POST'])
@developer_required
def developer_subscription_delete(pid):
    master = get_master_db()
    master.execute("DELETE FROM subscription_payments WHERE id=?", (pid,))
    master.commit()
    master.close()
    flash('Payment record deleted.', 'success')
    return redirect(url_for('developer_panel'))


@app.route('/developer/scanner/upload', methods=['POST'])
@developer_required
def developer_scanner_upload():
    f = request.files.get('scanner_image')
    if f and f.filename:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
            fname = 'upi_scanner' + ext
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            f.save(save_path)
            master = get_master_db()
            master.execute("""
                INSERT OR REPLACE INTO developer_settings (key, value, updated_at)
                VALUES ('scanner_image', ?, datetime('now'))
            """, (fname,))
            master.commit()
            master.close()
            flash('UPI Scanner image updated successfully.', 'success')
        else:
            flash('Invalid file type. Use PNG, JPG, or GIF.', 'danger')
    else:
        flash('No file selected.', 'danger')
    return redirect(url_for('developer_panel'))

# ── Tally Income & Profit ─────────────────────────────────────────────────────

def _tally_income(db, from_iso, to_iso):
    """Return dict of income amounts for the given ISO date range."""
    def ic(col):
        return f"substr({col},7,4)||'-'||substr({col},4,2)||'-'||substr({col},1,2)"

    def between(col):
        conds, p = [], []
        if from_iso: conds.append(f"{ic(col)} >= ?"); p.append(from_iso)
        if to_iso:   conds.append(f"{ic(col)} <= ?"); p.append(to_iso)
        return (' AND '.join(conds) if conds else '1=1'), tuple(p)

    c_rp, p_rp = between('rp.posting_date')
    interest = db.execute(
        f"SELECT COALESCE(SUM(rp.interest),0) FROM recovery_postings rp WHERE rp.installment_no>0 AND {c_rp}", p_rp
    ).fetchone()[0]

    c_ld, p_ld = between('ld.disbursement_date')
    proc = db.execute(
        f"SELECT COALESCE(SUM(la.processing_fee),0) FROM loan_disbursements ld "
        f"LEFT JOIN loan_applications la ON ld.application_id=la.id WHERE {c_ld}", p_ld
    ).fetchone()[0]
    ins = db.execute(
        f"SELECT COALESCE(SUM(la.insurance_fee+la.nominee_insurance_fee),0) FROM loan_disbursements ld "
        f"LEFT JOIN loan_applications la ON ld.application_id=la.id WHERE {c_ld}", p_ld
    ).fetchone()[0]

    c_m, p_m = between('m.date_of_join')
    mem_fee = db.execute(
        f"SELECT COALESCE(SUM(m.total_fees),0) FROM members m WHERE {c_m}", p_m
    ).fetchone()[0]

    return {'interest': interest, 'processing_fee': proc, 'insurance_fee': ins, 'membership_fee': mem_fee}


def _tally_expenses(db, from_iso, to_iso):
    """Return list of (group_name, total) for manual vouchers in the date range."""
    def ic(col):
        return f"substr({col},7,4)||'-'||substr({col},4,2)||'-'||substr({col},1,2)"
    conds, p = ["1=1"], []
    if from_iso: conds.append(f"{ic('tv.voucher_date')} >= ?"); p.append(from_iso)
    if to_iso:   conds.append(f"{ic('tv.voucher_date')} <= ?"); p.append(to_iso)
    where = ' AND '.join(conds)
    rows = db.execute(
        f"SELECT tg.name, COALESCE(SUM(tv.amount),0) as total "
        f"FROM tally_vouchers tv "
        f"JOIN tally_ledgers tl ON tv.ledger_id=tl.id "
        f"JOIN tally_groups tg ON tl.group_id=tg.id "
        f"WHERE {where} GROUP BY tg.name ORDER BY tg.sort_order", p
    ).fetchall()
    return rows


def _week_label(iso_date_str):
    """Given YYYY-MM-DD return DD/MM - DD/MM for the Mon-Sun week."""
    from datetime import datetime, timedelta
    try:
        d = datetime.strptime(iso_date_str, '%Y-%m-%d')
        mon = d - timedelta(days=d.weekday())
        sun = mon + timedelta(days=6)
        return f"{mon.strftime('%d/%m')} – {sun.strftime('%d/%m')}"
    except Exception:
        return iso_date_str


@app.route('/tally')
@admin_required
def tally_dashboard():
    db = get_db()
    from datetime import datetime, timedelta
    today = datetime.now()
    # Current week (Mon-Sun)
    wk_start = today - timedelta(days=today.weekday())
    wk_end   = wk_start + timedelta(days=6)
    # Current month
    mo_start = today.replace(day=1)
    import calendar
    mo_end   = today.replace(day=calendar.monthrange(today.year, today.month)[1])

    wk_s_iso = wk_start.strftime('%Y-%m-%d')
    wk_e_iso = wk_end.strftime('%Y-%m-%d')
    mo_s_iso = mo_start.strftime('%Y-%m-%d')
    mo_e_iso = mo_end.strftime('%Y-%m-%d')

    week_inc  = _tally_income(db, wk_s_iso, wk_e_iso)
    month_inc = _tally_income(db, mo_s_iso, mo_e_iso)

    week_exp  = sum(r['total'] for r in _tally_expenses(db, wk_s_iso, wk_e_iso))
    month_exp = sum(r['total'] for r in _tally_expenses(db, mo_s_iso, mo_e_iso))

    # Weekly breakdown for current month (group by ISO week Mon start)
    ic = "substr(rp.posting_date,7,4)||'-'||substr(rp.posting_date,4,2)||'-'||substr(rp.posting_date,1,2)"
    weekly_rows = db.execute(f"""
        SELECT
            date({ic}, 'weekday 1', '-6 days') as week_start,
            COALESCE(SUM(CASE WHEN rp.installment_no>0 THEN rp.interest ELSE 0 END),0) as interest
        FROM recovery_postings rp
        WHERE {ic} >= ? AND {ic} <= ?
        GROUP BY week_start ORDER BY week_start
    """, (mo_s_iso, mo_e_iso)).fetchall()

    ic_ld = "substr(ld.disbursement_date,7,4)||'-'||substr(ld.disbursement_date,4,2)||'-'||substr(ld.disbursement_date,1,2)"
    weekly_fees = db.execute(f"""
        SELECT
            date({ic_ld}, 'weekday 1', '-6 days') as week_start,
            COALESCE(SUM(la.processing_fee),0) as proc,
            COALESCE(SUM(la.insurance_fee+la.nominee_insurance_fee),0) as ins
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        WHERE {ic_ld} >= ? AND {ic_ld} <= ?
        GROUP BY week_start ORDER BY week_start
    """, (mo_s_iso, mo_e_iso)).fetchall()

    # Build weekly expense per week_start
    ic_tv = "substr(tv.voucher_date,7,4)||'-'||substr(tv.voucher_date,4,2)||'-'||substr(tv.voucher_date,1,2)"
    weekly_exp_rows = db.execute(f"""
        SELECT date({ic_tv}, 'weekday 1', '-6 days') as week_start,
               COALESCE(SUM(tv.amount),0) as exp
        FROM tally_vouchers tv
        WHERE {ic_tv} >= ? AND {ic_tv} <= ?
        GROUP BY week_start ORDER BY week_start
    """, (mo_s_iso, mo_e_iso)).fetchall()

    fees_map = {r['week_start']: dict(r) for r in weekly_fees}
    exp_map  = {r['week_start']: r['exp'] for r in weekly_exp_rows}

    weekly = []
    for r in weekly_rows:
        ws = r['week_start']
        proc = fees_map.get(ws, {}).get('proc', 0) or 0
        ins  = fees_map.get(ws, {}).get('ins', 0)  or 0
        exp  = exp_map.get(ws, 0)
        total_inc = (r['interest'] or 0) + proc + ins
        weekly.append({
            'week_label': _week_label(ws),
            'interest': r['interest'] or 0,
            'processing': proc,
            'insurance': ins,
            'total_income': total_inc,
            'expenses': exp,
            'net': total_inc - exp,
        })

    expense_groups = db.execute(
        "SELECT id, name FROM tally_groups WHERE nature='Expense' ORDER BY sort_order"
    ).fetchall()
    expense_ledgers = db.execute(
        "SELECT tl.id, tl.name, tg.name as group_name FROM tally_ledgers tl "
        "JOIN tally_groups tg ON tl.group_id=tg.id WHERE tg.nature='Expense' AND tl.active=1 ORDER BY tg.sort_order"
    ).fetchall()

    db.close()
    return render_template('tally/dashboard.html',
        week_inc=week_inc, month_inc=month_inc,
        week_exp=week_exp, month_exp=month_exp,
        weekly=weekly,
        month_label=today.strftime('%B %Y'),
        expense_ledgers=expense_ledgers)


@app.route('/tally/report')
@admin_required
def tally_report():
    db = get_db()
    from_date = request.args.get('from_date', '')
    to_date   = request.args.get('to_date', '')
    from_iso  = _to_iso(from_date) if from_date else ''
    to_iso    = _to_iso(to_date)   if to_date   else ''

    income = _tally_income(db, from_iso, to_iso)
    total_income = sum(income.values())

    exp_rows = _tally_expenses(db, from_iso, to_iso)
    total_expenses = sum(r['total'] for r in exp_rows)
    net_profit = total_income - total_expenses

    # Weekly breakdown within range
    ic = "substr(rp.posting_date,7,4)||'-'||substr(rp.posting_date,4,2)||'-'||substr(rp.posting_date,1,2)"
    conds = ['rp.installment_no>0']
    p = []
    if from_iso: conds.append(f"{ic} >= ?"); p.append(from_iso)
    if to_iso:   conds.append(f"{ic} <= ?"); p.append(to_iso)
    where = ' AND '.join(conds)
    weekly_int = db.execute(f"""
        SELECT date({ic}, 'weekday 1', '-6 days') as week_start,
               COALESCE(SUM(rp.interest),0) as interest
        FROM recovery_postings rp WHERE {where}
        GROUP BY week_start ORDER BY week_start
    """, p).fetchall()

    ic_ld = "substr(ld.disbursement_date,7,4)||'-'||substr(ld.disbursement_date,4,2)||'-'||substr(ld.disbursement_date,1,2)"
    conds2, p2 = [], []
    if from_iso: conds2.append(f"{ic_ld} >= ?"); p2.append(from_iso)
    if to_iso:   conds2.append(f"{ic_ld} <= ?"); p2.append(to_iso)
    w2 = (' AND '.join(conds2)) if conds2 else '1=1'
    weekly_fees = db.execute(f"""
        SELECT date({ic_ld}, 'weekday 1', '-6 days') as week_start,
               COALESCE(SUM(la.processing_fee),0) as proc,
               COALESCE(SUM(la.insurance_fee+la.nominee_insurance_fee),0) as ins
        FROM loan_disbursements ld
        LEFT JOIN loan_applications la ON ld.application_id=la.id
        WHERE {w2} GROUP BY week_start ORDER BY week_start
    """, p2).fetchall()

    ic_tv = "substr(tv.voucher_date,7,4)||'-'||substr(tv.voucher_date,4,2)||'-'||substr(tv.voucher_date,1,2)"
    conds3, p3 = [], []
    if from_iso: conds3.append(f"{ic_tv} >= ?"); p3.append(from_iso)
    if to_iso:   conds3.append(f"{ic_tv} <= ?"); p3.append(to_iso)
    w3 = (' AND '.join(conds3)) if conds3 else '1=1'
    weekly_exp_rows = db.execute(f"""
        SELECT date({ic_tv}, 'weekday 1', '-6 days') as week_start,
               COALESCE(SUM(tv.amount),0) as exp
        FROM tally_vouchers tv WHERE {w3}
        GROUP BY week_start ORDER BY week_start
    """, p3).fetchall()

    fees_map = {r['week_start']: dict(r) for r in weekly_fees}
    exp_map  = {r['week_start']: r['exp'] for r in weekly_exp_rows}
    # Merge all weeks
    all_weeks = sorted(set(
        [r['week_start'] for r in weekly_int] +
        list(fees_map.keys()) + list(exp_map.keys())
    ))
    weekly = []
    for ws in all_weeks:
        int_v  = next((r['interest'] for r in weekly_int if r['week_start']==ws), 0) or 0
        proc   = (fees_map.get(ws) or {}).get('proc', 0) or 0
        ins    = (fees_map.get(ws) or {}).get('ins', 0)  or 0
        exp    = exp_map.get(ws, 0) or 0
        ti     = int_v + proc + ins
        weekly.append({'week_label': _week_label(ws), 'interest': int_v,
                       'processing': proc, 'insurance': ins,
                       'total_income': ti, 'expenses': exp, 'net': ti - exp})

    db.close()
    return render_template('tally/report.html',
        income=income, total_income=total_income,
        exp_rows=exp_rows, total_expenses=total_expenses,
        net_profit=net_profit, weekly=weekly,
        from_date=from_date, to_date=to_date)


@app.route('/tally/vouchers', methods=['GET', 'POST'])
@admin_required
def tally_vouchers():
    db = get_db()
    if request.method == 'POST':
        ledger_id   = request.form.get('ledger_id')
        vdate       = request.form.get('voucher_date', '')
        amount      = request.form.get('amount', 0)
        narration   = request.form.get('narration', '')
        if ledger_id and vdate and float(amount or 0) > 0:
            db.execute(
                "INSERT INTO tally_vouchers (ledger_id,voucher_date,amount,narration,created_by) VALUES (?,?,?,?,?)",
                (ledger_id, vdate, amount, narration, session['user_id'])
            )
            db.commit()
            flash('Expense saved.', 'success')
        else:
            flash('Please fill all required fields.', 'danger')
        db.close()
        return redirect(url_for('tally_vouchers'))

    expense_ledgers = db.execute(
        "SELECT tl.id, tl.name, tg.name as group_name FROM tally_ledgers tl "
        "JOIN tally_groups tg ON tl.group_id=tg.id WHERE tg.nature='Expense' AND tl.active=1 ORDER BY tg.sort_order, tl.name"
    ).fetchall()
    # All groups (all natures) for Add Ledger modal
    all_groups = db.execute(
        "SELECT id, name, nature FROM tally_groups ORDER BY nature, sort_order, name"
    ).fetchall()
    vouchers = db.execute("""
        SELECT tv.*, tl.name as ledger_name, tg.name as group_name
        FROM tally_vouchers tv
        JOIN tally_ledgers tl ON tv.ledger_id=tl.id
        JOIN tally_groups tg ON tl.group_id=tg.id
        ORDER BY tv.id DESC LIMIT 100
    """).fetchall()
    db.close()
    return render_template('tally/vouchers.html',
        expense_ledgers=expense_ledgers, all_groups=all_groups, vouchers=vouchers)


@app.route('/tally/vouchers/<int:vid>/delete', methods=['POST'])
@admin_required
def tally_voucher_delete(vid):
    db = get_db()
    db.execute("DELETE FROM tally_vouchers WHERE id=?", (vid,))
    db.commit()
    db.close()
    flash('Expense deleted.', 'success')
    return redirect(url_for('tally_vouchers'))


@app.route('/tally/ledgers/add', methods=['POST'])
@admin_required
def tally_ledger_add():
    db = get_db()
    name     = request.form.get('name', '').strip()
    group_id = request.form.get('group_id')
    if name and group_id:
        try:
            db.execute("INSERT INTO tally_ledgers (name, group_id) VALUES (?,?)", (name, group_id))
            db.commit()
            flash(f'Ledger "{name}" added.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'danger')
    db.close()
    return redirect(url_for('tally_vouchers'))


@app.route('/tally/trial-balance')
@admin_required
def tally_trial_balance():
    db  = get_db()
    raw = request.args.get('as_at', '').strip()
    try:
        as_at_iso = datetime.strptime(raw, '%d/%m/%Y').strftime('%Y-%m-%d')
    except Exception:
        as_at_iso = datetime.now().strftime('%Y-%m-%d')
    as_at_display = datetime.strptime(as_at_iso, '%Y-%m-%d').strftime('%d/%m/%Y')

    # Date-column converter: stored as DD/MM/YYYY → compare as YYYY-MM-DD
    def ic(col):
        return f"substr({col},7,4)||'-'||substr({col},4,2)||'-'||substr({col},1,2)"

    def scalar(sql, p=()):
        r = db.execute(sql, p).fetchone()
        return (r[0] or 0) if r else 0

    # ── Balance-sheet items ───────────────────────────────────────────────────
    # Loans Outstanding (Asset DR) = disbursed − principal recovered (inception → as_at)
    disbursed  = scalar(
        f"SELECT COALESCE(SUM(disbursed_amount),0) FROM loan_disbursements "
        f"WHERE {ic('disbursement_date')} <= ?", (as_at_iso,))
    recovered  = scalar(
        f"SELECT COALESCE(SUM(principal),0) FROM recovery_postings "
        f"WHERE installment_no>0 AND {ic('posting_date')} <= ?", (as_at_iso,))
    loans_outstanding = max(disbursed - recovered, 0)

    # Member Savings (Liability CR) = total deposits − withdrawals
    sav_dep = scalar(
        f"SELECT COALESCE(SUM(deposit_amount),0)  FROM savings_transactions WHERE {ic('transaction_date')} <= ?",
        (as_at_iso,))
    sav_wit = scalar(
        f"SELECT COALESCE(SUM(withdraw_amount),0) FROM savings_transactions WHERE {ic('transaction_date')} <= ?",
        (as_at_iso,))
    member_savings = max(sav_dep - sav_wit, 0)

    # ── Income (Credit) — from inception to as_at ─────────────────────────────
    income = _tally_income(db, None, as_at_iso)

    penalty = scalar(
        f"SELECT COALESCE(SUM(penalty),0) FROM recovery_postings "
        f"WHERE installment_no>0 AND {ic('posting_date')} <= ?", (as_at_iso,))

    principal_recovered = scalar(
        f"SELECT COALESCE(SUM(principal),0) FROM recovery_postings "
        f"WHERE installment_no>0 AND {ic('posting_date')} <= ?", (as_at_iso,))

    # ── Expenses (Debit) — from inception to as_at ────────────────────────────
    expenses = _tally_expenses(db, None, as_at_iso)

    # ── Build DR / CR rows ────────────────────────────────────────────────────
    debit = []
    if loans_outstanding:
        debit.append({'name': 'Loans Outstanding to Members', 'nature': 'Asset',   'amount': loans_outstanding})
    for grp_name, total in expenses:
        if total:
            debit.append({'name': grp_name,                   'nature': 'Expense', 'amount': total})

    credit = []
    if income['interest']:
        credit.append({'name': 'Interest on Loans',    'nature': 'Income',    'amount': income['interest']})
    if income['processing_fee']:
        credit.append({'name': 'Processing Fees',      'nature': 'Income',    'amount': income['processing_fee']})
    if income['insurance_fee']:
        credit.append({'name': 'Insurance Fees',       'nature': 'Income',    'amount': income['insurance_fee']})
    if income['membership_fee']:
        credit.append({'name': 'Membership Fees',      'nature': 'Income',    'amount': income['membership_fee']})
    if penalty:
        credit.append({'name': 'Penalty / Fine Income','nature': 'Income',    'amount': penalty})
    if member_savings:
        credit.append({'name': 'Member Savings',       'nature': 'Liability', 'amount': member_savings})
    if principal_recovered:
        credit.append({'name': 'Loan Repayments (Principal Recovered)', 'nature': 'Liability', 'amount': principal_recovered})

    total_dr = sum(r['amount'] for r in debit)
    total_cr = sum(r['amount'] for r in credit)

    # Balancing figure
    diff = round(total_dr - total_cr, 2)
    if diff > 0:
        credit.append({'name': 'Surplus (Net Profit)',  'nature': 'Capital', 'amount': diff})
        total_cr = total_dr
    elif diff < 0:
        debit.append({'name':  'Deficit (Net Loss)',    'nature': 'Capital', 'amount': -diff})
        total_dr = total_cr

    db.close()
    return render_template('tally/trial_balance.html',
        debit=debit, credit=credit,
        total_dr=total_dr, total_cr=total_cr,
        as_at=as_at_display,
        disbursed=disbursed, recovered=recovered,
        total_income=sum([income['interest'], income['processing_fee'],
                          income['insurance_fee'], income['membership_fee'], penalty]),
        total_expenses=sum(t for _, t in expenses),
    )


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
