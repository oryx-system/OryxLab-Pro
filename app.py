from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file, Response, make_response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import openpyxl
import io
from ics import Calendar, Event
import shutil
from dotenv import load_dotenv

# Safe Imports for Dependencies that might be missing in old Docker Images
try:
    from PIL import Image, ImageDraw, ImageFont # Added for QR Poster
except ImportError:
    Image = None
    print("Warning: PIL (Pillow) not found. QR features will fail.")

try:
    import requests # Added for Telegram Notifications
except ImportError:
    requests = None
    print("Warning: requests not found. Telegram notifications will fail.")

try:
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader 
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as PlatypusImage
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    reportlab_available = True
except ImportError:
    reportlab_available = False
    print("Warning: reportlab not found. PDF features will fail.")

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import base64
import binascii
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import arrow
except ImportError:
    arrow = None
    print("Warning: arrow not found. ICS timezone handling will degrade.")

load_dotenv()

app = Flask(__name__)
# Fix for Synology Reverse Proxy (HTTPS -> HTTP)
try:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
except ImportError:
    print("Warning: ProxyFix not available. HTTPS headers may not work correctly.")

app.config['SECRET_KEY'] = 'dev-secret-key-change-this-in-prod'

# Absolute path for DB
basedir = os.path.abspath(os.path.dirname(__file__))


@app.before_request
def auto_logout_if_leaving_admin():
    # Check if user is admin OR developer
    is_admin = session.get('is_admin')
    is_dev = session.get('is_dev')
    
    if is_admin or is_dev:
        # Allow requests to admin/dev pages, login, logout, and static files
        allowed_prefixes = ['/admin', '/login', '/logout', '/static', '/favicon.ico', '/developer', '/dev', '/api']
        
        # Check if the current request path matches any allowed prefix
        is_allowed = any(request.path.startswith(prefix) for prefix in allowed_prefixes)
        
        if not is_allowed:
            # If navigating away from admin/dev/auth/static pages, log out
            session.pop('is_admin', None)
            session.pop('is_dev', None)

# --- Jinja Filters for Developer Console --- #
@app.template_filter('translate_method')
def translate_method_filter(method):
    mapping = {
        'GET': '조회',
        'POST': '전송',
        'PUT': '수정',
        'DELETE': '삭제',
        'HEAD': '헤더',
        'OPTIONS': '옵션'
    }
    return mapping.get(method, method)

@app.template_filter('detect_device')
def detect_device_filter(user_agent):
    if not user_agent:
        return 'Unknown'
    ua = user_agent.lower()
    if 'mobile' in ua or 'android' in ua or 'iphone' in ua or 'ipad' in ua:
        return 'Mobile'
    return 'PC'

@app.template_filter('simplify_ua')
def simplify_ua_filter(user_agent):
    if not user_agent:
        return '-'
    
    ua = user_agent.lower()
    browser = 'Other'
    os_name = 'Other'
    
    # Browser
    if 'chrome' in ua and 'edge' not in ua:
        browser = 'Chrome'
    elif 'safari' in ua and 'chrome' not in ua:
        browser = 'Safari'
    elif 'firefox' in ua:
        browser = 'Firefox'
    elif 'edge' in ua or 'edg' in ua:
        browser = 'Edge'
    elif 'whale' in ua:
        browser = 'Whale'
    elif 'samsungbrowser' in ua:
        browser = 'Samsung'
        
    # OS
    if 'windows' in ua:
        os_name = 'Windows'
    elif 'mac os' in ua:
        os_name = 'macOS'
    elif 'android' in ua:
        os_name = 'Android'
    elif 'iphone' in ua or 'ipad' in ua:
        os_name = 'iOS'
    elif 'linux' in ua:
        os_name = 'Linux'
        
    return f"{browser} ({os_name})"

