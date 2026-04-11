from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_required, current_user, logout_user
from werkzeug.security import check_password_hash
from sqlalchemy import or_

# Create blueprint without importing from app
admin_bp = Blueprint('admin', __name__)

# Admin credentials
ADMIN_EMAIL = "admin@quickhire.com"
ADMIN_PASSWORD = "admin123"  # In production, use a secure password and store as hash

# We'll get db from app when the blueprint is registered
db = None

# Models will be imported when needed to avoid circular imports
User = None
ChatMessage = None
ChatRoom = None
Rating = None
Application = None
Job = None

# This function will be called from app.py to initialize db and models
def init_admin_bp(app_db, models):
    global db, User, ChatMessage, ChatRoom, Rating, Application, Job
    db = app_db
    User = models['User']
    ChatMessage = models['ChatMessage']
    ChatRoom = models['ChatRoom']
    Rating = models['Rating']
    Application = models['Application']
    Job = models['Job']

@admin_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    # If already logged in as admin, redirect to admin dashboard
    if session.get('is_admin'):
        return redirect(url_for('admin.admin_dashboard'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Check admin credentials
        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session['is_admin'] = True
            flash('Admin login successful!', 'success')
            return redirect(url_for('admin.admin_dashboard'))
        else:
            flash('Invalid admin credentials!', 'danger')
    
    return render_template('admin_login.html')

@admin_bp.route('/admin/dashboard')
def admin_dashboard():
    # Check if user is logged in as admin
    if not session.get('is_admin'):
        flash('Please login as admin first!', 'warning')
        return redirect(url_for('admin.admin_login'))
    
    # Use the global User model that was initialized
    # Get all users
    users = User.query.all()
    
    return render_template('admin_dashboard.html', users=users)

@admin_bp.route('/admin/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    # Check if user is logged in as admin
    if not session.get('is_admin'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Please login as admin first!'}), 403
        flash('Please login as admin first!', 'warning')
        return redirect(url_for('admin.admin_login'))
    
    # Use the global models that were initialized
    user = User.query.get_or_404(user_id)
    
    try:
        # Delete related data
        # 1. Delete chat messages and chat rooms
        ChatMessage.query.filter(or_(ChatMessage.sender_id == user_id, 
                                    ChatMessage.receiver_id == user_id)).delete()
        ChatRoom.query.filter(or_(ChatRoom.user1_id == user_id, 
                                 ChatRoom.user2_id == user_id)).delete()
        
        # 2. Delete ratings associated with user's applications
        for application in user.applications:
            Rating.query.filter_by(application_id=application.id).delete()
        
        # 3. Delete applications
        Application.query.filter_by(applicant_id=user_id).delete()
        
        # 4. If employer, delete their jobs and associated applications
        if user.user_type == 'employer':
            for job in user.jobs_posted:
                # Delete applications for this job
                Application.query.filter_by(job_id=job.id).delete()
            
            # Delete jobs
            Job.query.filter_by(employer_id=user_id).delete()
        
        # 5. Finally delete the user
        db.session.delete(user)
        db.session.commit()
        
        # Check if request is AJAX
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': f'User {user.name} has been deleted successfully!'})
        
        flash(f'User {user.name} has been deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        
        # Check if request is AJAX
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': f'Error deleting user: {str(e)}'}), 500
        
        flash(f'Error deleting user: {str(e)}', 'danger')
    
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    flash('Admin logged out successfully!', 'success')
    return redirect(url_for('admin.admin_login'))