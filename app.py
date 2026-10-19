import os, io, csv, sqlite3, secrets, hashlib, hmac, json
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, redirect, url_for, session, flash, send_file, render_template_string, abort
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import cv2
import numpy as np
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from openpyxl import Workbook

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("OMR_DB_PATH", os.path.join(APP_DIR, "omr.sqlite3"))
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED = {"png", "jpg", "jpeg", "webp", "pdf"}
app = Flask(__name__)
app.secret_key = os.environ.get("OMR_SECRET_KEY") or secrets.token_hex(32)
app.config.update(MAX_CONTENT_LENGTH=15 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.environ.get("HTTPS_ONLY") == "1")

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','teacher')), active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS exams(id INTEGER PRIMARY KEY, title TEXT NOT NULL, question_count INTEGER NOT NULL,
          correct_marks REAL NOT NULL DEFAULT 1, wrong_marks REAL NOT NULL DEFAULT 0, blank_marks REAL NOT NULL DEFAULT 0,
          answer_key TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS results(id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id),
          roll TEXT NOT NULL, student_name TEXT NOT NULL DEFAULT '', answers TEXT NOT NULL, score REAL NOT NULL,
          correct INTEGER NOT NULL, wrong INTEGER NOT NULL, blank INTEGER NOT NULL, review INTEGER NOT NULL DEFAULT 0,
          image_name TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, UNIQUE(exam_id,roll));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, username TEXT, action TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        if c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"] == 0:
            # First-login credentials are printed once to server logs; change immediately.
            username = os.environ.get("OMR_ADMIN_USER", "admin")
            password = os.environ.get("OMR_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
            c.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                      (username, generate_password_hash(password), "admin"))
            print("\\n[FJMC OMR FIRST ADMIN] username:", username, " password:", password, "\\nChange this password after login.\\n")

def audit(action):
    with db() as c:
        c.execute("INSERT INTO audit(username,action,created_at) VALUES(?,?,?)",
                  (session.get("username","system"), action[:300], datetime.now(timezone.utc).isoformat()))

def login_required(fn):
    @wraps(fn)
    def inner(*a, **kw):
        if not session.get("uid"): return redirect(url_for("login"))
        return fn(*a, **kw)
    return inner

def roles(*allowed_roles):
    def deco(fn):
        @wraps(fn)
        def inner(*a, **kw):
            if not session.get("uid"): return redirect(url_for("login"))
            if session.get("role") not in allowed_roles: abort(403)
            return fn(*a, **kw)
        return inner
    return deco

def page(title, body):
    return render_template_string(BASE, title=title, body=body, user=session.get("username"), role=session.get("role"))

BASE = """
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{title}} | FJMC Academy Smart OMR</title>
<style>
:root{--red:#e63946;--ink:#17202a;--muted:#667085;--bg:#f5f7fb}*{box-sizing:border-box}
body{margin:0;font:15px system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--ink)}
header{background:#111827;color:white;padding:16px max(16px,calc((100% - 1100px)/2));display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap}
header b{font-size:18px}header a{color:white;text-decoration:none;margin-left:12px}
main{max-width:1100px;margin:24px auto;padding:0 16px}.card{background:white;border:1px solid #e4e7ec;border-radius:14px;padding:20px;margin-bottom:16px;box-shadow:0 2px 8px #10182808}
h1{font-size:26px;margin:0 0 14px}h2{font-size:19px;margin:0 0 14px}p{line-height:1.5}.muted{color:var(--muted)}label{display:block;font-weight:600;margin:10px 0 5px}
input,select,textarea{width:100%;padding:11px;border:1px solid #d0d5dd;border-radius:8px;background:white;font:inherit}
button,.btn{background:var(--red);color:white;border:0;border-radius:8px;padding:11px 15px;font:inherit;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}
.btn.secondary,button.secondary{background:#344054}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}
table{border-collapse:collapse;width:100%;background:white}th,td{padding:10px;text-align:left;border-bottom:1px solid #eaecf0}th{background:#f9fafb}
.notice{padding:12px;border-radius:8px;background:#fff4e5;margin:10px 0}.success{background:#ecfdf3}.bad{background:#fef3f2}
.pills{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.pill{background:#eef2ff;padding:6px 10px;border-radius:20px}
small{color:var(--muted)}footer{text-align:center;color:var(--muted);padding:25px}
@media(max-width:600px){main{margin:14px auto}.card{padding:15px}h1{font-size:22px}header a{margin-left:5px}}
</style></head><body><header><b>🔴 FJMC Academy <span style="color:#fda4af">Smart OMR</span></b>
<nav>{% if user %}<span>{{user}} · {{role}}</span><a href="{{url_for('dashboard')}}">Dashboard</a><a href="{{url_for('logout')}}">Logout</a>{% endif %}</nav></header>
<main>{% with messages=get_flashed_messages() %}{% for m in messages %}<div class="notice">{{m}}</div>{% endfor %}{% endwith %}{{body|safe}}</main>
<footer>FJMC Academy Smart OMR · Verify flagged readings before publishing results.</footer></body></html>
"""

