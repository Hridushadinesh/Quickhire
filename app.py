from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, current_app, make_response, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from datetime import datetime, timedelta, date
import json
import uuid
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
import numpy as np
from sklearn.pipeline import Pipeline
from sklearn.neighbors import KNeighborsClassifier
import requests
from time import sleep
import base64
from sqlalchemy import inspect, text, func, and_, or_, distinct
import string
import random
import time
import hashlib
import secrets
import logging
from sqlalchemy import or_, and_, func, desc
from sqlalchemy.exc import SQLAlchemyError
import eventlet
# Import SMS utility functions
from sms_utils import send_job_notification, send_job_invitation, send_application_status_update

import math
from fuzzywuzzy import fuzz
from sqlalchemy import func
# --- Constants ---
FUZZY_THRESHOLD = 40 # Adjusted based on previous discussion
DEFAULT_LOCATION_RADIUS_KM = 100 # Default search radius in kilometers - ADJUST AS NEEDED

# Import Gemini API
import google.generativeai as genai
import time

# Import admin routes
from admin_routes import admin_bp, init_admin_bp

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///quickhire.db'
# Add file upload configurations
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
# Enable Jinja2 extensions
app.jinja_env.add_extension('jinja2.ext.do')

# Initialize extensions
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Initialize Socket.IO with eventlet
socketio = SocketIO(app, 
                   async_mode='eventlet',
                   cors_allowed_origins="*",
                   logger=True,
                   engineio_logger=True)

# Keep track of which rooms users are in
user_rooms = {}

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Configure Gemini API
genai.configure(api_key="***REMOVED***")

# Helper function to analyze job data using Gemini
def analyze_job_data_with_gemini(job_data):
    # Create a well-formatted prompt with the job data
    prompt = f"""
    As an AI job analytics expert, analyze the following job data and provide insights:
    
    {json.dumps(job_data, indent=2)}
    
    Please provide the following analysis:
    1. Application trend analysis: Is there a pattern in when applications are received?
    2. Worker profile analysis: What types of workers are applying to these jobs?
    3. Job performance metrics: Which jobs are performing best in terms of applications?
    4. Recommendations: Based on the data, what should the employer do to improve application rates?
    5. Market insights: What can we learn about the job market from this data?
    
    Format your response as JSON with the following structure:
    {{
        "application_trend_analysis": {{
            "summary": "A brief summary",
            "details": "Detailed explanation",
            "recommendation": "A recommendation based on this trend"
        }},
        "worker_profile_analysis": {{
            "summary": "A brief summary",
            "details": "Detailed explanation",
            "top_skills": ["skill1", "skill2", "skill3"],
            "recommendation": "A recommendation based on this analysis"
        }},
        "job_performance_metrics": {{
            "best_performing_jobs": ["job1", "job2", "job3"],
            "details": "Why these jobs are performing well",
            "improvement_areas": "Areas where other jobs could improve"
        }},
        "overall_recommendations": [
            "recommendation1",
            "recommendation2",
            "recommendation3"
        ],
        "market_insights": {{
            "trends": ["trend1", "trend2", "trend3"],
            "opportunities": ["opportunity1", "opportunity2"],
            "challenges": ["challenge1", "challenge2"]
        }}
    }}
    
    ONLY respond with the JSON. Do not include any other text.
    """
    
    try:
        # Use Gemini 2.0 Flash model
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        
        # Parse the response as JSON
        try:
            # Clean the response text to ensure it's valid JSON
            response_text = response.text.strip()
            # Remove markdown code block markers if present
            if response_text.startswith("```json"):
                response_text = response_text.replace("```json", "", 1)
            if response_text.endswith("```"):
                response_text = response_text.rsplit("```", 1)[0]
            
            response_text = response_text.strip()
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON from Gemini response: {e}")
            print(f"Response was: {response.text}")
            return {
                "error": "Could not parse AI response",
                "raw_response": response.text
            }
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return {
            "error": f"Error calling AI service: {str(e)}"
        }

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Define ChatRoom and ChatMessage models before User model
class ChatRoom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user1_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user2_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    messages = db.relationship('ChatMessage', backref='chat_room', lazy=True, cascade="all, delete-orphan")
    
    def get_other_user(self, user_id):
        """Get the other user in the chat room"""
        if self.user1_id == user_id:
            return User.query.get(self.user2_id)
        elif self.user2_id == user_id:
            return User.query.get(self.user1_id)
        return None

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_room_id = db.Column(db.Integer, db.ForeignKey('chat_room.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(128))
    user_type = db.Column(db.String(10), nullable=False)  # 'worker' or 'employer'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='available')  # For workers: available, busy, unavailable
    
    # Profile enhancements
    profile_pic = db.Column(db.String(200))
    bio = db.Column(db.Text)
    skills = db.Column(db.String(500))  # Comma-separated skills for workers
    avg_rating = db.Column(db.Float, default=0.0)
    num_ratings = db.Column(db.Integer, default=0)
    hourly_rate = db.Column(db.Float)  # For workers
    location = db.Column(db.String(200), default='Delhi')  # Location field with default value
    latitude = db.Column(db.Float)  # For map display
    longitude = db.Column(db.Float)  # For map display
    is_premium = db.Column(db.Boolean, default=False)  # Premium subscription status
    has_smartphone = db.Column(db.Boolean, default=True)  # Whether user has a smartphone
    sms_notifications = db.Column(db.Boolean, default=False)  # Whether to send SMS notifications

    # Relationships
    jobs_posted = db.relationship('Job', backref='employer', lazy=True)
    applications = db.relationship('Application', backref='applicant', lazy=True)
    
    # Chat relationships
    sent_messages = db.relationship('ChatMessage', 
                                  foreign_keys='ChatMessage.sender_id',
                                  backref=db.backref('sender', lazy=True),
                                  lazy=True)
    received_messages = db.relationship('ChatMessage',
                                      foreign_keys='ChatMessage.receiver_id',
                                      backref=db.backref('receiver', lazy=True),
                                      lazy=True)
    chat_rooms_1 = db.relationship('ChatRoom',
                                foreign_keys='ChatRoom.user1_id',
                                backref=db.backref('user1', lazy=True),
                                lazy=True)
    chat_rooms_2 = db.relationship('ChatRoom',
                                foreign_keys='ChatRoom.user2_id',
                                backref=db.backref('user2', lazy=True),
                                lazy=True)

    # Ratings relationship
    ratings = db.relationship('Rating', 
                            secondary='application',
                            primaryjoin='User.id == Application.applicant_id',
                            secondaryjoin='and_(Application.id == Rating.application_id)',
                            backref=db.backref('worker', lazy=True),
                            lazy='dynamic',
                            overlaps="application")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
        
    def is_available_on_date(self, date):
        """Check if worker is available on a specific date"""
        if self.user_type != 'worker':
            return False
            
        # Check if worker has any accepted jobs on this date
        worker_jobs = db.session.query(Job)\
            .join(Application, Job.id == Application.job_id)\
            .filter(Application.applicant_id == self.id,
                    Application.status == 'accepted',
                    Job.work_date == date)\
            .count()
        
        return worker_jobs == 0 and self.status != 'unavailable'

class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    wage = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    employer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    applications = db.relationship('Application', backref='job', lazy=True)
    # New fields
    maximum_workers = db.Column(db.Integer, default=1)
    work_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='open')  # 'open', 'filled', 'completed', 'cancelled'
    
    # Add relationship to chat rooms
    chat_rooms = db.relationship('ChatRoom', backref='job', lazy=True)
    
    @property
    def is_filled(self):
        """Check if job has reached maximum workers"""
        accepted_applications = Application.query.filter_by(job_id=self.id, status='accepted').count()
        return accepted_applications >= self.maximum_workers
    
    @property
    def available_positions(self):
        """Get number of available positions left"""
        accepted_applications = Application.query.filter_by(job_id=self.id, status='accepted').count()
        return max(0, self.maximum_workers - accepted_applications)

class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, rejected, cancelled
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    applicant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # New fields
    initiated_by = db.Column(db.String(20), nullable=False)  # 'worker' or 'employer'
    worker_approved = db.Column(db.Boolean, default=False)
    employer_approved = db.Column(db.Boolean, default=False)
    message = db.Column(db.Text)  # Optional message for the request

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False
    )
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(300))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
class Rating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('application.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    application = db.relationship('Application', backref=db.backref('rating', uselist=False, overlaps="ratings,worker"), overlaps="ratings,worker")

    @staticmethod
    def calculate_worker_rating(worker_id):
        """Calculate the average rating for a worker"""
        ratings = Rating.query.join(Application).filter(Application.applicant_id == worker_id).all()
        if not ratings:
            return 0
        return sum(r.rating for r in ratings) / len(ratings)

# Add Review model for worker reviews
class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reviewee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=True)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    reviewer = db.relationship('User', foreign_keys=[reviewer_id], backref='reviews_given')
    reviewee = db.relationship('User', foreign_keys=[reviewee_id], backref='reviews_received')
    job = db.relationship('Job', backref='reviews')

# Mock worker data
MOCK_WORKERS = [
    {
        "id": 1,
        "name": "Rahul Sharma",
        "skills": ["Plumbing", "Repairs"],
        "rating": 4.2,
        "total_jobs": 24,
        "hourly_rate": 350,
        "location": "Mumbai, Maharashtra",
        "lat": 19.0760,
        "lng": 72.8777,
        "image": "https://randomuser.me/api/portraits/men/32.jpg",
        "availability": "Available Now"
    },
    {
        "id": 2,
        "name": "Priya Patel",
        "skills": ["Carpentry", "Furniture Assembly"],
        "rating": 4.8,
        "total_jobs": 42,
        "hourly_rate": 400,
        "location": "Delhi, NCR",
        "lat": 28.7041,
        "lng": 77.1025,
        "image": "https://randomuser.me/api/portraits/women/44.jpg",
        "availability": "Available from Tomorrow"
    },
    {
        "id": 3,
        "name": "Mohammed Khan",
        "skills": ["Electrical", "Wiring", "Repairs"],
        "rating": 4.5,
        "total_jobs": 36,
        "hourly_rate": 380,
        "location": "Bangalore, Karnataka",
        "lat": 12.9716,
        "lng": 77.5946,
        "image": "https://randomuser.me/api/portraits/men/87.jpg",
        "availability": "Available Now"
    },
    {
        "id": 4,
        "name": "Ravi Kumar",
        "skills": ["Painting", "Drywall", "Tiling"],
        "rating": 3.9,
        "total_jobs": 18,
        "hourly_rate": 320,
        "location": "Chennai, Tamil Nadu",
        "lat": 13.0827,
        "lng": 80.2707,
        "image": "https://randomuser.me/api/portraits/men/15.jpg",
        "availability": "Busy until next week"
    },
    {
        "id": 5,
        "name": "Anita Patel",
        "skills": ["House Cleaning", "Cooking"],
        "rating": 4.6,
        "total_jobs": 38,
        "hourly_rate": 250,
        "location": "Pune, Maharashtra",
        "lat": 18.5204,
        "lng": 73.8567,
        "image": "https://randomuser.me/api/portraits/women/2.jpg",
        "availability": "Available Now"
    }
]

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def home():
    # Redirect authenticated users to dashboard
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    # Show home page only to non-authenticated users
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    # If user is already logged in, redirect to dashboard
   # if current_user.is_authenticated:
       # return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        print(f"Login attempt for email: {email}")
        
        # Admin login should be handled by admin_routes.py, not here
        # Redirect to admin login page if admin email is detected
        if email == "admin@quickhire.com":
            flash('Please use the admin login page', 'info')
            return redirect(url_for('admin.admin_login'))
        
        user = User.query.filter_by(email=email).first()
        
        if user:
            print(f"User found: {user.name}, User type: {user.user_type}")
            
            # Check password
            if user.check_password(password):
                print("Password verified successfully")
                login_user(user)
                
                # Set the profile_needs_update flag if the profile is incomplete
                profile_incomplete = False
                
                # For workers, check if skills, bio, and hourly_rate are set
                if user.user_type == 'worker' and (not user.skills or not user.bio or not user.hourly_rate):
                    profile_incomplete = True
                # For employers, check if bio and location are set
                elif user.user_type == 'employer' and (not user.bio or not user.location):
                    profile_incomplete = True
                
                if profile_incomplete:
                    # Check if we should show the profile reminder
                    # Set the first_login flag to True and set the next reminder time
                    session['first_login'] = True
                    # Set next reminder time to now (show immediately after login)
                    session['next_profile_reminder'] = datetime.now().timestamp()
                
                # Redirect to dashboard with welcome parameter
                return redirect(url_for('dashboard', welcome=True))
            else:
                print("Password verification failed")
                flash('Invalid email or password.', 'danger')
        else:
            print("User not found")
            flash('Invalid email or password.', 'danger')
    
    return render_template('login.html')