@app.before_request
def make_session_permanent():
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
    password = db.Column(db.String(200), nullable=False) # Increased length for Hash
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    purpose = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), default='reserved') # reserved, checked_in, ended, cancelled, noshow_penalty
    admin_memo = db.Column(db.Text, nullable=True)
    signature_path = db.Column(db.String(255), nullable=True) # Legacy (File Path)
    signature_blob = db.Column(db.LargeBinary, nullable=True) # New (Database Storage)
    checkout_photo = db.Column(db.String(255), nullable=True) # New: Cleaning photo
    # New Fields for Application Form
    applicant_type = db.Column(db.String(10), default='개인')  # 개인/단체
    org_name = db.Column(db.String(100), nullable=True)  # 단체명 (단체 선택 시)
    facility_basic = db.Column(db.String(100), nullable=True)  # 자료실,문화강좌실,조리실
    facility_extra = db.Column(db.String(100), nullable=True)  # 빔프로젝트,스크린
    expected_count = db.Column(db.Integer, nullable=True)  # 이용예정인원
    birth_date = db.Column(db.String(20), nullable=True)  # 생년월일
    address = db.Column(db.String(200), nullable=True)  # 주소
    email = db.Column(db.String(100), nullable=True)  # 이메일
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        # Name Masking
        masked_name = self.name
        if len(self.name) > 2:
            masked_name = self.name[0] + '*' * (len(self.name) - 2) + self.name[-1]
        elif len(self.name) == 2:
            masked_name = self.name[0] + '*'
        
        # Status Colors (Premium Palette)
        status_colors = {
            'reserved': '#4e73df',        # Blue
            'checked_in': '#1cc88a',      # Green
            'ended': '#858796',           # Gray
            'noshow_penalty': '#e74a3b',  # Red
            'cancelled': '#f6c23e'        # Yellow (Hidden by default but defined)
        }
        bg_color = status_colors.get(self.status, '#4e73df')

        return {
            'id': self.id,
            'title': masked_name,
            'start': self.start_time.isoformat(),
            'end': self.end_time.isoformat(),
            'status': self.status,
            'backgroundColor': bg_color,
            'borderColor': bg_color,
            'textColor': '#ffffff'
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

@app.context_processor
def inject_privacy_policy():
    # Load Privacy Policy Globally
    policy = get_setting('privacy_policy')
    if not policy:
        # Default Logic if empty
        policy = '개인정보 처리방침 내용이 없습니다. 관리자에게 문의하세요.'
    return dict(privacy_policy=policy)

@app.route('/api/admin/settings', methods=['POST'])
def save_admin_settings():
    if not session.get('is_admin') and not session.get('is_dev'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    if not data or 'settings' not in data:
        return jsonify({'error': 'Invalid data'}), 400
        
    for key, value in data['settings'].items():
        set_setting(key, value)
        
    log_admin_action('admin', f'Updated Settings: {list(data["settings"].keys())}')
    return jsonify({'success': True})



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
        'telegram_chat_id': get_setting('telegram_chat_id', ''),
        'privacy_policy': get_setting('privacy_policy', ''),
        'door_qr_token': get_setting('door_qr_token', 'ORYX_LAB_DOOR_2025')
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

        # Try verifying as hash first, then plain text fallback
        is_admin_valid = False
        try:
            is_admin_valid = check_password_hash(saved_admin_pw, password)
        except:
            pass
        if not is_admin_valid:
            is_admin_valid = (saved_admin_pw == password)

        is_dev_valid = False
        try:
            is_dev_valid = check_password_hash(saved_dev_pw, password)
        except:
            pass
        if not is_dev_valid:
            is_dev_valid = (saved_dev_pw == password)

        if is_admin_valid:
            session['is_admin'] = True
            log_admin_action('admin', 'Login')
            return redirect(url_for('admin_page'))
        elif is_dev_valid:
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
        
        saved_dev_pw = get_setting('dev_pw', '123qwe!')
        is_valid = False
        try:
            is_valid = check_password_hash(saved_dev_pw, password)
        except:
            pass
        if not is_valid:
            is_valid = (saved_dev_pw == password)

        if is_valid:
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
    # Include 'ended' and 'noshow_penalty' for calendar visualization
    events = Reservation.query.filter(
        Reservation.status.in_(['reserved', 'checked_in', 'ended', 'noshow_penalty'])
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

@app.route('/api/reservations/availability', methods=['GET'])
def get_availability():
    """Return booked time slots for a given date"""
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'error': 'date parameter required'}), 400
    
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400
    
    day_start = target_date.replace(hour=0, minute=0, second=0)
    day_end = target_date.replace(hour=23, minute=59, second=59)
    
    reservations = Reservation.query.filter(
        Reservation.start_time >= day_start,
        Reservation.start_time <= day_end,
        Reservation.status.in_(['reserved', 'checked_in'])
    ).all()
    
    booked_slots = []
    for res in reservations:
        booked_slots.append({
            'start': res.start_time.strftime('%H:%M'),
            'end': res.end_time.strftime('%H:%M')
        })
    
    return jsonify({'date': date_str, 'booked': booked_slots})

@app.route('/api/reservations', methods=['POST'])
def create_reservation():
    data = request.json
    name = data.get('name')
    phone = data.get('phone')
    password = data.get('password')
    purpose = data.get('purpose')
    start_str = data.get('start')
    end_str = data.get('end')
    
    # Recurring Params
    repeat_type = data.get('repeat_type') # 'weekly' or None
    repeat_count = data.get('repeat_count', 1) 
    
    if not all([name, phone, password, purpose, start_str, end_str]):
        return jsonify({'error': '필수 입력 항목이 누락되었습니다.'}), 400

    try:
        base_start = datetime.fromisoformat(start_str)
        base_end = datetime.fromisoformat(end_str)
        repeat_count = int(repeat_count)
    except ValueError:
        return jsonify({'error': '날짜 형식이 올바르지 않습니다.'}), 400

    if base_start < datetime.now():
        return jsonify({'error': '지난 날짜는 예약할 수 없습니다.'}), 400

    # 1. Prepare Target Slots
    target_slots = []
    if repeat_type == 'weekly' and repeat_count > 1:
        # Limit max to 4 for safety
        count = min(repeat_count, 4)
        for i in range(count):
            delta = timedelta(weeks=i)
            target_slots.append((base_start + delta, base_end + delta))
    else:
        target_slots.append((base_start, base_end))

    # 2. Global Checks (Blacklist) - Check once for the user
    blocked = Blacklist.query.filter_by(phone=phone).first()
    if blocked:
        if blocked.release_date > datetime.now():
            return jsonify({'error': f'예약이 제한된 사용자입니다. (해제일: {blocked.release_date.strftime("%Y-%m-%d")})'}), 403
        else:
            db.session.delete(blocked)
            db.session.commit()

    # 3. Validation Loop (Atomic Check)
    # If ANY slot fails, the whole request fails.
    
    # Pre-fetch Image Blob if exists
    sig_blob = None
    if 'signature' in data and data['signature']:
        try:
             header, encoded = data['signature'].split(',', 1)
             sig_blob = base64.b64decode(encoded)
        except Exception as e:
             print(f"Signature Decode Error: {e}")

    reservations_to_create = []

    for idx, (s_time, e_time) in enumerate(target_slots):
        date_label = s_time.strftime('%Y-%m-%d')
        nth_label = f"{idx + 1}번째 예약({date_label})"

        # A. Pause Check
        if get_setting('reservation_paused') == 'true':
            pause_mode = get_setting('pause_mode', 'all')
            reason = get_setting('pause_reason', '시스템 점검')
            
            should_block = False
            if pause_mode == 'all':
                should_block = True
            elif pause_mode == 'partial':
                res_date = s_time.strftime('%Y-%m-%d')
                import json
                try:
                    pause_ranges = json.loads(get_setting('pause_ranges', '[]'))
                except:
                    pause_ranges = []
                
                # Fallback logic
                if not pause_ranges:
                    p_s = get_setting('pause_start')
                    p_e = get_setting('pause_end')
                    if p_s and p_e: pause_ranges.append({'start': p_s, 'end': p_e})

                for rng in pause_ranges:
                    if rng.get('start') <= res_date <= rng.get('end'):
                        should_block = True
                        if rng.get('reason'): reason = rng.get('reason')
                        break
            
            if should_block:
                return jsonify({'error': f'[{nth_label}] 해당 기간은 예약이 일시 중지되었습니다.\n사유: {reason}'}), 403

        # B. Overlap Check
        overlap = Reservation.query.filter(
            Reservation.start_time < e_time,
            Reservation.end_time > s_time,
            Reservation.status.in_(['reserved', 'checked_in'])
        ).first()
        
        if overlap:
            return jsonify({'error': f'[{nth_label}] 이미 예약된 시간입니다.'}), 409

        # C. Daily Limit Check
        t_start = s_time.replace(hour=0, minute=0, second=0, microsecond=0)
        t_end = s_time.replace(hour=23, minute=59, second=59, microsecond=999999)
        daily_res = Reservation.query.filter(
            Reservation.phone == phone,
            Reservation.start_time >= t_start,
            Reservation.start_time <= t_end,
            Reservation.status.in_(['reserved', 'checked_in', 'ended'])
        ).all()
        
        total_minutes = sum([(r.end_time - r.start_time).total_seconds() / 60 for r in daily_res])
        new_duration = (e_time - s_time).total_seconds() / 60
        
        if total_minutes + new_duration > 240:
             return jsonify({'error': f'[{nth_label}] 하루 최대 4시간까지만 이용 가능합니다.'}), 400

        # Ready to create
        new_res = Reservation(
            name=name.strip(),
            phone=phone.strip(),
            password=generate_password_hash(password.strip()),
            purpose=purpose.strip(),
            start_time=s_time,
            end_time=e_time,
            signature_blob=sig_blob,
            # New Fields
            applicant_type=data.get('applicant_type', '개인'),
            org_name=data.get('org_name', ''),
            facility_basic=data.get('facility_basic', ''),
            facility_extra=data.get('facility_extra', ''),
            expected_count=int(data.get('expected_count')) if data.get('expected_count') else None,
            birth_date=data.get('birth_date', ''),
            address=data.get('address', ''),
            email=data.get('email', '')
        )
        reservations_to_create.append(new_res)

    # 4. Atomic Commit
    try:
        db.session.add_all(reservations_to_create)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'데이터베이스 저장 중 오류가 발생했습니다: {str(e)}'}), 500
    
    # 5. Notifications
    # If multiple, send summary or multiple messages.
    # For now, we only alert the FIRST one to avoid spamming admin, or summary.
    try:
        first_res = reservations_to_create[0]
        count = len(reservations_to_create)
        
        type_str = f"[정기 예약 {count}건]" if count > 1 else "[새 예약]"
        
        # PII Masking (Default: ON, can be disabled in developer settings)
        mask_enabled = get_setting('telegram_mask_info', 'true') == 'true'
        safe_name = mask_name(first_res.name) if mask_enabled else first_res.name
        safe_phone = mask_phone(first_res.phone) if mask_enabled else first_res.phone
        
        msg = f"{type_str}\n- 예약자: {safe_name}\n- 전화번호: {safe_phone}\n- 첫 예약: {first_res.start_time.strftime('%Y-%m-%d %H:%M')}"
        if count > 1:
            msg += f"\n- 기간: {count}주간 반복"
        
        send_telegram_alert(msg)
    except:
        pass

    # Return ID of the first reservation for ICS download
    return jsonify({'success': True, 'id': reservations_to_create[0].id, 'count': len(reservations_to_create)}), 201

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
    # Use Arrow with KST timezone (uses globally safe-imported arrow)
    if arrow:
        kst = 'Asia/Seoul'
        e.begin = arrow.get(res.start_time, kst)
        e.end = arrow.get(res.end_time, kst)
    else:
        # Fallback: use datetime directly (may have timezone issues)
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
        
    # Match phone first, then verify password
    reservations = Reservation.query.filter_by(
        phone=phone
    ).order_by(Reservation.start_time.desc()).all()
    
    wifi_info = get_setting('wifi_info', '정보 없음')
    door_pw = get_setting('door_pw', '정보 없음')

    results = []
    for r in reservations:
        if check_password_hash(r.password, password):
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

