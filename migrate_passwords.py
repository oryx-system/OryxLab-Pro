from app import app, db, Reservation, get_setting, set_setting
from werkzeug.security import generate_password_hash

def is_hashed(password):
    if not password: return False
    return password.startswith('scrypt:') or password.startswith('pbkdf2:')

def migrate():
    print("Starting Password Migration...")
    app.app_context().push()
    
    # 1. Migrate Reservations
    reservations = Reservation.query.all()
    count_res = 0
    for res in reservations:
        if not is_hashed(res.password):
            res.password = generate_password_hash(res.password)
            count_res += 1
            
    # 2. Migrate Admin/Dev Passwords in Settings
    admin_pw = get_setting('admin_pw', 'admin123!')
    dev_pw = get_setting('dev_pw', '123qwe!')
    
    count_settings = 0
    if not is_hashed(admin_pw):
        set_setting('admin_pw', generate_password_hash(admin_pw))
        count_settings += 1
        print("Updated Admin Password to Hash")
        
    if not is_hashed(dev_pw):
        set_setting('dev_pw', generate_password_hash(dev_pw))
        count_settings += 1
        print("Updated Dev Password to Hash")
        
    try:
        db.session.commit()
        print(f"Migration Complete.")
        print(f"- Reservations Updated: {count_res}")
        print(f"- Settings Updated: {count_settings}")
    except Exception as e:
        db.session.rollback()
        print(f"Error during migration: {e}")

if __name__ == "__main__":
    migrate()
