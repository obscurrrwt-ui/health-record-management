import csv, io, os, sqlite3, uuid
from datetime import date, timedelta
from functools import wraps
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   Response, send_from_directory, session, url_for)

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "health.db")
UPLOADS = os.path.join(BASE, "uploads")
ALLOWED = {"pdf", "png", "jpg", "jpeg"}
STATUSES = ("Active", "Follow-up", "Resolved")

app = Flask(__name__)
app.secret_key = "change-me-for-real-use"
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
os.makedirs(UPLOADS, exist_ok=True)

# ---------- database helpers ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()

def q(sql, args=(), one=False):
    rows = db().execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows

def run(sql, args=()):
    cur = db().execute(sql, args)
    db().commit()
    return cur.lastrowid

# ---------- filters and context ----------
def today():
    return date.today().isoformat()

@app.template_filter("age")
def age(dob):
    d, t = date.fromisoformat(dob), date.today()
    return t.year - d.year - ((t.month, t.day) < (d.month, d.day))

@app.template_filter("d")
def fmt_date(v):
    return date.fromisoformat(v[:10]).strftime("%d %b %Y") if v else "—"

app.jinja_env.filters["pt"] = lambda i: f"PT-{i:04d}"
app.jinja_env.filters["rc"] = lambda i: f"REC-{i:04d}"
app.jinja_env.filters["dc"] = lambda i: f"DR-{i:04d}"

@app.context_processor
def ctx():
    role, uid, who = session.get("role"), session.get("uid"), None
    if role == "admin":
        who = "Administrator"
    elif role == "doctor":
        x = q("SELECT name FROM doctors WHERE id=?", (uid,), True)
        who = "Dr. " + x["name"] if x else None
    elif role == "patient":
        x = q("SELECT name FROM patients WHERE id=?", (uid,), True)
        who = x["name"] if x else None
    return dict(who=who, today=today(), statuses=STATUSES)

def role_required(r):
    def deco(f):
        @wraps(f)
        def wrap(*a, **k):
            if session.get("role") != r:
                flash("Please choose a role first.", "error")
                return redirect(url_for("home"))
            return f(*a, **k)
        return wrap
    return deco

# ---------- errors ----------
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(400)
@app.errorhandler(500)
def error(e):
    code = getattr(e, "code", 500)
    msg = {403: "You are not allowed to open this.", 404: "We could not find that page.",
           400: "That request did not look right."}.get(code, "Something went wrong on our side.")
    return render_template("error.html", code=code, msg=msg), code

@app.errorhandler(413)
def too_big(e):
    flash("That file is larger than 8 MB.", "error")
    return redirect(request.referrer or url_for("home"))

# ---------- home and role choice ----------
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/role/<r>")
def choose_role(r):
    if r == "admin":
        session.clear()
        session["role"] = "admin"
        return redirect(url_for("users"))
    if r == "doctor":
        people = q("""SELECT d.id, d.name, d.specialization AS sub, h.name AS extra
                      FROM doctors d JOIN hospitals h ON h.id = d.hospital_id ORDER BY d.name""")
    elif r == "patient":
        people = q("SELECT id, name, blood_group AS sub, phone AS extra FROM patients ORDER BY name")
    else:
        abort(404)
    return render_template("role_pick.html", r=r, people=people)

@app.post("/choose")
def choose():
    r, uid = request.form.get("role"), request.form.get("uid", type=int)
    table = {"doctor": "doctors", "patient": "patients"}.get(r)
    if not table or not q(f"SELECT 1 FROM {table} WHERE id=?", (uid,), True):
        abort(400)
    session.clear()
    session["role"], session["uid"] = r, uid
    return redirect(url_for("doctor_home" if r == "doctor" else "patient_home"))

# ---------- admin: users ----------
KINDS = {
    "doctor": ("doctors", ["name", "specialization", "hospital_id", "phone", "email"], ["name", "specialization", "hospital_id"]),
    "patient": ("patients", ["name", "dob", "gender", "blood_group", "phone", "address", "allergies", "emergency_contact"], ["name", "dob"]),
}