@app.route('/api/reservations/<int:id>/modify', methods=['POST'])
def modify_reservation(id):
    """Modify reservation: cancel original and create new one"""
    res = Reservation.query.get_or_404(id)
    data = request.json
    password = data.get('password')
    new_start = data.get('new_start')
    new_end = data.get('new_end')
    
    if not password or not new_start or not new_end:
        return jsonify({'error': '필수 정보가 누락되었습니다.'}), 400
    
    # Verify password
    if not check_password_hash(res.password, password):
        return jsonify({'error': '비밀번호가 일치하지 않습니다.'}), 403
    
    # Parse new times
    try:
        new_start_dt = datetime.fromisoformat(new_start)
        new_end_dt = datetime.fromisoformat(new_end)
    except ValueError:
        return jsonify({'error': '날짜 형식이 올바르지 않습니다.'}), 400
    
    if new_start_dt < datetime.now():
        return jsonify({'error': '지난 시간으로는 변경할 수 없습니다.'}), 400
    
    # Check for overlaps (excluding current reservation)
    overlap = Reservation.query.filter(
        Reservation.id != id,
        Reservation.start_time < new_end_dt,
        Reservation.end_time > new_start_dt,
        Reservation.status.in_(['reserved', 'checked_in'])
    ).first()
    
    if overlap:
        return jsonify({'error': '해당 시간에 이미 다른 예약이 있습니다.'}), 409
    
    # Cancel original reservation
    res.status = 'cancelled'
    
    # Create new reservation with same info
    new_res = Reservation(
        name=res.name,
        phone=res.phone,
        password=res.password,
        purpose=res.purpose,
        start_time=new_start_dt,
        end_time=new_end_dt,
        status='reserved',
        facility_basic=(res.facility_basic or ''),
        facility_extra=(res.facility_extra or ''),
        expected_count=res.expected_count,
        birth_date=res.birth_date,
        address=res.address,
        email=res.email
    )
    db.session.add(new_res)
    db.session.commit()
    
    return jsonify({'success': True, 'message': '예약이 변경되었습니다.', 'new_id': new_res.id})

@app.route('/api/checkin', methods=['POST'])
def checkin_process():
    data = request.json
    phone = data.get('phone')
    password = data.get('password')
    qr_token = data.get('qr_token')

    if not phone or not password:
        return jsonify({'error': '전화번호와 비밀번호를 모두 입력해주세요.'}), 400
    
    if not qr_token:
        return jsonify({'error': 'QR 스캔이 필요합니다.'}), 400
        
    # Verify QR Token
    valid_token = get_setting('door_qr_token', 'ORYX_LAB_DOOR_2025')
    if qr_token != valid_token:
        # Before rejecting, log it maybe?
        return jsonify({'error': '유효하지 않은 QR 코드입니다. 도서관 출입문의 코드를 스캔해주세요.'}), 403

    now = datetime.now()
    margin = timedelta(minutes=30) # 30 mins before start

    # 1. Credential Check (First check if user exists/password matches ANY reservation)
    # This separates "Authentication Error" from "No Reservation Error"
    all_reservations = Reservation.query.filter(Reservation.phone == phone).all()
    credential_valid = False
    for r in all_reservations:
        if check_password_hash(r.password, password):
            credential_valid = True
            break
            
    if not credential_valid:
        return jsonify({'error': '전화번호 또는 비밀번호가 일치하지 않습니다.'}), 404

    # 2. Status Check (Is there anything to check in?)
    candidates = Reservation.query.filter(
        Reservation.phone == phone,
        Reservation.status == 'reserved'
    ).all()
    
    valid_candidates = []
    for c in candidates:
        if check_password_hash(c.password, password):
            valid_candidates.append(c)

    if not valid_candidates:
         return jsonify({'error': '체크인할 수 있는 예약 내역이 없습니다.\n(이미 체크인했거나 종료된 예약일 수 있습니다)'}), 404

    # 3. Time Check
    target_res = None
    for r in valid_candidates:
        # Checkin allowed: [Start - 30min] ~ [Midnight of that day]
        midnight = r.start_time.replace(hour=23, minute=59, second=59)
        if (r.start_time - margin) <= now <= midnight: 
             target_res = r
             break
    
    if not target_res:
         # Check if too early or too late
        return jsonify({'error': '현재 체크인 가능한 시간이 아닙니다.\n(예약 30분 전부터 당일 자정까지 가능)'}), 404
        
    target_res.status = 'checked_in'
    db.session.commit()
    return jsonify({'success': True, 'name': target_res.name})

@app.route('/api/checkout', methods=['POST'])
def checkout_process():
    # User Request: Remove photo upload function
    data = request.json or request.form
    phone = data.get('phone')
    
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

    # No Photo Upload
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
    set_setting('door_qr_token', data.get('door_qr_token', 'ORYX_LAB_DOOR_2025'))
    
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
         
    set_setting('admin_pw', generate_password_hash(new_pw))
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



def _draw_border(canvas, doc):
    canvas.saveState()
    w, h = A4
    margin = 15*mm
    canvas.setLineWidth(0.8)
    canvas.rect(margin, margin, w - 2*margin, h - 2*margin)
    canvas.restoreState()

