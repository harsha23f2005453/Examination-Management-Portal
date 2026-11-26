import os, sqlite3
from datetime import date
from functools import wraps
from flask import (Flask, g, render_template as rt, request, redirect, url_for,
                   session, flash, jsonify, abort, Response)
from werkzeug.security import generate_password_hash as gph, check_password_hash as cph

app = Flask(__name__)
app.secret_key = 'emp-dev-secret'
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emp.db')
SCHEMA = '''
create table if not exists users(id integer primary key, role text, name text, email text unique, password text, phone text, department text, ref_no text, status text default 'approved');
create table if not exists courses(id integer primary key, code text unique, name text, description text, status text default 'Active');
create table if not exists exams(id integer primary key, course_id integer references courses(id) on delete cascade, name text, type text, duration integer, max_marks real, sc_start text, sc_end text, sb_start text, sb_end text, status text default 'Draft', published integer default 0);
create table if not exists rubrics(id integer primary key, exam_id integer references exams(id) on delete cascade, name text, max_marks real, weightage real, description text);
create table if not exists exam_examiners(exam_id integer references exams(id) on delete cascade, examiner_id integer references users(id) on delete cascade, primary key(exam_id, examiner_id));
create table if not exists slots(id integer primary key, exam_id integer references exams(id) on delete cascade, examiner_id integer references users(id), date text, start_time text, end_time text, capacity integer, available integer, status text default 'Available');
create table if not exists bookings(id integer primary key, student_id integer references users(id), slot_id integer references slots(id) on delete cascade, exam_id integer references exams(id) on delete cascade, booked_at text, status text default 'Booked', marks real, remarks text, evaluated integer default 0);
create table if not exists scores(booking_id integer references bookings(id) on delete cascade, rubric_id integer references rubrics(id) on delete cascade, marks real, primary key(booking_id, rubric_id));
'''
STATUSES = ['Draft', 'Slot Creation', 'Booking Open', 'Closed', 'Completed']
TYPES = ['Viva', 'Practical', 'Project Demo', 'Assessment']

def init_db():
    c = sqlite3.connect(DB); c.executescript(SCHEMA)
    if not c.execute("select 1 from users where role='admin'").fetchone():
        c.execute("insert into users(role,name,email,password) values('admin','Administrator','admin@emp.com',?)", (gph('admin123'),))
    c.commit(); c.close()

def db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
        g.db.execute('pragma foreign_keys=on')
    return g.db
@app.teardown_appcontext
def _close(e):
    d = g.pop('db', None)
    if d: d.close()
def q(sql, a=(), one=False):
    r = db().execute(sql, a).fetchall()
    return (r[0] if r else None) if one else r
def x(sql, a=()):
    c = db().execute(sql, a); db().commit(); return c.lastrowid
def n(sql, a=()): return q(sql, a, one=True)[0]
today = lambda: date.today().isoformat()
can_create = lambda e: e['status'] == 'Slot Creation' and e['sc_start'] <= today() <= e['sc_end']
can_book = lambda e: e['status'] == 'Booking Open' and e['sb_start'] <= today() <= e['sb_end']

def cur():
    return q('select * from users where id=?', (session['uid'],), one=True) if 'uid' in session else None
@app.context_processor
def _inj(): return dict(me=cur())
def role(*rs):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = cur()
            if not u: return redirect(url_for('login'))
            if u['role'] not in rs: abort(403)
            if u['role'] == 'examiner' and u['status'] != 'approved': return rt('pending.html')
            return f(*a, **k)
        return w
    return deco

# ---------- UI helpers ----------
def page(title, tables=(), cards=(), top=(), search=None, sel=None, su=''):
    return rt('table.html', title=title, tables=tables, cards=cards, top=top, search=search, sel=sel, su=su)
def T(title, headers, rows): return dict(title=title, headers=headers, rows=rows)
def R(cells, *actions): return dict(cells=cells, actions=actions)
def A(l, u, c='secondary', get=False): return (l, u, c, 'get' if get else '')
def F(spec, row=None):
    row = request.form if request.method == 'POST' else dict(row or {})
    out = []
    for nm, label, t, o in spec:
        v = row.get(nm); v = '' if v is None or t == 'password' else v
        out.append(dict(name=nm, label=label, type=t, options=o, value=v, req=(t != 'textarea')))
    return out
def form(title, spec, back, table, i=None, row=None, check=None, fixed=None):
    if request.method == 'POST':
        err = check(request.form) if check else None
        if err: flash(err, 'danger')
        else:
            cols = [s[0] for s in spec]; vals = [request.form.get(c, '').strip() for c in cols]
            try:
                if i: x(f'update {table} set ' + ','.join(c + '=?' for c in cols) + ' where id=?', [*vals, i])
                else:
                    fx = fixed or {}
                    x(f'insert into {table}({",".join(cols + list(fx))}) values({",".join("?" * (len(cols) + len(fx)))})', vals + list(fx.values()))
                flash('Saved', 'success'); return redirect(back)
            except sqlite3.IntegrityError: flash('Duplicate value (code/email must be unique)', 'danger')
    return rt('form.html', title=title, fields=F(spec, row))
