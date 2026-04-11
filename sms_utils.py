# SMS Utility Functions for QuickHire

import logging
from datetime import datetime
import requests
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_sms(phone_number, message):
    """
    Send SMS using Fast2SMS API or simulate sending for demonstration
    """
    try:
        # Check if we're in simulation mode
        simulation_mode = os.getenv('SMS_SIMULATION_MODE', 'true').lower() == 'true'
        
        if simulation_mode:
            # Simulate SMS sending
            logger.info(f"[SIMULATION] SMS would be sent to {phone_number}")
            logger.info(f"[SIMULATION] Message: {message}")
            logger.info("[SIMULATION] SMS sent successfully (simulated)")
            return True
            
        # Real Fast2SMS API implementation
        url = "https://www.fast2sms.com/dev/bulkV2"
        api_key = os.getenv('FAST2SMS_API_KEY')
        
        if not api_key:
            logger.error("Fast2SMS API key not configured")
            return False
            
        headers = {
            'authorization': api_key,
            'Content-Type': 'application/json'
        }
        
        phone_number = ''.join(filter(str.isdigit, phone_number))
        if not phone_number.startswith('91'):
            phone_number = '91' + phone_number.lstrip('0')
            
        payload = {
            'route': 'q',
            'sender_id': 'FSTSMS',
            'message': message,
            'language': 'english',
            'flash': 0,
            'numbers': phone_number
        }
        
        logger.info(f"Attempting to send SMS with the following details:")
        logger.info(f"URL: {url}")
        logger.info(f"Phone Number: {phone_number}")
        logger.info(f"Message: {message}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Payload: {payload}")
        
        response = requests.post(url, headers=headers, json=payload)
        
        logger.info(f"Response Status Code: {response.status_code}")
        logger.info(f"Response Content: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('return'):
                logger.info(f"SMS sent successfully to {phone_number}")
                return True
            else:
                error_msg = result.get('message', 'Unknown error')
                logger.error(f"Failed to send SMS: {error_msg}")
                logger.error(f"Full response: {result}")
                return False
        else:
            logger.error(f"Error sending SMS: HTTP {response.status_code}")
            logger.error(f"Response content: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending SMS: {str(e)}")
        logger.error(f"Exception details: {e.__class__.__name__}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def send_job_notification(worker, job):
    """
    Send SMS notification to a worker about a new job posting
    """
    if not worker.sms_notifications:
        return False
        
    message = f"""
New job available in {job.location}!
Title: {job.title}
Wage: ₹{job.wage}
Contact employer: {job.employer.phone}
    """.strip()
    
    return send_sms(worker.phone, message)

def send_job_invitation(worker, job):
    """
    Send SMS notification to a worker about a job invitation
    """
    if not worker.sms_notifications:
        return False
        
    message = f"""
You've been invited to a job in {job.location}!
Title: {job.title}
Wage: ₹{job.wage}
Contact employer: {job.employer.phone}
    """.strip()
    
    return send_sms(worker.phone, message)

def send_application_status_update(worker, job, status):
    """
    Send SMS notification about application status update
    """
    if not worker.sms_notifications:
        return False
        
    status_text = "accepted" if status == "accepted" else "rejected"
    message = f"""
Your application for {job.title} has been {status_text}.
Contact employer: {job.employer.phone}
    """.strip()
    
    return send_sms(worker.phone, message)