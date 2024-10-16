import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import HOUSESEATS_EMAIL, HOUSESEATS_PASSWORD, SENDER_EMAIL, SENDER_PASSWORD, RECEIVER_EMAIL
import sqlite3

# Use environment variables
HOUSESEATS_EMAIL = os.environ.get('HOUSESEATS_EMAIL')
HOUSESEATS_PASSWORD = os.environ.get('HOUSESEATS_PASSWORD')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
RECEIVER_EMAIL = os.environ.get('RECEIVER_EMAIL')

# Set up Chrome options for Heroku
chrome_options = webdriver.ChromeOptions()
chrome_options.add_argument('--headless')  # Run Chrome in headless mode
chrome_options.add_argument('--no-sandbox')  # Bypass OS security model, useful for PythonAnywhere
chrome_options.add_argument('--disable-dev-shm-usage')  # Overcome limited resource problems
chrome_options.binary_location = os.environ.get('GOOGLE_CHROME_BIN')

# Initialize the headless webdriver (you'll need to have chromedriver installed and in your PATH)
driver = webdriver.Chrome(options=chrome_options, executable_path=os.environ.get('CHROMEDRIVER_PATH'))

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

# Set up database connection
conn = sqlite3.connect('shows.db')
cursor = conn.cursor()

# Create table if it doesn't exist
cursor.execute('''
    CREATE TABLE IF NOT EXISTS shows (
        id TEXT PRIMARY KEY,
        name TEXT
    )
''')
conn.commit()

if event_info_div:
    show_links = event_info_div.find_all('a', href=lambda href: href and href.startswith('./tickets/view/'))
    
    new_shows = {}
    
    for link in show_links:
        show_name = link.text.strip()
        show_id = link['href'].split('=')[-1]
        
        if show_name:
            # Check if the show is already in the database
            cursor.execute("SELECT * FROM shows WHERE id = ?", (show_id,))
            if not cursor.fetchone():
                new_shows[show_id] = show_name
                # Add the new show to the database
                cursor.execute("INSERT INTO shows (id, name) VALUES (?, ?)", (show_id, show_name))
    
    conn.commit()

    if new_shows:
        # Prepare the email content for new shows
        email_content = f"Found {len(new_shows)} new shows:\n\n"
        for show_id, show_name in new_shows.items():
            email_content += f"New Show: {show_name} (ID: {show_id})\n"

        # Email configuration is now imported from config.py
        sender_email = SENDER_EMAIL
        sender_password = SENDER_PASSWORD
        receiver_email = RECEIVER_EMAIL

        # Create the email message
        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = receiver_email
        message["Subject"] = "HouseSeats Show List"

        # Attach the email content
        message.attach(MIMEText(email_content, "plain"))

        # Send the email
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(sender_email, sender_password)
                server.send_message(message)
            print("Email sent successfully!")
        except Exception as e:
            print(f"Failed to send email. Error: {e}")
    else:
        print("No new shows found.")
else:
    print("Could not find the event-info div. The page structure might have changed.")

# Close the database connection
conn.close()

# Don't forget to close the browser when you're done
driver.quit()

print("Scraping complete!")
