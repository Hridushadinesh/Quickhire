# 🚀 QuickHire – Job Portal for Daily Wage Workers

A web-based job portal that connects daily wage workers with employers, making job discovery, hiring, and communication easier.

## 📌 About the Project

QuickHire is a web application developed as part of a B.Tech group academic project. It provides a platform where daily wage workers can find suitable job opportunities and employers can connect with skilled workers.

The application offers separate interfaces for workers, employers, and administrators, along with job management, worker search, and real-time communication features.

## ✨ Features

- **User Authentication:** Separate registration and login for workers and employers.
- **Job Posting:** Employers can publish job opportunities.
- **Job Applications:** Workers can browse available jobs and apply.
- **Job Search:** Search and filter job listings.
- **Worker Search:** Employers can search for workers based on relevant details.
- **Location Map:** View worker locations through an interactive map.
- **Real-Time Chat:** Communication between workers and employers using Socket.IO.
- **Notifications:** Notification functionality for application-related updates.
- **Admin Dashboard:** Manage users and monitor platform activity.

## 🛠️ Technologies Used

| Category | Technologies |
|---|---|
| Frontend | HTML, CSS, JavaScript, Bootstrap |
| Backend | Python, Flask |
| Database | SQLite |
| Real-time Communication | Flask-SocketIO, Socket.IO |
| Map Integration | Leaflet, OpenStreetMap |

## 👥 User Roles

### 👷 Worker
- Register and log in.
- Create and manage a worker profile.
- Search for available jobs.
- Apply for job opportunities.
- Communicate with employers.
- View notifications.

### 🧑‍💼 Employer
- Register and log in.
- Post job opportunities.
- Search for workers.
- View job applicants.
- Communicate with workers.
- Manage job applications.

### 🛡️ Administrator
- Manage platform users.
- Monitor platform activity.

## ⚙️ Installation and Setup

Follow these steps to run QuickHire locally.

### 1. Clone the Repository

```bash
git clone https://github.com/Hridushadinesh/QuickHire.git
cd QuickHire
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
```

### 3. Activate the Virtual Environment

**Windows:**

```bash
venv\Scripts\activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Run the Application

```bash
python app.py
```

### 6. Open in Your Browser

Visit:

```text
http://127.0.0.1:5000/
```

## 📁 Project Structure

```text
QuickHire/
│
├── app.py
├── requirements.txt
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   └── notifications.html
│
├── static/
│   ├── css/
│   ├── js/
│   └── images/
│
├── instance/
│
└── README.md
```

*Note: The project structure above is illustrative. Your actual repository may contain additional files and folders.*

## 🎓 Project Information

- **Project Type:** B.Tech Group Academic Project
- **Project Name:** QuickHire – Job Portal for Daily Wage Workers
- **Domain:** Web Development

## 👩‍💻 Author

**Hridusha Dinesh Kumar U V**

This project was developed as part of a group academic project.

## 📄 License

This project was developed for academic purposes.
