from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file, Response, make_response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import openpyxl
import io
from ics import Calendar, Event
import shutil
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont # Added for QR Poster
import requests # Added for Telegram Notifications
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader # Added for blob image support

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import base64
import binascii

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'default-dev-key-change-this-in-prod')

# Absolute path for DB
basedir = os.path.abspath(os.path.dirname(__file__))


@app.before_request
def auto_logout_if_leaving_admin():
    # Check if user is admin OR developer
    is_admin = session.get('is_admin')
    is_dev = session.get('is_dev')
    
    if is_admin or is_dev:
        # Allow requests to admin/dev pages, login, logout, and static files
        allowed_prefixes = ['/admin', '/login', '/logout', '/static', '/favicon.ico', '/developer', '/dev']
        
        # Check if the current request path matches any allowed prefix
        is_allowed = any(request.path.startswith(prefix) for prefix in allowed_prefixes)
        
        if not is_allowed:
            # If navigating away from admin/dev/auth/static pages, log out
            session.pop('is_admin', None)
            session.pop('is_dev', None)

@app.before_request
def maintenance_check():
    # Maintenance Mode Check
    if get_setting('maintenance_mode') == 'true':
        # Allow static files and admin/dev login, and DEV APIs
        allowed_prefixes = ['/admin', '/login', '/logout', '/static', '/developer', '/dev-login', '/favicon.ico', '/dev/']
        if not any(request.path.startswith(prefix) for prefix in allowed_prefixes):
            return render_template('maintenance.html'), 503

    # Log Access (Exclude static and internal polling if any)
    if not request.path.startswith('/static') and not request.path == '/favicon.ico':
        try:
            # Create log entry
            log = AccessLog(
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string[:200],
                path=request.path,
                method=request.method
            )
            db.session.add(log)
            db.session.commit()
        except Exception:
            pass # Don't block request on log failure

@app.errorhandler(500)
def handle_500(e):
    import traceback
    try:
        log = ErrorLog(
            error_msg=str(e),
            traceback=traceback.format_exc()
        )
        db.session.add(log)
        db.session.commit()
    except:
        pass
    return "Internal Server Error", 500
instance_path = os.path.join(basedir, 'instance')
if not os.path.exists(instance_path):
    os.makedirs(instance_path)

db_path = os.path.join(instance_path, 'library.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_BINDS'] = {
    'logs': 'sqlite:///' + os.path.join(instance_path, 'logs.db')
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Models ---
class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    password = db.Column(db.String(20), nullable=False) # Changed from address
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    purpose = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), default='reserved') # reserved, checked_in, ended, cancelled, noshow_penalty
    admin_memo = db.Column(db.Text, nullable=True) # New Field
    signature_path = db.Column(db.String(255), nullable=True) # Legacy (File Path)
    signature_blob = db.Column(db.LargeBinary, nullable=True) # New (Database Storage)
    checkout_photo = db.Column(db.String(255), nullable=True) # New: Cleaning photo
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

# --- Log Models (logs.db) ---
class AccessLog(db.Model):
    __bind_key__ = 'logs'
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(200))
    path = db.Column(db.String(100))
    method = db.Column(db.String(10))
    timestamp = db.Column(db.DateTime, default=datetime.now)

class AdminLog(db.Model):
    __bind_key__ = 'logs'
    id = db.Column(db.Integer, primary_key=True)
    admin_type = db.Column(db.String(20)) # 'admin' or 'dev'
    action = db.Column(db.String(100))
    ip_address = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, default=datetime.now)

class ErrorLog(db.Model):
    __bind_key__ = 'logs'
    id = db.Column(db.Integer, primary_key=True)
    error_msg = db.Column(db.Text)
    traceback = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.now)

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