def delete(table, i):
    x(f'delete from {table} where id=?', (i,)); flash('Deleted', 'info')
    return redirect(request.referrer or url_for('home'))

# ---------- auth ----------
# Redirect an authenticated user to their role dashboard or show the login page.
@app.route('/')
def home():
    u = cur()
    return redirect(url_for(u['role'] + '_home') if u else url_for('login'))
# Authenticate a user and create a session for their account.
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = q('select * from users where email=?', (request.form['email'].lower().strip(),), one=True)
        if u and cph(u['password'], request.form['password']) and u['status'] != 'inactive':
            session.clear(); session['uid'] = u['id']; return redirect(url_for('home'))
        flash('Invalid credentials or deactivated account', 'danger')
    return rt('form.html', auth=True, title='Login', btn='Login', fields=F([('email', 'Email', 'email', None), ('password', 'Password', 'password', None)]))
# End the current session and return to the login page.
@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))
def make_user(f, r, status):
    if len(f['password']) < 6: return 'Password must be at least 6 characters'
    try:
        x('insert into users(role,name,email,password,phone,department,ref_no,status) values(?,?,?,?,?,?,?,?)',
          (r, f['name'].strip(), f['email'].lower().strip(), gph(f['password']), f['phone'], f['department'], f['ref_no'], status))
    except sqlite3.IntegrityError: return 'Email already registered'
UF = [('name', 'Full name', 'text', None), ('email', 'Email', 'email', None), ('phone', 'Phone', 'text', None),
      ('department', 'Department', 'text', None), ('ref_no', 'Student ID / Employee ID', 'text', None), ('password', 'Password (min 6)', 'password', None)]
# Register a new student or examiner account.
@app.route('/register', methods=['GET', 'POST'])
def register():
    spec = [('role', 'Register as', 'select', [('student', 'Student'), ('examiner', 'Examiner')])] + UF
    if request.method == 'POST':
        r = request.form['role']
        err = make_user(request.form, r, 'pending' if r == 'examiner' else 'approved') if r in ('student', 'examiner') else 'Invalid role'
        if err: flash(err, 'danger')
        else:
            flash('Registered! ' + ('Await admin approval.' if r == 'examiner' else 'Please log in.'), 'success'); return redirect(url_for('login'))
    return rt('form.html', title='Register', btn='Register', fields=F(spec))
# Allow a student or examiner to view and edit profile details.
@app.route('/profile', methods=['GET', 'POST'])
@role('student', 'examiner')
def profile():
    u = cur()
    spec = [s for s in UF if s[0] not in ('email', 'password')]
    return form('Edit profile', spec, url_for('home'), 'users', u['id'], row=u)

# ---------- admin ----------
# Display totals and pending-work summaries for the admin dashboard.
@app.route('/admin')
@role('admin')
def admin_home():
    cards = [('Courses', n('select count(*) from courses')), ('Examinations', n('select count(*) from exams')),
             ('Examiners', n("select count(*) from users where role='examiner'")), ('Students', n("select count(*) from users where role='student'")),
             ('Slots', n('select count(*) from slots')), ('Bookings', n('select count(*) from bookings')),
             ('Pending examiners', n("select count(*) from users where status='pending'"))]
    return page('Admin Dashboard', cards=cards, search='', su=url_for('admin_search'))
# Search students, examiners, examinations, and bookings.
@app.route('/admin/search')
@role('admin')
def admin_search():
    s = request.args.get('q', '').strip(); l = f'%{s}%'
    us = lambda r: [R([u['id'], u['name'], u['email'], u['ref_no'], u['status']]) for u in q("select * from users where role=? and (name like ? or ref_no like ? or email like ? or cast(id as text)=?)", (r, l, l, l, s))]
    ex = [R([e['id'], e['name'], e['type'], e['status']]) for e in q('select * from exams where name like ? or cast(id as text)=?', (l, s))]
    bk = [R([b['id'], b['sname'], b['ename'], b['date'], b['status']]) for b in q(BK + ' where u.name like ? or e.name like ? or cast(b.id as text)=?', (l, l, s))]
    h = ['ID', 'Name', 'Email', 'Ref no', 'Status']
    return page(f'Search: {s}', [T('Students', h, us('student')), T('Examiners', h, us('examiner')),
                T('Examinations', ['ID', 'Name', 'Type', 'Status'], ex), T('Bookings', ['ID', 'Student', 'Exam', 'Date', 'Status'], bk)], search=s, su=url_for('admin_search'))

