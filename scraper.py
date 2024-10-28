import os
import time
import logging
import asyncio
import psycopg2
import discord
from discord.ext import commands, tasks
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
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
DISCORD_CHANNEL_ID = int(os.environ.get('DISCORD_CHANNEL_ID'))
DATABASE_URL = os.environ.get('DATABASE_URL')

# Set logging level to WARNING to reduce output
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Initialize Discord bot with necessary intents
intents = discord.Intents.default()
intents.guilds = True  # Enable guild-related events
bot = commands.Bot(command_prefix='!', intents=intents)

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

async def send_discord_message(message_text):
    try:
        channel = await bot.fetch_channel(DISCORD_CHANNEL_ID)
        if channel is None:
            logger.error(f"Channel with ID {DISCORD_CHANNEL_ID} not found.")
            return
        await channel.send(message_text)
        logger.info("Discord message sent successfully!")
    except Exception as e:
        logger.error(f"Failed to send Discord message. Error: {e}")

def scrape_and_process():
    # Initialize the database
    initialize_database()

    # Set up Chrome options for Heroku
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # Run Chrome in headless mode
    chrome_options.add_argument('--no-sandbox')  # Bypass OS security model
    chrome_options.add_argument('--disable-dev-shm-usage')  # Overcome limited resource problems
    chrome_options.binary_location = os.environ.get('GOOGLE_CHROME_BIN', '/app/.apt/usr/bin/google-chrome')

    # Initialize the headless webdriver
    service = Service(executable_path=os.environ.get('CHROMEDRIVER_PATH', '/app/.chromedriver/bin/chromedriver'))
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        # Your scraping code here
        # ...

        # Prepare the message content
        if new_shows:
            message_text = "New shows found:\n"
            for show_id, show_name in new_shows:
                message_text += f"- {show_name}\n"
        else:
            message_text = "No new shows were found."

        # Schedule the message to be sent
        asyncio.run_coroutine_threadsafe(send_discord_message(message_text), bot.loop)

    except Exception as e:
        error_message = f"An error occurred: {e}"
        logger.error(error_message)
        asyncio.run_coroutine_threadsafe(send_discord_message(error_message), bot.loop)

    finally:
        driver.quit()

@tasks.loop(minutes=2)
async def scraping_task():
    await asyncio.to_thread(scrape_and_process)

@scraping_task.before_loop
async def before_scraping_task():
    await bot.wait_until_ready()

# Start the task when the bot is ready
scraping_task.start()

# Run the bot
bot.run(DISCORD_BOT_TOKEN)