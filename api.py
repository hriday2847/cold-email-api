from fastapi import FastAPI, HTTPException, Depends, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import openai
import os
import random
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("Missing OpenAI API key")

openai.api_key = api_key
client = openai

app = FastAPI(
    title="Pepsales AI API",
    description="API for generating and managing cold emails",
    version="1.0.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.pepsales.ai"],  # or list specific frontend domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting configuration
RATE_LIMIT_FILE = "rate_limits.json"
MAX_REQUESTS_PER_DAY = 15
MAX_REQUESTS_PER_HOUR = 5

# Default AI model
DEFAULT_AI_MODEL = "gpt-3.5-turbo"

# In-memory storage for emails (in production this would be a database)
saved_emails = []

# Request models
class EmailGenerationRequest(BaseModel):
    sender_company: str
    target_company: str
    industry: str
    person_name: str
    role: str
    email_subject: str
    tone: str = "Professional"
    length: str = "Concise"
    custom_instructions: Optional[str] = None
    session_id: Optional[str] = None

class EmailResponse(BaseModel):
    email_text: str
    subject: str

class SavedEmail(BaseModel):
    id: str
    date: str
    recipient: str
    company: str
    subject: str
    content: str

# Rate limiting functions
def load_rate_limits():
    """Load rate limit data from file"""
    if os.path.exists(RATE_LIMIT_FILE):
        try:
            with open(RATE_LIMIT_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"daily": {}, "hourly": {}}
    return {"daily": {}, "hourly": {}}

def save_rate_limits(data):
    """Save rate limit data to file"""
    with open(RATE_LIMIT_FILE, 'w') as f:
        json.dump(data, f)

def check_rate_limit(session_id: str):
    """Check if the current user is rate limited"""
    # Get current time
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    hour = now.strftime("%Y-%m-%d-%H")
    
    # Load existing rate limits
    rate_limits = load_rate_limits()
    
    # Clean up old entries (older than 1 day)
    daily_limits = {}
    for day, users in rate_limits["daily"].items():
        day_dt = datetime.strptime(day, "%Y-%m-%d")
        if (now - day_dt).days < 1:
            daily_limits[day] = users
    rate_limits["daily"] = daily_limits
    
    # Clean up old hourly entries (older than 1 hour)
    hourly_limits = {}
    for h, users in rate_limits["hourly"].items():
        hour_dt = datetime.strptime(h, "%Y-%m-%d-%H")
        if (now - hour_dt).total_seconds() < 3600:
            hourly_limits[h] = users
    rate_limits["hourly"] = hourly_limits
    
    # Initialize if needed
    if today not in rate_limits["daily"]:
        rate_limits["daily"][today] = {}
    if hour not in rate_limits["hourly"]:
        rate_limits["hourly"][hour] = {}
    
    # Get current counts
    daily_count = rate_limits["daily"][today].get(session_id, 0)
    hourly_count = rate_limits["hourly"][hour].get(session_id, 0)
    
    # Check if limits are exceeded
    if daily_count >= MAX_REQUESTS_PER_DAY:
        return False, f"Request limit exceeded. Please try again tomorrow."
    if hourly_count >= MAX_REQUESTS_PER_HOUR:
        return False, f"Request limit exceeded. Please try again later."
    
    return True, ""

def increment_rate_limit(session_id: str):
    """Increment the rate limit counters for the current user"""
    # Get current time
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    hour = now.strftime("%Y-%m-%d-%H")
    
    # Load existing rate limits
    rate_limits = load_rate_limits()
    
    # Initialize if needed
    if today not in rate_limits["daily"]:
        rate_limits["daily"][today] = {}
    if hour not in rate_limits["hourly"]:
        rate_limits["hourly"][hour] = {}
    
    # Increment counters
    rate_limits["daily"][today][session_id] = rate_limits["daily"][today].get(session_id, 0) + 1
    rate_limits["hourly"][hour][session_id] = rate_limits["hourly"][hour].get(session_id, 0) + 1
    
    # Save updated limits
    save_rate_limits(rate_limits)

@app.get("/")
async def root():
    return {"message": "Welcome to Sales Cold Email Generator"}

