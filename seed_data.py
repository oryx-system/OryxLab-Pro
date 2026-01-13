
import random
from datetime import datetime, timedelta
from app import app, db, Reservation

# Fake Data
names = ["김철수", "이영희", "박민수", "정수진", "최준호", "강지영", "윤서연", "임도현"]
purposes = ["독서 모임", "개인 공부", "조별 과제", "화상 회의", "코딩 스터디", "인문학 강의"]
statuses = ["reserved", "checked_in", "ended", "cancelled", "noshow_penalty"]

def seed_reservations():
    print("[INFO] Seeding dummy reservations...")
    
    # Clear existing (Optional, but safer for testing stats)
    # db.session.query(Reservation).delete()
    
    start_date = datetime.now() - timedelta(days=30) # Past 30 days
    end_date = datetime.now() + timedelta(days=7)    # Future 7 days
    
    current = start_date
    count = 0
    
    while current <= end_date:
        # Randomly decide how many reservations per day (0 to 5)
        daily_count = random.randint(0, 5)
        
        for _ in range(daily_count):
            # Random Hour (09:00 ~ 20:00)
            hour = random.randint(9, 20)
            duration = random.choice([1, 2, 3])
            
            s_time = current.replace(hour=hour, minute=0, second=0)
            e_time = s_time + timedelta(hours=duration)
            
            # Status Logic
            if e_time < datetime.now():
                status = random.choices(
                    ["ended", "noshow_penalty", "cancelled"], 
                    weights=[0.7, 0.1, 0.2]
                )[0]
            else:
                status = "reserved"

            res = Reservation(
                name=random.choice(names),
                phone=f"010-{random.randint(1000,9999)}-{random.randint(1000,9999)}",
                password="1234",
                purpose=random.choice(purposes),
                start_time=s_time,
                end_time=e_time,
                status=status
            )
            db.session.add(res)
            count += 1
            
        current += timedelta(days=1)
        
    db.session.commit()
    print(f"[SUCCESS] Created {count} dummy reservations.")

if __name__ == "__main__":
    with app.app_context():
        seed_reservations()
