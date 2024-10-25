import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import psycopg2
from psycopg2 import sql
import logging

# Use environment variables
HOUSESEATS_EMAIL = os.environ.get('HOUSESEATS_EMAIL')
HOUSESEATS_PASSWORD = os.environ.get('HOUSESEATS_PASSWORD')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
RECEIVER_EMAILS = os.environ.get('RECEIVER_EMAILS', '').split(',')
DATABASE_URL = os.environ.get('DATABASE_URL')

# Set up Chrome options for Heroku
chrome_options = Options()
chrome_options.add_argument('--headless')  # Run Chrome in headless mode
chrome_options.add_argument('--no-sandbox')  # Bypass OS security model, useful for PythonAnywhere
chrome_options.add_argument('--disable-dev-shm-usage')  # Overcome limited resource problems
chrome_options.binary_location = os.environ.get('GOOGLE_CHROME_BIN')

# Initialize the headless webdriver
service = Service(os.environ.get('CHROMEDRIVER_PATH'))
driver = webdriver.Chrome(service=service, options=chrome_options)

# Navigate to the login page
driver.get("https://lv.houseseats.com/login")

# Wait for the email input field to be visible
email_field = WebDriverWait(driver, 10).until(
	EC.presence_of_element_located((By.ID, "emailAddress"))
)

# Enter your login credentials
email_field.send_keys(HOUSESEATS_EMAIL)
password_field = driver.find_element(By.ID, "password")
password_field.send_keys(HOUSESEATS_PASSWORD)

# Submit the form
submit_button = driver.find_element(By.XPATH, "//button[contains(@class, 'btn-orange')]")
submit_button.click()

# Wait for the page to load
time.sleep(5)

# Get the page source and parse it with BeautifulSoup
soup = BeautifulSoup(driver.page_source, 'html.parser')

# Find the div with id "event-info"
event_info_div = soup.find('div', id='event-info')

# Set logging level to WARNING to reduce output
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def create_shows_table():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS shows (
            id TEXT PRIMARY KEY,
            name TEXT
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

def get_existing_shows():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, name FROM shows')
    existing_shows = {row[0]: row[1] for row in cur.fetchall()}
    cur.close()
    conn.close()
    return existing_shows

def insert_shows(shows):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('TRUNCATE TABLE shows')  # Clear the existing table
    for show_id, show_name in shows:
        cur.execute("""
            INSERT INTO shows (id, name) 
            VALUES (%s, %s)
        """, (show_id, show_name))
    conn.commit()
    cur.close()
    conn.close()

def get_all_shows():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, name FROM shows ORDER BY name')
    all_shows = [(row[0], row[1]) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return all_shows

def initialize_database():
    create_shows_table()

# Initialize the database
initialize_database()

def send_email(email_content):
    sender_email = SENDER_EMAIL
    sender_password = SENDER_PASSWORD
    receiver_emails = RECEIVER_EMAILS

    message = MIMEMultipart()
    message["From"] = sender_email
    message["Subject"] = "HouseSeats Complete Show List"
    message["To"] = ", ".join(receiver_emails)

    message.attach(MIMEText(email_content, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(message)
        logger.info("Email with complete show list sent successfully!")
    except Exception as e:
        logger.error(f"Failed to send email. Error: {e}")

if event_info_div:
	show_links = event_info_div.find_all('a', href=lambda href: href and href.startswith('./tickets/view/'))
	
	scraped_shows = set()
	existing_shows = get_existing_shows()
	
	logger.debug(f"Found {len(show_links)} show links")
	
	for link in show_links:
		show_name = link.text.strip()
		show_id = link['href'].split('=')[-1]
		
		# Skip "See All Dates" links and empty names
		if show_name == "See All Dates" or not show_name:
			continue
		
	 scraped_shows.add((show_id, show_name))
	
	logger.debug(f"Scraped {len(scraped_shows)} shows")
	
	# Find new shows
	new_shows = scraped_shows - set(existing_shows.items())
	
	# Insert all scraped shows (this will clear the table and insert the new data)
	insert_shows(scraped_shows)

	# Prepare the email content
	email_content = ""
	
	if new_shows:
		email_content += "New shows found:\n\n"
		for show_id, show_name in new_shows:
			email_content += f"{show_name} (ID: {show_id})\n"
		email_content += "\n\n"
	
	email_content += "Current list of all shows:\n\n"
	for show_id, show_name in sorted(scraped_shows, key=lambda x: x[1]):
		email_content += f"{show_name} (ID: {show_id})\n"

	# Send the email
	send_email(email_content)
else:
	logger.warning("Could not find the event-info div. The page structure might have changed.")

# Don't forget to close the browser when you're done
driver.quit()

print("Scraping complete!")
