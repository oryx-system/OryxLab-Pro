"""
Populate existing reservations with random optional field values
"""
import sqlite3
import random
import os

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'library.db')

# Random data options
applicant_types = ['개인', '단체']
org_names = ['독서모임', '코딩클럽', '영어스터디', '음악동아리', '봉사단체', '']
facility_basic_options = ['', '자료실', '문화강좌실', '조리실', '자료실,문화강좌실', '문화강좌실,조리실']
facility_extra_options = ['', '빔프로젝트', '스크린', '빔프로젝트,스크린']
addresses = ['', '충남 금산군 금산읍', '충남 금산군 추부면', '충남 금산군 진산면', '대전광역시']
emails = ['', 'test@example.com', 'user@mail.com', 'demo@test.co.kr']

def populate():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all reservations
    cursor.execute("SELECT id, name FROM reservation")
    reservations = cursor.fetchall()
    
    print(f"Found {len(reservations)} reservations")
    
    for res_id, name in reservations:
        app_type = random.choice(applicant_types)
        org_name = random.choice(org_names) if app_type == '단체' else ''
        fac_basic = random.choice(facility_basic_options)
        fac_extra = random.choice(facility_extra_options)
        exp_count = random.randint(1, 20) if random.random() > 0.3 else None
        birth = f"19{random.randint(70,99)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}" if random.random() > 0.5 else ''
        addr = random.choice(addresses)
        email = random.choice(emails)
        
        cursor.execute("""
            UPDATE reservation SET
                applicant_type = ?,
                org_name = ?,
                facility_basic = ?,
                facility_extra = ?,
                expected_count = ?,
                birth_date = ?,
                address = ?,
                email = ?
            WHERE id = ?
        """, (app_type, org_name, fac_basic, fac_extra, exp_count, birth, addr, email, res_id))
        
        print(f"  [OK] ID {res_id}: {app_type} / {name}")
    
    conn.commit()
    conn.close()
    print(f"\n[OK] Updated {len(reservations)} reservations")

if __name__ == "__main__":
    populate()