def _generate_pdf_buffer(res):
    """
    PDF 생성 - 원본 종이 양식과 100% 동일하게 출력
    원본 양식: 양식.jpg 기준으로 정확히 복제
    """
    # 1. Register Font
    font_path = "C:/Windows/Fonts/malgun.ttf"
    bold_path = "C:/Windows/Fonts/malgunbd.ttf"
    batang_path = "C:/Windows/Fonts/batang.ttc"
    
    if not os.path.exists(font_path):
        linux_font = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
        linux_bold = "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"
        if os.path.exists(linux_font):
            font_path = linux_font
            bold_path = linux_bold if os.path.exists(linux_bold) else linux_font
        else:
            print("ERROR: No Korean font found!")
            return None

    try:
        pdfmetrics.registerFont(TTFont('Malgun', font_path))
        if os.path.exists(bold_path):
            pdfmetrics.registerFont(TTFont('MalgunBd', bold_path))
        else:
            pdfmetrics.registerFont(TTFont('MalgunBd', font_path))
            
        # Register Batang (Myeongjo)
        if os.path.exists(batang_path):
            try:
                pdfmetrics.registerFont(TTFont('Batang', batang_path, subfontIndex=0))
            except: pass
    except Exception as e:
        print(f"PDF Font Registration Error: {e}")
        pass

    buffer = io.BytesIO()
    # A4 page (210mm x 297mm) - 중앙 배치
    doc = SimpleDocTemplate(buffer, pagesize=A4, 
                            leftMargin=20*mm, rightMargin=20*mm, 
                            topMargin=15*mm, bottomMargin=15*mm)
    
    elements = []
    
    # Fonts Check
    reg_fonts = pdfmetrics.getRegisteredFontNames()
    s_font = 'Batang' if 'Batang' in reg_fonts else 'Malgun'
    
    # Styles
    # 제목 스타일 (테이블 내에서 쓰일 것이므로 ParagraphStyle로 정의하되, 정렬은 TableStyle에서 제어)
    style_title = ParagraphStyle('Title', fontName='MalgunBd', fontSize=20, alignment=TA_CENTER, leading=24)
    
    style_cell = ParagraphStyle('Cell', fontName=s_font, fontSize=10, alignment=TA_CENTER, leading=13, wordWrap='CJK')
    style_cell_left = ParagraphStyle('CellLeft', fontName=s_font, fontSize=10, alignment=TA_LEFT, leading=13, leftIndent=2*mm, wordWrap='CJK')
    style_cell_bold = ParagraphStyle('CellBold', fontName=s_font, fontSize=10, alignment=TA_CENTER, leading=13, wordWrap='CJK')
    
    style_footer = ParagraphStyle('Footer', fontName=s_font, fontSize=11, alignment=TA_CENTER, leading=16)
    style_date = ParagraphStyle('Date', fontName=s_font, fontSize=12, alignment=TA_CENTER, leading=14)
    # User Request: Batang + Extra Bold (Simulated with Stroke)
    style_recipient = ParagraphStyle('Recipient', fontName=s_font, fontSize=16, alignment=TA_CENTER, leading=20, textStrokeWidth=1, textStrokeColor=colors.black)
    style_sig = ParagraphStyle('Sig', fontName=s_font, fontSize=11, alignment=TA_CENTER, leading=14)
    style_sig_right = ParagraphStyle('SigRight', fontName=s_font, fontSize=11, alignment=TA_RIGHT, leading=14)

    def P(text): return Paragraph(str(text) if text else "", style_cell)
    def PL(text): return Paragraph(str(text) if text else "", style_cell_left)
    def PB(text): return Paragraph(str(text) if text else "", style_cell_bold)

    # Data Preparation
    p_str = res.phone
    if len(p_str) == 11 and p_str.startswith('010'):
        p_str = f"{p_str[:3]}-{p_str[3:7]}-{p_str[7:]}"
    
    start_y = res.start_time.strftime('%Y')
    start_m = res.start_time.strftime('%m')
    start_d = res.start_time.strftime('%d')
    start_h = res.start_time.strftime('%H')
    end_y = res.end_time.strftime('%Y')
    end_m = res.end_time.strftime('%m')
    end_d = res.end_time.strftime('%d')
    end_h = res.end_time.strftime('%H')
    
    date_line1 = f"{start_y}년 {start_m}월 {start_d}일 {start_h}시 부터"
    date_line2 = f"{end_y}년 {end_m}월 {end_d}일 {end_h}시 까지"
    
    days_diff = (res.end_time.date() - res.start_time.date()).days
    if days_diff == 0: days_diff = 1
    
    facility_basic_list = (res.facility_basic or '').split(',') if res.facility_basic else []
    fb_display = ""
    for f in ['자료실', '문화강좌실', '조리실']:
        mark = "■" if f in facility_basic_list else "□"
        # User Request: Spacing Reduced (1/2 of x3).
        fb_display += f"{mark} {f}" + "&nbsp;"*5
    
    facility_extra_list = (res.facility_extra or '').split(',') if res.facility_extra else []
    fe_display = ""
    for f in ['빔프로젝트', '스크린']:
        mark = "■" if f in facility_extra_list else "□"
        fe_display += f"{mark} {f}" + "&nbsp;"*5
    
    count_display = f"{res.expected_count} 명" if res.expected_count else "명"
    birth_display = res.birth_date or ""
    addr_display = res.address or ""
    email_display = res.email or ""

    if res.applicant_type == '단체' and res.org_name:
        display_name = res.org_name
        rep_name = res.name
    else:
        display_name = res.name
        rep_name = ""

    # ===== [통합 테이블 구조] =====
    # 제목 + 메인 테이블 + 하단 문구까지 모두 하나의 메인 테이블(Main Table)로 통합하여
    # 엑셀 양식과 동일한 외곽선 및 레이아웃을 구현함.

    # 1. 메인 데이터 준비
    # 열 너비: [26, 24, 45, 24, 51] -> 합계 170mm (Rollback: 이메일 51mm 확보)
    col_widths = [26*mm, 24*mm, 45*mm, 24*mm, 51*mm]
    
    # Row 0: 제목
    title_row = [Paragraph("군북지혜마루작은도서관 시설 사용 허가 신청서", style_title), "", "", "", ""]
    
    # Rows 1~10: 본문
    main_rows = [
        [PB("사용 목적 (회의, 행사 등)"), "", P(res.purpose), "", ""],
        [PB("신청인<br/>(사용자 또는<br/>단체)"), PB("사용자(단체)명"), P(display_name), PB("전화번호"), P(p_str)],
        ["", PB("대표자(성명)"), P(rep_name), PB("사업자등록번호<br/>(생년월일)"), P(birth_display)],
        ["", PB("주소"), P(addr_display), "", ""],
        ["", PB("담당자"), P(""), PB("E-mail"), P(email_display)],
        [PB("사용시설"), PB("기본시설"), PL(fb_display), "", ""],
        [PB(""), PB("부대시설 및<br/>설비"), PL(fe_display), "", ""],
        [PB("사용기간"), P(f"{date_line1}<br/>{date_line2}"), "", "", PB(f"( {days_diff}일간 )<br/>*횟수 1회")],
        [PB("이용예정인원"), P(count_display), "", "", ""],
        [PB("사용료 등"), P("해당없음"), "", "", ""]
    ]

    # --- Footer Rows (Inside Main Table) ---
    
    # 1. Declaration (Row 11)
    footer_text1 = Paragraph("위와 같이 「금산군 작은도서관 설치 및 운영 조례」 제4조제4항에 따라<br/>작은도서관의 (    시설    ) 사용을 신청합니다.", style_footer)
    row_decl = [footer_text1, "", "", "", ""]
    
    # 2. Date (Row 12)
    # Using current date or reservation start date? Usually application date = today.
    d_y = datetime.now().strftime('%Y')
    d_m = datetime.now().strftime('%m')
    d_d = datetime.now().strftime('%d')
    date_str = f"{d_y} 년    {d_m} 월    {d_d} 일"
    date_text = Paragraph(date_str, style_date)
    row_date = [date_text, "", "", "", ""]

    # 3. Signature Section (Row 13)
    # 서명 이미지 준비
    
    sig_cell_content = []
    sig_img_flowable = None
    
    # 텍스트는 항상 표시 (User Request: "글자는 안보여 잘 넣어봐")
    # User Request: Text size 70% reduced.
    text_p = Paragraph('<font size="8">(서명 또는 날인)</font>', style_sig)
    
    if res.signature_blob:
        try:
            img_io = io.BytesIO(res.signature_blob)
            # Width/Height tuned: Significantly larger (40mm)
            sig_img_flowable = PlatypusImage(img_io, width=40*mm, height=15*mm)
        except Exception as e:
            print(f"Signature Blob Error: {e}")
    elif res.signature_path:
        sig_full_path = os.path.join(instance_path, 'signatures', res.signature_path)
        if os.path.exists(sig_full_path):
            try:
                sig_img_flowable = PlatypusImage(sig_full_path, width=40*mm, height=15*mm)
            except Exception as e:
                print(f"Signature File Error: {e}")
    
    if sig_img_flowable:
        # 이미지가 있으면 이미지 위에, 텍스트 아래에 (Stacking)
        sig_cell_content = [sig_img_flowable, text_p]
    else:
        sig_cell_content = [text_p]
    
    # 서명란: 우측 정렬된 "신청인 XXX (서명)" 형태를 구현하기 위해 Nested Table 사용
    # 전체 170mm 중 우측에 쏠리게 배치
    # [Label(60), Name(40), Sig(50)] = 150mm inside the merged cell
    
    sig_nested_data = [
        [Paragraph("신청인(단체명)", style_sig_right), Paragraph(display_name, style_sig), sig_cell_content],
        [Paragraph("성  명(대표자)", style_sig_right), Paragraph(res.name, style_sig), ""]
    ]
    
    # Parent Row Height is 21mm. Nested [9, 12].
    # Reverting to tight spacing (21mm total). Sig image (15mm) fits in SPANNED cell (21mm).
    sig_nested_table = Table(sig_nested_data, colWidths=[60*mm, 40*mm, 50*mm], rowHeights=[9*mm, 12*mm])
    sig_nested_table.setStyle(TableStyle([
        ('SPAN', (2,0), (2,1)), # Span Sig Image across both rows
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0,0), (0,1), 'RIGHT'),  # 라벨 우측 정렬
        ('ALIGN', (1,0), (1,1), 'CENTER'), # 이름 중앙 정렬
        ('ALIGN', (2,0), (2,1), 'CENTER'), # 서명 중앙 정렬 (이미지/텍스트 위치)
        ('VALIGN', (2,0), (2,1), 'MIDDLE'),
    ]))
    
    row_sig = [sig_nested_table, "", "", "", ""]
    
    # 4. Recipient (Row 14)
    # User Request: Batang + Bold tag
    recipient_text = Paragraph("<b>금산다락원장  귀하</b>", style_recipient)
    row_recipient = [recipient_text, "", "", "", ""]
    
    # 전체 데이터 합치기
    full_data = [title_row] + main_rows + [row_decl, row_date, row_sig, row_recipient]
    
    # 행 높이 설정 (User Request: Footer -30%, Body +30% redistributed)
    # Title: 25mm (Fixed)
    # Footer Original: [20, 15, 30, 25] = 90mm -> New (70%): [14, 10, 21, 18] = 63mm (-27mm)
    # Body Original: [12, 15, 12, 12, 12, 12, 12, 18, 12, 12] = 129mm
    # Body Target: 129 + 27 = 156mm.
    # Distributed approx +2~3mm per row:
    # New Body: [15, 18, 15, 15, 15, 15, 15, 20, 14, 14]
    
    full_row_heights = [25*mm] + \
                       [15*mm, 18*mm, 15*mm, 15*mm, 15*mm, 15*mm, 15*mm, 20*mm, 14*mm, 14*mm] + \
                       [14*mm, 10*mm, 21*mm, 18*mm]
    
    main_table = Table(full_data, colWidths=col_widths, rowHeights=full_row_heights)
    
    # 스타일 정의
    t_style_cmds = [
        ('FONTNAME', (0,0), (-1,-1), s_font),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        
        # 1. 메인 테이블 전체 외곽선 (Footer 포함)
        ('BOX', (0,0), (-1,-1), 0.4, colors.black),
        
        # 2. 제목 행 (Row 0)
        ('SPAN', (0,0), (-1,0)),
        ('VALIGN', (0,0), (-1,0), 'MIDDLE'),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('LINEBELOW', (0,0), (-1,0), 0.4, colors.black),
        
        # 3. 본문 그리드 (Rows 1~10)
        ('INNERGRID', (0,1), (-1,10), 0.4, colors.black),
        ('LINEBELOW', (0,10), (-1,10), 0.4, colors.black), # 본문 끝 선
        
        ('VALIGN', (0,1), (-1,10), 'MIDDLE'),
        ('ALIGN', (0,1), (-1,10), 'CENTER'),
        ('ALIGN', (2,6), (2,7), 'LEFT'), # 시설 체크박스 좌측 정렬
        
        # 본문 셀 병합
        ('SPAN', (0,1), (1,1)), ('SPAN', (2,1), (4,1)), # 사용목적
        ('SPAN', (0,2), (0,5)), # 신청인(라벨)
        ('SPAN', (2,4), (4,4)), # 주소
        ('SPAN', (0,6), (0,7)), # 사용시설(라벨)
        ('SPAN', (2,6), (4,6)), ('SPAN', (2,7), (4,7)), # 체크박스들
        ('SPAN', (1,8), (3,8)), # 사용기간
        ('SPAN', (1,9), (4,9)), # 인원
        ('SPAN', (1,10), (4,10)), # 사용료
        
        # 4. Footer Rows 스타일링
        # Declaration (Row 11)
        ('SPAN', (0,11), (-1,11)),
        ('VALIGN', (0,11), (-1,11), 'MIDDLE'),
        ('ALIGN', (0,11), (-1,11), 'CENTER'),
        
        # Date (Row 12)
        ('SPAN', (0,12), (-1,12)),
        ('VALIGN', (0,12), (-1,12), 'MIDDLE'),
        ('ALIGN', (0,12), (-1,12), 'CENTER'),
        
        # Signature (Row 13)
        ('SPAN', (0,13), (-1,13)),
        ('VALIGN', (0,13), (-1,13), 'MIDDLE'),
        ('ALIGN', (0,13), (-1,13), 'CENTER'), # Nested Table Center Align (Updated)
        
        # Recipient (Row 14)
        ('SPAN', (0,14), (-1,14)),
        ('VALIGN', (0,14), (-1,14), 'BOTTOM'),
        ('ALIGN', (0,14), (-1,14), 'CENTER'),
        ('BOTTOMPADDING', (0,14), (-1,14), 2*mm), # 귀하 텍스트 여백 
    ]
    
    main_table.setStyle(TableStyle(t_style_cmds))
    elements.append(main_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def _send_email_with_pdf(to_email, subject, body, pdf_buffer, filename):
    return _send_email_with_attachment(to_email, subject, body, pdf_buffer, filename, 'application/pdf')

def _send_email_with_attachment(to_email, subject, body, file_buffer, filename, mimetype='application/octet-stream'):
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
        
        file_buffer.seek(0)
        part = MIMEApplication(file_buffer.read(), Name=filename)
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
        download_name=f'{res.name}_{res.start_time.strftime("%Y%m%d")}.pdf'
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
        
    period = request.json.get('period', 'week') # week, half, month, custom
    official_email = get_setting('official_email')
    
    if not official_email:
        return jsonify({'error': '담당자 이메일이 설정되지 않았습니다.'}), 400
        
    # Date Calculation
    today = datetime.now()
    query = Reservation.query
    
    if period == 'custom':
        # Custom filter from frontend
        filter_date = request.json.get('date')
        filter_status = request.json.get('status')
        search_q = request.json.get('q')
        title_suffix = "검색결과"
        
        # Date filter
        if filter_date:
            try:
                if ' to ' in filter_date or ' ~ ' in filter_date:
                    separator = ' ~ ' if ' ~ ' in filter_date else ' to '
                    start_str, end_str = filter_date.split(separator)
                    start_date = datetime.strptime(start_str.strip(), '%Y-%m-%d')
                    end_date = datetime.strptime(end_str.strip(), '%Y-%m-%d') + timedelta(days=1)
                    query = query.filter(Reservation.start_time >= start_date, Reservation.start_time < end_date)
                else:
                    target_date = datetime.strptime(filter_date.strip(), '%Y-%m-%d')
                    next_date = target_date + timedelta(days=1)
                    query = query.filter(Reservation.start_time >= target_date, Reservation.start_time < next_date)
            except ValueError:
                pass
        
        # Status filter
        if filter_status:
            query = query.filter(Reservation.status == filter_status)
        
        # Search filter
        if search_q:
            import re
            name_phone_match = re.match(r'^(.+?)\s*\(([0-9\-]+)\)$', search_q.strip())
            if name_phone_match:
                search_name = f"%{name_phone_match.group(1).strip()}%"
                search_phone = f"%{name_phone_match.group(2).strip()}%"
            else:
                search_name = f"%{search_q}%"
                search_phone = f"%{search_q}%"
            query = query.filter(db.or_(
                Reservation.name.like(search_name),
                Reservation.phone.like(search_phone)
            ))
    elif period == 'week':
        start_date = today - timedelta(days=7)
        title_suffix = "주간"
        query = query.filter(Reservation.start_time >= start_date)
    elif period == 'half':
        start_date = today - timedelta(days=15)
        title_suffix = "보름"
        query = query.filter(Reservation.start_time >= start_date)
    elif period == 'month':
        start_date = today - timedelta(days=30)
        title_suffix = "월간"
        query = query.filter(Reservation.start_time >= start_date)
    else:
        return jsonify({'error': 'Invalid period'}), 400
        
    # Fetch Reservations (valid statuses only)
    reservations = query.filter(
        Reservation.status.in_(['reserved', 'checked_in', 'ended'])
    ).order_by(Reservation.start_time).all()
    
    if not reservations:
        return jsonify({'error': '해당 기간에 예약이 없습니다.'}), 404
    
    # Get format option (merged PDF or individual ZIP)
    file_format = request.json.get('format', 'merged')
    
    # Determine period string for email body
    if period == 'custom':
        filter_date = request.json.get('date', '')
        period_str = filter_date if filter_date else '검색 조건'
    else:
        period_str = f"{start_date.strftime('%Y-%m-%d')} ~ {today.strftime('%Y-%m-%d')}"
    
    if file_format == 'zip':
        # Generate individual PDFs and ZIP them
        import zipfile
        
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for idx, res in enumerate(reservations, 1):
                pdf_buffer = _generate_pdf_buffer(res)
                if pdf_buffer:
                    pdf_name = f"{idx:03d}_{res.name}_{res.start_time.strftime('%Y%m%d')}.pdf"
                    zf.writestr(pdf_name, pdf_buffer.read())
        
        zip_buffer.seek(0)
        buffer = zip_buffer
        filename = f"지혜마루_{title_suffix}_예약모음_{today.strftime('%Y%m%d')}.zip"
        mimetype = 'application/zip'
    else:
        # Generate Merged PDF using PyPDF2
        from PyPDF2 import PdfMerger
        
        merger = PdfMerger()
        
        for res in reservations:
            pdf_buffer = _generate_pdf_buffer(res)
            if pdf_buffer:
                merger.append(pdf_buffer)
        
        buffer = io.BytesIO()
        merger.write(buffer)
        merger.close()
        buffer.seek(0)
        filename = f"지혜마루_{title_suffix}_예약모음_{today.strftime('%Y%m%d')}.pdf"
        mimetype = 'application/pdf'
    
    # Send Email
    subject = f"[지혜마루] 시설 사용 신청서 모음 ({title_suffix})"
    
    body = f"""안녕하세요.
지혜마루 작은도서관입니다.

{title_suffix} 시설 사용 신청서 모음을 송부드립니다.
기간: {period_str}
총 건수: {len(reservations)}건

감사합니다."""

    success, error = _send_email_with_attachment(official_email, subject, body, buffer, filename, mimetype)

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
    is_valid = (res.phone == phone) and check_password_hash(res.password, password)
    
    if not is_valid:
        return jsonify({'error': '권한이 없습니다 (정보 불일치)'}), 403
        
    buffer = _generate_pdf_buffer(res)
    if not buffer:
        return jsonify({'error': 'PDF 생성 오류'}), 500
        
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=False, # Preview in browser
        download_name=f'{res.name}_{res.start_time.strftime("%Y%m%d")}.pdf'
    )