@app.post("/api/email/generate", response_model=EmailResponse)
async def generate_email(request: EmailGenerationRequest):
    # Validate required fields
    if not all([request.sender_company, request.target_company, 
                request.person_name, request.role, request.email_subject]):
        raise HTTPException(status_code=400, detail="All fields are required")
    
    # Generate or use provided session_id
    session_id = request.session_id or str(random.randint(10000, 99999))
    
    # Check rate limits
    can_proceed, limit_message = check_rate_limit(session_id)
    if not can_proceed:
        raise HTTPException(status_code=429, detail=limit_message)
    
    # Increment rate limit counter
    increment_rate_limit(session_id)
    
    # Construct the prompt
    prompt = f"""
You are an expert cold email copywriter and B2B personalization strategist.

Write a highly personalized cold email from {request.sender_company} to {request.person_name}, the {request.role} at {request.target_company} in the {request.industry} industry, based on the following subject line:

Subject: {request.email_subject}

The email should:
- Use a {request.tone.lower()} tone and be {request.length.lower()} in length
- Start with a hook that's personalized and relevant to {request.target_company} and their industry
- Explain how {request.sender_company}'s platform can solve pain points like lead qualification, demo personalization, or sales insights
- Show why this is useful for someone in the role of {request.role}
- Align with the theme of the subject line
- End with a friendly CTA to continue the conversation

{request.custom_instructions if request.custom_instructions else ""}

Return only the email body. Do NOT include signature or re-state the subject.
"""
    
    # Generate the email using OpenAI
    try:
        if not client:
            raise HTTPException(status_code=500, detail="OpenAI API key is missing")
        
        try:
            # Try the new OpenAI client approach first
            response = client.chat.completions.create(
                model=DEFAULT_AI_MODEL,
                messages=[
                    {"role": "system", "content": "You write persuasive and personalized B2B cold emails."},
                    {"role": "user", "content": prompt}
                ]
            )
            response_text = response.choices[0].message.content.strip()
        except AttributeError:
            # Fallback to the older API format
            response = client.ChatCompletion.create(
                model=DEFAULT_AI_MODEL,
                messages=[
                    {"role": "system", "content": "You write persuasive and personalized B2B cold emails."},
                    {"role": "user", "content": prompt}
                ]
            )
            response_text = response.choices[0].message.content.strip()
        
        # Save to history
        email_id = f"{len(saved_emails) + 1}_{random.randint(1000, 9999)}"
        saved_emails.append({
            "id": email_id,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "recipient": request.person_name,
            "company": request.target_company,
            "subject": request.email_subject,
            "content": response_text
        })
        
        return {
            "email_text": response_text,
            "subject": request.email_subject
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating email: {str(e)}")

@app.get("/api/emails/saved", response_model=List[SavedEmail])
async def get_saved_emails(limit: int = 50, offset: int = 0):
    """Get list of saved emails"""
    start = min(offset, len(saved_emails))
    end = min(offset + limit, len(saved_emails))
    return saved_emails[start:end]

@app.delete("/api/emails/{email_id}")
async def delete_email(email_id: str):
    """Delete a saved email by ID"""
    global saved_emails
    original_count = len(saved_emails)
    saved_emails = [email for email in saved_emails if email["id"] != email_id]
    
    if len(saved_emails) == original_count:
        raise HTTPException(status_code=404, detail="Email not found")
    
    return {"message": "Email deleted successfully"}

@app.get("/api/analytics")
async def get_analytics():
    """Get email generation analytics"""
    if not saved_emails:
        return {
            "total_emails": 0,
            "weekly_emails": 0,
            "avg_length": 0,
            "email_over_time": [],
            "top_companies": []
        }
    
    # Calculate basic metrics
    total_emails = len(saved_emails)
    
    # Calculate weekly emails
    today = datetime.now()
    one_week_ago = today - timedelta(days=7)
    weekly_emails = 0
    
    for email in saved_emails:
        try:
            email_date = datetime.strptime(email['date'], "%Y-%m-%d %H:%M")
            if email_date > one_week_ago:
                weekly_emails += 1
        except:
            pass
    
    # Calculate average length
    total_words = 0
    for email in saved_emails:
        total_words += len(email['content'].split())
    
    avg_length = total_words // max(1, len(saved_emails))
    
    # Calculate emails over time
    dates = []
    for email in saved_emails:
        try:
            email_date = datetime.strptime(email['date'], "%Y-%m-%d %H:%M")
            dates.append(email_date.date().strftime("%Y-%m-%d"))
        except:
            pass
    
    # Count occurrences of each date
    date_counts = {}
    for date in dates:
        date_counts[date] = date_counts.get(date, 0) + 1
    
    email_over_time = [{"date": date, "count": count} for date, count in date_counts.items()]
    
    # Calculate top companies
    companies = [email['company'] for email in saved_emails]
    company_counts = {}
    
    for company in companies:
        company_counts[company] = company_counts.get(company, 0) + 1
    
    top_companies = [{"company": company, "count": count} 
                     for company, count in sorted(company_counts.items(), 
                                                key=lambda x: x[1], 
                                                reverse=True)][:10]
    
    return {
        "total_emails": total_emails,
        "weekly_emails": weekly_emails,
        "avg_length": avg_length,
        "email_over_time": email_over_time,
        "top_companies": top_companies
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 