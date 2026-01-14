"""Update admin password to 1234"""
import sys
sys.path.insert(0, '.')

from app import app, db, Settings
from werkzeug.security import generate_password_hash

with app.app_context():
    # Update admin password
    admin_pw = Settings.query.filter_by(key='admin_pw').first()
    hashed = generate_password_hash('1234')
    
    if admin_pw:
        admin_pw.value = hashed
    else:
        admin_pw = Settings(key='admin_pw', value=hashed)
        db.session.add(admin_pw)
    
    db.session.commit()
    print("Admin password updated to: 1234")