def get_coordinates(location):
    """Get coordinates from OpenStreetMap's Nominatim service"""
    try:
        # Add India to the search query to improve results
        search_query = f"{location}, India"
        
        # Use Nominatim API with proper headers
        headers = {
            'User-Agent': 'QuickHire/1.0'  # Required by Nominatim's terms of use
        }
        response = requests.get(
            f"https://nominatim.openstreetmap.org/search",
            params={'q': search_query, 'format': 'json', 'limit': 1},
            headers=headers
        )
        
        # Respect Nominatim's usage policy with a small delay
        sleep(1)
        
        if response.status_code == 200:
            results = response.json()
            if results:
                return float(results[0]['lat']), float(results[0]['lon'])
    except Exception as e:
        print(f"Geocoding error: {str(e)}")
    
    # Default to center of India if geocoding fails
    return 20.5937, 78.9629

@app.route('/register', methods=['GET', 'POST'])
def register():
    # If user is already logged in, redirect to dashboard
  #  if current_user.is_authenticated:
     #   return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        user_type = request.form.get('user_type')
        
        # Validate input
        if not name or not email or not phone or not password or not confirm_password or not user_type:
            flash('All fields are required.', 'danger')
            return redirect(url_for('register'))
            
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register'))
            
        # Check if email already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email already registered.', 'danger')
            return redirect(url_for('register'))
            
        # Get smartphone access preference (only applicable for workers)
        has_smartphone = True
        sms_notifications = False
        
        if user_type == 'worker':
            smartphone_access = request.form.get('has_smartphone', 'yes')
            has_smartphone = smartphone_access == 'yes'
            # If user doesn't have a smartphone, enable SMS notifications
            sms_notifications = not has_smartphone
        
        # Create new user
        new_user = User(
            name=name,
            email=email,
            phone=phone,
            user_type=user_type,
            has_smartphone=has_smartphone,
            sms_notifications=sms_notifications
        )
        new_user.set_password(password)
        
        # Get default location
        location = request.form.get('location', 'Delhi')
        new_user.location = location
        
        # Attempt to get coordinates for the location
        try:
            lat, lng = get_coordinates(location)
            new_user.latitude = lat
            new_user.longitude = lng
        except:
            # Failed to get coordinates, use defaults for Delhi
            new_user.latitude = 28.6139
            new_user.longitude = 77.2090
            
        # Add to database
        db.session.add(new_user)
        db.session.commit()
        
        # Log the user in
        login_user(new_user)
        
        # Clear any previous profile_reminder_dismissed flag for a fresh registration
        if 'profile_reminder_dismissed' in session:
            session.pop('profile_reminder_dismissed')
        
        # Set first_login flag in session for newly registered users
        session['first_login'] = True
        
        flash('Registration successful! Welcome to QuickHire.', 'success')
        return redirect(url_for('dashboard', welcome=True))
        
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    # Clear all session data related to profile reminders
    if 'next_profile_reminder' in session:
        session.pop('next_profile_reminder', None)
    
    # Logout the user
    logout_user()
    
    # Create response that clears the profile reminder cookie
    response = make_response(redirect(url_for('home')))
    response.set_cookie('profile_reminder_dismissed', '', expires=0)
    
    return response

@app.route('/dashboard')
@login_required
def dashboard():
    # Check if profile reminder should be shown
    show_profile_reminder = False
    profile_incomplete = False
    missing_fields = []
    show_first_login_modal = False
    jobs = []
    applications = []
    today = datetime.now().date()
    
    # Determine if this is the first login
    if 'first_login' not in session:
        session['first_login'] = True
        show_first_login_modal = True
    
    # Check profile completeness
    if not current_user.bio or not current_user.profile_pic or not current_user.skills:
        profile_incomplete = True
        if not current_user.bio:
            missing_fields.append('bio')
        if not current_user.profile_pic:
            missing_fields.append('profile picture')
        if not current_user.skills:
            missing_fields.append('skills')
            
    # Check if we should show profile reminder
    profile_reminder_key = f'profile_reminder_{current_user.id}'
    if profile_incomplete and profile_reminder_key not in session:
        show_profile_reminder = True
        # Set a session variable to avoid showing the reminder on every page load
        session[profile_reminder_key] = datetime.now().timestamp()
    elif profile_incomplete and profile_reminder_key in session:
        # Only show the reminder once a day (86400 seconds)
        last_reminder = datetime.fromtimestamp(session[profile_reminder_key])
        if (datetime.now() - last_reminder).total_seconds() > 86400:
            show_profile_reminder = True
            session[profile_reminder_key] = datetime.now().timestamp()
    
    # Load relevant data based on user type
    if current_user.user_type == 'worker':
        # For workers: get available jobs and their applications
        # Get jobs they haven't applied to
        applied_job_ids = db.session.query(Application.job_id).filter_by(applicant_id=current_user.id).all()
        applied_job_ids = [job_id for (job_id,) in applied_job_ids]
        
        # Get open jobs that aren't filled
        today = datetime.now().date()
        jobs = Job.query.filter(
            ~Job.id.in_(applied_job_ids),
            Job.work_date >= today,
            Job.status == 'open'
        ).order_by(Job.created_at.desc()).limit(5).all()
        
        # Get worker's applications
        applications = Application.query.filter_by(applicant_id=current_user.id).all()
        
        # Return worker dashboard
        return render_template(
            'dashboard.html', 
            jobs=jobs,
            applications=applications,
            applied_jobs=applied_job_ids,
            first_login=show_first_login_modal,
            profile_incomplete=profile_incomplete,
            missing_fields=missing_fields,
            today=today
        )
    else:
        # Get employer's posted jobs
        jobs = Job.query.filter_by(employer_id=current_user.id).all()
        
        # Get ALL applications for those jobs with proper eager loading
        job_ids = [job.id for job in jobs]
        applications = []
        
        if job_ids:
            # Load all applications with applicant and job relationships
            # Use explicit query instead of relationship to ensure complete loading
            applications = Application.query.filter(
                Application.job_id.in_(job_ids)
            ).options(
                db.joinedload(Application.applicant),
                db.joinedload(Application.job)
            ).order_by(Application.created_at.desc()).all()
            
            # Ensure all worker applications have initiated_by set correctly
            for app in applications:
                if not app.initiated_by:
                    # If missing, determine based on context: 
                    # - If worker approved and employer didn't, it was worker-initiated
                    # - Otherwise, it was likely employer-initiated
                    app.initiated_by = 'worker' if app.worker_approved and not app.employer_approved else 'employer'
                    db.session.commit()
                
                # Double-check for debug: Print out application info
                print(f"Application {app.id}: initiated_by={app.initiated_by}, status={app.status}, worker_approved={app.worker_approved}, employer_approved={app.employer_approved}")
        
        # Render employer dashboard
        response = make_response(render_template(
            'dashboard.html', 
            posted_jobs=jobs,
            applications=applications,
            first_login=show_first_login_modal,
            profile_incomplete=profile_incomplete,
            missing_fields=missing_fields,
            is_premium=current_user.is_premium,
            today=datetime.now().date()
        ))
        return response

@app.route('/notifications')
@login_required
def notifications():
    user_notifications = Notification.query.filter_by(
        recipient_id=current_user.id
    ).order_by(Notification.created_at.desc()).all()

    return render_template(
        'notifications.html',
        notifications=user_notifications
    )


@app.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)

    if notification.recipient_id != current_user.id:
        flash('Access denied', 'danger')
        return redirect(url_for('notifications'))

    notification.is_read = True
    db.session.commit()

    return redirect(url_for('notifications'))
@app.route('/jobs')
@login_required
def job_listings():
    # Get search parameters
    title = request.args.get('title', '').strip()
    location = request.args.get('location', '').strip()
    work_date_str = request.args.get('work_date', '').strip()
    min_wage_str = request.args.get('min_wage', '').strip()
    
    # Start with base query
    query = Job.query.filter_by(status='open')
    
    # Apply filters
    if title:
        query = query.filter(Job.title.ilike(f'%{title}%'))
    if location:
        query = query.filter(Job.location.ilike(f'%{location}%'))
    if work_date_str:
        try:
            work_date = datetime.strptime(work_date_str, '%Y-%m-%d').date()
            query = query.filter(Job.work_date == work_date)
        except ValueError:
            pass
    if min_wage_str:
        try:
            min_wage = float(min_wage_str)
            query = query.filter(Job.wage >= min_wage)
        except ValueError:
            pass
    
    # Filter out jobs in the past
    query = query.filter(Job.work_date >= datetime.now().date())
    
    # Get jobs
    jobs = query.order_by(Job.work_date).all()
    
    # For workers, get the list of jobs they've already applied to
    applied_jobs = []
    if current_user.user_type == 'worker':
        applications = Application.query.filter_by(applicant_id=current_user.id).all()
        applied_jobs = [app.job_id for app in applications]
    
    return render_template('jobs.html', jobs=jobs, applied_jobs=applied_jobs)