def log_admin_action(admin_type, action):
    try:
        log = AdminLog(
            admin_type=admin_type,
            action=action,
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()
    except:
        pass # Fail silently for logs

def send_telegram_alert(message, token=None, chat_id=None):
    if not token:
        token = get_setting('telegram_token') or os.environ.get('TELEGRAM_BOT_TOKEN')
    if not chat_id:
        chat_id = get_setting('telegram_chat_id') or os.environ.get('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        return

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message
        }
        # Short timeout to avoid blocking main thread too long
        requests.post(url, json=payload, timeout=2) 
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")

# --- Routes ---

@app.route('/')
def index():
    notice = get_setting('notice_text', '').strip()
    if not notice:
        notice = "없음"
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
    # Allow Devs to access Admin seamlessly
    if not session.get('is_admin') and not session.get('is_dev'):
        return redirect(url_for('login'))
    
    reservations = Reservation.query.order_by(Reservation.start_time.desc()).all()
    
    # Settings for admin view
    import json
    try:
        current_ranges = json.loads(get_setting('pause_ranges', '[]'))
    except:
        current_ranges = []
        
    settings = {
        'notice_text': get_setting('notice_text'),
        'wifi_info': get_setting('wifi_info'),
        'door_pw': get_setting('door_pw'),
        'reservation_paused': get_setting('reservation_paused') == 'true',
        'pause_reason': get_setting('pause_reason'),
        'pause_mode': get_setting('pause_mode', 'all'),
        'pause_mode': get_setting('pause_mode', 'all'),
        'pause_ranges': current_ranges,
        'telegram_token': get_setting('telegram_token', ''),
        'telegram_chat_id': get_setting('telegram_chat_id', '')
    }
    
    # Fetch Feedback
    feedbacks = AdminLog.query.filter_by(admin_type='feedback').order_by(AdminLog.timestamp.desc()).limit(50).all()

    # Fetch Blocklist
    blocked_users = Blacklist.query.order_by(Blacklist.release_date.desc()).all()
    blocked_phones = [b.phone for b in blocked_users]

    return render_template('admin.html', reservations=reservations, settings=settings, feedbacks=feedbacks, blocked_users=blocked_users, blocked_phones=blocked_phones)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        
        # Check Admin PW (DB backed)
        saved_admin_pw = get_setting('admin_pw', 'admin123!')
        saved_dev_pw = get_setting('dev_pw', '123qwe!')

        if password == saved_admin_pw:
            session['is_admin'] = True
            log_admin_action('admin', 'Login')
            return redirect(url_for('admin_page'))
        elif password == saved_dev_pw:
            session['is_dev'] = True
            log_admin_action('dev', 'Login')
            return redirect(url_for('developer_page'))
        else:
            return render_template('login.html', error='비밀번호가 틀렸습니다.')
    return render_template('login.html')

@app.route('/dev-login', methods=['GET', 'POST'])
def dev_login_endpoint():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == '123qwe!':
            session['is_dev'] = True
            log_admin_action('dev', 'Login')
            return redirect(url_for('developer_page'))
        else:
            return render_template('login.html', dev_mode=True, error='비밀번호가 틀렸습니다.')
            
    return render_template('login.html', dev_mode=True)

@app.route('/logout')
def logout():
    if session.get('is_admin'):
        log_admin_action('admin', 'Logout')
    if session.get('is_dev'):
        log_admin_action('dev', 'Logout')
        
    session.pop('is_admin', None)
    session.pop('is_dev', None)
    return redirect(url_for('login'))

# --- API ---

@app.route('/api/reservations', methods=['GET'])
def get_reservations():
    events = Reservation.query.filter(
        Reservation.status.in_(['reserved', 'checked_in'])
    ).all()
    
    event_list = [e.to_dict() for e in events]
    
    # Inject Visual Block if Paused
    if get_setting('reservation_paused') == 'true':
        mode = get_setting('pause_mode', 'all')
        reason = get_setting('pause_reason', '')
        
        if mode == 'all':
            # Block for next 1 year
            start_dt = datetime.now()
            end_dt = start_dt + timedelta(days=365)
            event_list.append({
                'id': 'blocked_all',
                'title': f'⛔ 예약 중지 ({reason})',
                'start': start_dt.strftime('%Y-%m-%d'),
                'end': end_dt.strftime('%Y-%m-%d'),
                'color': '#757575',
                'allDay': True,
                'editable': False,
                'display': 'block' 
            })
        elif mode == 'partial':
            import json
            ranges_str = get_setting('pause_ranges', '[]')
            try:
                pause_ranges = json.loads(ranges_str)
            except:
                pause_ranges = []
                
            # Fallback
            if not pause_ranges:
                p_s = get_setting('pause_start')
                p_e = get_setting('pause_end')
                if p_s and p_e:
                     pause_ranges.append({'start': p_s, 'end': p_e})

            for idx, rng in enumerate(pause_ranges):
                try:
                    p_start = rng['start']
                    p_end = rng['end']
                    
                    # Add +1 day to end for FullCalendar exclusive end date
                    end_obj = datetime.strptime(p_end, '%Y-%m-%d') + timedelta(days=1)
                    p_end_exclusive = end_obj.strftime('%Y-%m-%d')
                    
                    range_reason = rng.get('reason', reason)
                    event_list.append({
                        'id': f'blocked_partial_{idx}',
                        'title': f'⛔ 예약 서비스 중지 ({range_reason})',
                        'start': p_start,
                        'end': p_end_exclusive,
                        'color': '#ff4444', 
                        'allDay': True,
                        'editable': False
                    })
                except:
                    pass

    return jsonify(event_list)

@app.route('/api/reservations', methods=['POST'])
def create_reservation():
    data = request.json
    name = data.get('name')
    phone = data.get('phone')
    password = data.get('password')
    purpose = data.get('purpose')
    start_str = data.get('start')
    end_str = data.get('end')
    
    if not all([name, phone, password, purpose, start_str, end_str]):
        return jsonify({'error': '필수 입력 항목이 누락되었습니다.'}), 400

    try:
        start_time = datetime.fromisoformat(start_str)
        end_time = datetime.fromisoformat(end_str)
    except ValueError:
        return jsonify({'error': '날짜 형식이 올바르지 않습니다.'}), 400

    if start_time < datetime.now():
        return jsonify({'error': '지난 날짜는 예약할 수 없습니다.'}), 400

    # 0. Global/Partial Pause Check
    if get_setting('reservation_paused') == 'true':
        pause_mode = get_setting('pause_mode', 'all')
        reason = get_setting('pause_reason', '시스템 점검으로 인한 예약 일시 중지')
        
        should_block = False
        if pause_mode == 'all':
            should_block = True
        elif pause_mode == 'partial':
            import json
            # Load ranges
            ranges_str = get_setting('pause_ranges', '[]')
            try:
                pause_ranges = json.loads(ranges_str)
            except:
                pause_ranges = []
                
            # Fallback for old single range if 'pause_ranges' is empty but legacy keys exist
            if not pause_ranges:
                p_start = get_setting('pause_start')
                p_end = get_setting('pause_end')
                if p_start and p_end:
                    pause_ranges.append({'start': p_start, 'end': p_end})
            
            # Check overlap
            res_date = start_time.strftime('%Y-%m-%d')
            for rng in pause_ranges:
                # Assuming rng is {start: 'YYYY-MM-DD', end: 'YYYY-MM-DD', reason: '...'}
                if rng.get('start') <= res_date <= rng.get('end'):
                    should_block = True
                    # Use specific reason if available
                    if rng.get('reason'):
                        reason = rng.get('reason')
                    break
                    
        if should_block:
            return jsonify({'error': f'해당 기간은 예약이 일시 중지되었습니다.\n사유: {reason}'}), 403

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

    # 4. Save Signature Image (DB Blob)
    sig_blob = None
    if 'signature' in data and data['signature']:
        try:
             # Format: "data:image/png;base64,iVBOR..."
             header, encoded = data['signature'].split(',', 1)
             img_data = base64.b64decode(encoded)
             sig_blob = img_data
        except Exception as e:
             print(f"Signature Decode Error: {e}")

    new_res = Reservation(
        name=name.strip(),
        phone=phone.strip(),
        password=password.strip(),
        purpose=purpose.strip(),
        start_time=start_time,
        end_time=end_time,
        signature_blob=sig_blob
    )
    db.session.add(new_res)
    db.session.commit()
    
    # Telegram Alert
    try:
        msg = f"[새 예약 알림]\n- 예약자: {new_res.name}\n- 전화번호: {new_res.phone}\n- 시간: {new_res.start_time.strftime('%Y-%m-%d %H:%M')} ~ {new_res.end_time.strftime('%H:%M')}\n- 목적: {new_res.purpose}"
        send_telegram_alert(msg)
    except:
        pass # Fail silently

    
    return jsonify({'success': True, 'id': new_res.id}), 201

@app.route('/api/feedback', methods=['POST'])
def submit_feedback():
    data = request.json
    msg = data.get('message', '').strip()
    contact = data.get('contact', '').strip()
    
    if not msg:
        return jsonify({'error': '내용을 입력해주세요.'}), 400
    
    full_msg = msg
    if contact:
        full_msg += f" (Contact: {contact})"

    # Store in AdminLog with type 'feedback'
    log_admin_action('feedback', full_msg)
    return jsonify({'success': True})

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

@app.route('/api/my_history', methods=['POST'])
def my_history_api():
    data = request.json
    phone = data.get('phone')
    password = data.get('password')

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
            'purpose': r.purpose,
            'status': r.status,
            'start': r.start_time.strftime('%Y-%m-%d %H:%M'),
            'end': r.end_time.strftime('%H:%M'),
            'wifi_info': wifi_info,
            'door_pw': door_pw
        })
    return jsonify({'success': True, 'reservations': results, 'wifi_info': wifi_info, 'door_pw': door_pw})

