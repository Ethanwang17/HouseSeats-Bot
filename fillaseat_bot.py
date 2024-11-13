import requests
import re
import time
import json
import os

# Load environment variables from .env file (useful for local development)
load_dotenv()  # Optional: remove this line when deploying to Heroku

# Replace credentials import with environment variables
USERNAME = os.environ.get('FILLASEAT_USERNAME')
PASSWORD = os.environ.get('FILLASEAT_PASSWORD')

# Validate environment variables
if not USERNAME or not PASSWORD:
    raise ValueError("Missing required environment variables. Please set FILLASEAT_USERNAME and FILLASEAT_PASSWORD")

# URLs
LOGIN_PAGE_URL = 'https://www.fillaseatlasvegas.com/login2.php'
LOGIN_ACTION_URL = 'https://www.fillaseatlasvegas.com/login.php'  # Action URL from the form
EVENTS_URL_TEMPLATE = 'https://www.fillaseatlasvegas.com/account/event_json.php?callback=getEventsSelect_cb&_={timestamp}'

# Create a session to persist cookies
session = requests.Session()

# Headers to mimic a real browser (optional but recommended)
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ' +
                  'AppleWebKit/537.36 (KHTML, like Gecko) ' +
                  'Chrome/115.0.0.0 Safari/537.36',
    'Referer': LOGIN_PAGE_URL
}

def get_sessid(session, headers):
    """
    Fetch the login page and extract the sessid value.
    """
    response = session.get(LOGIN_PAGE_URL, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to retrieve login page. Status code: {response.status_code}")
    
    # Use regex to extract the sessid value
    match = re.search(r'name=["\']sessid["\']\s+value=["\']([^"\']+)["\']', response.text)
    if not match:
        raise Exception("Failed to find sessid in the login form.")
    
    sessid = match.group(1)
    print(f"Retrieved sessid: {sessid}")
    return sessid

def login(session, headers, sessid, username, password):
    """
    Submit the login form with the provided credentials and sessid.
    """
    payload = {
        'sessid': sessid,
        'username': username,
        'password': password,
        'submit': 'Login'
    }
    
    response = session.post(LOGIN_ACTION_URL, data=payload, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Login request failed. Status code: {response.status_code}")
    
    return response

def is_login_successful(response):
    """
    Determine if login was successful by checking for indicators in the response.
    """
    # Example: Check if the response contains a logout link or specific user content
    if "logout.php" in response.text.lower():
        return True
    # Add more checks as needed based on the website's response after login
    return False

def fetch_events(session, headers):
    """
    Fetch and parse events from the event_json.php endpoint.
    """
    # Generate a timestamp for the cache-busting parameter
    timestamp = int(time.time() * 1000)
    events_url = EVENTS_URL_TEMPLATE.format(timestamp=timestamp)
    
    print(f"Fetching events from: {events_url}")
    
    response = session.get(events_url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to retrieve events. Status code: {response.status_code}")
    
    # The response is JSONP, e.g., getEventsSelect_cb([...])
    # Extract the JSON part using regex
    match = re.search(r'getEventsSelect_cb\((.*)\)', response.text, re.DOTALL)
    if not match:
        print("Response does not match expected JSONP format.")
        print("----- Response Start -----")
        print(response.text)
        print("----- Response End -----")
        raise Exception("Failed to parse JSONP response.")
    
    json_data = match.group(1)
    
    try:
        events = json.loads(json_data)
    except json.JSONDecodeError as e:
        raise Exception(f"JSON decoding failed: {e}")
    
    print(f"Number of events: {len(events)}")
    
    return events

def main():
    try:
        # Step 1: Get sessid from the login page
        sessid = get_sessid(session, headers)
        
        # Step 2: Submit the login form
        login_response = login(session, headers, sessid, USERNAME, PASSWORD)
        
        # Step 3: Verify if login was successful
        if is_login_successful(login_response):
            print("Login successful!")
            # Step 4: Access a protected page (optional)
            # access_protected_page(session, headers, PROTECTED_PAGE_URL)
            
            # Step 5: Fetch and print events
            events = fetch_events(session, headers)
            print("\n--- Events List ---")
            for event in events:
                event_id = event.get('e', 'N/A')
                event_name = event.get('s', 'N/A')
                show_url = f"https://www.fillaseatlasvegas.com/account/event_info.php?eid={event_id}"
                image_url = f"https://static.fillaseat.com/images/events/{event_id}_std.jpg"
                print(f"ID: {event_id}, Name: {event_name}")
                print(f"URL: {show_url}")
                print(f"Image: {image_url}\n")
        else:
            print("Login failed. Please check your credentials and try again.")
    
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()