@app.route("/")
def home():
    if session.get("uid"): return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        with db() as c:
            u = c.execute("SELECT * FROM users WHERE username=? AND active=1",(request.form.get("username",""),)).fetchone()
        if u and check_password_hash(u["password_hash"], request.form.get("password","")):
            session.clear(); session.update(uid=u["id"], username=u["username"], role=u["role"])
            audit("login"); return redirect(url_for("dashboard"))
        flash("Invalid username or password.")
    body = """<div class="card" style="max-width:460px;margin:40px auto"><h1>Secure sign in</h1>
    <p class="muted">Standalone OMR workspace. First admin credentials are printed in the server console on first run.</p>
    <form method="post"><label>Username</label><input name="username" required autocomplete="username">
    <label>Password</label><input type="password" name="password" required autocomplete="current-password">
    <p><button>Sign in</button></p></form></div>"""
    return page("Login", body)

@app.route("/logout")
@login_required
def logout():
    audit("logout"); session.clear(); return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    with db() as c:
        exams = c.execute("SELECT e.*, (SELECT COUNT(*) FROM results r WHERE r.exam_id=e.id) result_count FROM exams e ORDER BY id DESC").fetchall()
        total = c.execute("SELECT COUNT(*) n FROM results").fetchone()["n"]
        reviews = c.execute("SELECT COUNT(*) n FROM results WHERE review=1").fetchone()["n"]
    rows = "".join(f"<tr><td>{e['id']}</td><td>{e['title']}</td><td>{e['question_count']}</td><td>{e['result_count']}</td><td><a href='/exam/{e['id']}'>Open</a> · <a href='/exam/{e['id']}/results'>Results</a></td></tr>" for e in exams)
    body = f"""<h1>OMR Control Centre</h1><div class="pills"><span class="pill">Exams: {len(exams)}</span><span class="pill">Processed sheets: {total}</span><span class="pill">Need review: {reviews}</span></div>
    <div class="grid"><div class="card"><h2>Create an exam</h2><p class="muted">Set any question count, marking rules and answer key.</p><a class="btn" href="/exam/new">+ Create exam</a></div>
    <div class="card"><h2>Scan answer sheets</h2><p class="muted">Phone camera, photos, or scanner-produced images. Camera requires HTTPS on deployed websites.</p><a class="btn" href="/scan">Open scanner upload</a></div>
    <div class="card"><h2>Team accounts</h2><p class="muted">Admin can add teacher accounts.</p><a class="btn secondary" href="/users">Manage users</a></div></div>
    <div class="card"><h2>Exams</h2><div style="overflow:auto"><table><tr><th>ID</th><th>Exam</th><th>Questions</th><th>Sheets</th><th>Actions</th></tr>{rows or '<tr><td colspan=5>No exams yet.</td></tr>'}</table></div></div>"""
    return page("Dashboard", body)