@app.route('/api/reservations/<int:id>/cancel', methods=['POST'])
def cancel_reservation(id):
    res = Reservation.query.get_or_404(id)

    if res.start_time < datetime.now():
        return jsonify({'error': '지난 예약은 취소할 수 없습니다.'}), 400

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

@app.route('/api/checkout', methods=['POST'])
def checkout_process():
    if 'photo' not in request.files:
        return jsonify({'error': '청소 사진을 업로드해주세요.'}), 400
    
    file = request.files['photo']
    phone = request.form.get('phone')
    
    if file.filename == '':
        return jsonify({'error': '파일이 선택되지 않았습니다.'}), 400
        
    if not phone:
        return jsonify({'error': '식별 정보(전화번호)가 누락되었습니다.'}), 400

    # Find the active reservation (checked_in)
    target_res = Reservation.query.filter(
        Reservation.phone.like(f'%{phone}'),
        Reservation.status == 'checked_in'
    ).order_by(Reservation.start_time.desc()).first()

    if not target_res:
         # Fallback: check if 'reserved' (user skipped checkin)
        target_res = Reservation.query.filter(
            Reservation.phone.like(f'%{phone}'),
            Reservation.status == 'reserved'
        ).order_by(Reservation.start_time.desc()).first()

    if not target_res:
        return jsonify({'error': '퇴실 가능한 예약이 없습니다.'}), 404

    # Save File
    filename = f"checkout_{target_res.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
    upload_folder = os.path.join(basedir, 'static', 'uploads')
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
        
    filepath = os.path.join(upload_folder, filename)
    file.save(filepath)

    target_res.checkout_photo = filename
    target_res.status = 'ended'
    db.session.commit()

    return jsonify({'success': True, 'message': '퇴실 처리가 완료되었습니다.'})

# --- Admin API ---

