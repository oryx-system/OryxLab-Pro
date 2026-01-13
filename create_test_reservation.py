from datetime import datetime, timedelta
from app import app, db, Reservation

def create_manual_user():
    with app.app_context():
        # Check if exists
        existing = Reservation.query.filter_by(phone="010-9999-9999").first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
            
        # Create future reservation
        s_time = datetime.now().replace(hour=14, minute=0, second=0) + timedelta(days=1)
        e_time = s_time + timedelta(hours=2)
        
        res = Reservation(
            name="ManualUser",
            phone="010-9999-9999",
            password="1234",
            purpose="Manual Creation Test",
            start_time=s_time,
            end_time=e_time,
            status="reserved"
        )
        db.session.add(res)
        db.session.commit()
        print("Created ManualUser reservation.")

if __name__ == "__main__":
    create_manual_user()
