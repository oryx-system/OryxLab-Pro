from app import app, db, Reservation

def update_name():
    """
    Finds all reservations with name '이도윤' and updates them to '박시윤'.
    """
    app.app_context().push()
    
    target_name = "이도윤"
    new_name = "박시윤"
    
    reservations = Reservation.query.filter_by(name=target_name).all()
    count = len(reservations)
    
    if count > 0:
        for res in reservations:
            res.name = new_name
        
        try:
            db.session.commit()
            print(f"Successfully updated {count} reservations from '{target_name}' to '{new_name}'.")
        except Exception as e:
            db.session.rollback()
            print(f"Error updating records: {e}")
    else:
        print(f"No reservations found with name '{target_name}'.")

if __name__ == "__main__":
    update_name()