@app.route('/admin/settings', methods=['POST'])
def update_settings():
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    set_setting('notice_text', data.get('notice_text', ''))
    set_setting('wifi_info', data.get('wifi_info', ''))
    set_setting('door_pw', data.get('door_pw', ''))
    set_setting('telegram_token', data.get('telegram_token', ''))
    set_setting('telegram_chat_id', data.get('telegram_chat_id', ''))
    
    return jsonify({'success': True})

@app.route('/admin/test_telegram', methods=['POST'])
def test_telegram():
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    token = data.get('token')
    chat_id = data.get('chat_id')
    
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {'chat_id': chat_id, 'text': "[테스트 알림] 설정이 정상적으로 완료되었습니다!"}
        res = requests.post(url, json=payload, timeout=5)
        
        if res.status_code == 200:
            return jsonify({'success': True})
        else:
            return jsonify({'error': f"전송 실패 (Code: {res.status_code}): {res.text}"})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/admin/memo/<int:id>', methods=['POST'])
def update_admin_memo(id):
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    res = Reservation.query.get_or_404(id)
    res.admin_memo = request.json.get('memo', '')
    db.session.commit()
    return jsonify({'success': True})

@app.route('/admin/change_password', methods=['POST'])
def change_admin_password():
    if not session.get('is_admin') and not session.get('is_dev'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    new_pw = data.get('new_password')
    
    if not new_pw or len(new_pw) < 4:
         return jsonify({'error': '비밀번호는 4자 이상이어야 합니다.'}), 400
         
    set_setting('admin_pw', new_pw)
    log_admin_action('admin', 'Changed Admin Password')
    
    return jsonify({'success': True})

@app.route('/admin/backup')
def backup_db():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    
    return send_file(db_path, as_attachment=True, download_name=f'library_backup_{datetime.now().strftime("%Y%m%d")}.sqlite')

    # Headers for processing (though we use openpyxl manual write below)
    
    output = io.BytesIO()
    
    # Use openpyxl directly instead of pandas
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '예약내역'
    # ... (rest of excel export) ...
    # Wait, I am inserting BEFORE this or AFTER this? 
    # I will insert the new route BEFORE download_excel for better organization, or after.
    # Actually, let's insert it AFTER existing admin routes.
    # The snippet in "TargetContent" needs to be precise.
    # I will use appending to the end of admin routes section, e.g. before "download_excel" or after.
    # Let's target the gap before download_excel.



def _draw_application_form(c, res, width, height):
    # Title
    c.setFont('Malgun', 24)
    c.drawCentredString(width/2, height - 30*mm, "지혜마루 작은 도서관")
    c.setFont('Malgun', 36)
    c.drawCentredString(width/2, height - 50*mm, "시설 사용 신청서")
    
    # Content
    c.setFont('Malgun', 14)
    y = height - 80*mm
    line_height = 12*mm
    
    # Box Logic
    margin_x = 30*mm
    
    def draw_row(label, value, y_pos):
        c.setFont('Malgun', 14)
        c.drawString(margin_x, y_pos, label)
        c.drawString(margin_x + 40*mm, y_pos, f":  {value}")
        c.line(margin_x, y_pos - 2*mm, width - margin_x, y_pos - 2*mm)
        return y_pos - line_height

    y = draw_row("예약 번호", str(res.id), y)
    y = draw_row("성       명", res.name, y)
    
    # Format Phone Number (010-xxxx-xxxx)
    p_str = res.phone
    if len(p_str) == 11 and p_str.startswith('010'):
         p_str = f"{p_str[:3]}-{p_str[3:7]}-{p_str[7:]}"
         
    y = draw_row("전화번호", p_str, y)
    y = draw_row("사용 일자", res.start_time.strftime('%Y년 %m월 %d일'), y)
    y = draw_row("사용 시간", f"{res.start_time.strftime('%H:%M')} ~ {res.end_time.strftime('%H:%M')}", y)
    y = draw_row("사용 목적", res.purpose, y)
    
    # Agreement
    y -= 20*mm
    c.setFont('Malgun', 12)
    c.drawString(margin_x, y, "본인은 위와 같이 지혜마루 작은 도서관 시설을 사용하고자 신청하며,")
    y -= 8*mm
    c.drawString(margin_x, y, "시설 이용 규정을 준수하고 발생되는 모든 문제에 대해 책임을 질 것을 확약합니다.")
    
    # Date & Signature
    y -= 40*mm
    c.setFont('Malgun', 14)
    c.drawCentredString(width/2, y, datetime.now().strftime('%Y년 %m월 %d일'))
    
    y -= 20*mm
    
    # Text Components
    name_str = f"신청인 :  {res.name}"
    seal_str = "(인)"
    
    # Calculate widths for centering
    c.setFont('Malgun', 14)
    name_w = c.stringWidth(name_str)
    
    c.setFont('Malgun', 10) # Smaller as requested
    seal_w = c.stringWidth(seal_str)
    
    spacing = 10*mm # Space between name and (in)
    total_w = name_w + spacing + seal_w
    
    # Starting X to center the whole block
    start_x = (width - total_w) / 2
    
    # 1. Draw Name (Black)
    c.setFillColorRGB(0, 0, 0)
    c.setFont('Malgun', 14)
    c.drawString(start_x, y, name_str)
    
    # 2. Draw (in) (Gray)
    seal_x = start_x + name_w + spacing
    c.setFillColorRGB(0.7, 0.7, 0.7) # Light Gray
    c.setFont('Malgun', 10)
    # Adjust y slightly if needed for baseline alignment, but same y is usually fine for 14 vs 10
    c.drawString(seal_x, y, seal_str)
    
    # Reset color
    c.setFillColorRGB(0, 0, 0)
    
    # 3. Draw Signature Image
    # Priority: Blob -> Path -> None
    sig_img_reader = None
    
    if res.signature_blob:
        try:
            sig_img_reader = ImageReader(io.BytesIO(res.signature_blob))
        except:
            pass
    elif res.signature_path:
        sig_full_path = os.path.join(instance_path, 'signatures', res.signature_path)
        if os.path.exists(sig_full_path):
            sig_img_reader = sig_full_path # Filename is also valid for drawImage
            
    if sig_img_reader:
        # Target Center: Center of "(in)" text
        center_x = seal_x + (seal_w / 2)
        center_y = y + 1.5*mm 
        
        # Size: ~30.25 x 14.52 (Approx using aspect ratio)
        sig_w = 30.25 * mm
        sig_h = 14.52 * mm
        
        try:
            c.drawImage(sig_img_reader, center_x - (sig_w/2), center_y - (sig_h/2), width=sig_w, height=sig_h, mask='auto', preserveAspectRatio=True)
        except Exception as e:
            print(f"PDF Signature Draw Error: {e}")

def _generate_pdf_buffer(res):
    # 1. Register Font
    font_path = "C:/Windows/Fonts/malgun.ttf"
    if not os.path.exists(font_path):
         return None
         
    try:
        pdfmetrics.registerFont(TTFont('Malgun', font_path))
    except:
        pass

    # 2. Generate PDF
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    _draw_application_form(c, res, width, height)
    c.save()
    buffer.seek(0)
    return buffer

def _send_email_with_pdf(to_email, subject, body, pdf_buffer, filename):
    smtp_host = get_setting('smtp_host')
    smtp_port = get_setting('smtp_port') or 587
    smtp_email = get_setting('smtp_email')
    smtp_password = get_setting('smtp_password')
    
    if not smtp_host or not smtp_email or not smtp_password:
        return False, "SMTP 설정이 누락되었습니다."
        
    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        pdf_buffer.seek(0)
        part = MIMEApplication(pdf_buffer.read(), Name=filename)
        part['Content-Disposition'] = f'attachment; filename="{filename}"'
        msg.attach(part)
        
        with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
            
        return True, None
    except Exception as e:
        return False, str(e)


@app.route('/admin/reservations/<int:id>/preview', methods=['POST'])
def admin_preview_pdf(id):
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    res = Reservation.query.get_or_404(id)
    buffer = _generate_pdf_buffer(res)
    
    if not buffer:
        return jsonify({'error': 'PDF 생성 오류'}), 500
        
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=False,
        download_name=f'application_{id}.pdf'
    )