@app.route("/exam/new", methods=["GET","POST"])
@roles("admin","teacher")
def exam_new():
    if request.method == "POST":
        title = request.form.get("title","").strip()
        try:
            n = int(request.form.get("question_count","0"))
            cm, wm, bm = float(request.form.get("correct_marks","1")), float(request.form.get("wrong_marks","0")), float(request.form.get("blank_marks","0"))
            key = [x.strip().upper() for x in request.form.get("answer_key","").replace("\\n",",").split(",") if x.strip()]
            if not title or not (1 <= n <= 300): raise ValueError()
            if len(key) != n or any(x not in "ABCD" for x in key): raise ValueError("Answer key must contain exactly one A/B/C/D entry per question, comma-separated.")
        except ValueError as ex:
            flash(str(ex) or "Check question count and marking values."); return redirect(url_for("exam_new"))
        with db() as c:
            cur = c.execute("INSERT INTO exams(title,question_count,correct_marks,wrong_marks,blank_marks,answer_key,created_at) VALUES(?,?,?,?,?,?,?)",
                (title,n,cm,wm,bm,json.dumps(key),datetime.now(timezone.utc).isoformat()))
            eid = cur.lastrowid
        audit(f"created exam {eid}"); flash("Exam created. Print the matching OMR template and use it for scanning.")
        return redirect(url_for("exam_detail", exam_id=eid))
    body = """<div class="card"><h1>Create OMR exam</h1><form method="post">
    <label>Exam name</label><input name="title" placeholder="CSIR NET Mathematics Mock Test 01" required>
    <div class="grid"><div><label>Number of questions (1–300)</label><input name="question_count" type="number" min="1" max="300" value="100" required></div>
    <div><label>Marks per correct answer</label><input name="correct_marks" type="number" step="0.25" value="2" required></div>
    <div><label>Marks per wrong answer (usually negative)</label><input name="wrong_marks" type="number" step="0.25" value="-0.5" required></div>
    <div><label>Marks per blank answer</label><input name="blank_marks" type="number" step="0.25" value="0" required></div></div>
    <label>Answer key (exactly N comma-separated answers)</label><textarea name="answer_key" rows="4" placeholder="A,C,B,D,A,..." required></textarea>
    <small>For 100 questions, enter 100 letters separated by commas. The app validates the count.</small><p><button>Create exam</button></p></form></div>"""
    return page("Create exam", body)

@app.route("/exam/<int:exam_id>")
@login_required
def exam_detail(exam_id):
    with db() as c: e = c.execute("SELECT * FROM exams WHERE id=?",(exam_id,)).fetchone()
    if not e: abort(404)
    body = f"""<div class="card"><h1>{e['title']}</h1><div class="pills"><span class="pill">{e['question_count']} questions</span><span class="pill">Correct: +{e['correct_marks']}</span><span class="pill">Wrong: {e['wrong_marks']}</span><span class="pill">Blank: {e['blank_marks']}</span></div>
    <p><a class="btn" href="/template/{exam_id}">Download printable OMR sheet PDF</a> <a class="btn secondary" href="/scan?exam_id={exam_id}">Scan sheets</a> <a class="btn secondary" href="/exam/{exam_id}/results">View results</a></p>
    <p class="notice">This template uses fixed bubble coordinates for the built-in scanner. Print at 100% scale on A4 paper, do not resize, and test with a few sheets first. Name is handwritten; roll number is bubbled.</p></div>"""
    return page("Exam", body)

