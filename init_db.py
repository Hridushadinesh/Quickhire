from app import app, db, User
from datetime import datetime

def init_db():
    with app.app_context():
        # Create all tables
        db.create_all()
        
        # Create sample users
        workers = [
            {
                'name': 'Rahul Sharma',
                'email': 'rahul@example.com',
                'phone': '9876543210',
                'user_type': 'worker',
                'skills': 'Plumbing,Repairs',
                'hourly_rate': 350,
                'location': 'Mumbai, Maharashtra',
                'latitude': 19.0760,
                'longitude': 72.8777,
                'status': 'available'
            },
            {
                'name': 'Priya Patel',
                'email': 'priya@example.com',
                'phone': '9876543211',
                'user_type': 'worker',
                'skills': 'Carpentry,Furniture Assembly',
                'hourly_rate': 400,
                'location': 'Delhi, NCR',
                'latitude': 28.7041,
                'longitude': 77.1025,
                'status': 'available'
            }
        ]

        employers = [
            {
                'name': 'Amit Kumar',
                'email': 'amit@example.com',
                'phone': '9876543212',
                'user_type': 'employer',
                'location': 'Bangalore, Karnataka'
            }
        ]

        # Add workers
        for worker_data in workers:
            worker = User(**worker_data)
            worker.set_password('password123')
            db.session.add(worker)

        # Add employers
        for employer_data in employers:
            employer = User(**employer_data)
            employer.set_password('password123')
            db.session.add(employer)

        # Commit changes
        db.session.commit()
        print("Database initialized with sample data!")

if __name__ == '__main__':
    init_db() 