@app.route('/admin/reservations/<int:id>/send_official', methods=['POST'])
def send_official_pdf(id):
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Get official email
    official_email = get_setting('official_email')
    if not official_email:
         return jsonify({'error': '담당자 이메일이 설정되지 않았습니다.'}), 400

    res = Reservation.query.get_or_404(id)
    buffer = _generate_pdf_buffer(res)
    
    if not buffer:
        return jsonify({'error': 'PDF 생성 실패'}), 500
    
    # Send Email
    subject = f"[지혜마루] 시설 사용 신청서 - {res.name}"
    body = f"""안녕하세요.
지혜마루 작은도서관입니다.

신청인: {res.name}
사용일: {res.start_time.strftime('%Y-%m-%d')}
사용시간: {res.start_time.strftime('%H:%M')} ~ {res.end_time.strftime('%H:%M')}

붙임의 신청서를 확인해주시기 바랍니다.
감사합니다."""
    filename = f"신청서_{res.name}_{res.start_time.strftime('%Y%m%d')}.pdf"

    success, error = _send_email_with_pdf(official_email, subject, body, buffer, filename)
    
    if success:
        log_admin_action('admin', f'Sent Official Email for Reservation {id}')
        return jsonify({'success': True})
    else:
        return jsonify({'error': f"메일 전송 실패: {error}"}), 500