@app.route("/template/<int:exam_id>")
@login_required
def template_pdf(exam_id):
    with db() as c: e = c.execute("SELECT * FROM exams WHERE id=?",(exam_id,)).fetchone()
    if not e: abort(404)
    buf = io.BytesIO(); p = canvas.Canvas(buf, pagesize=A4); W,H=A4
    p.setTitle("FJMC Academy OMR Sheet")
    p.setFont("Helvetica-Bold",17); p.drawString(38,H-40,"FJMC ACADEMY — SMART OMR")
    p.setFont("Helvetica",9); p.drawString(38,H-57,e["title"])
    p.drawString(38,H-76,"Name (write clearly): ______________________________________________")
    p.drawString(38,H-94,"Roll number: fill one bubble per digit. Use digits 0–9.")
    # corner registration marks
    for x,y in [(24,H-24),(W-24,H-24),(24,24),(W-24,24)]:
        p.rect(x-4,y-4,8,8,fill=1)
    # Roll bubbles: 10 columns digits, 8 rows max. If roll longer, user can use max 8 digits.
    p.setFont("Helvetica-Bold",8); p.drawString(38,H-113,"ROLL DIGITS")
    x0=95; y0=H-127; dx=42; dy=13
    for col in range(8):
        p.drawCentredString(x0+col*dx,y0+5,str(col+1))
    for digit in range(10):
        yy=y0-13-digit*dy
        p.drawCentredString(55,yy-3,str(digit))
        for col in range(8):
            p.circle(x0+col*dx,yy,4.3,stroke=1,fill=0)
    p.setFont("Helvetica-Bold",10); p.drawString(38,H-290,"ANSWER SHEET")
    p.setFont("Helvetica",7); p.drawString(38,H-302,"Fill bubbles completely with dark pen/pencil. One answer per question. Do not fold or mark registration squares.")
    # Layout in 3 columns, row count adapts to page; for very large exams generate continuation pages.
    n=e["question_count"]; per_col=35; cols=3; per_page=per_col*cols
    q=1
    while q <= n:
        if q > 1:
            p.showPage()
            p.setFont("Helvetica-Bold",14); p.drawString(38,H-40,"FJMC ACADEMY — OMR CONTINUATION")
            p.setFont("Helvetica",9); p.drawString(38,H-57,f"{e['title']} · Questions {q}–{min(n,q+per_page-1)}")
        top=H-330 if q==1 else H-85
        for col in range(cols):
            xx=38+col*184
            p.setFont("Helvetica-Bold",8); p.drawString(xx,top+13,"Q No.      A        B        C        D")
            for row in range(per_col):
                if q>n: break
                yy=top-row*13
                p.setFont("Helvetica",7); p.drawRightString(xx+24,yy-3,str(q))
                for k in range(4):
                    p.circle(xx+49+k*34,yy,4.2,stroke=1,fill=0)
                q+=1
        p.setFont("Helvetica",7); p.drawString(38,22,"FJMC Academy Smart OMR · Keep all four corner registration marks visible.")
        p.showPage() if q<=n else None
    p.save(); buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=f"fjmc_omr_exam_{exam_id}.pdf")

