import os
import requests
import re
import time
import json
import logging
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# URLs
LOGIN_PAGE_URL = 'https://www.fillaseatlasvegas.com/login2.php'
LOGIN_ACTION_URL = 'https://www.fillaseatlasvegas.com/login.php'  # Action URL from the form
EVENTS_URL_TEMPLATE = 'https://www.fillaseatlasvegas.com/account/event_json.php?callback=getEventsSelect_cb&_={timestamp}'
PERF_DATE_URL_TEMPLATE = 'https://www.fillaseatlasvegas.com/includes/getPerfDateJson.php?callback=jsoncall&date={date}&_={timestamp}'

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
        logger.error(f"Failed to retrieve login page. Status code: {response.status_code}")
        raise Exception(f"Failed to retrieve login page. Status code: {response.status_code}")
    
    # Use regex to extract the sessid value
    match = re.search(r'name=["\']sessid["\']\s+value=["\']([^"\']+)["\']', response.text)
    if not match:
        logger.error("Failed to find sessid in the login form.")
        raise Exception("Failed to find sessid in the login form.")
    
    sessid = match.group(1)
    logger.info(f"Retrieved sessid: {sessid}")
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
        logger.error(f"Login request failed. Status code: {response.status_code}")
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
    
    logger.info(f"Fetching events from: {events_url}")
    
    response = session.get(events_url, headers=headers)
    if response.status_code != 200:
        logger.error(f"Failed to retrieve events. Status code: {response.status_code}")
        raise Exception(f"Failed to retrieve events. Status code: {response.status_code}")
    
    # The response is JSONP, e.g., getEventsSelect_cb([...])
    # Extract the JSON part using regex
    match = re.search(r'getEventsSelect_cb\((.*)\)', response.text, re.DOTALL)
    if not match:
        logger.error("Response does not match expected JSONP format.")
        logger.debug(f"Response content: {response.text}")
        raise Exception("Failed to parse JSONP response.")
    
    json_data = match.group(1)
    
    try:
        events = json.loads(json_data)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decoding failed: {e}")
        raise Exception(f"JSON decoding failed: {e}")
    
    logger.info(f"Number of events: {len(events)}")
    
    return events

def fetch_performances_for_date(session, headers, date_str):
    """
    Fetch performances for a specific date.
    """
    timestamp = int(time.time() * 1000)
    perf_url = PERF_DATE_URL_TEMPLATE.format(date=date_str, timestamp=timestamp)
    
    logger.info(f"Fetching performances for {date_str} from: {perf_url}")
    
    response = session.get(perf_url, headers=headers)
    if response.status_code != 200:
        logger.warning(f"Failed to retrieve performances for {date_str}. Status code: {response.status_code}")
        return None
    
    # The response is JSONP, e.g., jsoncall({...})
    match = re.search(r'jsoncall\((.*)\)', response.text, re.DOTALL)
    if not match:
        logger.warning(f"Response for {date_str} does not match expected JSONP format.")
        return None
    
    json_data = match.group(1)
    
    try:
        data = json.loads(json_data)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decoding failed for date {date_str}: {e}")
        return None
    
    return data.get('performances', [])

def main():
    try:
        # Retrieve environment variables
        USERNAME = os.environ.get('FILLASEAT_USERNAME')
        PASSWORD = os.environ.get('FILLASEAT_PASSWORD')
        
        if not USERNAME or not PASSWORD:
            logger.error("FILLASEAT_USERNAME and FILLASEAT_PASSWORD environment variables must be set.")
            raise Exception("FILLASEAT_USERNAME and FILLASEAT_PASSWORD environment variables must be set.")
        
        # Step 1: Get sessid from the login page
        sessid = get_sessid(session, headers)
        
        # Step 2: Submit the login form
        login_response = login(session, headers, sessid, USERNAME, PASSWORD)
        
        # Step 3: Verify if login was successful
        if is_login_successful(login_response):
            logger.info("Login successful!")
            # Step 4: Fetch and parse events
            events = fetch_events(session, headers)
            logger.info("\n--- Events List ---")
            # Create a dictionary to map event IDs to event names and initialize imgurl and pid
            events_dict = {}
            for event in events:
                event_id = event.get('e', 'N/A')
                event_name = event.get('s', 'N/A')
                events_dict[event_id] = {
                    'name': event_name,
                    'imgurl': None,
                    'pid': None
                }
                logger.info(f"ID: {event_id}, Name: {event_name}")
            
            # Step 5: Iterate over dates to fetch performances
            start_date = datetime.today()
            max_days = 90  # Maximum number of days to iterate to prevent infinite loops
            consecutive_no_perf = 0  # Counter for consecutive days with no performances
            max_consecutive_no_perf = 10  # Stop after 10 consecutive days with no performances
            
            current_date = start_date
            for day in range(max_days):
                date_str = current_date.strftime('%Y-%m-%d')
                performances = fetch_performances_for_date(session, headers, date_str)
                
                if performances:
                    logger.info(f"Found {len(performances)} performances on {date_str}")
                    for perf in performances:
                        eid = perf.get('eid')
                        imgurl = perf.get('imgurl')
                        pid = perf.get('pid')
                        
                        if eid in events_dict:
                            events_dict[eid]['imgurl'] = imgurl
                            events_dict[eid]['pid'] = pid
                            logger.info(f"Updated Event ID {eid}: imgurl={imgurl}, pid={pid}")
                        else:
                            logger.warning(f"Performance with eid {eid} not found in events list.")
                    consecutive_no_perf = 0  # Reset counter
                else:
                    logger.info(f"No performances found on {date_str}")
                    consecutive_no_perf += 1
                    if consecutive_no_perf >= max_consecutive_no_perf:
                        logger.info(f"Reached {max_consecutive_no_perf} consecutive days with no performances. Stopping.")
                        break  # Exit the loop
                
                # Move to the next day
                current_date += timedelta(days=1)
                time.sleep(1)  # Be polite and avoid hitting the server too quickly
            
            # Step 6: Print or process the enriched events list
            logger.info("\n--- Enriched Events List ---")
            for eid, details in events_dict.items():
                logger.info(f"ID: {eid}, Name: {details['name']}, imgurl: {details['imgurl']}, pid: {details['pid']}")
            
            # Optionally, you can save the data to a file or database here
            
        else:
            logger.error("Login failed. Please check your credentials and try again.")
    
    except Exception as e:
        logger.error(f"An error occurred: {e}")

if __name__ == "__main__":
    main()