@app.route('/admin/stats/report', methods=['POST'])
def send_bulk_report():
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    period = request.json.get('period', 'week') # week, half, month
    official_email = get_setting('official_email')
    
    if not official_email:
        return jsonify({'error': '담당자 이메일이 설정되지 않았습니다.'}), 400
        
    # Date Calculation
    today = datetime.now()
    if period == 'week':
        # Last 7 days
        start_date = today - timedelta(days=7)
        title_suffix = "주간"
    elif period == 'half':
        # Last 15 days
        start_date = today - timedelta(days=15)
        title_suffix = "보름"
    elif period == 'month':
        start_date = today - timedelta(days=30)
        title_suffix = "월간"
    else:
        return jsonify({'error': 'Invalid period'}), 400
        
    # Fetch Reservations
    reservations = Reservation.query.filter(
        Reservation.start_time >= start_date,
        Reservation.status.in_(['reserved', 'checked_in', 'ended'])
    ).order_by(Reservation.start_time).all()
    
    if not reservations:
        return jsonify({'error': '해당 기간에 예약이 없습니다.'}), 404
        
    # Generate Merged PDF
    font_path = "C:/Windows/Fonts/malgun.ttf"
    if not os.path.exists(font_path):
         return jsonify({'error': '폰트 없음'}), 500
         
    try:
        pdfmetrics.registerFont(TTFont('Malgun', font_path))
    except:
        pass
        
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    for res in reservations:
        _draw_application_form(c, res, width, height)
        c.showPage() # New Page
        
    c.save()
    buffer.seek(0)
    
    # Send Email
    subject = f"[지혜마루] 시설 사용 신청서 모음 ({title_suffix})"
    body = f"""안녕하세요.
지혜마루 작은도서관입니다.

{title_suffix} 시설 사용 신청서 모음을 송부드립니다.
기간: {start_date.strftime('%Y-%m-%d')} ~ {today.strftime('%Y-%m-%d')}
총 건수: {len(reservations)}건

감사합니다."""
    filename = f"지혜마루_{title_suffix}_예약모음_{today.strftime('%Y%m%d')}.pdf"

    success, error = _send_email_with_pdf(official_email, subject, body, buffer, filename)

    if success:
        log_admin_action('admin', f'Sent Bulk Report ({period}) - Email')
        return jsonify({'success': True, 'count': len(reservations)})
    else:
        return jsonify({'error': f"메일 전송 실패: {error}"}), 500

@app.route('/admin/reservations/<int:id>/send_pdf', methods=['POST'])
def send_reservation_pdf(id):
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401

    res = Reservation.query.get_or_404(id)
    buffer = _generate_pdf_buffer(res)
    
    if not buffer:
        return jsonify({'error': 'PDF 생성 실패 (폰트 없음)'}), 500
    
    # 3. Send to Telegram
    token = get_setting('telegram_token')
    chat_id = get_setting('telegram_chat_id')
    
    if not token or not chat_id:
        return jsonify({'error': '텔레그램 설정이 되어있지 않습니다.'}), 400
        
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    files = {
        'document': (f'신청서_{res.name}_{res.start_time.strftime("%Y%m%d")}.pdf', buffer, 'application/pdf')
    }
    data = {'chat_id': chat_id, 'caption': f"📄 시설 사용 신청서 ({res.name})"}
    
    try:
        r = requests.post(url, data=data, files=files, timeout=10)
        if r.status_code == 200:
            log_admin_action('admin', f'Sent PDF for Reservation {id}')
            return jsonify({'success': True})
        else:
            return jsonify({'error': f"전송 실패: {r.text}"}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reservations/<int:id>/preview_pdf', methods=['POST'])
def preview_pdf(id):
    data = request.json
    phone = data.get('phone')
    password = data.get('password')
    
    res = Reservation.query.get_or_404(id)
    
    # Verify Owner
    if res.phone != phone or res.password != password:
        return jsonify({'error': '권한이 없습니다 (정보 불일치)'}), 403
        
    buffer = _generate_pdf_buffer(res)
    if not buffer:
        return jsonify({'error': 'PDF 생성 오류'}), 500
        
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=False, # Preview in browser
        download_name=f'application_{id}.pdf'
    )

