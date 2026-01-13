import os
import random
import requests
import io
import time
from datetime import datetime, timedelta
from app import app, db, Reservation, Blacklist
from PIL import Image, ImageDraw

# Setup contexts
app.app_context().push()

# --- Config ---
SIGNATURE_CACHE_DIR = os.path.join(app.root_path, 'static', 'signatures_cache')
if not os.path.exists(SIGNATURE_CACHE_DIR):
    os.makedirs(SIGNATURE_CACHE_DIR)

# Scraped URLs from Wikimedia Commons
SIGNATURE_URLS = [
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e1/20040821T180600-GC2004-Johnathan_Wendel-Fatal1ty-Signature.svg/500px-20040821T180600-GC2004-Johnathan_Wendel-Fatal1ty-Signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/0/03/2006_Comic_Exhibition_Takayuki_Mizusina_signature.svg/500px-2006_Comic_Exhibition_Takayuki_Mizusina_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/d/df/A_A_PEJOVIC_SIGNATURE_LOW_RES.svg/500px-A_A_PEJOVIC_SIGNATURE_LOW_RES.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/f/ff/Abdul_Rahman_Taib_signature_1984.svg/500px-Abdul_Rahman_Taib_signature_1984.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f1/Abdurehim_Otkur_Imza.svg/500px-Abdurehim_Otkur_Imza.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/3/36/Abidin_dino_signature.svg/500px-Abidin_dino_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/f/ff/Abiel_Foster_signature.svg/500px-Abiel_Foster_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0a/Abraham_Ojanper%C3%A4_signature.svg/500px-Abraham_Ojanper%C3%A4_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c6/Abu_Bakar_Apong_signature_%28vectorised%29.svg/500px-Abu_Bakar_Apong_signature_%28vectorised%29.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/f/fd/Adam_J._Elkhadem_Signature.svg/500px-Adam_J._Elkhadem_Signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4c/ADONXS_signature_2022.svg/500px-ADONXS_signature_2022.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cf/Adrian_Fenty_Signature.svg/500px-Adrian_Fenty_Signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Adrian_Lewis_signature.svg/500px-Adrian_Lewis_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/5/54/Agust%C3%ADn_Casanova_signature.svg/500px-Agust%C3%ADn_Casanova_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4e/Ahmad_bin_Isa_signature_%28vectorised%29.svg/500px-Ahmad_bin_Isa_signature_%28vectorised%29.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/4/41/Ahmad_Jumat_signature_%28vectorised%29.svg/500px-Ahmad_Jumat_signature_%28vectorised%29.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/7/70/Alan_Garner_signature.svg/500px-Alan_Garner_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/9/94/Alan_Watts_signature.svg/500px-Alan_Watts_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ef/Albert%2C_King_of_Saxony_signature.svg/500px-Albert%2C_King_of_Saxony_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f1/Aleijadinho_signature.svg/500px-Aleijadinho_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/7/79/Alexander_I_of_Yugoslavia_signature.svg/500px-Alexander_I_of_Yugoslavia_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8b/Alexander_III_of_Russia_signature.svg/500px-Alexander_III_of_Russia_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Alexander_Jagiellon_signature.svg/500px-Alexander_Jagiellon_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/f/fd/Alexander_Kara%C4%91or%C4%91evi%C4%87_signature.svg/500px-Alexander_Kara%C4%91or%C4%91evi%C4%87_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e6/Alexander_Matu%C5%A1ka_Signature.svg/500px-Alexander_Matu%C5%A1ka_Signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/2/29/Alexandru_Ioan_Cuza_signature.svg/500px-Alexandru_Ioan_Cuza_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1c/Alexis_of_Russia_signature.svg/500px-Alexis_of_Russia_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/68/Alfons_Mucha_signature_from_letter.svg/500px-Alfons_Mucha_signature_from_letter.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c7/Alfred_Stevens_signature_svg.svg/500px-Alfred_Stevens_signature_svg.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0d/Ali_Zafar_signature.svg/500px-Ali_Zafar_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ad/Andr%C3%A9_Vingt-Trois_signature.svg/500px-Andr%C3%A9_Vingt-Trois_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/2/29/Angel_Chavez_Martinez_signature.svg/500px-Angel_Chavez_Martinez_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/b/bd/Aniruddha_Brahmbhatt_autograph.svg/500px-Aniruddha_Brahmbhatt_autograph.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e6/Anna_Hodger_Signature.svg/500px-Anna_Hodger_Signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b5/Anna_Jagiellon_signature.svg/500px-Anna_Jagiellon_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/9/97/Anna_of_Russia_signature.svg/500px-Anna_of_Russia_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/f/fb/Anthony_Kennedy_signature.svg/500px-Anthony_Kennedy_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/b/bd/Antonio_Kowatsch_signature.svg/500px-Antonio_Kowatsch_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/4/42/Antonio_Nari%C3%B1o_signature.svg/500px-Antonio_Nari%C3%B1o_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c4/Appletons%27_Bonaparte_Jerome_signature.svg/500px-Appletons%27_Bonaparte_Jerome_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2a/Arap_moi_Signature.svg/500px-Arap_moi_Signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/d/df/Archibald_Campbell_Tait_signature.svg/500px-Archibald_Campbell_Tait_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1c/Arlo_James_Barnes_signature.svg/500px-Arlo_James_Barnes_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f8/Arnaldo_Tamayo_Signature.svg/500px-Arnaldo_Tamayo_Signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d2/Arthur_Stanton_signature.svg/500px-Arthur_Stanton_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/1/12/Arturo_Bertollo_signature.svg/500px-Arturo_Bertollo_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8e/August_III_signature.svg/500px-August_III_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d6/Augustus_II_signature.svg/500px-Augustus_II_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0b/Augustus_III_signature.svg/500px-Augustus_III_signature.svg.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/3/32/Author_Yogesh_Joshi_Autograph1.svg/500px-Author_Yogesh_Joshi_Autograph1.svg.png"
]

