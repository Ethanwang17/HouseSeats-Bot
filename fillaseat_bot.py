import requests
import re
import time
import json
import os
import psycopg2
import datetime
import random

# Replace credentials import with environment variables
USERNAME = os.environ.get('FILLASEAT_USERNAME')
PASSWORD = os.environ.get('FILLASEAT_PASSWORD')
DATABASE_URL = os.environ.get('DATABASE_URL')


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

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def create_fillaseat_shows_table():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS fillaseat_current_shows (
            id TEXT PRIMARY KEY,
            name TEXT,
            url TEXT,
            image_url TEXT
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

def delete_all_fillaseat_shows():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM fillaseat_current_shows')
    conn.commit()
    cur.close()
    conn.close()

def insert_fillaseat_shows(shows):
    conn = get_db_connection()
    cur = conn.cursor()
    for show_id, show_info in shows.items():
        try:
            cur.execute('''
                INSERT INTO fillaseat_current_shows (id, name, url, image_url) 
                VALUES (%s, %s, %s, %s)
            ''', (show_id, show_info['name'], show_info['url'], show_info['image_url']))
        except Exception as e:
            logger.error(f"Error inserting FillASeat show {show_id}: {e}")
    conn.commit()
    cur.close()
    conn.close()

def create_fillaseat_all_shows_table():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS fillaseat_all_shows (
            id TEXT PRIMARY KEY,
            name TEXT,
            url TEXT,
            image_url TEXT,
            first_seen_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

def add_to_fillaseat_all_shows(shows):
    conn = get_db_connection()
    cur = conn.cursor()
    for show_id, show_info in shows.items():
        try:
            # Use INSERT ... ON CONFLICT to handle duplicates
            cur.execute('''
                INSERT INTO fillaseat_all_shows (id, name, url, image_url)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            ''', (show_id, show_info['name'], show_info['url'], show_info['image_url']))
        except Exception as e:
            logger.error(f"Error inserting show {show_id} into fillaseat_all_shows: {e}")
    conn.commit()
    cur.close()
    conn.close()

def is_within_operating_hours():
    """
    Check if current time is between 8am and 5pm
    """
    current_time = datetime.datetime.now().time()
    start_time = datetime.time(8, 0)  # 8:00 AM
    end_time = datetime.time(17, 0)   # 5:00 PM
    return start_time <= current_time <= end_time

def main():
    while True:
        try:
            if not is_within_operating_hours():
                # Calculate time until next operating window
                now = datetime.datetime.now()
                next_run = now.replace(hour=8, minute=0, second=0, microsecond=0)
                if now.time() >= datetime.time(17, 0):
                    next_run += datetime.timedelta(days=1)
                
                sleep_seconds = (next_run - now).total_seconds()
                print(f"Outside operating hours. Sleeping until {next_run.strftime('%I:%M %p')}")
                time.sleep(sleep_seconds)
                continue

            # Create both tables if they don't exist
            create_fillaseat_shows_table()
            create_fillaseat_all_shows_table()
            
            # Get sessid and login
            sessid = get_sessid(session, headers)
            login_response = login(session, headers, sessid, USERNAME, PASSWORD)
            
            if is_login_successful(login_response):
                print("Login successful!")
                
                # Fetch events and create a dictionary of shows
                events = fetch_events(session, headers)
                current_shows = {}
                
                for event in events:
                    event_id = event.get('e', 'N/A')
                    show_name = event.get('s', 'N/A')
                    show_url = f"https://www.fillaseatlasvegas.com/account/event_info.php?eid={event_id}"
                    image_url = f"https://static.fillaseat.com/images/events/{event_id}_std.jpg"
                    
                    current_shows[event_id] = {
                        'name': show_name,
                        'url': show_url,
                        'image_url': image_url
                    }
                
                # Add to all_shows before updating current shows
                add_to_fillaseat_all_shows(current_shows)
                
                # Clear existing shows and insert new ones
                delete_all_fillaseat_shows()
                insert_fillaseat_shows(current_shows)
                
                print("Database updated successfully!")
                
            else:
                print("Login failed. Please check your credentials and try again.")
            
            # Sleep for 2-3 minutes before next run
            sleep_time = random.uniform(120, 180)
            print(f"Sleeping for {sleep_time:.1f} seconds until next check")
            time.sleep(sleep_time)
            
        except Exception as e:
            print(f"An error occurred: {e}")
            # Still sleep before retry even if there was an error
            time.sleep(120)

if __name__ == "__main__":
    main()