@app.route('/api/reservations/<int:id>/send_to_admin', methods=['POST'])
def user_send_pdf_to_admin(id):
    data = request.json
    phone = data.get('phone')
    password = data.get('password')
    
    res = Reservation.query.get_or_404(id)
    
    # Verify Owner
    if res.phone != phone or res.password != password:
        return jsonify({'error': '권한이 없습니다 (정보 불일치)'}), 403
        
    buffer = _generate_pdf_buffer(res)
    if not buffer:
         return jsonify({'error': 'PDF 생성 오류'}), 500

    token = get_setting('telegram_token')
    chat_id = get_setting('telegram_chat_id')
    
    if not token or not chat_id:
        return jsonify({'error': '관리자 알림 설정이 되어있지 않습니다.'}), 400
        
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    files = {
        'document': (f'신청서_{res.name}_{res.start_time.strftime("%Y%m%d")}.pdf', buffer, 'application/pdf')
    }
    
    # Diff caption to indicate user sent it
    data = {'chat_id': chat_id, 'caption': f"📩 [사용자 제출] 시설 사용 신청서 ({res.name})"}
    
    try:
        r = requests.post(url, data=data, files=files, timeout=10)
        if r.status_code == 200:
            return jsonify({'success': True})
        else:
            return jsonify({'error': f"전송 실패: {r.text}"}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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

    # Headers for processing (though we use openpyxl manual write below)
    
    output = io.BytesIO()
    
    # Use openpyxl directly instead of pandas
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '예약내역'
    
    # Headers
    headers = ['ID', '이름', '전화번호', '사용목적', '시작시간', '종료시간', '상태', '관리자 메모']
    ws.append(headers)
    
    for r in reservations:
        row = [
            r.id,
            r.name,
            r.phone,
            r.purpose,
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

@app.route('/admin/unblock/<phone>', methods=['POST'])
def manual_unblock(phone):
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    blocked = Blacklist.query.filter_by(phone=phone).first()
    if blocked:
        db.session.delete(blocked)
        db.session.commit()
        log_admin_action('admin', f'Unblocked User: {blocked.name} ({phone})')
        
    return jsonify({'success': True})

@app.route('/admin/toggle_pause', methods=['POST'])
def toggle_pause():
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    should_pause = data.get('pause') # Boolean
    reason = data.get('reason', '').strip()
    mode = data.get('mode', 'all')
    
    # List of {start: '...', end: '...'}
    ranges = data.get('ranges', []) 
    
    if should_pause:
        import json
        set_setting('reservation_paused', 'true')
        set_setting('pause_reason', reason)
        set_setting('pause_mode', mode)
        set_setting('pause_ranges', json.dumps(ranges))
        
        # Notice Logic
        current_notice = get_setting('notice_text', '')
        set_setting('original_notice', current_notice) # Backup
        
        if mode == 'all':
            notice_msg = f"[예약 중지 안내] {reason}"
        else:
            # Maybe show first range + etc
            if ranges:
                first = ranges[0]
                count = len(ranges)
                suffix = f" 외 {count-1}건" if count > 1 else ""
                notice_msg = f"[부분 예약 중지] {reason} ({first['start']}~{first['end']}{suffix})"
            else:
                 notice_msg = f"[부분 예약 중지] {reason}"
            
        set_setting('notice_text', notice_msg)
        log_admin_action('admin', f'Paused Reservations ({mode}): {reason}')
    else:
        set_setting('reservation_paused', 'false')
        # Restore original notice if exists
        # We prefer storing empty string if original was empty
        orig = get_setting('original_notice')
        if orig is not None:
             set_setting('notice_text', orig)
        
        log_admin_action('admin', 'Resumed Reservations')
        
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


@app.route('/developer')
def developer_page():
    if not session.get('is_dev'):
        return redirect(url_for('login'))
    
    # Fetch Data
    reservations = Reservation.query.order_by(Reservation.start_time.desc()).all()
    access_logs = AccessLog.query.order_by(AccessLog.timestamp.desc()).limit(100).all()
    admin_logs = AdminLog.query.order_by(AdminLog.timestamp.desc()).limit(100).all()
    error_logs = ErrorLog.query.order_by(ErrorLog.timestamp.desc()).limit(50).all()
    feedback_logs = AdminLog.query.filter_by(admin_type='feedback').order_by(AdminLog.timestamp.desc()).all()
    
    maintenance_mode = get_setting('maintenance_mode') == 'true'

    # Settings
    settings = {
        'notice_text': get_setting('notice_text'),
        'wifi_info': get_setting('wifi_info'),
        'door_pw': get_setting('door_pw'),
        'official_email': get_setting('official_email'),
        'smtp_host': get_setting('smtp_host'),
        'smtp_port': get_setting('smtp_port'),
        'smtp_email': get_setting('smtp_email')
    }

    # Status Map
    status_map = {
        'reserved': '예약중',
        'checked_in': '입실완료',
        'ended': '종료됨',
        'cancelled': '취소됨',
        'noshow_penalty': '노쇼(패널티)'
    }

    return render_template('developer.html', 
                           reservations=reservations,
                           access_logs=access_logs, 
                           admin_logs=admin_logs,
                           error_logs=error_logs,
                           feedback_logs=feedback_logs,
                           settings=settings,
                           maintenance_mode=maintenance_mode,
                           status_map=status_map)

@app.route('/dev/toggle_maintenance', methods=['POST'])
def toggle_maintenance():
    if not session.get('is_dev'): return jsonify({'error': 'Unauthorized'}), 401
    
    current = get_setting('maintenance_mode')
    new_val = 'false' if current == 'true' else 'true'
    set_setting('maintenance_mode', new_val)
    log_admin_action('dev', f'Set Maintenance Mode: {new_val}')
    return jsonify({'success': True, 'mode': new_val})

@app.route('/dev/integrity_check', methods=['POST'])
def integrity_check():
    if not session.get('is_dev'): return jsonify({'error': 'Unauthorized'}), 401
    
    # Check for past 'reserved'
    now = datetime.now()
    past_reserved = Reservation.query.filter(
        Reservation.start_time < now,
        Reservation.status == 'reserved'
    ).all()
    
    report = []
    if past_reserved:
        report.append(f"과거 날짜의 '예약중' 상태 {len(past_reserved)}건 발견. (자동 완료 처리 권장)")
    
    log_admin_action('dev', 'Run Integrity Check')
    return jsonify({'success': True, 'report': report, 'issues_count': len(past_reserved)})

@app.route('/dev/integrity_fix', methods=['POST'])
def integrity_fix():
    if not session.get('is_dev'): return jsonify({'error': 'Unauthorized'}), 401
    
    now = datetime.now()
    past_reserved = Reservation.query.filter(
        Reservation.start_time < now,
        Reservation.status == 'reserved'
    ).all()
    
    count = 0
    for r in past_reserved:
        r.status = 'ended'
        count += 1
        
    db.session.commit()
    log_admin_action('dev', f'Fixed {count} Integrity Issues')
    return jsonify({'success': True, 'fixed_count': count})

@app.route('/dev/reservations/<int:id>/delete', methods=['POST'])
def delete_reservation_dev(id):
    if not session.get('is_dev'): return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        res = Reservation.query.get_or_404(id)
        
        # Manually create log to ensure single transaction commit
        log = AdminLog(
            admin_type='dev',
            action=f'Deleted Reservation ID {id}: {res.name} ({res.start_time})',
            ip_address=request.remote_addr
        )
        
        db.session.add(log)
        db.session.delete(res)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        # The global error handler will catch this and log it to ErrorLog
        raise e

@app.route('/dev/reservations/delete_bulk', methods=['POST'])
def delete_bulk_reservations():
    if not session.get('is_dev'): return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    mode = data.get('mode') # 'all' or 'selected'
    
    try:
        count = 0
        if mode == 'all':
            # Delete All
            count = Reservation.query.delete()
            action_msg = f"Bulk Deleted ALL Data ({count} records)"
        elif mode == 'selected':
            ids = data.get('ids', [])
            if not ids:
                return jsonify({'error': 'No items selected'}), 400
            
            # Delete Selected
            count = Reservation.query.filter(Reservation.id.in_(ids)).delete(synchronize_session=False)
            action_msg = f"Bulk Deleted {count} records (IDs: {ids})"
        else:
             return jsonify({'error': 'Invalid mode'}), 400
             
        # Log Action
        log = AdminLog(
            admin_type='dev',
            action=action_msg,
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()
        
        return jsonify({'success': True, 'count': count})
        
    except Exception as e:
        db.session.rollback()
        raise e

@app.route('/dev/download_logs')
def download_logs_db():
    if not session.get('is_dev'): return redirect(url_for('login'))
    log_db_path = os.path.join(instance_path, 'logs.db')
    if os.path.exists(log_db_path):
        return send_file(log_db_path, as_attachment=True, download_name=f'logs_backup_{datetime.now().strftime("%Y%m%d")}.sqlite')
    else:
        return "Log DB does not exist yet.", 404

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

@app.route('/admin/download_qr_poster')
def download_qr_poster():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    # 1. Generate QR URL
    host_url = request.host_url
    if 'localhost' in host_url or '127.0.0.1' in host_url:
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

    # 2. Create QR Image
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=20,
        border=2,
    )
    qr.add_data(checkin_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGBA')

    # 3. Create A4 Canvas (approx 150 DPI: 1240 x 1754)
    # White background
    width, height = 1240, 1754
    canvas = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(canvas)

    # 4. Load Fonts (Windows default Korean font)
    # Using 'malgun.ttf' (Malgun Gothic)
    font_path = "C:/Windows/Fonts/malgun.ttf"
    if not os.path.exists(font_path):
        font_path = "C:/Windows/Fonts/malgunbd.ttf" # Try bold
    
    try:
        title_font = ImageFont.truetype(font_path, 120)
        subtitle_font = ImageFont.truetype(font_path, 60)
        desc_font = ImageFont.truetype(font_path, 40)
        small_font = ImageFont.truetype(font_path, 30)
    except IOError:
        # Fallback if no font found (should not happen on standard Windows)
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        desc_font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    # 5. Draw Content
    # Border
    border_px = 50
    draw.rectangle([border_px, border_px, width-border_px, height-border_px], outline="black", width=10)

    # Title
    draw.text((width/2, 200), "지혜마루 작은 도서관", font=subtitle_font, fill="black", anchor="mm")
    draw.text((width/2, 350), "입실 체크인", font=title_font, fill="#0056b3", anchor="mm")

    # Place QR
    # Resize QR to fit nicely (e.g. 800x800)
    qr_size = 800
    qr_img = qr_img.resize((qr_size, qr_size))
    qr_x = (width - qr_size) // 2
    qr_y = 500
    canvas.paste(qr_img, (qr_x, qr_y), qr_img)

    # Instructions
    text_y = qr_y + qr_size + 100
    draw.text((width/2, text_y), "스마트폰 카메라를 켜고", font=desc_font, fill="#333", anchor="mm")
    draw.text((width/2, text_y + 60), "위 QR 코드를 스캔하세요", font=desc_font, fill="#333", anchor="mm")
    
    # Detail
    draw.text((width/2, text_y + 180), "예약된 전화번호로 인증 후 입실할 수 있습니다.", font=small_font, fill="#666", anchor="mm")
    draw.text((width/2, text_y + 230), "문의: 관리자 호출", font=small_font, fill="#999", anchor="mm")

    # 6. Save
    output = io.BytesIO()
    canvas.save(output, format='PNG')
    output.seek(0)

    return send_file(output, mimetype='image/png', as_attachment=True, download_name='checkin_poster_a4.png')
    
def create_init_data():
    if not os.path.exists('instance'):
        os.makedirs('instance')
    db.create_all()
    try:
        db.create_all(bind='logs')
    except:
        pass
    
    # Init default settings if empty
    if not Settings.query.all():
        set_setting('notice_text', '지혜마루 작은 도서관에 오신 것을 환영합니다.')
        set_setting('wifi_info', 'ID: JihyeLib / PW: readbooks')
        set_setting('door_pw', '1234*')

if __name__ == '__main__':
    with app.app_context():
        create_init_data()
    app.run(host='0.0.0.0', port=5000, debug=True)