# List every course and provide add, edit, and delete actions.
@app.route('/admin/courses')
@role('admin')
def courses():
    rows = [R([c['id'], c['code'], c['name'], c['status']], A('Edit', url_for('course_edit', i=c['id']), get=True), A('Delete', url_for('course_del', i=c['id']), 'danger')) for c in q('select * from courses')]
    return page('Courses', [T('', ['ID', 'Code', 'Name', 'Status'], rows)], top=[('Add course', url_for('course_edit', i=0))])
# Create or edit a course record.
@app.route('/admin/courses/<int:i>/edit', methods=['GET', 'POST'])
@role('admin')
def course_edit(i):
    spec = [('code', 'Course code', 'text', None), ('name', 'Course name', 'text', None), ('description', 'Description', 'textarea', None),
            ('status', 'Status', 'select', [('Active', 'Active'), ('Inactive', 'Inactive')])]
    return form('Course', spec, url_for('courses'), 'courses', i, row=q('select * from courses where id=?', (i,), one=True) if i else None)
# Delete a course by ID.
@app.post('/admin/courses/<int:i>/delete')
@role('admin')
def course_del(i): return delete('courses', i)

# List examinations and their administrative actions.
@app.route('/admin/exams')
@role('admin')
def exams():
    rows = []
    for e in q('select e.*, c.name cname from exams e join courses c on c.id=e.course_id'):
        s = lambda l, st: A(l, url_for('exam_status', i=e['id'], s=st), 'primary')
        rows.append(R([e['id'], e['name'], e['cname'], e['type'], e['max_marks'], e['status'], f"{e['sc_start']} → {e['sc_end']}", f"{e['sb_start']} → {e['sb_end']}", 'Yes' if e['published'] else 'No'],
                      A('Edit', url_for('exam_edit', i=e['id']), get=True), A('Rubrics', url_for('rubrics', e=e['id']), get=True), A('Examiners', url_for('exam_examiners', i=e['id']), get=True),
                      s('Open slot creation', 'Slot Creation'), s('Open booking', 'Booking Open'), s('Close', 'Closed'), s('Complete', 'Completed'),
                      A('Unpublish' if e['published'] else 'Publish results', url_for('exam_publish', i=e['id']), 'success'), A('Delete', url_for('exam_del', i=e['id']), 'danger')))
    return page('Examinations', [T('', ['ID', 'Name', 'Course', 'Type', 'Max', 'Status', 'Slot creation', 'Booking', 'Published'], rows)], top=[('Add examination', url_for('exam_edit', i=0))])
# Create or edit an examination configuration.
@app.route('/admin/exams/<int:i>/edit', methods=['GET', 'POST'])
@role('admin')
def exam_edit(i):
    spec = [('course_id', 'Course', 'select', [(c['id'], f"{c['code']} - {c['name']}") for c in q('select * from courses')]), ('name', 'Examination name', 'text', None),
            ('type', 'Type', 'select', [(t, t) for t in TYPES]), ('duration', 'Duration (minutes)', 'number', None), ('max_marks', 'Maximum marks', 'number', None),
            ('sc_start', 'Slot creation start', 'date', None), ('sc_end', 'Slot creation end', 'date', None), ('sb_start', 'Booking start', 'date', None),
            ('sb_end', 'Booking end', 'date', None), ('status', 'Status', 'select', [(s, s) for s in STATUSES])]
    def check(f):
        if f['sc_start'] > f['sc_end'] or f['sb_start'] > f['sb_end']: return 'End date must not be before start date'
        if float(f['max_marks']) <= 0 or int(f['duration']) <= 0: return 'Marks and duration must be positive'
    return form('Examination', spec, url_for('exams'), 'exams', i, row=q('select * from exams where id=?', (i,), one=True) if i else None, check=check)
# Delete an examination and its dependent records.
@app.post('/admin/exams/<int:i>/delete')
@role('admin')
def exam_del(i): return delete('exams', i)
# Change an examination lifecycle status.
@app.post('/admin/exams/<int:i>/status/<s>')
@role('admin')
def exam_status(i, s):
    if s in STATUSES: x('update exams set status=? where id=?', (s, i)); flash(f'Status set to {s}', 'success')
    return redirect(url_for('exams'))
# Toggle whether completed examination results are published.
@app.post('/admin/exams/<int:i>/publish')
@role('admin')
def exam_publish(i):
    x('update exams set published=1-published where id=?', (i,)); return redirect(url_for('exams'))