@app.route("/scan", methods=["GET","POST"])
@roles("admin","teacher")
def scan():
    with db() as c: exams=c.execute("SELECT id,title,question_count FROM exams ORDER BY id DESC").fetchall()
    if request.method=="POST":
        exam_id=request.form.get("exam_id",type=int)
        files=request.files.getlist("sheets")
        if not exam_id or not files or all(not f.filename for f in files):
            flash("Select an exam and at least one image."); return redirect(url_for("scan"))
        with db() as c: e=c.execute("SELECT * FROM exams WHERE id=?",(exam_id,)).fetchone()
        if not e: abort(404)
        key=json.loads(e["answer_key"]); processed=0; errors=[]
        for f in files:
            if not f.filename: continue
            ext=f.filename.rsplit(".",1)[-1].lower() if "." in f.filename else ""
            if ext not in ALLOWED:
                errors.append(f"{f.filename}: unsupported file type"); continue
            if ext=="pdf":
                errors.append(f"{f.filename}: PDF upload is accepted as a scan source but automatic page extraction needs the optional Poppler/pdf2image dependency. Export PDF pages to JPG/PNG first.")
                continue
            raw=f.read()
            if len(raw)>12*1024*1024: errors.append(f"{f.filename}: file too large"); continue
            arr=np.frombuffer(raw,np.uint8); img=cv2.imdecode(arr,cv2.IMREAD_COLOR)
            if img is None: errors.append(f"{f.filename}: cannot read image"); continue
            try:
                result=read_sheet(img, e["question_count"])
                roll=result["roll"]; answers=result["answers"]; review=result["review"]
                correct=sum(1 for a,k in zip(answers,key) if a==k)
                wrong=sum(1 for a,k in zip(answers,key) if a not in ("",None) and a!=k)
                blank=sum(1 for a in answers if not a)
                score=correct*e["correct_marks"]+wrong*e["wrong_marks"]+blank*e["blank_marks"]
                if not roll: roll="REVIEW-"+secrets.token_hex(4).upper(); review=True
                name="" # Handwritten names are intentionally not guessed by OCR.
                fname=secure_filename(f.filename)[:100]
                with db() as c:
                    c.execute("""INSERT INTO results(exam_id,roll,student_name,answers,score,correct,wrong,blank,review,image_name,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(exam_id,roll) DO UPDATE SET student_name=excluded.student_name,answers=excluded.answers,score=excluded.score,correct=excluded.correct,wrong=excluded.wrong,blank=excluded.blank,review=excluded.review,image_name=excluded.image_name,created_at=excluded.created_at""",
                    (exam_id,roll,name,json.dumps(answers),score,correct,wrong,blank,int(review),fname,datetime.now(timezone.utc).isoformat()))
                processed+=1
            except Exception as ex:
                errors.append(f"{f.filename}: {str(ex)[:180]}")
        audit(f"scan exam={exam_id}; processed={processed}; errors={len(errors)}")
        flash(f"Processed {processed} sheet(s). Please review flagged readings before publishing.")
        for er in errors[:5]: flash(er)
        return redirect(url_for("exam_results",exam_id=exam_id))
    opts="".join(f'<option value="{e["id"]}" {"selected" if request.args.get("exam_id",type=int)==e["id"] else ""}>{e["title"]} ({e["question_count"]} Q)</option>' for e in exams)
    body=f"""<div class="card"><h1>Scan OMR sheets</h1><p class="muted">Use the generated FJMC PDF template. For phone scanning, open this site over HTTPS and choose camera capture. For physical machines, scan to JPG/PNG and bulk upload.</p>
    <form method="post" enctype="multipart/form-data"><label>Exam</label><select name="exam_id" required>{opts}</select>
    <label>Choose one or many OMR images</label><input type="file" name="sheets" accept="image/*" capture="environment" multiple required>
    <p><button>Scan selected sheets</button></p></form></div>
    <div class="card"><h2>Important calibration note</h2><p>The included recognizer is a baseline calibrated to the generated template's fixed coordinates. Different printers, camera angles, cropped images or third-party OMR forms may require alignment/calibration. Confirm sample sheets before a real exam.</p></div>"""
    return page("Scan sheets",body)

