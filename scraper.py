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
    cur.execute('SELECT id FROM shows')
    existing_shows = set(row[0] for row in cur.fetchall())
    cur.close()
    conn.close()
    return existing_shows

def insert_new_shows(new_shows):
    conn = get_db_connection()
    cur = conn.cursor()
    for show in new_shows:
        cur.execute('INSERT INTO shows (id, name) VALUES (%s, %s)', (show[0], show[1]))
    conn.commit()
    cur.close()
    conn.close()

if event_info_div:
	show_links = event_info_div.find_all('a', href=lambda href: href and href.startswith('./tickets/view/'))
	
	new_shows = []
	existing_shows = get_existing_shows()
	
	conn = get_db_connection()
	cur = conn.cursor()
	
	for link in show_links:
		show_name = link.text.strip()
		show_id = link['href'].split('=')[-1]
		
		if show_name and show_id not in existing_shows:
			new_shows.append((show_id, show_name))
			cur.execute("INSERT INTO shows (id, name) VALUES (%s, %s)", (show_id, show_name))
	
	conn.commit()
	cur.close()
	conn.close()

	# Prepare the email content
	if new_shows:
		email_content = f"Found {len(new_shows)} new shows:\n\n"
		for show_id, show_name in new_shows:
			email_content += f"New Show: {show_name} (ID: {show_id})\n"
	else:
		email_content = "No new shows found."

	# Email configuration
	sender_email = SENDER_EMAIL
	sender_password = SENDER_PASSWORD

	# Create the email message
	message = MIMEMultipart()
	message["From"] = sender_email
	message["Subject"] = "HouseSeats Show List Update"
	message["To"] = ", ".join(RECEIVER_EMAILS)  # Set the "To" field to all recipients

	# Attach the email content
	message.attach(MIMEText(email_content, "plain"))

	# Send the email to multiple recipients
	try:
		with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
			server.login(sender_email, sender_password)
			server.send_message(message)
		print("Emails sent successfully!")
	except Exception as e:
		print(f"Failed to send emails. Error: {e}")
else:
	print("Could not find the event-info div. The page structure might have changed.")

# Don't forget to close the browser when you're done
driver.quit()

print("Scraping complete!")