# List approved examiners and show their assignment status for an exam.
@app.route('/admin/exams/<int:i>/examiners')
@role('admin')
def exam_examiners(i):
    rows = []
    for u in q("select * from users where role='examiner' and status='approved'"):
        a = q('select 1 from exam_examiners where exam_id=? and examiner_id=?', (i, u['id']), one=True)
        rows.append(R([u['id'], u['name'], u['department'], 'Assigned' if a else '-'], A('Unassign' if a else 'Assign', url_for('exam_assign', i=i, u=u['id']), 'warning' if a else 'primary')))
    return page('Assign examiners', [T('', ['ID', 'Name', 'Department', 'Assigned'], rows)], top=[('Back', url_for('exams'))])
# Toggle an examiner assignment for an examination.
@app.post('/admin/exams/<int:i>/assign/<int:u>')
@role('admin')
def exam_assign(i, u):
    if q('select 1 from exam_examiners where exam_id=? and examiner_id=?', (i, u), one=True): x('delete from exam_examiners where exam_id=? and examiner_id=?', (i, u))
    else: x('insert into exam_examiners values(?,?)', (i, u))
    return redirect(url_for('exam_examiners', i=i))
# List the rubric criteria for an examination.
@app.route('/admin/exams/<int:e>/rubrics')
@role('admin')
def rubrics(e):
    rs = q('select * from rubrics where exam_id=?', (e,))
    rows = [R([r['id'], r['name'], r['max_marks'], r['weightage'], r['description']], A('Edit', url_for('rubric_edit', e=e, i=r['id']), get=True), A('Delete', url_for('rubric_del', i=r['id']), 'danger')) for r in rs]
    return page(f'Rubrics (total max {sum(r["max_marks"] for r in rs)}, weightage {sum(r["weightage"] for r in rs)})', [T('', ['ID', 'Criterion', 'Max marks', 'Weightage', 'Description'], rows)],
                top=[('Add criterion', url_for('rubric_edit', e=e, i=0)), ('Back', url_for('exams'))])
# Create or edit a rubric criterion for an examination.
@app.route('/admin/exams/<int:e>/rubrics/<int:i>/edit', methods=['GET', 'POST'])
@role('admin')
def rubric_edit(e, i):
    spec = [('name', 'Criterion name', 'text', None), ('max_marks', 'Maximum marks', 'number', None), ('weightage', 'Weightage (%)', 'number', None), ('description', 'Description', 'textarea', None)]
    return form('Rubric criterion', spec, url_for('rubrics', e=e), 'rubrics', i, row=q('select * from rubrics where id=?', (i,), one=True) if i else None, fixed={'exam_id': e})
# Delete a rubric criterion.
@app.post('/admin/rubrics/<int:i>/delete')
@role('admin')
def rubric_del(i): return delete('rubrics', i)

# List examiners and provide approval or deactivation actions.
@app.route('/admin/examiners')
@role('admin')
def admin_examiners():
    rows = []
    for u in q("select * from users where role='examiner'"):
        act = [A('Deactivate', url_for('set_user', i=u['id'], s='inactive'), 'danger')] if u['status'] == 'approved' else [A('Approve', url_for('set_user', i=u['id'], s='approved'), 'success')]
        rows.append(R([u['id'], u['name'], u['email'], u['department'], u['phone'], u['status']], *act))
    return page('Examiners', [T('', ['ID', 'Name', 'Email', 'Department', 'Phone', 'Status'], rows)], top=[('Add examiner', url_for('add_examiner'))])
# Approve or deactivate an examiner account.
@app.post('/admin/users/<int:i>/<s>')
@role('admin')
def set_user(i, s):
    if s in ('approved', 'inactive'): x("update users set status=? where id=? and role='examiner'", (s, i))
    return redirect(url_for('admin_examiners'))
# Add an examiner account directly as approved.
@app.route('/admin/examiners/new', methods=['GET', 'POST'])
@role('admin')
def add_examiner():
    if request.method == 'POST':
        err = make_user(request.form, 'examiner', 'approved')
        if err: flash(err, 'danger')
        else: return redirect(url_for('admin_examiners'))
    return rt('form.html', title='Add examiner', fields=F(UF))
# List registered student accounts.
@app.route('/admin/students')
@role('admin')
def admin_students():
    rows = [R([u['id'], u['name'], u['email'], u['ref_no'], u['department']]) for u in q("select * from users where role='student'")]
    return page('Students', [T('', ['ID', 'Name', 'Email', 'Student ID', 'Department'], rows)])
# List all examination slots and their assigned examiners.
@app.route('/admin/slots')
@role('admin')
def admin_slots():
    rows = [R([s['id'], s['ename'], s['xname'], s['date'], f"{s['start_time']}-{s['end_time']}", f"{s['capacity'] - s['available']}/{s['capacity']}", s['status']], A('Change examiner', url_for('change_examiner', i=s['id']), get=True))
            for s in q('select s.*, e.name ename, u.name xname from slots s join exams e on e.id=s.exam_id join users u on u.id=s.examiner_id order by date')]
    return page('All examination slots', [T('', ['ID', 'Exam', 'Examiner', 'Date', 'Time', 'Booked', 'Status'], rows)])