@app.route('/jobs/<int:job_id>/apply', methods=['POST'])
@login_required
def apply_for_job(job_id):
    try:
        # Check if user is a worker
        if current_user.user_type != 'worker':
            flash('Only workers can apply for jobs', 'danger')
            return redirect(url_for('job_listings'))
        
        # Get the job or return 404
        job = Job.query.get_or_404(job_id)
        
        # Check if job is already filled
        if job.is_filled:
            flash('This job is already filled', 'warning')
            return redirect(url_for('job_listings'))
        
        # Check if job date is in the past
        if job.work_date < datetime.now().date():
            flash('Cannot apply for jobs in the past', 'warning')
            return redirect(url_for('job_listings'))
            
        # Check if worker is available on that date
        if not current_user.is_available_on_date(job.work_date):
            flash('You already have a job scheduled for this date or are marked unavailable', 'warning')
            return redirect(url_for('job_listings'))
        
        # Check for existing application
        existing_application = Application.query.filter_by(
            job_id=job_id, 
            applicant_id=current_user.id
        ).first()
        
        if existing_application:
            flash('You have already applied for this job', 'warning')
            return redirect(url_for('job_listings'))
        
        message = request.form.get('message', 'I am interested in this job')
        
        # Create new application with worker-initiated flag
        application = Application(
            job_id=job_id,
            applicant_id=current_user.id,
            status='pending',
            initiated_by='worker',  # CRITICAL: This must be set to 'worker'
            worker_approved=True,   # Worker approved by applying
            employer_approved=False, # Employer needs to approve
            message=message
        )
        
        # Add to database first to get the ID
        db.session.add(application)
        db.session.commit()
        
        # Double-check that the application was saved correctly with initiated_by set
        saved_app = Application.query.get(application.id)
        app.logger.info(f"WORKER APPLICATION: Worker {current_user.id} applied to job {job_id} - Application ID: {application.id}")
        app.logger.info(f"Application fields: initiated_by='{saved_app.initiated_by}', worker_approved={saved_app.worker_approved}, employer_approved={saved_app.employer_approved}")
        
        # Create or get chat room for this job and worker
        existing_chat = ChatRoom.query.filter(
            ((ChatRoom.user1_id == job.employer_id) & (ChatRoom.user2_id == current_user.id)) |
            ((ChatRoom.user1_id == current_user.id) & (ChatRoom.user2_id == job.employer_id))
        ).first()

        if not existing_chat:
            chat_room = ChatRoom(
                user1_id=job.employer_id,  # Employer is always user1
                user2_id=current_user.id,  # Worker is always user2
                job_id=job_id
            )
            db.session.add(chat_room)
            db.session.commit() # Commit the chat room to get its ID
        
        # Send initial message in chat
        if not existing_chat:
            initial_message = ChatMessage(
                chat_room_id=chat_room.id,
                sender_id=current_user.id,
                receiver_id=job.employer_id,
                message=f"Hi! I've applied for your job: {job.title}. {message}",
                timestamp=datetime.utcnow()
            )
            db.session.add(initial_message)
            db.session.commit()
        
        # Notify the employer directly about this application
        new_notification = Notification(
            recipient_id=job.employer_id,
            title="New Job Application",
            message=f"{current_user.name} applied for your job: {job.title}",
            link=url_for('job_applications', job_id=job.id)
        )

        db.session.add(new_notification)
        db.session.commit()        
        flash('Application submitted successfully! You can now chat with the employer.', 'success')
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error applying for job: {str(e)}', 'danger')
        return redirect(url_for('job_listings'))