@app.route('/api/reservations/<int:id>/send_to_admin', methods=['POST'])
def user_send_pdf_to_admin(id):
    data = request.json
    phone = data.get('phone')
    password = data.get('password')
    
    res = Reservation.query.get_or_404(id)
    
    # Verify Owner
    is_valid = (res.phone == phone) and check_password_hash(res.password, password)
    
    if not is_valid:
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


@app.route('/admin/download_excel')
def download_excel():
    if not session.get('is_admin') and not session.get('is_dev'):
        return redirect(url_for('login'))
    
    # Filter Logic
    query = Reservation.query
    
    # DEBUG: Log received parameters
    print(f"[EXCEL DEBUG] Received params - date: '{request.args.get('date')}', status: '{request.args.get('status')}', q: '{request.args.get('q')}'")
    print(f"[EXCEL DEBUG] Full args: {dict(request.args)}")
    
    # 1. Date Filter (Range Support)
    filter_date = request.args.get('date')
    if filter_date:
        try:
            if ' to ' in filter_date or ' ~ ' in filter_date:
                # Support both ' to ' and ' ~ ' separators (flatpickr locale differences)
                separator = ' ~ ' if ' ~ ' in filter_date else ' to '
                start_str, end_str = filter_date.split(separator)
                start_date = datetime.strptime(start_str.strip(), '%Y-%m-%d')
                end_date = datetime.strptime(end_str.strip(), '%Y-%m-%d') + timedelta(days=1) # Include end date
                query = query.filter(Reservation.start_time >= start_date, Reservation.start_time < end_date)
            else:
                target_date = datetime.strptime(filter_date.strip(), '%Y-%m-%d')
                next_date = target_date + timedelta(days=1)
                query = query.filter(Reservation.start_time >= target_date, Reservation.start_time < next_date)
        except ValueError:
            pass # Invalid date format, ignore
            
    # 2. Status Filter
    # (Retrieve blocked phones from Blacklist model)
    blocked_phone_entries = Blacklist.query.all()
    blocked_phones = [b.phone for b in blocked_phone_entries]

    filter_status = request.args.get('status')
    if filter_status:
        if filter_status == 'noshow_blocked':
            # Combined filter: noshow_penalty status OR phone in blacklist
            query = query.filter(db.or_(
                Reservation.status == 'noshow_penalty',
                Reservation.phone.in_(blocked_phones)
            ))
        elif filter_status == 'blocked':
            # Legacy support for blocked-only filter
            query = query.filter(Reservation.phone.in_(blocked_phones))
        else:
            query = query.filter(Reservation.status == filter_status)
        
    # 3. Search Filter (Name, Phone, Status)
    search_q = request.args.get('q')
    if search_q:
        # Handle "이름 (전화번호)" format from frontend autocomplete
        import re
        name_phone_match = re.match(r'^(.+?)\s*\(([0-9\-]+)\)$', search_q.strip())
        if name_phone_match:
            # Extract name and phone separately
            search_name = f"%{name_phone_match.group(1).strip()}%"
            search_phone = f"%{name_phone_match.group(2).strip()}%"
        else:
            search_name = f"%{search_q}%"
            search_phone = f"%{search_q}%"
        search = f"%{search_q}%"
        
        # Define Frontend Keywords for robust matching
        # (Must match 'admin.html' data-search attributes)
        status_keywords = {
            'reserved': ['예약중', '예약됨', '예약'],
            'checked_in': ['체크인', '이용중', '입실완료', '이용', '입실'],
            'ended': ['종료', '이용완료', '완료'],
            'cancelled': ['취소', '취소됨'],
            'noshow_penalty': ['노쇼'],
            'blocked': ['차단', '차단됨']
        }
        
        # Find which statuses match the search query
        matched_statuses = []
        is_blocked_search = False
        
        for status_code, keywords in status_keywords.items():
            for k in keywords:
                if search_q in k or k in search_q:
                    if status_code == 'blocked':
                        is_blocked_search = True
                    else:
                        matched_statuses.append(status_code)
                    break
        
        # Remove duplicates
        matched_statuses = list(set(matched_statuses))
        
        conditions = [
            Reservation.name.like(search_name),
            Reservation.phone.like(search_phone)
        ]
        
        if matched_statuses:
            conditions.append(Reservation.status.in_(matched_statuses))
            
        if is_blocked_search and blocked_phones:
             conditions.append(Reservation.phone.in_(blocked_phones))
            
        with open('excel_debug.log', 'a', encoding='utf-8') as f:
            f.write(f"Search query: {search_q}\n")
            f.write(f"Search pattern: {search}\n")
            f.write(f"Conditions count: {len(conditions)}\n")
        query = query.filter(db.or_(*conditions))

        
    # Order by Start Time Desc
    reservations = query.order_by(Reservation.start_time.desc()).all()
    with open('excel_debug.log', 'a', encoding='utf-8') as f:
        f.write(f"Total reservations found: {len(reservations)}\\n")
    
    # Status Translation Map
    status_map = {
        'reserved': '예약됨',
        'cancelled': '취소됨',
        'checked_in': '입실완료',
        'checked_out': '퇴실완료',
        'ended': '이용완료',
        'noshow_penalty': '노쇼(패널티)'
    }

    output = io.BytesIO()
    
    # Use openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '예약내역'
    
    # All Data Headers
    headers = [
        'ID', '이름', '전화번호', '생년월일', '이메일', '주소',
        '신청유형', '단체명', '사용목적', 
        '기본시설', '부대시설', '이용예정인원',
        '시작시간', '종료시간', '상태', '관리자 메모', '신청일시'
    ]
    ws.append(headers)
    
    for r in reservations:
        row = [
            r.id,
            r.name,
            r.phone,
            r.birth_date or '',
            r.email or '',
            r.address or '',
            r.applicant_type or '개인',
            r.org_name or '',
            r.purpose,
            r.facility_basic or '',
            r.facility_extra or '',
            r.expected_count or 0,
            r.start_time,
            r.end_time,
            status_map.get(r.status, r.status),
            r.admin_memo,
            r.created_at
        ]
        ws.append(row)
        
    # Column Width Auto-adjustment (Approximation)
    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter # Get the column name
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = (max_length + 2) * 1.1
        ws.column_dimensions[column].width = adjusted_width
        
    wb.save(output)
    output.seek(0)
    
    filename = f"reservation_list_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
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
    print(f"DEBUG: toggle_pause called. DATA: {data}")
    is_paused = data.get('pause', False)
    print(f"DEBUG: is_paused resolved to: {is_paused} (type: {type(is_paused)})")
    reason = data.get('reason', '').strip()
    mode = data.get('mode', 'all')
    
    # List of {start: '...', end: '...'}
    ranges = data.get('ranges', []) 
    
    if is_paused:
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
        # Only restore if backup actually exists in DB
        backup_setting = Settings.query.get('original_notice')
        if backup_setting and backup_setting.value is not None:
            set_setting('notice_text', backup_setting.value)
            print(f"DEBUG: notice_text restored to '{backup_setting.value}'")
            set_setting('original_notice', '')  # Clear backup after restore
        else:
            print("DEBUG: No backup found, keeping current notice")
        
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