# Reassign a slot to a different approved examiner.
@app.route('/admin/slots/<int:i>/examiner', methods=['GET', 'POST'])
@role('admin')
def change_examiner(i):
    s = q('select * from slots where id=?', (i,), one=True) or abort(404)
    if request.method == 'POST':
        x('update slots set examiner_id=? where id=?', (request.form['examiner_id'], i))
        x('insert or ignore into exam_examiners values(?,?)', (s['exam_id'], request.form['examiner_id']))
        flash('Examiner changed', 'success'); return redirect(url_for('admin_slots'))
    spec = [('examiner_id', 'New examiner', 'select', [(u['id'], u['name']) for u in q("select * from users where role='examiner' and status='approved'")])]
    return rt('form.html', title='Change assigned examiner', fields=F(spec, s))
BK = ("select b.*, u.name sname, u.ref_no, e.name ename, e.max_marks, e.published, e.sb_end, s.date, s.start_time, s.end_time, s.examiner_id, x.name xname "
      "from bookings b join users u on u.id=b.student_id join exams e on e.id=b.exam_id join slots s on s.id=b.slot_id join users x on x.id=s.examiner_id")
# List every student booking and available rescheduling actions.
@app.route('/admin/bookings')
@role('admin')
def admin_bookings():
    rows = [R([b['id'], b['sname'], b['ename'], b['xname'], b['date'], f"{b['start_time']}-{b['end_time']}", b['status'], b['marks']],
              *([A('Reschedule', url_for('reschedule', i=b['id']), get=True)] if b['status'] == 'Booked' else [])) for b in q(BK + ' order by b.id desc')]
    return page('All bookings', [T('', ['ID', 'Student', 'Exam', 'Examiner', 'Date', 'Time', 'Status', 'Marks'], rows)])
# Move an active booking to another available slot.
@app.route('/admin/bookings/<int:i>/reschedule', methods=['GET', 'POST'])
@role('admin')
def reschedule(i):
    b = q('select * from bookings where id=?', (i,), one=True) or abort(404)
    if request.method == 'POST':
        new = q("select * from slots where id=? and exam_id=? and available>0 and status='Available'", (request.form['slot_id'], b['exam_id']), one=True)
        if not new or new['id'] == b['slot_id']: flash('Choose a different slot with free seats', 'danger')
        else:
            x("update slots set available=available+1, status='Available' where id=? and status='Full'", (b['slot_id'],))
            x("update slots set available=available+1 where id=? and status='Available'", (b['slot_id'],))
            x("update slots set available=available-1, status=case when available-1<=0 then 'Full' else status end where id=?", (new['id'],))
            x('update bookings set slot_id=? where id=?', (new['id'], i)); flash('Booking rescheduled', 'success'); return redirect(url_for('admin_bookings'))
    opts = [(s['id'], f"{s['date']} {s['start_time']}-{s['end_time']} ({s['xname']}, {s['available']} free)") for s in
            q("select s.*, u.name xname from slots s join users u on u.id=s.examiner_id where exam_id=? and available>0 and status='Available' and id!=?", (b['exam_id'], b['slot_id']))]
    return rt('form.html', title='Reschedule booking', fields=F([('slot_id', 'New slot', 'select', opts)]))

# ---------- examiner ----------
# Display the examiner dashboard and assigned-exam summary.
@app.route('/examiner')
@role('examiner')
def examiner_home():
    me = cur()['id']
    cards = [('Assigned exams', n('select count(*) from exam_examiners where examiner_id=?', (me,))), ('Slots created', n('select count(*) from slots where examiner_id=?', (me,))),
             ('Students booked', n("select count(*) from bookings b join slots s on s.id=b.slot_id where s.examiner_id=? and b.status!='Cancelled'", (me,))),
             ('Pending evaluations', n("select count(*) from bookings b join slots s on s.id=b.slot_id where s.examiner_id=? and b.status='Booked'", (me,)))]
    rows = [R([e['name'], e['type'], e['status'], f"{e['sc_start']} → {e['sc_end']}", 'Yes' if can_create(e) else 'No']) for e in
            q('select e.* from exams e join exam_examiners x on x.exam_id=e.id where x.examiner_id=?', (me,))]
    return page('Examiner Dashboard', [T('Assigned examinations', ['Exam', 'Type', 'Status', 'Slot creation window', 'Can create slots now'], rows)], cards, top=[('Create slot', url_for('slot_edit', i=0)), ('My slots', url_for('my_slots'))])