@app.route('/post-job', methods=['GET', 'POST'])
@login_required
def post_job():
    if current_user.user_type != 'employer':
        flash('Only employers can post jobs', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        location = request.form.get('location')
        wage = float(request.form.get('wage'))
        maximum_workers = int(request.form.get('maximum_workers', 1))
        work_date_str = request.form.get('work_date')
        
        # Convert date string to date object
        try:
            work_date = datetime.strptime(work_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date format. Please use YYYY-MM-DD.', 'danger')
            return redirect(url_for('post_job'))
            
        # Check if date is in the future
        if work_date < datetime.now().date():
            flash('Work date must be in the future.', 'danger')
            return redirect(url_for('post_job'))
        
        # Create and save the job
        job = Job(
            title=title,
            description=description,
            location=location,
            wage=wage,
            employer_id=current_user.id,
            maximum_workers=maximum_workers,
            work_date=work_date,
            status='open'
        )
        db.session.add(job)
        db.session.commit()

        # Create a chat room for this job
        chat_room = ChatRoom(
            user1_id=current_user.id,
            user2_id=None,  # Will be set when a worker joins
            job_id=job.id  # Add this field to ChatRoom model
        )
        db.session.add(chat_room)
        db.session.commit()
        
        # Send SMS notifications to workers without smartphones
        try:
            # Find workers who have opted for SMS notifications
            sms_workers = User.query.filter_by(user_type='worker', sms_notifications=True).all()
            
            if sms_workers:
                notification_count = 0
                for worker in sms_workers:
                    # Send job notification via SMS
                    if send_job_notification(worker, job):
                        notification_count += 1
                
                if notification_count > 0:
                    flash(f'Job posted successfully! SMS notifications sent to {notification_count} workers without smartphones.', 'success')
                else:
                    flash('Job posted successfully', 'success')
            else:
                flash('Job posted successfully', 'success')
        except Exception as e:
            app.logger.error(f"Error sending SMS notifications: {str(e)}")
            flash('Job posted successfully, but there was an error sending SMS notifications.', 'warning')
            
        return redirect(url_for('dashboard'))
    
    return render_template('post_job.html')

@app.route('/jobs/<int:job_id>/applications')
@login_required
def job_applications(job_id):
    if current_user.user_type != 'employer':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    job = Job.query.get_or_404(job_id)
    if job.employer_id != current_user.id:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    applications = Application.query.filter_by(job_id=job_id).all()
    return render_template('job_applications.html', job=job, applications=applications)

@app.route('/applications/<int:application_id>/update', methods=['POST'])
@login_required
def update_application_status(application_id):
    application = Application.query.get_or_404(application_id)
    
    # Verify permissions - must be either the employer or the worker involved
    is_employer = current_user.user_type == 'employer' and application.job.employer_id == current_user.id
    is_worker = current_user.user_type == 'worker' and application.applicant_id == current_user.id
    
    if not (is_employer or is_worker):
        flash('You do not have permission to update this application', 'danger')
        return redirect(url_for('dashboard'))
    
    # Get the status from the form
    action = request.form.get('action')
    
    # Enforce proper permission flow:
    # - If employer initiated (invited worker), only worker can accept/reject
    # - If worker initiated (applied to job), only employer can accept/reject
    if application.initiated_by == 'employer' and is_employer:
        flash('Only the worker can respond to an invitation', 'warning')
        return redirect(url_for('job_applications', job_id=application.job_id))
    
    if application.initiated_by == 'worker' and is_worker:
        flash('Only the employer can respond to your application', 'warning') 
        return redirect(url_for('dashboard'))
    
    if is_employer:
        # Employer actions - only for worker-initiated applications
        if action == 'approve':
            application.employer_approved = True
            application.status = 'accepted'  # Set status to accepted immediately
            print(f"DEBUG: Approving application {application.id}. Status set to: {application.status}")
            
            # Send SMS notification if worker doesn't have a smartphone
            worker = User.query.get(application.applicant_id)
            if worker and worker.sms_notifications:
                try:
                    send_application_status_update(worker, application.job, 'accepted')
                except Exception as e:
                    app.logger.error(f"Error sending SMS status update: {str(e)}")
            
            flash('You have approved this application', 'success')
            
            # If job now reaches maximum workers, update job status
            job = application.job
            accepted_count = Application.query.filter_by(job_id=job.id, status='accepted').count() + 1  # +1 for current application
            if accepted_count >= job.maximum_workers and job.status != 'filled':
                job.status = 'filled'
                flash('The job is now filled to capacity', 'info')
                
        elif action == 'reject':
            application.employer_approved = False
            application.status = 'rejected'
            print(f"DEBUG: Rejecting application {application.id}. Status set to: {application.status}")
            flash('Application has been rejected', 'info')
    elif is_worker:
        # Worker actions - only for employer-initiated invitations
        if action == 'approve':
            application.worker_approved = True
            application.status = 'accepted'  # Set status to accepted immediately
            flash('You have approved this job invitation', 'success')
            
            # If job now reaches maximum workers, update job status
            job = application.job
            accepted_count = Application.query.filter_by(job_id=job.id, status='accepted').count() + 1  # +1 for current application
            if accepted_count >= job.maximum_workers and job.status != 'filled':
                job.status = 'filled'
                flash('The job is now filled to capacity', 'info')
                
        elif action == 'reject':
            application.worker_approved = False
            application.status = 'rejected'
            flash('Job invitation has been declined', 'info')
    
    # Commit the changes to the database
    db.session.commit()
    
    # Verify the application status after database commit
    updated_app = Application.query.get(application_id)
    print(f"DEBUG: After commit - Application {updated_app.id} status: {updated_app.status}, employer_approved: {updated_app.employer_approved}, worker_approved: {updated_app.worker_approved}")
    
    # Redirect based on user type
    if is_employer:
        return redirect(url_for('job_applications', job_id=application.job_id))
    else:
        return redirect(url_for('dashboard'))

# Optional: Slightly updated KNN training function returning a map for easier lookup
def train_knn_model_v2():
    """
    Trains KNN model and returns pipeline and a dictionary mapping worker IDs to worker objects.
    """
    try:
        workers = User.query.filter_by(user_type='worker').all()
        if not workers:
            return None, {}

        data = []
        worker_ids_map = {} # Store ID -> worker object
        for worker in workers:
            skills = worker.skills.split(',') if worker.skills else []
            features = {
                # Include 'id' temporarily for joining back later if needed, but don't train on it
                'skills': skills,
                'rating': float(worker.avg_rating) if worker.avg_rating else 0.0,
                'hourly_rate': float(worker.hourly_rate) if worker.hourly_rate else 0.0,
                'latitude': worker.latitude if worker.latitude else 0.0,
                'longitude': worker.longitude if worker.longitude else 0.0
            }
            data.append(features)
            worker_ids_map[worker.id] = worker # Map ID to object

        if not data:
             return None, {}

        df = pd.DataFrame(data)

        # Define feature columns (ensure these names match keys in 'features' dict)
        categorical_features = ['skills'] # Make sure 'skills' is handled correctly as potentially list-like by OneHotEncoder
        numerical_features = ['rating', 'hourly_rate', 'latitude', 'longitude']

        # Handle skills appropriately for OneHotEncoder if they are lists
        # One way is to MultiLabelBinarizer or similar, or flatten/join them carefully.
        # For simplicity with OneHotEncoder expecting single category per row in standard use,
        # let's ensure 'skills' column is treated correctly.
        # A simple approach if OneHotEncoder struggles: use TF-IDF or CountVectorizer for skills text.
        # Sticking with OneHotEncoder for now, assuming it handles list-like input or needs adjustment.
        # If skills are complex, consider a different text vectorization approach.

        # Let's assume skills need preprocessing before OneHotEncoder if they are lists
        # A placeholder/simplification: Join skills into a single string for OneHotEncoding basic demo
        # A better approach would use MultiLabelBinarizer or handle list features properly.
        df['skills_joined'] = df['skills'].apply(lambda x: ' '.join(sorted(list(set(x))))) # Simple join

        preprocessor = ColumnTransformer(
            transformers=[
                # Use the joined skills string for OHE
                ('skills', OneHotEncoder(handle_unknown='ignore', sparse_output=False), ['skills_joined']),
                ('num', StandardScaler(), numerical_features)
            ],
            remainder='drop' # Drop original 'skills' list column if not used elsewhere
        )

        # KNN doesn't strictly need to be in the pipeline for fitting the preprocessor,
        # but it's convenient to bundle them. We don't fit KNN here, just the preprocessor.
        pipeline = Pipeline([
            ('preprocessor', preprocessor),
            # ('knn', NearestNeighbors()) # We fit KNN later on the relevant subset
        ])

        # Fit the preprocessor on the entire dataset
        pipeline.fit(df)

        # Return the pipeline (with fitted preprocessor) and the worker map
        return pipeline, worker_ids_map

    except Exception as e:
        current_app.logger.error(f"Error training KNN model: {str(e)}", exc_info=True) # Use logger
        return None, {}
    
    
# --- Haversine Function ---
def haversine(lon1, lat1, lon2, lat2):
    """Calculate the great-circle distance between two points in kilometers"""
    # Ensure inputs are floats and not None
    if None in [lon1, lat1, lon2, lat2]:
        return float('inf') # Return infinite distance if coordinates are missing
    try:
        # Convert degrees to radians
        lon1, lat1, lon2, lat2 = map(math.radians, [float(lon1), float(lat1), float(lon2), float(lat2)])

        # Haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        radius_earth = 6371  # Earth radius in kilometers
        return radius_earth * c
    except (ValueError, TypeError):
         return float('inf') # Handle potential conversion errors


@app.route('/search')
@login_required
def search_workers():
    try:
        # --- 1. Get and clean search parameters ---
        search_name = request.args.get('name', '').strip()
        search_skill = request.args.get('skill', '').strip()
        search_location = request.args.get('location', '').strip()
        min_rating = float(request.args.get('min_rating', 0))
        max_rate_str = request.args.get('max_rate')
        search_status = request.args.get('status', '').strip()

        max_rate = None
        if max_rate_str:
            try:
                max_rate = float(max_rate_str)
            except ValueError:
                flash('Invalid maximum rate provided.', 'warning')
                pass # Ignore invalid rate

        # --- 2. Initial Database Query (Non-String Filters) ---
        query = User.query.filter_by(user_type='worker')
        if min_rating > 0:
            query = query.filter(User.avg_rating >= min_rating)
        if max_rate is not None:
            query = query.filter(User.hourly_rate <= max_rate)
        if search_status:
            query = query.filter(User.status == search_status) # Case-sensitive status match

        initial_candidates = query.all()
        workers_found = []
        search_performed = bool(search_name or search_skill or search_location)
        # Initialize search_mode - this will be passed to the template
        search_mode = 'no_results'

        # --- 3. Python-based Filtering (Exact Matches First) ---
        if initial_candidates and search_performed:
            exact_matches = list(initial_candidates) # Start with all candidates passing DB filters

            # Filter by name (case-insensitive substring match)
            if search_name:
                exact_matches = [w for w in exact_matches if search_name.lower() in w.name.lower()]

            # Filter by skills (any searched skill substring-matches any worker skill)
            if search_skill:
                skill_terms = {s.strip().lower() for s in search_skill.split(',') if s.strip()}
                if skill_terms:
                    temp_matches = []
                    for w in exact_matches:
                        worker_skills = {ws.strip().lower() for ws in w.skills.split(',') if ws.strip()} if w.skills else set()
                        if any(st in ws for st in skill_terms for ws in worker_skills):
                             temp_matches.append(w)
                    exact_matches = temp_matches

            # Filter by location (any searched location substring-matches worker location)
            if search_location:
                location_terms = {loc.strip().lower() for loc in search_location.split(',') if loc.strip()}
                if location_terms:
                    exact_matches = [w for w in exact_matches if w.location and any(lt in w.location.lower() for lt in location_terms)]

            # Check if exact filtering yielded results
            if exact_matches:
                workers_found = exact_matches # Store exact matches
                search_mode = 'exact'        # Set mode to 'exact'

        # --- 4. Fuzzy Search Fallback ---
        # Perform fuzzy search ONLY if exact search failed AND a search was performed
        if search_mode != 'exact' and initial_candidates and search_performed:
            current_app.logger.info("No exact matches found, performing fuzzy search...") # Use logger
            fuzzy_matches = list(initial_candidates) # Start again with all initial candidates

            # Filter fuzzily by name
            if search_name:
                fuzzy_matches = [
                    w for w in fuzzy_matches
                    if fuzz.token_sort_ratio(search_name.lower(), w.name.lower()) >= FUZZY_THRESHOLD
                ]

            # Filter fuzzily by skills
            if search_skill:
                skill_terms = {s.strip().lower() for s in search_skill.split(',') if s.strip()}
                if skill_terms:
                    temp_matches = []
                    for w in fuzzy_matches:
                        worker_skills = {ws.strip().lower() for ws in w.skills.split(',') if ws.strip()} if w.skills else set()
                        if not worker_skills: continue
                        # Check if *any* searched skill fuzzily matches *any* worker skill
                        match_found = any(fuzz.token_sort_ratio(st, ws) >= FUZZY_THRESHOLD for st in skill_terms for ws in worker_skills)
                        if match_found:
                            temp_matches.append(w)
                    fuzzy_matches = temp_matches

            # Filter fuzzily by location (string matching)
            if search_location:
                location_terms = {loc.strip().lower() for loc in search_location.split(',') if loc.strip()}
                if location_terms:
                    temp_matches = []
                    for w in fuzzy_matches:
                        if not w.location: continue
                        # Check if *any* searched location term fuzzily matches the worker's location string
                        match_found = any(fuzz.token_sort_ratio(lt, w.location.lower()) >= FUZZY_THRESHOLD for lt in location_terms)
                        if match_found:
                            temp_matches.append(w)
                    fuzzy_matches = temp_matches

            # Check if fuzzy filtering yielded results
            if fuzzy_matches:
                workers_found = fuzzy_matches # Store fuzzy matches
                search_mode = 'fuzzy'        # Set mode to 'fuzzy'

        # --- 5. Handle Case: No String Search ---
        # If no specific search terms were entered, show initial candidates
        elif not search_performed and initial_candidates:
             workers_found = initial_candidates
             search_mode = 'broad' # Indicate results are broad, not specific search matches

        # If workers_found is still empty here, search_mode remains 'no_results'

        # --- 6. Prepare Employer/Application Data ---
        employer_jobs = []
        worker_job_applications = {}
        if current_user.user_type == 'employer':
            employer_jobs = Job.query.filter_by(employer_id=current_user.id, status='open').all()
            if workers_found: # Only proceed if we have workers to check against
                job_ids = [job.id for job in employer_jobs]
                if job_ids:
                    worker_ids = [worker.id for worker in workers_found]
                    applications = Application.query.filter(
                        Application.job_id.in_(job_ids),
                        Application.applicant_id.in_(worker_ids)
                    ).all()
                    # Organize applications for easy lookup in the template
                    for app in applications:
                        if app.applicant_id not in worker_job_applications:
                            worker_job_applications[app.applicant_id] = {}
                        worker_job_applications[app.applicant_id][app.job_id] = app.status

        # --- 7. KNN-based sorting (Applied to final list: workers_found) ---
        ordered_workers = workers_found # Default order is the filtered order
        if workers_found: # Only attempt KNN sorting if there are results
            current_app.logger.info(f"Attempting KNN sorting on {len(workers_found)} workers.")
            # Assuming train_knn_model_v2 is defined elsewhere and returns (pipeline, worker_id_map)
            knn_pipeline, all_worker_ids_map = train_knn_model_v2()
            if knn_pipeline and all_worker_ids_map:
                try:
                    # --- Prepare data for ALL workers in the KNN model ---
                    all_worker_data = []
                    all_worker_ids_list = list(all_worker_ids_map.keys()) # Consistent order
                    for wid in all_worker_ids_list:
                        worker = all_worker_ids_map[wid]
                        all_worker_data.append({
                            'skills': worker.skills.split(',') if worker.skills else [],
                            'rating': float(worker.avg_rating or 0.0),
                            'hourly_rate': float(worker.hourly_rate or 0.0),
                            'latitude': worker.latitude or 0.0, # KNN uses coordinates
                            'longitude': worker.longitude or 0.0
                        })

                    if not all_worker_data:
                        raise ValueError("No data available for KNN model training.")

                    all_df = pd.DataFrame(all_worker_data)
                    # Transform ALL data using the fitted preprocessor from the pipeline
                    X_all = knn_pipeline.named_steps['preprocessor'].transform(all_df)

                    # --- Identify indices of the FILTERED workers within the ALL data ---
                    filtered_worker_ids = {w.id for w in workers_found}
                    original_indices_map = {wid: i for i, wid in enumerate(all_worker_ids_list)}
                    filtered_indices_in_all = [original_indices_map[wid] for wid in filtered_worker_ids if wid in original_indices_map]

                    if not filtered_indices_in_all:
                         current_app.logger.warning("Filtered workers not found in KNN model data. Skipping KNN sort.")
                    else:
                        # Select feature vectors for the filtered workers
                        X_filtered = X_all[filtered_indices_in_all]
                        # Number of neighbors is max the number of filtered results
                        n_neighbors = min(len(filtered_indices_in_all), 50) # Limit neighbors for performance? Or use len(filtered_indices_in_all)

                        if n_neighbors > 0:
                            # Fit KNN on the filtered subset to find neighbors *within* this subset
                            nn = NearestNeighbors(n_neighbors=n_neighbors, metric='cosine') # Cosine often good for high-dim sparse data
                            nn.fit(X_filtered)

                            # Find neighbors for the first worker as a starting point for ordering
                            # This provides one potential ordering based on similarity to the 'most relevant' (?) first result.
                            # Other strategies exist (e.g., clustering, averaging vectors).
                            distances, indices = nn.kneighbors(X_filtered[0:1])

                            # Reconstruct the ordered list based on KNN results
                            temp_ordered_workers = []
                            seen_ids = set()
                            # Map indices within the filtered subset back to worker IDs and then objects
                            original_indices_lookup_filtered = {i: idx_in_all for i, idx_in_all in enumerate(filtered_indices_in_all)}

                            for idx_in_filtered_subset in indices[0]: # indices[0] corresponds to neighbors of the first item
                                try:
                                     original_idx = original_indices_lookup_filtered[idx_in_filtered_subset]
                                     worker_id = all_worker_ids_list[original_idx]
                                     # Find the actual worker object from our 'workers_found' list
                                     worker_obj = next((w for w in workers_found if w.id == worker_id), None)
                                     if worker_obj and worker_id not in seen_ids:
                                         temp_ordered_workers.append(worker_obj)
                                         seen_ids.add(worker_id)
                                except KeyError:
                                     current_app.logger.warning(f"Index mismatch during KNN reordering: {idx_in_filtered_subset}")


                            # Add any remaining workers from the original filtered list who weren't in the KNN result
                            for w in workers_found:
                                if w.id not in seen_ids:
                                    temp_ordered_workers.append(w)

                            if temp_ordered_workers: # Ensure we don't overwrite with an empty list if something went wrong
                                 ordered_workers = temp_ordered_workers
                        else:
                             current_app.logger.info("Not enough neighbors for KNN sorting.")

                except Exception as e:
                    current_app.logger.error(f"KNN sorting error: {str(e)}", exc_info=True)
                    # Keep original workers_found order if KNN fails, already assigned to ordered_workers

        # --- 8. Format Workers for Display ---
        formatted_workers = []
        for worker in ordered_workers: # Use the potentially KNN-sorted list
            formatted_worker = {
                'id': worker.id,
                'name': worker.name,
                'skills': worker.skills.split(',') if worker.skills else [],
                'rating': float(worker.avg_rating) if worker.avg_rating else 0.0,
                'hourly_rate': float(worker.hourly_rate) if worker.hourly_rate else 0.0,
                'location': worker.location,
                'status': worker.status,
                'image': worker.profile_pic,
                'lat': worker.latitude,    # Pass coordinates for map
                'lng': worker.longitude,
                'job_applications': worker_job_applications.get(worker.id, {}) # Pass application status
            }
            formatted_workers.append(formatted_worker)

        current_app.logger.info(f"Search finished. Mode: {search_mode}. Workers returned: {len(formatted_workers)}")
        # --- Pass results and mode to the template ---
        return render_template('search.html',
                             workers=formatted_workers,
                             employer_jobs=employer_jobs,
                             search_mode=search_mode) # Pass the determined search mode

    except Exception as e:
        current_app.logger.error(f"Unhandled Search error: {str(e)}", exc_info=True) # Log the full error
        flash('An unexpected error occurred while searching for workers.', 'error')
        # Pass 'error' mode to template
        return render_template('search.html', workers=[], employer_jobs=[], search_mode='error')

@app.route('/api/workers')
def get_workers():
    return jsonify(MOCK_WORKERS)

@app.route('/jobs/<int:job_id>/delete', methods=['POST'])
@login_required
def delete_job(job_id):
    job = Job.query.get_or_404(job_id)
    
    # Check if the current user is the employer who posted the job
    if job.employer_id != current_user.id:
        flash('You can only delete your own job postings', 'danger')
        return redirect(url_for('dashboard'))
    
    # Delete associated applications first
    Application.query.filter_by(job_id=job.id).delete()
    
    # Delete the job
    db.session.delete(job)
    db.session.commit()
    
    flash('Job deleted successfully', 'success')
    return redirect(url_for('dashboard'))

@app.route('/workers/status', methods=['POST'])
@login_required
def update_worker_status():
    if current_user.user_type != 'worker':
        flash('Only workers can update their status', 'danger')
        return redirect(url_for('dashboard'))
    
    new_status = request.form.get('status')
    if new_status in ['available', 'busy', 'unavailable']:
        current_user.status = new_status
        db.session.commit()
        flash('Status updated successfully', 'success')
    
    return redirect(url_for('dashboard'))

@app.route('/workers/<int:worker_id>/invite/<int:job_id>', methods=['GET', 'POST'])
@login_required
def invite_worker(worker_id, job_id):
    # Check if user is an employer
    if current_user.user_type != 'employer':
        flash('Only employers can invite workers', 'danger')
        return redirect(url_for('dashboard'))
    
    # Get the worker and job
    worker = User.query.get_or_404(worker_id)
    job = Job.query.get_or_404(job_id)
    
    # Verify this is the employer's job
    if job.employer_id != current_user.id:
        flash('You can only invite workers to your own jobs', 'danger')
        return redirect(url_for('search_workers'))
    
    # Check if job is already filled
    if job.is_filled:
        flash('This job is already filled', 'warning')
        return redirect(url_for('job_applications', job_id=job_id))
        
    # Check if job date is in the past
    if job.work_date < datetime.now().date():
        flash('Cannot invite workers to jobs in the past', 'warning')
        return redirect(url_for('search_workers'))
    
    # Check for existing application
    existing_application = Application.query.filter_by(
        job_id=job_id, 
        applicant_id=worker_id
    ).first()
    
    if existing_application:
        flash('This worker has already applied or been invited to this job', 'warning')
        return redirect(url_for('search_workers'))
    
    # Check if worker is available on that date
    if not worker.is_available_on_date(job.work_date):
        flash('This worker is unavailable on the selected date', 'warning')
        return redirect(url_for('search_workers'))
    
    if request.method == 'POST':
        # Create invitation (employer-initiated application)
        message = request.form.get('message', '')
        
        application = Application(
            job_id=job_id,
            applicant_id=worker_id,
            status='pending',
            initiated_by='employer',  # This is important - marks it as employer initiated
            worker_approved=False,    # Worker needs to approve invitation
            employer_approved=True,   # Employer approved by inviting
            message=message
        )
        
        db.session.add(application)
        db.session.commit()
        
        app.logger.info(f"Employer {current_user.id} invited worker {worker_id} to job {job_id} - Application ID: {application.id}")
        
        # Create or get chat room for this job and worker
        existing_chat = ChatRoom.query.filter(
            ((ChatRoom.user1_id == current_user.id) & (ChatRoom.user2_id == worker_id)) |
            ((ChatRoom.user1_id == worker_id) & (ChatRoom.user2_id == current_user.id))
        ).first()

        if not existing_chat:
            chat_room = ChatRoom(
                user1_id=current_user.id,  # Employer is always user1
                user2_id=worker_id,       # Worker is always user2
                job_id=job_id
            )
            db.session.add(chat_room)
            db.session.commit()
            
            # Send initial message in chat
            initial_message = ChatMessage(
                chat_room_id=chat_room.id,
                sender_id=current_user.id,
                receiver_id=worker_id,
                message=f"Hi! I've invited you to my job: {job.title}. {message if message else 'I think you would be a good fit for this position.'}",
                timestamp=datetime.utcnow()
            )
            db.session.add(initial_message)
            db.session.commit()
        
        flash(f'Invitation sent to {worker.name}', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('invite_worker.html', worker=worker, job=job)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    # Check if this is a dismiss request
    dismiss = request.args.get('dismiss') == 'true'
    if dismiss:
        # Set the next reminder time to 30 minutes from now
        next_reminder_time = datetime.now() + timedelta(minutes=30)
        session['next_profile_reminder'] = next_reminder_time.timestamp()
        
        # Set a cookie to remember the dismissal
        response = make_response(jsonify(success=True, message="Profile reminder dismissed for 30 minutes"))
        response.set_cookie('profile_reminder_dismissed', 'true', max_age=30*60)  # 30 minutes
        
        # If this is an AJAX request, return JSON response
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return response
        
        # Otherwise redirect to dashboard with the cookie
        redirect_response = make_response(redirect(url_for('dashboard')))
        redirect_response.set_cookie('profile_reminder_dismissed', 'true', max_age=30*60)
        return redirect_response
    
    if request.method == 'POST':
        # Get form data
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        bio = request.form.get('bio')
        location = request.form.get('location')
        
        # For workers only
        if current_user.user_type == 'worker':
            hourly_rate = request.form.get('hourly_rate')
            skills = request.form.get('skills')
            smartphone_access = request.form.get('has_smartphone', 'yes')
            
            if hourly_rate:
                current_user.hourly_rate = float(hourly_rate)
            
            if skills:
                current_user.skills = skills
                
            # Update smartphone access preference
            has_smartphone = smartphone_access == 'yes'
            current_user.has_smartphone = has_smartphone
            # If user doesn't have a smartphone, enable SMS notifications
            current_user.sms_notifications = not has_smartphone
        
        # Update common fields
        if name:
            current_user.name = name
        
        if email:
            current_user.email = email
        
        if phone:
            current_user.phone = phone
        
        if bio:
            current_user.bio = bio
            
        if location:
            current_user.location = location
        
        # Handle profile picture upload
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename != '':
                if allowed_file(file.filename):
                    # Generate a secure filename
                    filename = secure_filename(file.filename)
                    # Create a unique filename
                    unique_filename = f"{current_user.id}_{int(time.time())}_{filename}"
                    # Save file
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    file.save(file_path)
                    # Update user's profile picture path
                    current_user.profile_pic = unique_filename
                else:
                    flash('Invalid file format. Please upload images only.', 'danger')
                    return redirect(url_for('profile'))
        
        # Save changes
        db.session.commit()
        
        # Check if profile is now complete
        profile_incomplete = False
        if current_user.user_type == 'worker' and (not current_user.skills or not current_user.hourly_rate):
            profile_incomplete = True
        elif current_user.user_type == 'employer' and not current_user.bio:
            profile_incomplete = True
            
        # If profile is complete, remove the reminder settings and cookie
        if not profile_incomplete:
            session.pop('next_profile_reminder', None)
            response = make_response(redirect(url_for('profile')))
            response.set_cookie('profile_reminder_dismissed', '', expires=0)  # Clear the cookie
            flash('Profile updated successfully!', 'success')
            return response
        
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))
    
    return render_template('profile.html', user=current_user)

# ChatRoom model is already defined at the top of the file

# ChatMessage model is already defined at the top of the file
# Removing duplicate definition

# Chat routes
@app.route('/chat')
@login_required
def chat_list():
    # Get all chat rooms for the current user
    chat_rooms = ChatRoom.query.filter(
        (ChatRoom.user1_id == current_user.id) | 
        (ChatRoom.user2_id == current_user.id)
    ).all()
    
    # Filter out self-chat rooms and rooms where worker hasn't joined yet
    if current_user.user_type == 'employer':
        chat_rooms = [room for room in chat_rooms if room.user2_id is not None]
    
    # Add current datetime to template context
    now = datetime.utcnow()
    
    return render_template('chat_list.html', chat_rooms=chat_rooms, now=now)

@app.route('/chat/<int:room_id>')
@login_required
def chat(room_id):
    try:
        # Get the chat room
        room = ChatRoom.query.get_or_404(room_id)
        
        # Check if user has access to this chat room
        if current_user.id not in [room.user1_id, room.user2_id]:
            flash('You do not have access to this chat room', 'error')
            return redirect(url_for('chat_list'))
        
        # Get the other user
        other_user = room.get_other_user(current_user.id)
        if not other_user:
            flash('Chat partner not found', 'error')
            return redirect(url_for('chat_list'))
        
        # Get chat history
        messages = ChatMessage.query.filter_by(chat_room_id=room_id).order_by(ChatMessage.timestamp).all()
        
        # Mark unread messages as read
        unread_messages = ChatMessage.query.filter_by(
            chat_room_id=room_id,
            receiver_id=current_user.id,
            is_read=False
        ).all()
        
        for msg in unread_messages:
            msg.is_read = True
        db.session.commit()
        
        return render_template('chat.html', 
                             room=room,
                             other_user=other_user,
                             messages=messages)
    except Exception as e:
        print(f"Chat error: {str(e)}")
        flash('An error occurred while loading the chat', 'error')
        return redirect(url_for('chat_list'))

@app.route('/chat/create/<int:user_id>')
@login_required
def create_chat(user_id):
    try:
        # Check if chat room already exists
        existing_room = ChatRoom.query.filter(
            ((ChatRoom.user1_id == current_user.id) & (ChatRoom.user2_id == user_id)) |
            ((ChatRoom.user1_id == user_id) & (ChatRoom.user2_id == current_user.id))
        ).first()
        
        if existing_room:
            return redirect(url_for('chat', room_id=existing_room.id))
        
        # Create new chat room
        chat_room = ChatRoom(
            user1_id=current_user.id,
            user2_id=user_id
        )
        db.session.add(chat_room)
        db.session.commit()
        
        return redirect(url_for('chat', room_id=chat_room.id))
    except Exception as e:
        print(f"Create chat error: {str(e)}")
        flash('An error occurred while creating the chat room', 'error')
        return redirect(url_for('chat_list'))

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")
    user_rooms[request.sid] = set()

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")
    if request.sid in user_rooms:
        # Leave all rooms
        for room in user_rooms[request.sid]:
            leave_room(room)
        del user_rooms[request.sid]

@socketio.on('join')
def on_join(data):
    try:
        room = data['room']
        join_room(room)
        if request.sid not in user_rooms:
            user_rooms[request.sid] = set()
        user_rooms[request.sid].add(room)
        
        # Get chat history
        messages = ChatMessage.query.filter_by(chat_room_id=room).order_by(ChatMessage.timestamp).all()
        emit('chat_history', [{
            'content': msg.message,
            'sender_id': msg.sender_id,
            'timestamp': msg.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        } for msg in messages])
    except Exception as e:
        print(f"Error joining room: {str(e)}")
        emit('error', {'message': 'Failed to join chat room'})

@socketio.on('leave')
def on_leave(data):
    try:
        room = data['room']
        leave_room(room)
        if request.sid in user_rooms:
            user_rooms[request.sid].discard(room)
    except Exception as e:
        print(f"Error leaving room: {str(e)}")

@socketio.on('message')
def handle_message(data):
    try:
        print(f"Received message data: {data}")  # Debug log
        room_id = str(data.get('room'))
        message = data.get('message')
        sender_id = int(data.get('sender_id'))
        receiver_id = int(data.get('receiver_id'))
        
        if not all([room_id, message, sender_id, receiver_id]):
            raise ValueError("Missing required message data")
            
        # Validate sender
        if sender_id != current_user.id:
            raise ValueError("Invalid sender ID")
            
        # Create and save message
        new_message = ChatMessage(
            chat_room_id=room_id,
            sender_id=sender_id,
            receiver_id=receiver_id,
            message=message,
            timestamp=datetime.utcnow()
        )
        db.session.add(new_message)
        db.session.commit()
        
        # Prepare message data for broadcasting
        message_data = {
            'message': message,
            'sender_id': sender_id,
            'receiver_id': receiver_id,
            'timestamp': new_message.timestamp.isoformat()
        }
        
        print(f"Broadcasting message: {message_data}")  # Debug log
        emit('message', message_data, room=room_id)
        
    except ValueError as e:
        print(f"Validation error: {str(e)}")  # Debug log
        emit('error', {'message': str(e)})
    except Exception as e:
        print(f"Error handling message: {str(e)}")  # Debug log
        emit('error', {'message': 'Failed to send message'})

@app.route('/jobs/<int:job_id>')
@login_required
def job_details(job_id):
    job = Job.query.get_or_404(job_id)
    
    # Check if user has already applied
    has_applied = False
    if current_user.user_type == 'worker':
        has_applied = Application.query.filter_by(
            job_id=job_id,
            applicant_id=current_user.id
        ).first() is not None
    
    # Get or create chat room
    chat_room = None
    if current_user.user_type == 'worker':
        chat_room = ChatRoom.query.filter_by(job_id=job_id).first()
        if not chat_room:
            chat_room = ChatRoom(
                user1_id=job.employer_id,
                user2_id=current_user.id,
                job_id=job.id
            )
            db.session.add(chat_room)
    
    return render_template('job_details.html',
                         job=job,
                         has_applied=has_applied,
                         chat_room=chat_room)
    
    
@app.context_processor
def inject_chat_rooms():
    if current_user.is_authenticated:
        rooms = ChatRoom.query.filter(
            (ChatRoom.user1_id == current_user.id) |
            (ChatRoom.user2_id == current_user.id)
        ).all()

        unread_notifications = Notification.query.filter_by(
            recipient_id=current_user.id,
            is_read=False
        ).count()

        return dict(
            chat_rooms=rooms,
            unread_notifications=unread_notifications
        )

    return dict(
        chat_rooms=[],
        unread_notifications=0
    )


@app.route('/jobs/<int:job_id>/delete-application', methods=['POST'])
@login_required
def delete_application(job_id):
    if current_user.user_type != 'worker':
        flash('Only workers can delete their applications', 'danger')
        return redirect(url_for('dashboard'))
    
    application = Application.query.filter_by(
        job_id=job_id,
        applicant_id=current_user.id
    ).first_or_404()
    
    # Only allow deletion of pending applications
    if application.status != 'pending':
        flash('Only pending applications can be deleted', 'warning')
        return redirect(url_for('job_details', job_id=job_id))
    
    db.session.delete(application)
    db.session.commit()
    
    flash('Application deleted successfully', 'success')
    return redirect(url_for('job_details', job_id=job_id))

@app.route('/profile/<int:user_id>')
@login_required
def view_profile(user_id):
    try:
        # If viewing own profile, redirect to profile page
        if user_id == current_user.id:
            return redirect(url_for('profile'))

        # Get the user
        user = User.query.get(user_id)
        if not user:
            print(f"Profile error: User {user_id} not found")
            flash('Worker not found.', 'danger')
            return redirect(url_for('search_workers'))

        # Only allow viewing worker profiles
        if user.user_type != 'worker':
            print(f"Profile error: User {user_id} is not a worker")
            flash('Access denied', 'danger')
            return redirect(url_for('dashboard'))

        # Get employer's jobs for the invitation dropdown
        employer_jobs = []
        worker_job_applications = {}

        if current_user.user_type == 'employer':
            # Get open jobs that can be applied to
            employer_jobs = Job.query.filter_by(employer_id=current_user.id, status='open').all()

            # Get all applications that involve this worker and the employer's jobs
            job_ids = [job.id for job in employer_jobs]
            if job_ids:
                applications = Application.query.filter(
                    Application.job_id.in_(job_ids),
                    Application.applicant_id == user_id
                ).all()

                # Organize applications by job_id for easy lookup
                for app in applications:
                    worker_job_applications[app.job_id] = app.status

        # Get worker's reviews
        reviews = Review.query.filter_by(reviewee_id=user_id).order_by(Review.created_at.desc()).all()

        # Add current datetime object (not a function) for template
        now = datetime.utcnow()

        # Ensure user.skills is never None
        if user.skills is None:
            user.skills = ""

        return render_template('view_profile.html',
                              user=user,
                              employer_jobs=employer_jobs,
                              worker_job_applications=worker_job_applications,
                              reviews=reviews,
                              now=now)
    except Exception as e:
        import traceback
        print(f"Profile error: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        flash('An error occurred while loading the profile.', 'danger')
        return redirect(url_for('dashboard'))



@app.route('/api/autocomplete', methods=['GET'])
def autocomplete():
    term = request.args.get('term', '')
    type_filter = request.args.get('type', '')
    
    if not term or len(term) < 2:
        return jsonify([])
    
    results = []
    
    if type_filter == 'worker_names':
        # Query for worker names
        workers = User.query.filter(
            User.user_type == 'worker',
            User.name.ilike(f'%{term}%')
        ).limit(10).all()
        results = [worker.name for worker in workers]
    
    elif type_filter == 'skills':
        # Query for skills
        workers = User.query.filter(
            User.user_type == 'worker',
            User.skills.ilike(f'%{term}%')
        ).limit(20).all()
        
        # Extract all skills and flatten the list
        all_skills = []
        for worker in workers:
            if worker.skills:
                worker_skills = [skill.strip() for skill in worker.skills.split(',')]
                all_skills.extend(worker_skills)
        
        # Filter skills that match the term and get unique values
        matching_skills = set()
        for skill in all_skills:
            if term.lower() in skill.lower():
                matching_skills.add(skill)
        
        results = list(matching_skills)[:10]  # Limit to 10 suggestions
    
    elif type_filter == 'locations':
        # Query for locations
        workers = User.query.filter(
            User.user_type == 'worker',
            User.location.ilike(f'%{term}%')
        ).limit(10).all()
        
        # Get unique locations
        locations = set()
        for worker in workers:
            if worker.location:
                locations.add(worker.location)
        
        results = list(locations)
    
    return jsonify(results)

@app.route('/job_analytics')
@login_required
def job_analytics():
    # Only allow employers to access this page
    if current_user.user_type != 'employer':
        flash('Only employers can access job analytics', 'danger')
        return redirect(url_for('dashboard'))
    
    # Check if the employer has premium subscription
    if not current_user.is_premium:
        flash('This is a premium feature. Please upgrade to access Job Analytics.', 'warning')
        return redirect(url_for('premium_subscription'))
    
    # Get the employer's jobs
    jobs = Job.query.filter_by(employer_id=current_user.id).all()
    
    if not jobs:
        flash('You need to post jobs before accessing analytics', 'warning')
        return redirect(url_for('dashboard'))
    
    # Prepare data for analysis
    job_data = []
    total_applications = 0
    applications_by_date = {}
    worker_skills = {}
    
    for job in jobs:
        job_detail = {
            'id': job.id,
            'title': job.title,
            'location': job.location,
            'wage': job.wage,
            'description': job.description,
            'work_date': job.work_date.strftime('%Y-%m-%d') if job.work_date else None,
            'created_at': job.created_at.strftime('%Y-%m-%d'),
            'applications': []
        }
        
        # Process applications for this job
        for app in job.applications:
            # Record application date for trend analysis
            app_date = app.created_at.strftime('%Y-%m-%d')
            if app_date in applications_by_date:
                applications_by_date[app_date] += 1
            else:
                applications_by_date[app_date] = 1
            
            # Record worker skills
            if app.applicant.skills:
                for skill in app.applicant.skills.split(','):
                    skill = skill.strip()
                    if skill in worker_skills:
                        worker_skills[skill] += 1
                    else:
                        worker_skills[skill] = 1
            
            # Add application detail
            job_detail['applications'].append({
                'id': app.id,
                'applicant_name': app.applicant.name,
                'applicant_skills': app.applicant.skills,
                'status': app.status,
                'created_at': app.created_at.strftime('%Y-%m-%d'),
                'message': app.message if app.message else ""
            })
            
            total_applications += 1
        
        job_data.append(job_detail)
    
    # Get date range for trend analysis
    date_range = []
    if jobs:
        oldest_job = min(jobs, key=lambda j: j.created_at)
        start_date = oldest_job.created_at.date()
        end_date = datetime.now().date()
        
        # Create a list of all dates between start and end
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            date_range.append({
                'date': date_str,
                'count': applications_by_date.get(date_str, 0)
            })
            current_date += timedelta(days=1)
    
    # Get top skills
    top_skills = sorted(worker_skills.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # Basic statistics without AI
    basic_stats = {
        'total_jobs': len(jobs),
        'total_applications': total_applications,
        'application_per_job_avg': total_applications / len(jobs) if jobs else 0,
        'top_skills': dict(top_skills),
        'applications_by_date': date_range
    }
    
    # Prepare data for AI analysis
    ai_input = {
        'jobs': [{'id': j.id, 'title': j.title, 'applications': len(j.applications)} for j in jobs],
        'total_applications': total_applications,
        'applications_by_date': applications_by_date,
        'top_skills': dict(top_skills)
    }
    
    # Only run AI analysis if there's enough data
    ai_analysis = {}
    if total_applications > 0:
        try:
            # Check if cached analysis exists and is less than 1 day old
            cache_key = f"ai_analysis_{current_user.id}"
            if cache_key in session and session.get(f"{cache_key}_timestamp") > time.time() - 86400:
                ai_analysis = session[cache_key]
            else:
                # Run AI analysis
                ai_analysis = analyze_job_data_with_gemini(ai_input)
                
                # Cache the result
                session[cache_key] = ai_analysis
                session[f"{cache_key}_timestamp"] = time.time()
        except Exception as e:
            print(f"Error in AI analysis: {e}")
            ai_analysis = {
                "error": f"Could not complete AI analysis: {str(e)}"
            }
    
    return render_template('job_analytics.html', 
                          jobs=jobs, 
                          basic_stats=basic_stats, 
                          ai_analysis=ai_analysis)

@app.route('/job_analytics/refresh_ai', methods=['POST'])
@login_required
def refresh_job_analytics():
    # Only allow employers to access this page
    if current_user.user_type != 'employer':
        flash('Only employers can access job analytics', 'danger')
        return redirect(url_for('dashboard'))
    
    # Get the employer's jobs
    jobs = Job.query.filter_by(employer_id=current_user.id).all()
    
    if not jobs:
        flash('You need to post jobs before accessing analytics', 'warning')
        return redirect(url_for('dashboard'))
    
    # Prepare data for analysis (similar to the job_analytics route)
    job_data = []
    total_applications = 0
    applications_by_date = {}
    worker_skills = {}
    
    for job in jobs:
        # Process applications for this job
        for app in job.applications:
            # Record application date for trend analysis
            app_date = app.created_at.strftime('%Y-%m-%d')
            if app_date in applications_by_date:
                applications_by_date[app_date] += 1
            else:
                applications_by_date[app_date] = 1
            
            # Record worker skills
            if app.applicant.skills:
                for skill in app.applicant.skills.split(','):
                    skill = skill.strip()
                    if skill in worker_skills:
                        worker_skills[skill] += 1
                    else:
                        worker_skills[skill] = 1
            
            total_applications += 1
    
    # Get top skills
    top_skills = sorted(worker_skills.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # Prepare data for AI analysis
    ai_input = {
        'jobs': [{'id': j.id, 'title': j.title, 'applications': len(j.applications)} for j in jobs],
        'total_applications': total_applications,
        'applications_by_date': applications_by_date,
        'top_skills': dict(top_skills)
    }
    
    # Run AI analysis without checking cache
    ai_analysis = {}
    if total_applications > 0:
        try:
            # Run AI analysis
            ai_analysis = analyze_job_data_with_gemini(ai_input)
            
            # Update the cache
            cache_key = f"ai_analysis_{current_user.id}"
            session[cache_key] = ai_analysis
            session[f"{cache_key}_timestamp"] = time.time()
            
            flash('AI analysis has been refreshed!', 'success')
        except Exception as e:
            print(f"Error in AI analysis: {e}")
            ai_analysis = {
                "error": f"Could not complete AI analysis: {str(e)}"
            }
            flash('Error refreshing AI analysis', 'danger')
    else:
        flash('You need applications before AI analysis can be performed', 'warning')
    
    # Redirect back to job analytics page
    return redirect(url_for('job_analytics'))

# New route for AI assistant chat
@app.route('/ai_assistant', methods=['GET', 'POST'])
@login_required
def ai_assistant():
    # Only allow employers to access this page
    if current_user.user_type != 'employer':
        flash('Only employers can access the AI assistant', 'danger')
        return redirect(url_for('dashboard'))
    
    # Check if the employer has premium subscription
    if not current_user.is_premium:
        flash('This is a premium feature. Please upgrade to access the AI Assistant.', 'warning')
        return redirect(url_for('premium_subscription'))
    
    # Get all workers and jobs for context
    all_workers = User.query.filter_by(user_type='worker').all()
    employer_jobs = Job.query.filter_by(employer_id=current_user.id).all()
    
    # Build worker profiles for context
    worker_profiles = []
    for worker in all_workers:
        # Calculate average rating
        rating_text = f"{worker.avg_rating:.1f}/5.0 from {worker.num_ratings} reviews" if worker.num_ratings > 0 else "No ratings yet"
        
        # Format skills as a list
        skills_list = worker.skills.split(',') if worker.skills else []
        skills_formatted = [skill.strip() for skill in skills_list]
        
        # Get application history with this employer
        applications = Application.query.filter_by(
            applicant_id=worker.id
        ).join(
            Job, Job.id == Application.job_id
        ).filter(
            Job.employer_id == current_user.id
        ).all()
        
        application_history = []
        for app in applications:
            application_history.append({
                'job_title': app.job.title,
                'status': app.status,
                'date': app.created_at.strftime('%Y-%m-%d')
            })
        
        # Add worker profile
        worker_profiles.append({
            'id': worker.id,
            'name': worker.name,
            'location': worker.location,
            'skills': skills_formatted,
            'rating': rating_text,
            'status': worker.status,
            'hourly_rate': worker.hourly_rate if worker.hourly_rate else "Not specified",
            'bio': worker.bio if worker.bio else "No bio provided",
            'application_history': application_history
        })
    
    # Build job details for context
    job_details = []
    for job in employer_jobs:
        applications_count = len(job.applications)
        accepted_count = len([a for a in job.applications if a.status == 'accepted'])
        
        job_details.append({
            'id': job.id,
            'title': job.title,
            'location': job.location,
            'wage': job.wage,
            'description': job.description,
            'work_date': job.work_date.strftime('%Y-%m-%d'),
            'status': job.status,
            'applications_count': applications_count,
            'accepted_count': accepted_count,
            'is_filled': job.is_filled
        })
    
    # Initialize chat history
    if 'ai_chat_history' not in session:
        session['ai_chat_history'] = []
    
    # Handle form submission
    ai_response = None
    if request.method == 'POST':
        # Get the user message
        user_message = request.form.get('user_message', '').strip()
        
        # Handle image upload if present
        uploaded_image = None
        if 'image' in request.files and request.files['image'].filename != '':
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # Fix: Use the Flask app instance directly, not the variable name that might be shadowed
                file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                
                # Prepare image for AI
                with open(file_path, "rb") as img_file:
                    uploaded_image = img_file.read()
        
        if user_message or uploaded_image:
            # Save user message to chat history
            if user_message:
                session['ai_chat_history'].append({
                    'role': 'user',
                    'content': user_message
                })
            elif uploaded_image:
                session['ai_chat_history'].append({
                    'role': 'user',
                    'content': "[Uploaded an image of work that needs to be done]"
                })
            
            # Create system prompt with context about workers and jobs
            system_prompt = f"""
# QUICKHIRE ASSISTANT - READ THIS PROMPT CAREFULLY AND FOLLOW ALL INSTRUCTIONS

## CORE IDENTITY
You are 'QuickHire Assistant' - a specialized database query tool integrated into the QuickHire platform.
This platform connects employers with daily wage workers for short-term jobs.

## YOUR DATABASE ACCESS
You have DIRECT ACCESS to the following database information which is REAL and CURRENT:

1. WORKER DATABASE: Contains information about {len(worker_profiles)} workers including their skills, locations, ratings, and availability status.
2. JOB DATABASE: Contains information about {len(job_details)} jobs posted by the current employer ({current_user.name}).
3. APPLICATION HISTORY: Records of which workers have applied to which jobs.

## CRITICAL BEHAVIORAL RULES
1. You are NOT a general AI assistant or language model - YOU ARE THE QUICKHIRE ASSISTANT with database access
2. NEVER say phrases like "I don't have access to specific information" or "I can't access real-time data"
3. NEVER describe yourself as an AI, chatbot, or language model
4. ALWAYS answer using the SPECIFIC data from the databases provided below
5. NEVER invent or hallucinate information about workers or jobs
6. ALWAYS provide SPECIFIC worker names and details when asked about available workers

## PLATFORM DESCRIPTION
The QuickHire platform allows:
- Employers to post jobs, specifying location, wage, work date, and required skills
- Workers to apply to these jobs
- Employers to invite specific workers to jobs
- Both parties to chat and finalize job details
- Rating system after job completion

## DATABASE CONTENTS
### WORKER DATABASE:
```json
{json.dumps(worker_profiles, indent=2)}
```

### JOB DATABASE:
```json
{json.dumps(job_details, indent=2)}
```

## HOW TO RESPOND TO SPECIFIC QUERIES

1. If asked "Who are the workers?":
   - List the actual workers from the database with their names, skills, and ratings
   - Example: "I have information on {len(worker_profiles)} workers. Here are some available workers: [list actual worker names and details]"

2. If asked about specific skills (e.g., "Who can do plumbing?"):
   - Search the worker database for those with matching skills
   - List those specific workers with their details
   - Example: "Based on our database, the following workers have plumbing skills: [list actual workers with plumbing skills]"

3. If asked about the platform:
   - Explain that QuickHire connects employers with daily wage workers
   - Describe relevant features like job posting, worker search, and the application process

4. If users upload an image:
   - Analyze what work appears to be needed in the image
   - Recommend specific workers from the database with relevant skills

## RESPONSE FORMAT
- Use markdown formatting for all responses
- Use tables when listing multiple workers or jobs
- Use bold text for important information
- Use headings to organize your response
- Always be specific, concise, and helpful

Remember: You are a database query tool, not a general assistant. Your purpose is to help employers find and manage workers based on REAL database information you have access to.
"""
            
            # Function to call Gemini API with retry logic
            def get_gemini_response(prompt_content, image_data=None, max_retries=3, retry_delay=2):
                retries = 0
                while retries < max_retries:
                    try:
                        # Initialize the model with the correct version
                        if image_data:
                            model = genai.GenerativeModel('gemini-2.0-flash')
                            response = model.generate_content([
                                {"role": "user", "parts": [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image_data).decode('utf-8')}}]},
                                {"role": "user", "parts": [prompt_content]}
                            ])
                        else:
                            model = genai.GenerativeModel('gemini-2.0-flash')
                            
                            # Prepare the message history for the API
                            # For the first message, combine system prompt with user message
                            messages = []
                            
                            # Create a history of messages for the API in the correct format
                            for i, message in enumerate(session['ai_chat_history']):
                                if message['role'] == 'user':
                                    # For the first user message, prepend the system instructions
                                    if i == 0:
                                        combined_content = f"{system_prompt}\n\nUser: {message['content']}"
                                        messages.append({"role": "user", "parts": [combined_content]})
                                    else:
                                        messages.append({"role": "user", "parts": [message['content']]})
                                else:
                                    messages.append({"role": "model", "parts": [message['content']]})
                            
                            # If we have no history yet but received a new message
                            if not messages and user_message:
                                combined_content = f"{system_prompt}\n\nUser: {user_message}"
                                messages.append({"role": "user", "parts": [combined_content]})
                            
                            response = model.generate_content(messages)
                        
                        return response.text
                    except Exception as e:
                        retries += 1
                        print(f"Error calling Gemini API: {e}")
                        if retries < max_retries:
                            print(f"Retrying in {retry_delay} seconds...")
                            time.sleep(retry_delay)
                        else:
                            return f"Sorry, I encountered an error while processing your request. Please try again later. Error: {str(e)}"
            
            try:
                # Prepare the conversation content
                conversation_content = system_prompt
                
                # Add few-shot examples to guide the model's behavior
                conversation_content += "\n\n## EXAMPLE CONVERSATIONS\n\n"
                
                # Example 1: Website question
                conversation_content += f"""User: "How is this website about?"
Assistant: "QuickHire is a platform that connects employers like you with daily wage workers. You can post jobs, find workers with specific skills, and manage applications all in one place. Currently, you have access to information about {len(worker_profiles)} workers and {len(job_details)} jobs."

"""
                
                # Example 2: Plumber question with actual data
                conversation_content += """User: "Tell me which worker is a plumber?"
Assistant: "Here are the workers in our database with plumbing skills:

| Name | Skills | Rating | Location | Status |
|------|--------|--------|----------|--------|
"""
                
                # Add actual plumbers from the database to the example
                plumbers_found = False
                for worker in worker_profiles:
                    if any("plumb" in skill.lower() for skill in worker['skills']):
                        conversation_content += f"| {worker['name']} | {', '.join(worker['skills'])} | {worker['rating']} | {worker['location']} | {worker['status']} |\n"
                        plumbers_found = True
                
                if not plumbers_found:
                    conversation_content += "| [No workers with plumbing skills were found in the database] | | | | |\n"
                
                # Example 3: Help question
                conversation_content += """\n
User: "What can you help me with?"
Assistant: "As the QuickHire assistant, I can help you with:

1. **Finding Workers**: I can search our database for workers with specific skills, locations, or availability
2. **Job Analysis**: I can analyze your current job postings and application rates
3. **Worker Recommendations**: I can suggest suitable workers for your specific job requirements
4. **Application Management**: I can show you which workers have applied to your jobs
5. **Image Analysis**: You can upload images of work that needs to be done, and I'll suggest workers with relevant skills"

"""
                
                # Add chat history (limited to last 10 messages)
                conversation_content += "\n## CURRENT CONVERSATION\n\n"
                for msg in session['ai_chat_history'][-10:]:
                    role = "User" if msg['role'] == 'user' else "Assistant"
                    conversation_content += f"{role}: {msg['content']}\n\n"
                
                # Add the current query
                if uploaded_image:
                    conversation_content += "User: [Uploaded an image of work that needs to be done]\n\nPlease analyze this image and suggest suitable workers from the database who have the skills needed for this type of work.\n\nAssistant:"
                    ai_response = get_gemini_response(conversation_content, uploaded_image)
                else:
                    conversation_content += f"User: {user_message}\n\nAssistant:"
                    ai_response = get_gemini_response(conversation_content)
                
                # Save AI response to chat history
                session['ai_chat_history'].append({
                    'role': 'assistant',
                    'content': ai_response
                })
                
                # Save chat history to session
                session.modified = True
                
            except Exception as e:
                print(f"Error in AI assistant: {str(e)}")
                ai_response = f"I'm sorry, I encountered an error: {str(e)}"
                session['ai_chat_history'].append({
                    'role': 'assistant',
                    'content': ai_response
                })
    
    return render_template('ai_assistant.html', 
                          chat_history=session.get('ai_chat_history', []),
                          worker_count=len(all_workers),
                          job_count=len(employer_jobs))

@app.route('/ai_assistant/clear', methods=['POST'])
@login_required
def clear_ai_chat():
    # Only allow employers to access this functionality
    if current_user.user_type != 'employer':
        flash('Only employers can access the AI assistant', 'danger')
        return redirect(url_for('dashboard'))
    
    # Clear chat history
    session.pop('ai_chat_history', None)
    flash('Chat history cleared', 'success')
    return redirect(url_for('ai_assistant'))

@app.route('/ai_hub')
@login_required
def ai_hub():
    # Only allow employers to access this page
    if current_user.user_type != 'employer':
        flash('Only employers can access the AI Hub', 'danger')
        return redirect(url_for('dashboard'))
    
    # Check if the employer has premium subscription
    if not current_user.is_premium:
        flash('This is a premium feature. Please upgrade to access the AI Hub.', 'warning')
        return redirect(url_for('premium_subscription'))
    
    return render_template('ai_hub.html')

@app.route('/premium_subscription', methods=['GET', 'POST'])
@login_required
def premium_subscription():
    # Only allow employers to purchase premium
    if current_user.user_type != 'employer':
        flash('Only employers can purchase premium subscription', 'danger')
        return redirect(url_for('dashboard'))
    
    # If the user is already premium
    if current_user.is_premium:
        flash('You already have a premium subscription!', 'success')
        return redirect(url_for('dashboard'))
    
    # Handle payment submission
    if request.method == 'POST':
        upi_id = request.form.get('upi_id')
        
        if not upi_id:
            flash('Please enter a UPI ID', 'danger')
            return redirect(url_for('premium_subscription'))
        
        # In a real-world scenario, we would process the payment here
        # For this mock implementation, we'll just mark the user as premium
        current_user.is_premium = True
        db.session.commit()
        
        flash('Payment successful! You are now a premium employer!', 'success')
        return redirect(url_for('dashboard'))
    
    # Render the premium subscription page
    subscription_fee = 499  # Monthly subscription fee in Rupees
    return render_template('premium_subscription.html', subscription_fee=subscription_fee)

@app.route('/applications/<int:application_id>/mark-completed', methods=['POST'])
@login_required
def mark_job_completed(application_id):
    # Get the application
    application = Application.query.get_or_404(application_id)
    
    # Verify permissions - must be the worker who applied
    if current_user.user_type != 'worker' or application.applicant_id != current_user.id:
        flash('You do not have permission to mark this job as completed', 'danger')
        return redirect(url_for('dashboard'))
    
    # Verify the job is accepted and the work date is today or in the past
    if application.status != 'accepted':
        flash('Only accepted jobs can be marked as completed', 'warning')
        return redirect(url_for('dashboard'))
    
    if application.job.work_date > datetime.now().date():
        flash('You cannot mark a future job as completed', 'warning')
        return redirect(url_for('dashboard'))
    
    # Update the job status to completed
    application.job.status = 'completed'
    db.session.commit()
    
    # Redirect to the rating page
    return redirect(url_for('rate_worker', application_id=application_id))

@app.route('/applications/<int:application_id>/rate', methods=['GET', 'POST'])
@login_required
def rate_worker(application_id):
    # Get the application
    application = Application.query.get_or_404(application_id)
    
    # Verify permissions - must be the employer who posted the job
    if current_user.user_type != 'employer' or application.job.employer_id != current_user.id:
        flash('You do not have permission to rate this worker', 'danger')
        return redirect(url_for('dashboard'))
    
    # Verify the job is completed
    if application.job.status != 'completed':
        flash('You can only rate workers for completed jobs', 'warning')
        return redirect(url_for('dashboard'))
    
    # Check if a review already exists
    existing_review = Review.query.filter_by(
        job_id=application.job_id,
        reviewer_id=current_user.id,
        reviewee_id=application.applicant_id
    ).first()
    
    if existing_review:
        flash('You have already rated this worker', 'warning')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        rating = int(request.form.get('rating', 0))
        comment = request.form.get('comment', '')
        
        if not 1 <= rating <= 5:
            flash('Rating must be between 1 and 5', 'danger')
            return redirect(url_for('rate_worker', application_id=application_id))
        
        # Create new review
        review = Review(
            rating=rating,
            comment=comment,
            reviewer_id=current_user.id,
            reviewee_id=application.applicant_id,
            job_id=application.job_id
        )
        
        # Update worker's average rating
        worker = application.applicant
        current_total = worker.avg_rating * worker.num_ratings
        worker.num_ratings += 1
        worker.avg_rating = (current_total + rating) / worker.num_ratings
        
        db.session.add(review)
        db.session.commit()
        
        flash('Thank you for rating the worker!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('rate_worker.html', application=application)

@app.route('/submit_rating', methods=['POST'])
@login_required
def submit_rating():
    if current_user.user_type != 'employer':
        flash('Only employers can submit ratings.', 'error')
        return redirect(url_for('dashboard'))
    
    application_id = request.form.get('application_id')
    rating_value = request.form.get('rating')
    comments = request.form.get('comments')
    
    if not application_id or not rating_value:
        flash('Rating and application ID are required.', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        rating_value = int(rating_value)
        if not 1 <= rating_value <= 5:
            raise ValueError('Rating must be between 1 and 5')
        
        application = Application.query.get_or_404(application_id)
        
        # Verify the employer owns the job
        if application.job.employer_id != current_user.id:
            flash('You can only rate workers for your own jobs.', 'error')
            return redirect(url_for('dashboard'))
        
        # Verify the job is completed
        if application.status != 'accepted' or application.job.status != 'completed':
            flash('You can only rate workers for completed jobs.', 'error')
            return redirect(url_for('dashboard'))
        
        # Check if rating already exists
        if Rating.query.filter_by(application_id=application_id).first():
            flash('You have already rated this worker for this job.', 'error')
            return redirect(url_for('dashboard'))
        
        # Create and save the rating
        rating = Rating(
            application_id=application_id,
            rating=rating_value,
            comments=comments
        )
        db.session.add(rating)
        
        # Update worker's average rating and number of ratings
        worker = application.applicant
        worker.avg_rating = Rating.calculate_worker_rating(worker.id)
        worker.num_ratings = Rating.query.join(Application).filter(Application.applicant_id == worker.id).count()
        
        db.session.commit()
        flash('Rating submitted successfully!', 'success')
        
    except ValueError as e:
        flash(str(e), 'error')
    except Exception as e:
        flash('An error occurred while submitting the rating.', 'error')
        print(f"Error submitting rating: {str(e)}")
        
    return redirect(url_for('dashboard'))

# Initialize admin blueprint with db and models after all models are defined
models = {
    'User': User,
    'ChatMessage': ChatMessage,
    'ChatRoom': ChatRoom,
    'Rating': Rating,
    'Application': Application,
    'Job': Job
}

# Initialize admin blueprint with db and models
init_admin_bp(db, models)

# Register blueprints after initialization
app.register_blueprint(admin_bp)

if __name__ == '__main__':
    # Create database tables if they don't exist
    with app.app_context():
        # Check if is_premium column needs to be added to the User table
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('user')]
        
        if 'is_premium' not in columns:
            print("Adding is_premium column to User table...")
            # Use raw SQL to add the column with a default value
            with db.engine.begin() as connection:
                connection.execute(text('ALTER TABLE user ADD COLUMN is_premium BOOLEAN DEFAULT 0'))
            print("is_premium column added successfully with default value of 0 (false)")
        
        # Create all tables without dropping existing ones
        db.create_all()
        print("Database tables initialized successfully!")
    
    socketio.run(app, debug=True)