def read_sheet(img, n):
    # Template coordinate reader for the built-in A4 layout; assumes full-page image, not perspective-cropped.
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    h,w=gray.shape
    # Normalize to template A4 portrait pixel coordinate system 595x842.
    gray=cv2.resize(gray,(595,842))
    # Threshold dark pixels; compute filled ratio within inner bubble area.
    _,th=cv2.threshold(gray,150,255,cv2.THRESH_BINARY_INV)
    # Determine answers from 3 columns, 35 rows each per page. This reader expects one-page answer area.
    answers=[]; review=False
    # question area on first page: y top approx 512px; columns x positions and answer centers
    # PDF points mapped to 595x842 pixels; point-to-pixel factor 842/842 approx 1.0.
    for qi in range(n):
        page_idx=qi//105; local=qi%105
        if page_idx>0:
            # Multi-page sheets require per-page image processing; fail safely instead of guessing.
            answers.append(""); review=True; continue
        col=local//35; row=local%35
        x0=[38,222,406][col]
        y_top=842-330
        y=y_top-row*13
        centers=[x0+49+k*34 for k in range(4)]
        yy=842-y
        scores=[]
        for x in centers:
            xx=int(x); cy=int(yy)
            patch=th[max(0,cy-3):cy+4,max(0,xx-3):xx+4]
            scores.append(float(np.mean(patch))/255 if patch.size else 0)
        # Outline is excluded by small central patch. Marked bubble must be darker and clear winner.
        order=np.argsort(scores)[::-1]
        best=scores[order[0]]; second=scores[order[1]]
        if best < 0.28:
            answers.append("")
        elif best-second < 0.08:
            answers.append(""); review=True
        else:
            answers.append("ABCD"[int(order[0])])
    # Roll number bubble reader (8 digits max); coordinates follow PDF generation.
    digits=[]
    x0=95; y0=842-(842-127) # y in points from top -> normalized image coordinates
    # Original PDF y0 is H-127, so pixel from top=127.
    y0=127
    for col in range(8):
        vals=[]
        for d in range(10):
            cy=int(127+13+d*13) # bubble rows start y0-13-d*13 in PDF => pixel top = 127+13+d*13
            cx=int(x0+col*42)
            patch=th[max(0,cy-3):cy+4,max(0,cx-3):cx+4]
            vals.append(float(np.mean(patch))/255 if patch.size else 0)
        ix=np.argsort(vals)[::-1]
        if vals[ix[0]]<0.28: 
            if digits: break
            continue
        if vals[ix[0]]-vals[ix[1]]<0.08: review=True; digits.append("?")
        else: digits.append(str(int(ix[0])))
    roll="".join(digits)
    return {"roll":roll,"answers":answers,"review":review}

@app.route("/exam/<int:exam_id>/results")
@login_required
def exam_results(exam_id):
    with db() as c:
        e=c.execute("SELECT * FROM exams WHERE id=?",(exam_id,)).fetchone()
        rows=c.execute("SELECT * FROM results WHERE exam_id=? ORDER BY score DESC, correct DESC, roll ASC",(exam_id,)).fetchall()
    if not e: abort(404)
    trs=""
    for i,r in enumerate(rows,1):
        trs+=f"""<tr><td>{i}</td><td>{r['roll']}</td><td>{r['student_name'] or '—'}</td><td>{r['score']:.2f}</td><td>{r['correct']}</td><td>{r['wrong']}</td><td>{r['blank']}</td><td>{'⚠ Review' if r['review'] else 'OK'}</td><td><a href="/result/{r['id']}/edit">Review/edit</a></td></tr>"""
    body=f"""<div class="card"><h1>{e['title']} — Results</h1><div class="pills"><span class="pill">Students: {len(rows)}</span><span class="pill">Needs review: {sum(r['review'] for r in rows)}</span></div>
    <p><a class="btn" href="/export/{exam_id}/csv">Export CSV</a> <a class="btn" href="/export/{exam_id}/xlsx">Export Excel</a> <a class="btn secondary" href="/export/{exam_id}/pdf">Export PDF report</a> <a class="btn secondary" href="/scan?exam_id={exam_id}">Scan more</a></p>
    <div style="overflow:auto"><table><tr><th>Rank</th><th>Roll</th><th>Name</th><th>Score</th><th>Correct</th><th>Wrong</th><th>Blank</th><th>Status</th><th>Action</th></tr>{trs or '<tr><td colspan=9>No sheets scanned yet.</td></tr>'}</table></div></div>"""
    return page("Results",body)

