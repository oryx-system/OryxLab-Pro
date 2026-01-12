from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file, Response, make_response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import openpyxl
import io
from ics import Calendar, Event
import shutil
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'default-dev-key-change-this-in-prod')

# Absolute path for DB
basedir = os.path.abspath(os.path.dirname(__file__))

@app.before_request
def auto_logout_if_leaving_admin():
    # If user is admin (session has 'is_admin')
    if session.get('is_admin'):
        # Allow requests to admin pages, login, logout, and static files
        # Also allow favicon.ico which browsers request automatically
        allowed_prefixes = ['/admin', '/login', '/logout', '/static', '/favicon.ico']
        
        # Check if the current request path matches any allowed prefix
        is_allowed = any(request.path.startswith(prefix) for prefix in allowed_prefixes)
        
        if not is_allowed:
            # If navigating away from admin/auth/static pages, log out
            session.pop('is_admin', None)
instance_path = os.path.join(basedir, 'instance')
if not os.path.exists(instance_path):
    os.makedirs(instance_path)

db_path = os.path.join(instance_path, 'library.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Models ---
class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    password = db.Column(db.String(20), nullable=False) # Changed from address
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    purpose = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), default='reserved') # reserved, checked_in, ended, cancelled, noshow_penalty
    admin_memo = db.Column(db.Text, nullable=True) # New Field
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        # Name Masking
        masked_name = self.name
        if len(self.name) > 2:
            masked_name = self.name[0] + '*' * (len(self.name) - 2) + self.name[-1]
        elif len(self.name) == 2:
            masked_name = self.name[0] + '*'
        
        return {
            'id': self.id,
            'title': masked_name,
            'start': self.start_time.isoformat(),
            'end': self.end_time.isoformat(),
            'status': self.status,
            # Private info NOT included
        }