@app.route('/api/admin/stats')
def admin_stats():
    if not session.get('is_admin') and not session.get('is_dev'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    reservations = Reservation.query.all()
    
    # Init Data Structures
    # 0 = Mon, 6 = Sun
    weekly_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0} 
    hourly_counts = {h: 0 for h in range(9, 23)} # 09:00 ~ 22:00
    status_counts = {'reserved': 0, 'checked_in': 0, 'ended': 0, 'cancelled': 0, 'noshow_penalty': 0}
    
    for r in reservations:
        # Status
        s = r.status
        if s in status_counts:
            status_counts[s] += 1
        else:
            # Group others
            status_counts.setdefault('other', 0)
            status_counts['other'] += 1
            
        # Skip cancelled for Usage Stats? 
        # Requirement says "When people use it", so maybe exclude cancelled for time stats.
        if r.status in ['cancelled']:
            continue
            
        # Weekly
        dow = r.start_time.weekday()
        weekly_counts[dow] += 1
        
        # Hourly (Count every hour occupied)
        # Simple version: Start Hour
        h = r.start_time.hour
        if 9 <= h <= 22:
            hourly_counts[h] += 1
            
    return jsonify({
        'weekly': weekly_counts,
        'hourly': hourly_counts,
        'status': status_counts
    })


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
        'smtp_email': get_setting('smtp_email'),
        'telegram_mask_info': get_setting('telegram_mask_info', 'true')
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