@app.route("/result/<int:result_id>/edit", methods=["GET","POST"])
@roles("admin","teacher")
def result_edit(result_id):
    with db() as c:
        r=c.execute("SELECT r.*,e.answer_key,e.correct_marks,e.wrong_marks,e.blank_marks,e.question_count,e.title FROM results r JOIN exams e ON e.id=r.exam_id WHERE r.id=?",(result_id,)).fetchone()
    if not r: abort(404)
    answers=json.loads(r["answers"]); key=json.loads(r["answer_key"])
    if request.method=="POST":
        roll=request.form.get("roll","").strip()
        name=request.form.get("student_name","").strip()
        vals=[request.form.get(f"q{i+1}","").upper() for i in range(r["question_count"])]
        if not roll or any(a not in ("","A","B","C","D") for a in vals):
            flash("Roll is required; answers must be blank or A/B/C/D."); return redirect(url_for("result_edit",result_id=result_id))
        correct=sum(a==k for a,k in zip(vals,key)); wrong=sum(a and a!=k for a,k in zip(vals,key)); blank=sum(not a for a in vals)
        score=correct*r["correct_marks"]+wrong*r["wrong_marks"]+blank*r["blank_marks"]
        try:
            with db() as c:
                c.execute("UPDATE results SET roll=?,student_name=?,answers=?,score=?,correct=?,wrong=?,blank=?,review=0 WHERE id=?",
                    (roll,name,json.dumps(vals),score,correct,wrong,blank,result_id))
        except sqlite3.IntegrityError:
            flash("That roll number already exists in this exam."); return redirect(url_for("result_edit",result_id=result_id))
        audit(f"manually reviewed result {result_id}"); flash("Answers saved and score recalculated."); return redirect(url_for("exam_results",exam_id=r["exam_id"]))
    fields="".join(f'<div><label>Q{i+1} (correct answer: {key[i]})</label><select name="q{i+1}"><option value="" {"selected" if not answers[i] else ""}>Blank / unclear</option>'+''.join(f'<option value="{a}" {"selected" if answers[i]==a else ""}>{a}</option>' for a in "ABCD")+'</select></div>' for i in range(r["question_count"]))
    body=f"""<div class="card"><h1>Review scanned result</h1><p class="muted">{r['title']}. Confirm the image manually if the scanner flagged the sheet.</p><form method="post"><label>Roll number</label><input name="roll" value="{r['roll']}" required><label>Student name (handwritten; enter manually)</label><input name="student_name" value="{r['student_name'] or ''}"><div class="grid">{fields}</div><p><button>Save reviewed answers</button></p></form></div>"""
    return page("Review result",body)

@app.route("/users", methods=["GET","POST"])
@roles("admin")
def users():
    if request.method=="POST":
        username=request.form.get("username","").strip()
        password=request.form.get("password","")
        role=request.form.get("role","teacher")
        if len(username)<3 or len(password)<12 or role not in ("admin","teacher"):
            flash("Username must be 3+ characters; password must be 12+ characters."); return redirect(url_for("users"))
        try:
            with db() as c: c.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",(username,generate_password_hash(password),role))
            audit(f"created user {username} role={role}"); flash("User created.")
        except sqlite3.IntegrityError: flash("Username already exists.")
        return redirect(url_for("users"))
    with db() as c: us=c.execute("SELECT id,username,role,active FROM users ORDER BY id").fetchall()
    rows="".join(f"<tr><td>{u['username']}</td><td>{u['role']}</td><td>{'Active' if u['active'] else 'Disabled'}</td></tr>" for u in us)
    body=f"""<div class="card"><h1>Manage accounts</h1><p class="muted">Use unique, long passwords. Teachers can create exams and scan; only admins can manage users.</p>
    <form method="post"><div class="grid"><div><label>Username</label><input name="username" required minlength="3"></div><div><label>Temporary password (12+ characters)</label><input name="password" type="password" required minlength="12"></div><div><label>Role</label><select name="role"><option>teacher</option><option>admin</option></select></div></div><p><button>Create account</button></p></form></div>
    <div class="card"><h2>Accounts</h2><table><tr><th>Username</th><th>Role</th><th>Status</th></tr>{rows}</table></div>"""
    return page("Users",body)

