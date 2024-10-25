import os
import time
import logging
import smtplib
import psycopg2
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# Use environment variables
HOUSESEATS_EMAIL = os.environ.get('HOUSESEATS_EMAIL')
HOUSESEATS_PASSWORD = os.environ.get('HOUSESEATS_PASSWORD')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
RECEIVER_EMAILS = os.environ.get('RECEIVER_EMAILS', '').split(',')
DATABASE_URL = os.environ.get('DATABASE_URL')

def main():
    # Set up Chrome options for Heroku
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # Run Chrome in headless mode
    chrome_options.add_argument('--no-sandbox')  # Bypass OS security model
    chrome_options.add_argument('--disable-dev-shm-usage')  # Overcome limited resource problems
    chrome_options.binary_location = os.environ.get('GOOGLE_CHROME_BIN')

    # Initialize the headless webdriver
    service = Service(os.environ.get('CHROMEDRIVER_PATH'))
    driver = webdriver.Chrome(service=service, options=chrome_options)

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

    def delete_all_shows():
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('DELETE FROM shows')
        conn.commit()
        cur.close()
        conn.close()

    def insert_all_shows(shows):
        conn = get_db_connection()
        cur = conn.cursor()
        for show_id, show_name in shows:
            try:
                cur.execute('INSERT INTO shows (id, name) VALUES (%s, %s)', (show_id, show_name))
            except Exception as e:
                logger.error(f"Error inserting show {show_id}: {e}")
        conn.commit()
        cur.close()
        conn.close()

    def initialize_database():
        create_shows_table()

    def send_email(email_content):
        sender_email = SENDER_EMAIL
        sender_password = SENDER_PASSWORD
        receiver_emails = RECEIVER_EMAILS

        message = MIMEMultipart()
        message["From"] = sender_email
        message["Subject"] = "HouseSeats Show Update"
        message["To"] = ", ".join(receiver_emails)

        message.attach(MIMEText(email_content, "plain"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(sender_email, sender_password)
                server.send_message(message)
            logger.info("Email with show update sent successfully!")
        except Exception as e:
            logger.error(f"Failed to send email. Error: {e}")

    # Initialize the database
    initialize_database()

    try:
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

        if event_info_div:
            # Find all panels representing shows
            panels = event_info_div.find_all('div', class_='panel panel-default')

            # Initialize an empty dictionary to store scraped shows
            scraped_shows_dict = {}

            logger.debug(f"Found {len(panels)} show panels")

            for panel in panels:
                heading = panel.find('div', class_='panel-heading')
                if not heading:
                    continue  # Skip if no heading found

                link = heading.find('a', href=lambda href: href and href.startswith('./tickets/view/'))
                if not link:
                    continue  # Skip if no valid link found

                show_name = link.text.strip()
                show_id = link['href'].split('=')[-1]

                # Skip empty show names
                if not show_name or show_name == "[...]":
                    continue

                # Add to dictionary without overwriting existing entries with empty names
                if show_id not in scraped_shows_dict or scraped_shows_dict[show_id] == "[...]":
                    scraped_shows_dict[show_id] = show_name

            # Convert dictionary to list of tuples
            scraped_shows = list(scraped_shows_dict.items())

            # Get existing shows from the database
            existing_shows = get_existing_shows()  # returns dict {id: name}

            # Find new shows
            existing_show_ids = set(existing_shows.keys())
            scraped_show_ids = set(scraped_shows_dict.keys())

            new_show_ids = scraped_show_ids - existing_show_ids

            new_shows = [(show_id, scraped_shows_dict[show_id]) for show_id in new_show_ids]

            logger.debug(f"Identified {len(new_shows)} new shows")

            # Now erase the database and rewrite it with all the shows just found
            delete_all_shows()
            insert_all_shows(scraped_shows)

            # Prepare the email content
            email_content = ""

            if new_shows:
                email_content += "New shows found:\n\n"
                for show_id, show_name in new_shows:
                    email_content += f"{show_name} (ID: {show_id})\n"
                email_content += "\n"
            else:
                email_content += "No new shows were found.\n\n"

            email_content += "Current list of all shows:\n\n"
            for show_id, show_name in scraped_shows:
                email_content += f"{show_name} (ID: {show_id})\n"

            # Send the email
            send_email(email_content)
        else:
            logger.warning("Could not find the event-info div. The page structure might have changed.")

    except Exception as e:
        logger.error(f"An error occurred: {e}")

    finally:
        # Don't forget to close the browser when you're done
        driver.quit()

    print("Scraping complete!")

if __name__ == "__main__":
    while True:
        main()
        time.sleep(120)  # Sleep for 120 seconds (2 minutes)