# List slots created by the current examiner.
@app.route('/examiner/slots')
@role('examiner')
def my_slots():
    rows = []
    for s in q('select s.*, e.name ename, e.status est from slots s join exams e on e.id=s.exam_id where examiner_id=? order by date', (cur()['id'],)):
        act = [A('Students', url_for('slot_students', i=s['id']), get=True)]
        if s['est'] in ('Draft', 'Slot Creation'): act += [A('Edit', url_for('slot_edit', i=s['id']), get=True), A('Delete', url_for('slot_del', i=s['id']), 'danger')]
        rows.append(R([s['id'], s['ename'], s['date'], f"{s['start_time']}-{s['end_time']}", f"{s['capacity'] - s['available']}/{s['capacity']}", s['status']], *act))
    return page('My slots', [T('', ['ID', 'Exam', 'Date', 'Time', 'Booked', 'Status'], rows)], top=[('Create slot', url_for('slot_edit', i=0))])
# Create or edit a slot for an assigned examination.
@app.route('/examiner/slots/<int:i>/edit', methods=['GET', 'POST'])
@role('examiner')
def slot_edit(i):
    me = cur()['id']; s = q('select * from slots where id=?', (i,), one=True) if i else None
    if s and s['examiner_id'] != me: abort(403)
    if s and q('select status from exams where id=?', (s['exam_id'],), one=True)[0] not in ('Draft', 'Slot Creation'):
        flash('Slots cannot be changed once booking has started', 'warning'); return redirect(url_for('my_slots'))
    ex = [e for e in q('select e.* from exams e join exam_examiners x on x.exam_id=e.id where x.examiner_id=?', (me,)) if can_create(e) or (s and e['id'] == s['exam_id'])]
    spec = [('exam_id', 'Examination', 'select', [(e['id'], e['name']) for e in ex]), ('date', 'Date', 'date', None), ('start_time', 'Start time', 'time', None),
            ('end_time', 'End time', 'time', None), ('capacity', 'Max students', 'number', None)]
    if request.method == 'POST':
        f = request.form; err = None
        try: eid = int(f['exam_id']); cap = int(f['capacity'])
        except (ValueError, KeyError): eid = cap = 0; err = 'Invalid input'
        booked = n("select count(*) from bookings where slot_id=? and status!='Cancelled'", (i,)) if s else 0
        if not err:
            if eid not in [e['id'] for e in ex]: err = 'Slot creation is not open for this examination'
            elif f['end_time'] <= f['start_time']: err = 'End time must be after start time'
            elif cap < 1: err = 'Capacity must be at least 1'
            elif cap < booked: err = f'{booked} students are already booked'
            elif q('select 1 from slots where examiner_id=? and date=? and start_time<? and end_time>? and id!=?', (me, f['date'], f['end_time'], f['start_time'], i), one=True): err = 'Overlaps with another of your slots'
        if err: flash(err, 'danger')
        else:
            av = cap - booked
            if s: x('update slots set exam_id=?,date=?,start_time=?,end_time=?,capacity=?,available=?,status=? where id=?', (eid, f['date'], f['start_time'], f['end_time'], cap, av, 'Full' if av == 0 else 'Available', i))
            else: x('insert into slots(exam_id,examiner_id,date,start_time,end_time,capacity,available) values(?,?,?,?,?,?,?)', (eid, me, f['date'], f['start_time'], f['end_time'], cap, cap))
            flash('Slot saved', 'success'); return redirect(url_for('my_slots'))
    return rt('form.html', title='Examination slot', fields=F(spec, s))
# Delete an examiner-owned slot before booking begins.
@app.post('/examiner/slots/<int:i>/delete')
@role('examiner')
def slot_del(i):
    s = q('select s.*, e.status est from slots s join exams e on e.id=s.exam_id where s.id=?', (i,), one=True) or abort(404)
    if s['examiner_id'] != cur()['id']: abort(403)
    if s['est'] not in ('Draft', 'Slot Creation'): flash('Booking already started', 'warning'); return redirect(url_for('my_slots'))
    return delete('slots', i)
# List students booked into a specific slot.
@app.route('/examiner/slots/<int:i>/students')
@role('examiner')
def slot_students(i):
    if not q('select 1 from slots where id=? and examiner_id=?', (i, cur()['id']), one=True): abort(403)
    rows = [R([b['id'], b['sname'], b['ref_no'], b['status'], b['marks'], b['remarks']], *([A('Evaluate', url_for('evaluate', b=b['id']), 'primary', get=True)] if b['status'] != 'Cancelled' else []))
            for b in q(BK + ' where b.slot_id=?', (i,))]
    return page('Booked students', [T('', ['Booking', 'Student', 'Student ID', 'Status', 'Marks', 'Remarks'], rows)], top=[('Back', url_for('my_slots'))])