def result_rows(exam_id):
    with db() as c:
        e=c.execute("SELECT * FROM exams WHERE id=?",(exam_id,)).fetchone()
        rows=c.execute("SELECT * FROM results WHERE exam_id=? ORDER BY score DESC,correct DESC,roll ASC",(exam_id,)).fetchall()
    if not e: abort(404)
    return e,rows

@app.route("/export/<int:exam_id>/csv")
@login_required
def export_csv(exam_id):
    e,rows=result_rows(exam_id); out=io.StringIO(); w=csv.writer(out)
    w.writerow(["Rank","Roll","Student Name","Score","Correct","Wrong","Blank","Needs Review"])
    for i,r in enumerate(rows,1): w.writerow([i,r["roll"],r["student_name"],r["score"],r["correct"],r["wrong"],r["blank"],"YES" if r["review"] else "NO"])
    data=io.BytesIO(out.getvalue().encode("utf-8-sig")); return send_file(data,mimetype="text/csv",as_attachment=True,download_name=f"fjmc_exam_{exam_id}_results.csv")

@app.route("/export/<int:exam_id>/xlsx")
@login_required
def export_xlsx(exam_id):
    e,rows=result_rows(exam_id); wb=Workbook(); ws=wb.active; ws.title="Results"
    ws.append(["Rank","Roll","Student Name","Score","Correct","Wrong","Blank","Needs Review"])
    for i,r in enumerate(rows,1): ws.append([i,r["roll"],r["student_name"],r["score"],r["correct"],r["wrong"],r["blank"],"YES" if r["review"] else "NO"])
    ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width=min(26,max(12,max(len(str(cell.value or "")) for cell in col)+2))
    out=io.BytesIO(); wb.save(out); out.seek(0)
    return send_file(out,mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",as_attachment=True,download_name=f"fjmc_exam_{exam_id}_results.xlsx")

@app.route("/export/<int:exam_id>/pdf")
@login_required
def export_pdf(exam_id):
    e,rows=result_rows(exam_id); out=io.BytesIO(); p=canvas.Canvas(out,pagesize=A4); W,H=A4
    p.setFont("Helvetica-Bold",16); p.drawString(36,H-40,"FJMC Academy — OMR Results")
    p.setFont("Helvetica",10); p.drawString(36,H-58,e["title"])
    p.drawString(36,H-74,f"Students: {len(rows)} | Questions: {e['question_count']}")
    y=H-105
    def header():
        p.setFont("Helvetica-Bold",8)
        for x,t in zip([36,65,130,260,315,365,415,465],["Rank","Roll","Name","Score","Correct","Wrong","Blank","Review"]): p.drawString(x,y,t)
    header(); y-=15
    for i,r in enumerate(rows,1):
        if y<45: p.showPage(); y=H-45; header(); y-=15
        p.setFont("Helvetica",8)
        vals=[i,r["roll"],(r["student_name"] or "")[:20],f"{r['score']:.2f}",r["correct"],r["wrong"],r["blank"],"YES" if r["review"] else "NO"]
        for x,v in zip([36,65,130,260,315,365,415,465],vals): p.drawString(x,y,str(v))
        y-=14
    p.save(); out.seek(0); return send_file(out,mimetype="application/pdf",as_attachment=True,download_name=f"fjmc_exam_{exam_id}_results.pdf")

@app.errorhandler(403)
def forbidden(e): return page("Forbidden","<div class='card'><h1>Access denied</h1><p>Your role cannot access this page.</p></div>"),403
@app.errorhandler(413)
def too_large(e): return page("File too large","<div class='card'><h1>Upload too large</h1><p>Maximum upload size is 15 MB per request.</p></div>"),413

init_db()
if __name__ == "__main__":
    # For local testing only. For public deployment use a production WSGI server and HTTPS.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT","5000")), debug=False)