@app.route('/dev/toggle_masking', methods=['POST'])
def toggle_masking():
    if not session.get('is_dev'): return jsonify({'error': 'Unauthorized'}), 401
    
    current = get_setting('telegram_mask_info', 'true')
    new_val = 'false' if current == 'true' else 'true'
    set_setting('telegram_mask_info', new_val)
    log_admin_action('dev', f'Set Telegram Masking: {new_val}')
    return jsonify({'success': True, 'enabled': new_val})

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

@app.route('/dev/restore_db', methods=['POST'])
def restore_db():
    if not session.get('is_dev'): return jsonify({'error': 'Unauthorized'}), 401
    
    if 'file' not in request.files:
        return jsonify({'error': '파일이 업로드되지 않았습니다.'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '파일이 선택되지 않았습니다.'}), 400
    
    # Validate extension
    if not file.filename.endswith(('.sqlite', '.db')):
        return jsonify({'error': '올바른 SQLite 파일이 아닙니다.'}), 400
    
    try:
        # Create backup of current DB first
        backup_name = f'library_pre_restore_{datetime.now().strftime("%Y%m%d_%H%M%S")}.sqlite'
        backup_path = os.path.join(instance_path, backup_name)
        
        import shutil
        if os.path.exists(db_path):
            shutil.copy2(db_path, backup_path)
        
        # Save uploaded file
        file.save(db_path)
        
        log_admin_action('dev', f'Restored DB from uploaded file: {file.filename}')
        return jsonify({'success': True, 'backup': backup_name})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

import qrcode

def generate_random_color():
    return f"#{random.randint(0, 0xFFFFFF):06x}"

def mask_name(name):
    if not name or len(name) < 2: return name
    if len(name) == 2: return name[0] + "*"
    # Hong Gil Dong -> Hong * Dong
    return name[0] + "*" * (len(name) - 2) + name[-1]

def mask_phone(phone):
    if not phone: return phone
    
    # Remove all non-digit characters
    clean_phone = ''.join(filter(str.isdigit, phone))
    
    # 010-1234-5678 (11 digits)
    if len(clean_phone) == 11:
        return f"{clean_phone[:3]}-****-{clean_phone[7:]}"
    # 010-123-4567 (10 digits)
    elif len(clean_phone) == 10:
        return f"{clean_phone[:3]}-***-{clean_phone[6:]}"
        
    # Fallback for weird formats (just mask last 4 chars if long enough)
    if len(phone) > 4:
        return phone[:-4] + "****"
        
    return phone # Too short to mask

@app.route('/admin/qr_code')
def generate_qr_code():
    if not session.get('is_admin') and not session.get('is_dev'):
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

@app.route('/admin/door_qr')
def generate_door_qr():
    if not session.get('is_admin') and not session.get('is_dev'):
        return redirect(url_for('login'))
        
    token = get_setting('door_qr_token', 'ORYX_LAB_DOOR_2025')
    
    img = qrcode.make(token)
    output = io.BytesIO()
    img.save(output, format='PNG')
    output.seek(0)
    return send_file(output, mimetype='image/png')