# Evaluate a student booking using rubric or direct marks.
@app.route('/examiner/evaluate/<int:b>', methods=['GET', 'POST'])
@role('examiner')
def evaluate(b):
    bk = q(BK + ' where b.id=? and s.examiner_id=? and b.status!=\'Cancelled\'', (b, cur()['id']), one=True) or abort(403)
    rs = q('select * from rubrics where exam_id=?', (bk['exam_id'],))
    old = {r['rubric_id']: r['marks'] for r in q('select * from scores where booking_id=?', (b,))}
    if rs: spec = [(f"r{r['id']}", f"{r['name']} (max {r['max_marks']}, weight {r['weightage']}%)", 'number', None) for r in rs]
    else: spec = [('total', f"Total marks (max {bk['max_marks']})", 'number', None)]
    spec.append(('remarks', 'Remarks', 'textarea', None))
    if request.method == 'POST':
        f = request.form; err = None; got = {}
        try:
            for r in rs:
                got[r['id']] = float(f[f"r{r['id']}"])
                if not 0 <= got[r['id']] <= r['max_marks']: err = f"{r['name']}: marks must be between 0 and {r['max_marks']}"
            if not rs:
                total = float(f['total'])
                if not 0 <= total <= bk['max_marks']: err = f"Marks must be between 0 and {bk['max_marks']}"
        except (ValueError, KeyError): err = 'Enter valid numbers'
        if err: flash(err, 'danger')
        else:
            if rs:
                w = sum(r['weightage'] for r in rs)
                total = round(sum(got[r['id']] / r['max_marks'] * r['weightage'] for r in rs) / w * bk['max_marks'], 2) if w > 0 else sum(got.values())
                x('delete from scores where booking_id=?', (b,))
                for k, v in got.items(): x('insert into scores values(?,?,?)', (b, k, v))
            x("update bookings set marks=?, remarks=?, evaluated=1, status='Completed' where id=?", (total, f['remarks'].strip(), b))
            if not n("select count(*) from bookings where slot_id=? and status='Booked'", (bk['slot_id'],)): x("update slots set status='Completed' where id=?", (bk['slot_id'],))
            flash('Evaluation submitted', 'success'); return redirect(url_for('slot_students', i=bk['slot_id']))
    row = {f'r{k}': v for k, v in old.items()}; row.update(total=bk['marks'], remarks=bk['remarks'])
    fields = F(spec, row)
    for fl in fields:
        if fl['type'] == 'number': fl['extra'] = 'min=0 step=any'
    return rt('form.html', title=f"Evaluate {bk['sname']} – {bk['ename']}", fields=fields)

# ---------- student ----------
# Display upcoming examinations and published results for the student.
@app.route('/student')
@role('student')
def student_home():
    me = cur()['id']
    up = [R([b['ename'], b['date'], f"{b['start_time']}-{b['end_time']}", b['xname'], b['status']]) for b in q(BK + " where b.student_id=? and b.status='Booked' order by s.date", (me,))]
    res = [R([b['ename'], f"{b['marks']}/{b['max_marks']}", b['remarks']]) for b in q(BK + ' where b.student_id=? and b.evaluated=1 and e.published=1', (me,))]
    av = [e for e in q('select * from exams') if can_book(e)]
    cards = [('Exams open for booking', len(av)), ('Available slots', sum(n("select count(*) from slots where exam_id=? and available>0 and status='Available'", (e['id'],)) for e in av)),
             ('Upcoming', len(up)), ('Published results', len(res))]
    return page('Student Dashboard', [T('Upcoming / booked examinations', ['Exam', 'Date', 'Time', 'Examiner', 'Status'], up), T('Published results', ['Exam', 'Marks', 'Remarks'], res)],
                cards, top=[('Browse exams', url_for('student_exams')), ('History', url_for('student_bookings')), ('Edit profile', url_for('profile'))])
# Search and browse examinations available for booking.
@app.route('/student/exams')
@role('student')
def student_exams():
    s = request.args.get('q', '').strip(); t = request.args.get('type', '')
    rows = [R([e['name'], e['cname'], e['type'], e['duration'], e['max_marks'], e['status'], f"{e['sb_start']} → {e['sb_end']}"], A('View slots', url_for('student_exam', i=e['id']), 'primary', get=True))
            for e in q("select e.*, c.name cname from exams e join courses c on c.id=e.course_id where e.status!='Draft' and (e.name like ? or c.name like ? or c.code like ?) and (?='' or e.type=?)", (f'%{s}%',) * 3 + (t, t))]
    return page('Examinations', [T('', ['Exam', 'Course', 'Type', 'Mins', 'Max marks', 'Status', 'Booking window'], rows)], search=s, sel=('type', t, TYPES))
