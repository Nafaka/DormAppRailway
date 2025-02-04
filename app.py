import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from sqlalchemy import func
from apscheduler.schedulers.background import BackgroundScheduler

# Initialize Flask app
app = Flask(__name__)

# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///laundry.db').replace('postgres://', 'postgresql://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key')

# Initialize database and login manager
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(200))
    name = db.Column(db.String(100))
    appliances = db.relationship('Appliance', backref='user', lazy=True)

class Appliance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20))  # 'washer' or 'dryer'
    status = db.Column(db.String(20), default='free')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    reservation_time = db.Column(db.DateTime)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Background scheduler for status updates
scheduler = BackgroundScheduler(daemon=True)

def update_appliance_status(appliance):
    if appliance.status in ['in_use', 'almost_done'] and appliance.reservation_time:
        now = datetime.utcnow()
        reservation_end = appliance.reservation_time + timedelta(hours=1)
        
        if now > reservation_end:
            appliance.status = 'free'
            appliance.user_id = None
            appliance.reservation_time = None
        elif (reservation_end - now) <= timedelta(minutes=10):
            appliance.status = 'almost_done'
        else:
            appliance.status = 'in_use'
        
        db.session.commit()

def update_all_appliances():
    with app.app_context():
        appliances = Appliance.query.all()
        for appliance in appliances:
            update_appliance_status(appliance)
        print(f"[{datetime.utcnow()}] Updated all appliance statuses")

scheduler.add_job(func=update_all_appliances, trigger='interval', minutes=1)
scheduler.start()

# Routes
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        name = request.form.get('name')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()
        if user:
            flash('Email already exists', 'error')
            return redirect(url_for('register'))

        new_user = User(
            email=email,
            name=name,
            password=generate_password_hash(password, method='pbkdf2:sha256')
        )
        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password, password):
            flash('Invalid email or password', 'error')
            return redirect(url_for('login'))

        login_user(user)
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/index')
@login_required
def index():
    appliances = Appliance.query.all()
    return render_template('index.html', 
                         appliances=appliances,
                         datetime=datetime,
                         timedelta=timedelta)

@app.route('/reserve/<int:appliance_id>')
@login_required
def reserve(appliance_id):
    appliance = Appliance.query.get(appliance_id)
    today = datetime.utcnow().date()
    
    if appliance.status == 'free':
        existing_same_type = Appliance.query.filter(
            Appliance.user_id == current_user.id,
            Appliance.type == appliance.type,
            func.date(Appliance.reservation_time) == today
        ).first()
        
        if existing_same_type:
            flash(f'You can only reserve one {appliance.type} per day!', 'error')
            return redirect(url_for('index'))
            
        appliance.status = 'in_use'
        appliance.user_id = current_user.id
        appliance.reservation_time = datetime.utcnow()
        db.session.commit()
        flash(f'{appliance.type.capitalize()} {appliance_id} reserved for 1 hour!', 'success')
    else:
        flash('This appliance is already in use!', 'error')
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if Appliance.query.count() < 7:
            for i in range(4):
                db.session.add(Appliance(type='washer'))
            for i in range(3):
                db.session.add(Appliance(type='dryer'))
            db.session.commit()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('DEBUG') == '1')