class Blacklist(db.Model):
    phone = db.Column(db.String(20), primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    release_date = db.Column(db.DateTime, nullable=False)
    reason = db.Column(db.String(200), nullable=False)

class Settings(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text, nullable=True)

# --- Helpers ---
def get_setting(key, default=''):
    setting = Settings.query.get(key)
    return setting.value if setting else default

def set_setting(key, value):
    setting = Settings.query.get(key)
    if setting:
        setting.value = value
    else:
        setting = Settings(key=key, value=value)
        db.session.add(setting)
    db.session.commit()

# --- Routes ---

@app.route('/')
def index():
    notice = get_setting('notice_text', '지혜마루 작은 도서관 예약 시스템에 오신 것을 환영합니다.')
    return render_template('index.html', notice=notice)

@app.route('/my')
def my_page():
    return render_template('my_reservation.html')

@app.route('/checkin')
def checkin_page():
    return render_template('checkin.html')

@app.route('/display')
def display_page():
    # Digital Signage Page
    return render_template('display.html')

@app.route('/admin')
def admin_page():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    
    reservations = Reservation.query.order_by(Reservation.start_time.desc()).all()
    
    # Settings for admin view
    settings = {
        'notice_text': get_setting('notice_text'),
        'wifi_info': get_setting('wifi_info'),
        'door_pw': get_setting('door_pw')
    }
    
    return render_template('admin.html', reservations=reservations, settings=settings)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == 'admin123!':
            session['is_admin'] = True
            return redirect(url_for('admin_page'))
        else:
            return render_template('login.html', error='비밀번호가 틀렸습니다.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('is_admin', None)
    return redirect(url_for('login'))

# --- API ---

@app.route('/api/reservations', methods=['GET'])
def get_reservations():
    events = Reservation.query.filter(
        Reservation.status.in_(['reserved', 'checked_in'])
    ).all()
    return jsonify([e.to_dict() for e in events])

@app.route('/api/reservations', methods=['POST'])
def create_reservation():
    data = request.json
    name = data.get('name')
    phone = data.get('phone')
    password = data.get('password')
    start_str = data.get('start')
    end_str = data.get('end')
    
    if not all([name, phone, password, start_str, end_str]):
        return jsonify({'error': '필수 입력 항목이 누락되었습니다.'}), 400

    try:
        start_time = datetime.fromisoformat(start_str)
        end_time = datetime.fromisoformat(end_str)
    except ValueError:
        return jsonify({'error': '날짜 형식이 올바르지 않습니다.'}), 400

    # 1. Blacklist Check
    blocked = Blacklist.query.filter_by(phone=phone).first()
    if blocked:
        if blocked.release_date > datetime.now():
            return jsonify({'error': f'예약이 제한된 사용자입니다. (해제일: {blocked.release_date.strftime("%Y-%m-%d")})'}), 403
        else:
            db.session.delete(blocked)
            db.session.commit()

    # 2. Status Check: Do not double book
    overlap = Reservation.query.filter(
        Reservation.start_time < end_time,
        Reservation.end_time > start_time,
        Reservation.status.in_(['reserved', 'checked_in'])
    ).first()
    if overlap:
        return jsonify({'error': '이미 예약된 시간입니다.'}), 409

    # 3. Daily Limit (4 hours)
    today_start = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = start_time.replace(hour=23, minute=59, second=59, microsecond=999999)
    daily_res = Reservation.query.filter(
        Reservation.phone == phone,
        Reservation.start_time >= today_start,
        Reservation.start_time <= today_end,
        Reservation.status.in_(['reserved', 'checked_in', 'ended'])
    ).all()
    
    total_minutes = sum([(r.end_time - r.start_time).total_seconds() / 60 for r in daily_res])
    new_duration = (end_time - start_time).total_seconds() / 60
    
    if total_minutes + new_duration > 240:
        return jsonify({'error': '하루 최대 4시간까지만 이용 가능합니다.'}), 400

    new_res = Reservation(
        name=name.strip(),
        phone=phone.strip(),
        password=password.strip(),
        start_time=start_time,
        end_time=end_time
    )
    db.session.add(new_res)
    db.session.commit()
    
    return jsonify({'success': True, 'id': new_res.id}), 201

@app.route('/api/reservations/<int:id>/download_ics')
def download_ics(id):
    res = Reservation.query.get_or_404(id)
    c = Calendar()
    e = Event()
    e.name = f"지혜마루 예약 ({res.name})"
    e.begin = res.start_time
    e.end = res.end_time
    e.location = "지혜마루 작은 도서관"
    c.events.add(e)
    
    return Response(
        str(c),
        mimetype='text/calendar',
        headers={'Content-Disposition': f'attachment; filename=reservation_{id}.ics'}
    )

@app.route('/api/my_reservations', methods=['GET'])
def my_reservations_api():
    phone = request.args.get('phone')
    password = request.args.get('password')

    if not phone or not password:
        return jsonify({'error': '전화번호와 비밀번호가 필요합니다.'}), 400
        
    # Match both phone and password
    reservations = Reservation.query.filter_by(
        phone=phone, 
        password=password
    ).order_by(Reservation.start_time.desc()).all()
    
    wifi_info = get_setting('wifi_info', '정보 없음')
    door_pw = get_setting('door_pw', '정보 없음')

    results = []
    for r in reservations:
        results.append({
            'id': r.id,
            'name': r.name,
            'id': r.id,
            'name': r.name,
            # 'address': r.address, # Removed
            'status': r.status,
            'start': r.start_time.strftime('%Y-%m-%d %H:%M'),
            'end': r.end_time.strftime('%H:%M'),
            'wifi_info': wifi_info, # Secure info only returned to verified user
            'door_pw': door_pw
        })
    return jsonify(results)

@app.route('/api/reservations/<int:id>/cancel', methods=['POST'])
def cancel_reservation(id):
    res = Reservation.query.get_or_404(id)
    data = request.json
    is_penalty = data.get('is_penalty', False)

    if is_penalty:
        res.status = 'noshow_penalty'
        release_date = datetime.now() + timedelta(days=30)
        existing_bl = Blacklist.query.filter_by(phone=res.phone).first()
        if not existing_bl:
            bl = Blacklist(phone=res.phone, name=res.name, release_date=release_date, reason="당일 취소 패널티")
            db.session.add(bl)
        else:
            existing_bl.release_date = release_date
            existing_bl.reason = "당일 취소 패널티 (갱신)"
    else:
        res.status = 'cancelled'
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/checkin', methods=['POST'])
def checkin_process():
    data = request.json
    phone = data.get('phone')
    if not phone:
        return jsonify({'error': '전화번호 입력 필요'}), 400

    now = datetime.now()
    margin = timedelta(minutes=10)

    # Simple logic: Find upcoming 'reserved' event
    candidates = Reservation.query.filter(
        Reservation.phone.like(f'%{phone}'),
        Reservation.status == 'reserved'
    ).all()
    
    target_res = None
    for r in candidates:
        if (r.start_time - margin) <= now < r.end_time:
            target_res = r
            break
    
    if not target_res:
        return jsonify({'error': '현재 체크인 가능한 예약이 없습니다.'}), 404
        
    target_res.status = 'checked_in'
    db.session.commit()
    return jsonify({'success': True, 'name': target_res.name})

# --- Admin API ---

@app.route('/admin/settings', methods=['POST'])
def update_settings():
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    set_setting('notice_text', data.get('notice_text', ''))
    set_setting('wifi_info', data.get('wifi_info', ''))
    set_setting('door_pw', data.get('door_pw', ''))
    
    return jsonify({'success': True})

@app.route('/admin/memo/<int:id>', methods=['POST'])
def update_admin_memo(id):
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    res = Reservation.query.get_or_404(id)
    res.admin_memo = request.json.get('memo', '')
    db.session.commit()
    return jsonify({'success': True})

@app.route('/admin/backup')
def backup_db():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    
    return send_file(db_path, as_attachment=True, download_name=f'library_backup_{datetime.now().strftime("%Y%m%d")}.sqlite')

@app.route('/admin/download_excel')
def download_excel():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    
    reservations = Reservation.query.all()
    data = []
    
    # Status Translation Map
    status_map = {
        'reserved': '예약됨',
        'cancelled': '취소됨',
        'checked_in': '입실완료',
        'checked_out': '퇴실완료',
        'ended': '이용완료',
        'noshow_penalty': '노쇼(패널티)'
    }

    for r in reservations:
        data.append({
            'ID': r.id,
            '이름': r.name,
            '전화번호': r.phone,
            '주소': r.address,
            '시작시간': r.start_time,
            '종료시간': r.end_time,
            '상태': status_map.get(r.status, r.status), # Translate status
            '관리자 메모': r.admin_memo
        })
        
    if not data:
        return "데이터가 없습니다."
        
    # Ensure correct column order
    # cols = ['ID', '이름', '전화번호', '주소', '시작시간', '종료시간', '상태', '관리자 메모']

    output = io.BytesIO()
    
    # Use openpyxl directly instead of pandas
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '예약내역'
    
    # Headers
    headers = ['ID', '이름', '전화번호', '시작시간', '종료시간', '상태', '관리자 메모']
    ws.append(headers)
    
    for r in reservations:
        row = [
            r.id,
            r.name,
            r.phone,
            r.start_time,
            r.end_time,
            status_map.get(r.status, r.status),
            r.admin_memo
        ]
        ws.append(row)
        
    wb.save(output)
    output.seek(0)
    
    filename = f"reservation_list_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename)

@app.route('/admin/block/<phone>', methods=['POST'])
def manual_block(phone):
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    release_date = datetime.now() + timedelta(days=30)
    name = request.json.get('name', 'Unknown')
    
    existing = Blacklist.query.filter_by(phone=phone).first()
    if existing:
        existing.release_date = release_date
        existing.reason = "관리자 수동 차단"
    else:
        bl = Blacklist(phone=phone, name=name, release_date=release_date, reason="관리자 수동 차단")
        db.session.add(bl)
        
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/stats_today')
def stats_today():
    # Only for digital signage
    today_start = datetime.now().replace(hour=0, minute=0, second=0)
    today_end = datetime.now().replace(hour=23, minute=59, second=59)
    
    res_list = Reservation.query.filter(
        Reservation.start_time >= today_start, 
        Reservation.start_time <= today_end, 
        Reservation.status.in_(['reserved', 'checked_in'])
    ).order_by(Reservation.start_time).all()
    
    return jsonify([r.to_dict() for r in res_list])


import qrcode

@app.route('/admin/qr_code')
def generate_qr_code():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
        
    # Generate URL for check-in page (using current host)
    # Ideally should be a fixed domain, but using request.host_url for now
    host_url = request.host_url
    if 'localhost' in host_url or '127.0.0.1' in host_url:
        # Suggest local IP if running locally for mobile access
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            checkin_url = f"http://{local_ip}:5000/checkin"
        except:
            checkin_url = f"{host_url}checkin"
    else:
        checkin_url = f"{host_url}checkin"
        
    img = qrcode.make(checkin_url)
    output = io.BytesIO()
    img.save(output, format='PNG')
    output.seek(0)
    
    return send_file(output, mimetype='image/png')
    
def create_init_data():
    if not os.path.exists('instance'):
        os.makedirs('instance')
    db.create_all()
    
    # Init default settings if empty
    if not Settings.query.all():
        set_setting('notice_text', '지혜마루 작은 도서관에 오신 것을 환영합니다.')
        set_setting('wifi_info', 'ID: JihyeLib / PW: readbooks')
        set_setting('door_pw', '1234*')

if __name__ == '__main__':
    with app.app_context():
        create_init_data()
    app.run(host='0.0.0.0', port=5000, debug=True)