# Show available slots for one examination.
@app.route('/student/exams/<int:i>')
@role('student')
def student_exam(i):
    e = q('select * from exams where id=?', (i,), one=True) or abort(404)
    rows = [R([s['id'], s['date'], f"{s['start_time']}-{s['end_time']}", s['xname'], s['available'], s['status']], *([A('Book', url_for('book', sid=s['id']), 'success')] if can_book(e) and s['status'] == 'Available' else []))
            for s in q('select s.*, u.name xname from slots s join users u on u.id=s.examiner_id where exam_id=? order by date', (i,))]
    if not can_book(e): flash('Booking is currently closed for this examination', 'warning')
    return page(e['name'] + ' – slots', [T('', ['Slot', 'Date', 'Time', 'Examiner', 'Free seats', 'Status'], rows)], top=[('Back', url_for('student_exams'))])
# Create a student booking for an available slot.
@app.post('/student/book/<int:sid>')
@role('student')
def book(sid):
    me = cur()['id']; s = q('select * from slots where id=?', (sid,), one=True) or abort(404)
    e = q('select * from exams where id=?', (s['exam_id'],), one=True)
    if not can_book(e): flash('Booking is not open', 'danger')
    elif q("select 1 from bookings where student_id=? and exam_id=? and status in ('Booked','Completed')", (me, e['id']), one=True): flash('You already have a booking for this examination', 'danger')
    elif s['status'] != 'Available' or s['available'] < 1: flash('Slot is full', 'danger')
    else:
        x("update slots set available=available-1, status=case when available-1<=0 then 'Full' else status end where id=?", (sid,))
        x('insert into bookings(student_id,slot_id,exam_id,booked_at) values(?,?,?,?)', (me, sid, e['id'], today()))
        flash('Slot booked', 'success'); return redirect(url_for('student_bookings'))
    return redirect(url_for('student_exam', i=e['id']))
# Show a student's booking history and published scorecards.
@app.route('/student/bookings')
@role('student')
def student_bookings():
    rows = []
    for b in q(BK + ' where b.student_id=? order by b.id desc', (cur()['id'],)):
        act = [A('Cancel', url_for('cancel', b=b['id']), 'danger')] if b['status'] == 'Booked' and today() <= b['sb_end'] else []
        if b['evaluated'] and b['published']: act.append(A('Scorecard', url_for('scorecard', b=b['id']), get=True))
        rows.append(R([b['id'], ' ' + b['ename'], b['date'], f"{b['start_time']}-{b['end_time']}", b['xname'], b['booked_at'], b['status'],
                       f"{b['marks']}/{b['max_marks']}" if b['evaluated'] and b['published'] else '-', b['remarks'] if b['evaluated'] and b['published'] else ''], *act))
    return page('Booking history', [T('', ['ID', 'Exam', 'Date', 'Time', 'Examiner', 'Booked on', 'Status', 'Result', 'Feedback'], rows)])
# Cancel an active student booking and restore slot capacity.
@app.post('/student/cancel/<int:b>')
@role('student')
def cancel(b):
    bk = q(BK + ' where b.id=? and b.student_id=?', (b, cur()['id']), one=True) or abort(404)
    if bk['status'] != 'Booked' or today() > bk['sb_end']: flash('Cannot cancel after the booking deadline', 'danger')
    else:
        x("update bookings set status='Cancelled' where id=?", (b,))
        x("update slots set available=available+1, status='Available' where id=? and status in ('Available','Full')", (bk['slot_id'],))
        flash('Booking cancelled', 'info')
    return redirect(url_for('student_bookings'))
# Download a published scorecard as a text file.
@app.route('/student/scorecard/<int:b>')
@role('student')
def scorecard(b):
    bk = q(BK + ' where b.id=? and b.student_id=? and b.evaluated=1 and e.published=1', (b, cur()['id']), one=True) or abort(404)
    lines = [f"SCORECARD - {bk['ename']}", f"Student: {bk['sname']} ({bk['ref_no']})", f"Examiner: {bk['xname']}  Date: {bk['date']}", '']
    lines += [f"{r['name']}: {r['marks']}/{r['max_marks']}" for r in q('select r.name, r.max_marks, s.marks from scores s join rubrics r on r.id=s.rubric_id where s.booking_id=?', (b,))]
    lines += [f"TOTAL: {bk['marks']}/{bk['max_marks']}", f"Remarks: {bk['remarks']}"]
    return Response('\n'.join(lines), mimetype='text/plain', headers={'Content-Disposition': f'attachment; filename=scorecard_{b}.txt'})

# ---------- JSON API (admin) ----------
# Return a selected application collection as admin-only JSON.
@app.route('/api/<what>')
@role('admin')
def api(what):
    qs = {'courses': 'select * from courses', 'exams': 'select * from exams', 'slots': 'select * from slots', 'bookings': 'select * from bookings',
          'examiners': "select id,name,email,department,status from users where role='examiner'", 'students': "select id,name,email,ref_no from users where role='student'"}
    if what not in qs: abort(404)
    return jsonify([dict(r) for r in q(qs[what])])

init_db()
if __name__ == '__main__':
    app.run(debug=True)
