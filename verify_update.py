from app import app, db, Reservation

def verify():
    app.app_context().push()
    count = Reservation.query.filter_by(name='이도윤').count()
    print(f"Remaining count: {count}")
    
    new_count = Reservation.query.filter_by(name='박시윤').count()
    print(f"New name count: {new_count}")

if __name__ == "__main__":
    verify()