@app.route("/admin/users")
@role_required("admin")
def users():
    kind = request.args.get("kind", "doctor")
    if kind not in KINDS:
        abort(404)
    if kind == "doctor":
        rows = q("""SELECT d.*, h.name AS hospital FROM doctors d
                    JOIN hospitals h ON h.id = d.hospital_id ORDER BY d.name""")
    else:
        rows = q("SELECT * FROM patients ORDER BY name")
    return render_template("users.html", kind=kind, rows=rows)

@app.route("/admin/people/<kind>/new", methods=["GET", "POST"])
@app.route("/admin/people/<kind>/<int:uid>/edit", methods=["GET", "POST"])
@role_required("admin")
def user_form(kind, uid=None):
    if kind not in KINDS:
        abort(404)
    table, cols, need = KINDS[kind]
    item = q(f"SELECT * FROM {table} WHERE id=?", (uid,), True) if uid else None
    if uid and not item:
        abort(404)
    v = dict(item) if item else {}
    if request.method == "POST":
        v = {c: (request.form.get(c) or "").strip() or None for c in cols}
        missing = [c for c in need if not v[c]]
        if missing:
            flash("Please fill in: " + ", ".join(m.replace("_id", "").replace("_", " ") for m in missing) + ".", "error")
        else:
            try:
                if uid:
                    run(f"UPDATE {table} SET " + ",".join(f"{c}=?" for c in cols) + " WHERE id=?", [*v.values(), uid])
                else:
                    run(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", list(v.values()))
                flash("Saved.", "ok")
                return redirect(url_for("users", kind=kind))
            except sqlite3.IntegrityError:
                flash("That email address is already in use.", "error")
    hospitals = q("SELECT id, name FROM hospitals ORDER BY name")
    return render_template("user_form.html", kind=kind, v=v, uid=uid, hospitals=hospitals)

@app.post("/admin/people/<kind>/<int:uid>/delete")
@role_required("admin")
def user_delete(kind, uid):
    if kind not in KINDS:
        abort(404)
    try:
        run(f"DELETE FROM {KINDS[kind][0]} WHERE id=?", (uid,))
        flash("Deleted.", "ok")
    except sqlite3.IntegrityError:
        flash("This doctor still has patient records, so they cannot be deleted.", "error")
    return redirect(url_for("users", kind=kind))

# ---------- admin: hospitals ----------
@app.route("/admin/hospitals")
@role_required("admin")
def hospitals():
    rows = q("""SELECT h.*, (SELECT COUNT(*) FROM doctors WHERE hospital_id = h.id) AS docs
                FROM hospitals h ORDER BY h.name""")
    return render_template("hospitals.html", rows=rows)

@app.route("/admin/hospitals/new", methods=["GET", "POST"])
@app.route("/admin/hospitals/<int:hid>/edit", methods=["GET", "POST"])
@role_required("admin")
def hospital_form(hid=None):
    item = q("SELECT * FROM hospitals WHERE id=?", (hid,), True) if hid else None
    if hid and not item:
        abort(404)
    v = dict(item) if item else {}
    if request.method == "POST":
        v = {c: (request.form.get(c) or "").strip() or None for c in ("name", "city", "phone", "address")}
        if not v["name"] or not v["city"]:
            flash("Please fill in the name and city.", "error")
        else:
            if hid:
                run("UPDATE hospitals SET name=?, city=?, phone=?, address=? WHERE id=?",
                    (v["name"], v["city"], v["phone"], v["address"], hid))
            else:
                run("INSERT INTO hospitals(name, city, phone, address) VALUES(?,?,?,?)",
                    (v["name"], v["city"], v["phone"], v["address"]))
            flash("Saved.", "ok")
            return redirect(url_for("hospitals"))
    return render_template("hospital_form.html", v=v, hid=hid)

@app.post("/admin/hospitals/<int:hid>/delete")
@role_required("admin")
def hospital_delete(hid):
    try:
        run("DELETE FROM hospitals WHERE id=?", (hid,))
        flash("Deleted.", "ok")
    except sqlite3.IntegrityError:
        flash("Doctors are still linked to this hospital. Move or delete them first.", "error")
    return redirect(url_for("hospitals"))

# ---------- admin: reports ----------
@app.route("/admin/reports")
@role_required("admin")
def reports():
    start = request.args.get("start") or (date.today() - timedelta(days=180)).isoformat()
    end = request.args.get("end") or today()
    hosp = request.args.get("hospital", type=int)
    where, args = "r.visit_date >= ? AND r.visit_date <= ?", [start, end]
    if hosp:
        where += " AND d.hospital_id = ?"
        args.append(hosp)
    frm = f"FROM medical_records r JOIN doctors d ON d.id = r.doctor_id WHERE {where}"
    if request.args.get("csv"):
        rows = q(f"""SELECT r.id, r.visit_date, p.name AS patient, d.name AS doctor, r.diagnosis, r.status
                     FROM medical_records r JOIN doctors d ON d.id = r.doctor_id
                     JOIN patients p ON p.id = r.patient_id WHERE {where} ORDER BY r.visit_date""", args)
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Record", "Visit date", "Patient", "Doctor", "Diagnosis", "Status"])
        for r in rows:
            w.writerow([f"REC-{r['id']:04d}", r["visit_date"], r["patient"], r["doctor"], r["diagnosis"], r["status"]])
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=visit-report.csv"})
    data = dict(
        totals=q(f"SELECT COUNT(*) AS visits, COUNT(DISTINCT r.patient_id) AS patients {frm}", args, True),
        diagnoses=q(f"SELECT MIN(r.diagnosis) AS name, COUNT(*) AS n {frm} GROUP BY LOWER(r.diagnosis) ORDER BY n DESC LIMIT 8", args),
        by_status=q(f"SELECT r.status AS name, COUNT(*) AS n {frm} GROUP BY r.status ORDER BY n DESC", args),
        by_doctor=q(f"SELECT d.name AS name, COUNT(*) AS n {frm} GROUP BY d.id ORDER BY n DESC", args),
        by_month=q(f"SELECT strftime('%Y-%m', r.visit_date) AS name, COUNT(*) AS n {frm} GROUP BY name ORDER BY name", args),
    )
    return render_template("reports.html", start=start, end=end, hosp=hosp, data=data,
                           hospitals=q("SELECT id, name FROM hospitals ORDER BY name"))

# ---------- records ----------
def get_record(rid):
    r = q("""SELECT r.*, p.name AS pname, p.dob, p.allergies, p.blood_group, p.gender,
                    d.name AS dname, d.specialization, h.name AS hname
             FROM medical_records r JOIN patients p ON p.id = r.patient_id
             JOIN doctors d ON d.id = r.doctor_id JOIN hospitals h ON h.id = d.hospital_id
             WHERE r.id = ?""", (rid,), True)
    if not r:
        abort(404)
    role = session.get("role")
    if role is None or (role == "patient" and r["patient_id"] != session.get("uid")):
        abort(403)
    return r

def own_record(rid):
    r = get_record(rid)
    if r["doctor_id"] != session.get("uid"):
        abort(403)
    return r

@app.route("/records/<int:rid>")
def record_view(rid):
    r = get_record(rid)
    return render_template("record.html", r=r,
        rx=q("SELECT * FROM prescriptions WHERE record_id=? ORDER BY id", (rid,)),
        files=q("SELECT * FROM reports WHERE record_id=? ORDER BY id", (rid,)),
        can_edit=(session.get("role") == "doctor" and r["doctor_id"] == session.get("uid")))

@app.route("/records/<int:rid>/sheet")
def record_sheet(rid):
    r = get_record(rid)
    return render_template("sheet.html", r=r, rx=q("SELECT * FROM prescriptions WHERE record_id=? ORDER BY id", (rid,)))

@app.route("/doctor")
@role_required("doctor")
def doctor_home():
    uid, status = session["uid"], request.args.get("status", "")
    sql = """SELECT r.*, p.name AS pname FROM medical_records r JOIN patients p ON p.id = r.patient_id
             WHERE r.doctor_id = ?"""
    args = [uid]
    if status in STATUSES:
        sql += " AND r.status = ?"
        args.append(status)
    rows = q(sql + " ORDER BY r.visit_date DESC, r.id DESC", args)
    soon = (date.today() + timedelta(days=7)).isoformat()
    due = q("""SELECT r.*, p.name AS pname FROM medical_records r JOIN patients p ON p.id = r.patient_id
               WHERE r.doctor_id = ? AND r.status != 'Resolved' AND r.follow_up_date IS NOT NULL
               AND r.follow_up_date <= ? ORDER BY r.follow_up_date""", (uid, soon))
    return render_template("doctor.html", rows=rows, due=due, status=status)

def num(s, cast):
    s = (s or "").strip()
    return cast(s) if s else None

def save_record(rec):
    f = request.form
    v = dict(rec) if rec else {"visit_date": today(), "status": "Active", "patient_id": request.args.get("patient_id", type=int)}
    rx = q("SELECT * FROM prescriptions WHERE record_id=? ORDER BY id", (rec["id"],)) if rec else []
    if request.method == "POST":
        v = {k: (f.get(k) or "").strip() for k in
             ("visit_date", "complaint", "bp", "pulse", "temperature", "weight", "diagnosis", "notes", "status", "follow_up_date")}
        v["patient_id"] = rec["patient_id"] if rec else f.get("patient_id", type=int)
        rx = [dict(medicine=m.strip(), dosage=d.strip(), frequency=fr.strip(), duration=du.strip())
              for m, d, fr, du in zip(f.getlist("medicine"), f.getlist("dosage"), f.getlist("frequency"), f.getlist("duration"))
              if m.strip()]
        error = None
        if not v["patient_id"] or not q("SELECT 1 FROM patients WHERE id=?", (v["patient_id"],), True):
            error = "Choose a patient."
        elif not (v["visit_date"] and v["complaint"] and v["diagnosis"]):
            error = "Visit date, complaint and diagnosis are required."
        elif v["status"] not in STATUSES:
            error = "Choose a valid status."
        else:
            try:
                p, t, w = num(v["pulse"], int), num(v["temperature"], float), num(v["weight"], float)
            except ValueError:
                error = "Pulse, temperature and weight must be numbers."
        if error:
            flash(error, "error")
        else:
            vals = [v["visit_date"], v["complaint"], v["bp"] or None, p, t, w, v["diagnosis"],
                    v["notes"] or None, v["status"], v["follow_up_date"] or None]
            if rec:
                run("""UPDATE medical_records SET visit_date=?, complaint=?, bp=?, pulse=?, temperature=?, weight=?,
                       diagnosis=?, notes=?, status=?, follow_up_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    [*vals, rec["id"]])
                rid = rec["id"]
                run("DELETE FROM prescriptions WHERE record_id=?", (rid,))
            else:
                rid = run("""INSERT INTO medical_records(visit_date, complaint, bp, pulse, temperature, weight,
                             diagnosis, notes, status, follow_up_date, patient_id, doctor_id)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", [*vals, v["patient_id"], session["uid"]])
            for x in rx:
                run("INSERT INTO prescriptions(record_id, medicine, dosage, frequency, duration) VALUES(?,?,?,?,?)",
                    (rid, x["medicine"], x["dosage"] or None, x["frequency"] or None, x["duration"] or None))
            flash("Record saved.", "ok")
            return redirect(url_for("record_view", rid=rid))
    patients = q("SELECT id, name, dob, allergies FROM patients ORDER BY name")
    return render_template("record_form.html", v=v, rx=rx, rec=rec, patients=patients)

@app.route("/doctor/records/new", methods=["GET", "POST"])
@role_required("doctor")
def record_new():
    return save_record(None)

@app.route("/doctor/records/<int:rid>/edit", methods=["GET", "POST"])
@role_required("doctor")
def record_edit(rid):
    return save_record(own_record(rid))

@app.post("/doctor/records/<int:rid>/upload")
@role_required("doctor")
def upload(rid):
    own_record(rid)
    f, title = request.files.get("file"), (request.form.get("title") or "").strip()
    ext = f.filename.rsplit(".", 1)[-1].lower() if f and "." in f.filename else ""
    if not f or not f.filename:
        flash("Choose a file to upload.", "error")
    elif ext not in ALLOWED:
        flash("Only PDF, PNG and JPG files are accepted.", "error")
    else:
        name = uuid.uuid4().hex + "." + ext
        f.save(os.path.join(UPLOADS, name))
        run("INSERT INTO reports(record_id, title, filename, original_name) VALUES(?,?,?,?)",
            (rid, title or f.filename, name, os.path.basename(f.filename)))
        flash("Report uploaded.", "ok")
    return redirect(url_for("record_view", rid=rid))

@app.route("/reports/<int:fid>/download")
def download(fid):
    rep = q("SELECT * FROM reports WHERE id=?", (fid,), True)
    if not rep:
        abort(404)
    get_record(rep["record_id"])  # access check
    return send_from_directory(UPLOADS, rep["filename"], as_attachment=True, download_name=rep["original_name"])

# ---------- patient ----------
@app.route("/patient")
@role_required("patient")
def patient_home():
    uid, tab = session["uid"], request.args.get("tab", "records")
    p = q("SELECT * FROM patients WHERE id=?", (uid,), True)
    if not p:
        abort(404)
    recs = q("""SELECT r.*, d.name AS dname FROM medical_records r JOIN doctors d ON d.id = r.doctor_id
                WHERE r.patient_id = ? ORDER BY r.visit_date DESC, r.id DESC""", (uid,))
    rx = q("""SELECT x.*, r.visit_date FROM prescriptions x JOIN medical_records r ON r.id = x.record_id
              WHERE r.patient_id = ? ORDER BY r.visit_date DESC, x.id""", (uid,))
    files = q("""SELECT f.*, r.visit_date FROM reports f JOIN medical_records r ON r.id = f.record_id
                 WHERE r.patient_id = ? ORDER BY f.id DESC""", (uid,))
    soon = (date.today() + timedelta(days=7)).isoformat()
    due = [r for r in recs if r["status"] != "Resolved" and r["follow_up_date"] and r["follow_up_date"] <= soon]
    return render_template("patient.html", p=p, recs=recs, rx=rx, files=files, due=due, tab=tab)

# ---------- setup ----------
def seed(con):
    d = lambda n: (date.today() + timedelta(days=n)).isoformat()
    con.executemany("INSERT INTO hospitals(name, city, phone, address) VALUES(?,?,?,?)", [
        ("Riverside General Hospital", "Pune", "020 5550 1100", "14 River Road"),
        ("Lakeview Medical Centre", "Nashik", "0253 555 2200", "3 Lake Street"),
        ("St. Mary's Clinic", "Mumbai", "022 5550 3300", "88 Hill Lane")])
    con.executemany("INSERT INTO doctors(hospital_id, name, specialization, phone, email) VALUES(?,?,?,?,?)", [
        (1, "Anita Deshmukh", "General medicine", "98200 11111", "anita@example.com"),
        (1, "Rohan Kulkarni", "Cardiology", "98200 22222", "rohan@example.com"),
        (2, "Meera Iyer", "Paediatrics", "98200 33333", "meera@example.com"),
        (3, "Farhan Sheikh", "Orthopaedics", "98200 44444", "farhan@example.com")])
    con.executemany("""INSERT INTO patients(name, dob, gender, blood_group, phone, address, allergies, emergency_contact)
                       VALUES(?,?,?,?,?,?,?,?)""", [
        ("Sneha Patil", "1994-03-12", "Female", "B+", "99000 10001", "21 Garden Colony, Pune", "Penicillin", "Ravi Patil, 99000 20001"),
        ("Arjun Mehta", "1988-11-02", "Male", "O+", "99000 10002", "7 Park Avenue, Pune", None, "Nisha Mehta, 99000 20002"),
        ("Kavya Nair", "2015-06-25", "Female", "A+", "99000 10003", "5 Temple Road, Nashik", "Peanuts", "Suresh Nair, 99000 20003"),
        ("Imran Khan", "1975-01-30", "Male", "AB-", "99000 10004", "42 Market Street, Mumbai", "Sulfa drugs", "Zara Khan, 99000 20004"),
        ("Pooja Joshi", "2001-09-09", "Female", "O-", "99000 10005", "9 College Road, Pune", None, "Mohan Joshi, 99000 20005"),
        ("Devendra Rao", "1960-12-18", "Male", "B-", "99000 10006", "18 Sea View, Mumbai", "Aspirin", "Latha Rao, 99000 20006")])
    recs = [  # patient, doctor, days ago, complaint, bp, pulse, temp, wt, diagnosis, status, follow-up offset
        (1, 1, -50, "Fever and sore throat for three days", "118/76", 88, 38.4, 58, "Streptococcal pharyngitis", "Resolved", None),
        (1, 1, -6, "Recurring headaches", "122/80", 76, 36.8, 58, "Tension headache", "Follow-up", 3),
        (2, 2, -30, "Chest tightness on climbing stairs", "142/92", 84, 36.7, 82, "Stage 1 hypertension", "Follow-up", -2),
        (3, 3, -14, "Cough and runny nose", "100/65", 96, 37.6, 22, "Viral upper respiratory infection", "Active", None),
        (4, 4, -20, "Knee pain after a fall", "130/85", 78, 36.6, 79, "Medial collateral ligament sprain", "Follow-up", 5),
        (5, 1, -9, "Fatigue and dizziness", "104/68", 72, 36.5, 52, "Iron deficiency anaemia", "Active", 20),
        (6, 2, -3, "Palpitations at night", "150/94", 92, 36.9, 74, "Atrial fibrillation, under review", "Active", 6),
        (2, 1, -2, "Seasonal allergy symptoms", "126/82", 74, 36.6, 82, "Allergic rhinitis", "Active", None)]
    for i, (p, dr, ago, c, bp, pu, t, w, dx, st, fu) in enumerate(recs, 1):
        con.execute("""INSERT INTO medical_records(patient_id, doctor_id, visit_date, complaint, bp, pulse, temperature,
                       weight, diagnosis, status, follow_up_date) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (p, dr, d(ago), c, bp, pu, t, w, dx, st, d(fu) if fu is not None else None))
    con.executemany("INSERT INTO prescriptions(record_id, medicine, dosage, frequency, duration) VALUES(?,?,?,?,?)", [
        (1, "Azithromycin", "500 mg", "Once daily", "5 days"), (1, "Paracetamol", "500 mg", "Every 6 hours if needed", "3 days"),
        (2, "Ibuprofen", "200 mg", "Twice daily after food", "5 days"),
        (3, "Amlodipine", "5 mg", "Once daily", "30 days"),
        (4, "Saline nasal drops", "2 drops", "Three times daily", "5 days"), (4, "Paracetamol syrup", "5 ml", "Every 8 hours if needed", "3 days"),
        (5, "Diclofenac gel", "Thin layer", "Twice daily", "10 days"),
        (6, "Ferrous sulphate", "200 mg", "Once daily", "60 days"), (6, "Vitamin C", "500 mg", "Once daily", "60 days"),
        (7, "Metoprolol", "25 mg", "Twice daily", "14 days"),
        (8, "Cetirizine", "10 mg", "Once at night", "7 days")])
    con.commit()

def init_db():
    con = sqlite3.connect(DB)
    if not con.execute("SELECT name FROM sqlite_master WHERE name='hospitals'").fetchone():
        with open(os.path.join(BASE, "schema.sql")) as fh:
            con.executescript(fh.read())
        seed(con)
    con.close()

init_db()

if __name__ == "__main__":
    app.run(debug=True)