@app.route('/admin/download_qr_poster')
def download_qr_poster():
    if not session.get('is_admin') and not session.get('is_dev'):
        return redirect(url_for('login'))

    # 1. Generate QR URL (Unified)
    door_token = get_setting('door_qr_token', 'ORYX_LAB_DOOR_2025')
    
    host_url = request.host_url
    if 'localhost' in host_url or '127.0.0.1' in host_url:
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            checkin_url = f"http://{local_ip}:5000/checkin?door_token={door_token}"
        except:
            checkin_url = f"{host_url}checkin?door_token={door_token}"
    else:
        checkin_url = f"{host_url}checkin?door_token={door_token}"

    # 2. Create QR Image (LOW error correction = simplest pattern)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=20,
        border=2,
    )
    qr.add_data(checkin_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGBA')

    # 3. Create A4 Canvas (High Quality)
    width, height = 1240, 1754  # A4 portrait ratio
    canvas = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(canvas)

    # 4. Load Fonts
    font_path = "C:/Windows/Fonts/malgun.ttf"
    bold_path = "C:/Windows/Fonts/malgunbd.ttf"
    
    # Check for Linux/Docker Paths (NanumGothic)
    if not os.path.exists(font_path):
        linux_font = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
        linux_bold = "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"
        if os.path.exists(linux_font):
            font_path = linux_font
            bold_path = linux_bold if os.path.exists(linux_bold) else linux_font
        else:
            font_path = "C:/Windows/Fonts/arial.ttf"
    
    if not os.path.exists(bold_path): bold_path = font_path

    try:
        header_font = ImageFont.truetype(bold_path, 70)
        title_font = ImageFont.truetype(bold_path, 110)
        desc_font = ImageFont.truetype(font_path, 45)
        token_label_font = ImageFont.truetype(bold_path, 40)
        token_font = ImageFont.truetype(bold_path, 60)
        footer_font = ImageFont.truetype(font_path, 30)
    except:
        header_font = ImageFont.load_default()
        title_font = ImageFont.load_default()
        desc_font = ImageFont.load_default()
        token_label_font = ImageFont.load_default()
        token_font = ImageFont.load_default()
        footer_font = ImageFont.load_default()

    # 5. Draw Content (Vertically Centered Layout)
    
    # --- Header Section ---
    header_height = 180
    draw.rectangle([0, 0, width, header_height], fill="#003366")
    draw.text((width/2, header_height/2), "지혜마루 작은 도서관", font=header_font, fill="white", anchor="mm")

    # --- Main Title (Centered in remaining space) ---
    content_start = header_height + 180
    draw.text((width/2, content_start), "입실 체크인", font=title_font, fill="black", anchor="mm")
    
    # --- QR Code (Centered) ---
    qr_size = 700  # Slightly larger for A4
    qr_img = qr_img.resize((qr_size, qr_size))
    qr_x = (width - qr_size) // 2
    qr_y = content_start + 120
    canvas.paste(qr_img, (qr_x, qr_y))

    # --- Guide Text ---
    text_y = qr_y + qr_size + 80
    draw.text((width/2, text_y), "스마트폰 카메라를 켜고", font=desc_font, fill="#555", anchor="mm")
    draw.text((width/2, text_y + 70), "위 QR 코드를 스캔하세요", font=desc_font, fill="#555", anchor="mm")

    # --- Footer ---
    draw.text((width/2, height - 100), "문의: 관리자 호출", font=footer_font, fill="#999", anchor="mm")
    
    # 6. Save
    output = io.BytesIO()
    canvas.save(output, format='PNG')
    output.seek(0)
    
    return send_file(output, mimetype='image/png', as_attachment=True, download_name='checkin_poster_complete.png')
    
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

def perform_cleanup(days=365):
    cutoff_date = datetime.now() - timedelta(days=days)
    print(f"Cleanup Started. Cutoff: {cutoff_date}")
    
    # 1. Find Old Reservations (Anonymize instead of Delete)
    old_reservations = Reservation.query.filter(Reservation.end_time < cutoff_date).all()
    
    deleted_files = 0
    anonymized_count = 0
    
    for res in old_reservations:
        # Skip if COMPLETELY anonymized (Check all fields)
        if (res.name == '정보삭제' and res.phone == '000-0000-0000' and 
            res.email is None and res.address is None and res.birth_date is None):
            continue

        # Delete Signature File
        if res.signature_path:
            try:
                sig_path = os.path.join(instance_path, 'signatures', res.signature_path)
                if os.path.exists(sig_path):
                    os.remove(sig_path)
                    deleted_files += 1
            except Exception as e:
                print(f"Error deleting signature {res.id}: {e}")
                
        # Delete Checkout Photo
        if res.checkout_photo:
            try:
                photo_path = os.path.join(basedir, 'static', 'uploads', res.checkout_photo)
                if os.path.exists(photo_path):
                    os.remove(photo_path)
                    deleted_files += 1
            except Exception as e:
                print(f"Error deleting photo {res.id}: {e}")
        
        # Anonymize DB Record (Keep ID, Date, Status for Stats)
        res.name = '정보삭제'
        res.phone = '000-0000-0000'
        res.password = 'deleted' # Dummy header for hash check failure
        res.birth_date = None
        res.address = None
        res.email = None
        res.purpose = '보존 기한 경과로 데이터 파기됨'
        res.signature_path = None
        res.signature_blob = None
        res.checkout_photo = None
        res.admin_memo = f"Personal data anonymized on {datetime.now().strftime('%Y-%m-%d')} (Policy: {days} days)"
        
        anonymized_count += 1
        
    # 2. Find Old Logs (Hard Delete Logs)
    old_access_logs = AccessLog.query.filter(AccessLog.timestamp < cutoff_date).delete()
    old_error_logs = ErrorLog.query.filter(ErrorLog.timestamp < cutoff_date).delete()
    old_admin_logs = AdminLog.query.filter(AdminLog.timestamp < cutoff_date).delete()
    
    deleted_logs = old_access_logs + old_error_logs + old_admin_logs
    
    db.session.commit()
    
    log_msg = f"Auto Cleanup executed. Anonymized {anonymized_count} reservations, Deleted {deleted_files} files, {deleted_logs} logs."
    print(log_msg)
    log_admin_action('dev', log_msg)
    
    return anonymized_count, deleted_logs

@app.route('/dev/cleanup', methods=['POST'])
def dev_cleanup_route():
    if not session.get('is_dev'): return jsonify({'error': 'Unauthorized'}), 401
    
    anonymized, logs = perform_cleanup()
    return jsonify({'success': True, 'deleted_count': anonymized, 'deleted_logs': logs})

# --- Scheduler for Auto Cleanup ---
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

def scheduled_cleanup():
    with app.app_context():
        try:
            print("Running Scheduled Cleanup...")
            perform_cleanup()
        except Exception as e:
            print(f"Scheduled Cleanup Failed: {e}")

def scheduled_auto_mail(period):
    """Send automatic bulk report email"""
    with app.app_context():
        try:
            # Check if auto mail is enabled
            setting_key = 'auto_mail_weekly' if period == 'week' else 'auto_mail_monthly'
            if get_setting(setting_key) != 'true':
                print(f"Auto mail ({period}) is disabled, skipping...")
                return
                
            official_email = get_setting('official_email')
            if not official_email:
                print(f"Auto mail ({period}): No official email configured")
                return
            
            # Calculate date range
            today = datetime.now()
            if period == 'week':
                start_date = today - timedelta(days=7)
                title_suffix = "주간"
            else:  # month
                start_date = today - timedelta(days=30)
                title_suffix = "월간"
            
            # Fetch reservations
            reservations = Reservation.query.filter(
                Reservation.start_time >= start_date,
                Reservation.status.in_(['reserved', 'checked_in', 'ended'])
            ).order_by(Reservation.start_time).all()
            
            if not reservations:
                print(f"Auto mail ({period}): No reservations found")
                return
            
            # Get file format setting
            file_format = get_setting('auto_mail_format') or 'merged'
            
            if file_format == 'zip':
                # Generate individual PDFs and ZIP them
                import zipfile
                
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for idx, res in enumerate(reservations, 1):
                        pdf_buffer = _generate_pdf_buffer(res)
                        if pdf_buffer:
                            pdf_name = f"{idx:03d}_{res.name}_{res.start_time.strftime('%Y%m%d')}.pdf"
                            zf.writestr(pdf_name, pdf_buffer.read())
                
                zip_buffer.seek(0)
                buffer = zip_buffer
                filename = f"지혜마루_{title_suffix}_예약모음_{today.strftime('%Y%m%d')}.zip"
            else:
                # Generate Merged PDF using PyPDF2
                from PyPDF2 import PdfMerger
                
                merger = PdfMerger()
                
                for res in reservations:
                    pdf_buffer = _generate_pdf_buffer(res)
                    if pdf_buffer:
                        merger.append(pdf_buffer)
                
                buffer = io.BytesIO()
                merger.write(buffer)
                merger.close()
                buffer.seek(0)
                filename = f"지혜마루_{title_suffix}_예약모음_{today.strftime('%Y%m%d')}.pdf"
            
            # Send email
            subject = f"[지혜마루] 시설 사용 신청서 모음 ({title_suffix}) - 자동발송"
            body = f"""안녕하세요.
지혜마루 작은도서관입니다.

{title_suffix} 시설 사용 신청서 모음을 자동 송부드립니다.
기간: {start_date.strftime('%Y-%m-%d')} ~ {today.strftime('%Y-%m-%d')}
총 건수: {len(reservations)}건

감사합니다.

* 이 메일은 자동 발송되었습니다."""
            
            success, error = _send_email_with_pdf(official_email, subject, body, buffer, filename)
            
            if success:
                print(f"Auto mail ({period}): Sent successfully to {official_email}, {len(reservations)} reservations")
            else:
                print(f"Auto mail ({period}): Failed - {error}")
                
        except Exception as e:
            print(f"Auto mail ({period}) Error: {e}")

scheduler = BackgroundScheduler()
# Run daily at 00:00
scheduler.add_job(func=scheduled_cleanup, trigger="cron", hour=0, minute=0)
# Weekly report: Every Monday at 09:00
scheduler.add_job(func=lambda: scheduled_auto_mail('week'), trigger="cron", day_of_week='mon', hour=9, minute=0, id='auto_mail_weekly')
# Monthly report: Every 1st of month at 09:00
scheduler.add_job(func=lambda: scheduled_auto_mail('month'), trigger="cron", day=1, hour=9, minute=0, id='auto_mail_monthly')
scheduler.start()

# Shut down the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown())

@app.route('/admin/diagnostics')
def diagnostics():
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    import shutil
    import subprocess
    
    # 1. Check wkhtmltopdf
    wkhtml_path = shutil.which('wkhtmltopdf')
    wkhtml_version = "Not Found"
    if wkhtml_path:
        try:
            wkhtml_version = subprocess.check_output([wkhtml_path, '--version'], stderr=subprocess.STDOUT).decode().strip()
        except Exception as e:
            wkhtml_version = f"Error: {str(e)}"
            
    # 2. Check Fonts
    font_files = []
    font_dirs = ['C:/Windows/Fonts', '/usr/share/fonts/truetype/nanum']
    for d in font_dirs:
        if os.path.exists(d):
            try:
                files = os.listdir(d)
                font_files.append(f"{d}: Found {len(files)} files")
            except:
                font_files.append(f"{d}: Access Denied")
        else:
            font_files.append(f"{d}: Not Found")
            
    # 3. Check Write Permissions
    write_check = {}
    for p in ['instance', 'logs', 'static/uploads']:
        write_check[p] = os.access(p, os.W_OK)
        
    return jsonify({
        'wkhtmltopdf_path': wkhtml_path,
        'wkhtmltopdf_version': wkhtml_version,
        'fonts': font_files,
        'write_permissions': write_check,
        'os': os.name
    })

if __name__ == '__main__':
    with app.app_context():
        create_init_data()
    app.run(host='0.0.0.0', port=5000, debug=True)