REALISTIC_PURPOSES = [
    "인문학 강의: 서양 미술의 이해",
    "독서 동아리: 밤의 도서관 정기모임",
    "어린이 코딩 교실: 파이썬 기초",
    "시 낭송회: 가을의 속삭임",
    "역사 탐방 준비 모임",
    "영어 회화 스터디 (중급)",
    "가죽 공예 원데이 클래스",
    "캘리그라피 수업: 예쁜 손글씨",
    "영화 인문학 산책",
    "중장년 스마트폰 활용 교육",
    "프랑스 자수 기초반",
    "글쓰기 치료 워크숍",
    "지역 주민 반상회",
    "청소년 진로 상담",
    "독서 토론: 한강의 채식주의자"
]

FAMILY_NAMES = ['김', '이', '박', '최', '정', '강', '조', '윤', '장', '임', '한', '오', '서', '신', '권', '황', '안', '송', '전', '홍']
GIVEN_NAMES = ['민준', '서준', '예준', '시우', '하준', '지호', '지후', '준우', '준서', '서윤', '서연', '지우', '지유', '하윤', '서현', '하은', '민서', '지민', '채원']

def generate_fallback_signature():
    """Generates a transparent 'scribble' signature as a last resort."""
    img = Image.new('RGBA', (200, 100), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    for _ in range(5):
        start_x = random.randint(0, 200)
        start_y = random.randint(0, 100)
        end_x = random.randint(0, 200)
        end_y = random.randint(0, 100)
        draw.line((start_x, start_y, end_x, end_y), fill='black', width=2)
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()

def get_signature_blob():
    """
    Tries to get a realistic signature from cache or download.
    Retries up to 3 times with different URLs.
    Falls back to generate_fallback_signature() if all fail.
    NEVER returns empty/None.
    """
    max_retries = 3
    for _ in range(max_retries):
        url = random.choice(SIGNATURE_URLS)
        filename = url.split('/')[-1]
        filepath = os.path.join(SIGNATURE_CACHE_DIR, filename)

        if os.path.exists(filepath):
             try:
                with open(filepath, 'rb') as f:
                    content = f.read()
                    if content: return content
             except:
                 pass
        
        # Download
        try:
            print(f"Downloading signature: {filename}")
            res = requests.get(url, timeout=3, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code == 200 and res.content:
                with open(filepath, 'wb') as f:
                    f.write(res.content)
                return res.content
        except Exception:
            pass
        
        time.sleep(0.5)

    print("Warning: Failed to get realistic signature, using fallback.")
    return generate_fallback_signature()

def generate_korean_name():
    return random.choice(FAMILY_NAMES) + random.choice(GIVEN_NAMES)

def generate_phone():
    mid = random.randint(1000, 9999)
    last = random.randint(1000, 9999)
    return f"010-{mid}-{last}"

def clear_data():
    print("Clearing all data...")
    db.session.query(Reservation).delete()
    db.session.query(Blacklist).delete()
    db.session.commit()

def generate_batch(start_date, end_date, min_per_week, max_per_week, is_future=False):
    current_week_start = start_date
    count = 0
    
    while current_week_start <= end_date:
        num_reservations = random.randint(min_per_week, max_per_week)
        # Fix: correctly handle week range
        days_in_week = []
        for i in range(7):
             d = current_week_start + timedelta(days=i)
             if d <= end_date:
                 days_in_week.append(d)
        
        if not days_in_week: break
            
        selected_days = random.sample(days_in_week, min(len(days_in_week), num_reservations))
        
        for day in selected_days:
            start_hour = random.randint(9, 18)
            duration = random.randint(1, 4)
            start_time = day.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(hours=duration)
            
            # Status
            if is_future:
                status = 'reserved'
            else:
                r = random.random()
                if r < 0.7: status = 'ended'
                elif r < 0.9: status = 'cancelled'
                else: status = 'noshow_penalty'
            
            name = generate_korean_name()
            phone = generate_phone()
            
            # --- Enforce Signature ---
            sig_blob = get_signature_blob()
            # -------------------------

            res = Reservation(
                name=name,
                phone=phone,
                password="1234",
                start_time=start_time,
                end_time=end_time,
                purpose=random.choice(REALISTIC_PURPOSES),
                status=status,
                signature_blob=sig_blob,
                created_at=datetime.now()
            )
            
            if status == 'noshow_penalty':
                bl = Blacklist(phone=phone, name=name, release_date=end_time + timedelta(days=30), reason="노쇼 패널티")
                db.session.add(bl)

            db.session.add(res)
            count += 1
            
        current_week_start += timedelta(weeks=1)
    
    try:
        db.session.commit()
        print(f"Batch ({'Future' if is_future else 'Past'}) added {count} items.")
    except Exception as e:
        db.session.rollback()
        print(f"Error: {e}")

def main():
    clear_data()
    
    yesterday = datetime.now() - timedelta(days=1)
    past_start = datetime(2025, 1, 1)
    
    if past_start <= yesterday:
        generate_batch(past_start, yesterday, 2, 3, is_future=False)
        
    tomorrow = datetime.now() + timedelta(days=1)
    future_end = datetime(2026, 3, 1)
    
    if tomorrow <= future_end:
        generate_batch(tomorrow, future_end, 1, 1, is_future=True)

if __name__ == "__main__":
    main()
