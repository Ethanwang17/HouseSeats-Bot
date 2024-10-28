import os
import time
import logging
import asyncio
import psycopg2
import discord
from discord import app_commands
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
GUILD_ID = int(os.environ.get('GUILD_ID'))

# Set logging level to WARNING to reduce output
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Initialize Discord bot with necessary intents
intents = discord.Intents.default()
intents.guilds = True  # Enable guild-related events
intents.messages = True  # Enable message-related events
bot = commands.Bot(command_prefix='!', intents=intents)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def create_shows_table():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS shows (
            id TEXT PRIMARY KEY,
            name TEXT,
            url TEXT,
            image_url TEXT
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

def create_user_blacklist_table():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_blacklists (
            user_id BIGINT,
            show_id TEXT,
            PRIMARY KEY (user_id, show_id)
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

def get_existing_shows():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, name, url, image_url FROM shows')
    existing_shows = {row[0]: {'name': row[1], 'url': row[2], 'image_url': row[3]} for row in cur.fetchall()}
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
    for show_id, show_info in shows.items():
        try:
            cur.execute('INSERT INTO shows (id, name, url, image_url) VALUES (%s, %s, %s, %s)',
                        (show_id, show_info['name'], show_info['url'], show_info['image_url']))
        except Exception as e:
            logger.error(f"Error inserting show {show_id}: {e}")
    conn.commit()
    cur.close()
    conn.close()

def initialize_database():
    create_shows_table()
    create_user_blacklist_table()

def add_show_to_user_blacklist(user_id, show_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO user_blacklists (user_id, show_id) VALUES (%s, %s)', (user_id, show_id))
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        pass  # Show is already in blacklist
    except Exception as e:
        logger.error(f"Error adding show to blacklist: {e}")
    finally:
        cur.close()
        conn.close()

def remove_show_from_user_blacklist(user_id, show_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('DELETE FROM user_blacklists WHERE user_id = %s AND show_id = %s', (user_id, show_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Error removing show from blacklist: {e}")
    finally:
        cur.close()
        conn.close()

def get_user_blacklist(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT show_id FROM user_blacklists WHERE user_id = %s', (user_id,))
    blacklisted_shows = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return blacklisted_shows

@bot.tree.command(name="blacklist", description="Add or remove a show from your blacklist.")
@app_commands.describe(action="Choose 'add' or 'remove' to manage your blacklist.", show_id="The ID of the show.")
async def blacklist_command(interaction: discord.Interaction, action: str, show_id: str):
    user_id = interaction.user.id
    action = action.lower()

    if action not in ['add', 'remove']:
        await interaction.response.send_message("Invalid action. Please choose 'add' or 'remove'.", ephemeral=True)
        return

    # Validate show_id exists
    existing_shows = get_existing_shows()
    if show_id not in existing_shows:
        await interaction.response.send_message(f"Show ID {show_id} does not exist.", ephemeral=True)
        return

    if action == 'add':
        add_show_to_user_blacklist(user_id, show_id)
        await interaction.response.send_message(f"Show ID {show_id} has been added to your blacklist.", ephemeral=True)
    elif action == 'remove':
        remove_show_from_user_blacklist(user_id, show_id)
        await interaction.response.send_message(f"Show ID {show_id} has been removed from your blacklist.", ephemeral=True)

async def send_discord_message(user, message_text=None, embed=None):
    try:
        if embed:
            await user.send(content=message_text, embed=embed)
        else:
            await user.send(content=message_text)
        logger.info(f"Discord message sent successfully to user {user.id}!")
    except discord.Forbidden:
        logger.warning(f"Cannot send messages to user {user.id}. They might have DMs disabled.")
    except Exception as e:
        logger.error(f"Failed to send Discord message to user {user.id}. Error: {e}")

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

                # Construct the full show URL
                show_url = 'https://lv.houseseats.com/member' + link['href'][1:]  # Remove the leading '.'

                # Get the image URL
                image_tag = panel.find('img', src=lambda src: src and src.startswith('/resources/media/'))
                if image_tag:
                    image_url = 'https://lv.houseseats.com' + image_tag['src']
                else:
                    image_url = None  # Handle cases where image is not available

                # Skip empty show names
                if not show_name or show_name == "[...]":
                    continue

                # Add to dictionary
                scraped_shows_dict[show_id] = {
                    'name': show_name,
                    'url': show_url,
                    'image_url': image_url
                }

            # Get existing shows from the database
            existing_shows = get_existing_shows()  # returns dict {id: {'name', 'url', 'image_url'}}

            # Find new shows
            existing_show_ids = set(existing_shows.keys())
            scraped_show_ids = set(scraped_shows_dict.keys())

            new_show_ids = scraped_show_ids - existing_show_ids

            new_shows = {show_id: scraped_shows_dict[show_id] for show_id in new_show_ids}

            logger.debug(f"Identified {len(new_shows)} new shows")

            # Now erase the database and rewrite it with all the shows just found
            delete_all_shows()
            insert_all_shows(scraped_shows_dict)

            # Prepare and send Discord messages only if there are new shows
            if new_shows:
                # For each user, send personalized notifications
                guild = bot.get_guild(GUILD_ID)
                if guild is None:
                    logger.error(f"Guild with ID {GUILD_ID} not found.")
                    return

                members = guild.members
                for member in members:
                    # Skip bots
                    if member.bot:
                        continue

                    user_blacklist = get_user_blacklist(member.id)
                    # Filter new_shows for this user
                    user_new_shows = {show_id: show_info for show_id, show_info in new_shows.items() if show_id not in user_blacklist}

                    if user_new_shows:
                        try:
                            # Send heading message
                            heading_message = "🎭 **New Shows Available!** 🎭"
                            asyncio.run_coroutine_threadsafe(send_discord_message(user=member, message_text=heading_message), bot.loop)

                            # Send individual embeds
                            for show_id, show_info in user_new_shows.items():
                                embed = discord.Embed(
                                    title=f"{show_info['name']} (Show ID:{show_id})",
                                    url=show_info['url']
                                )
                                if show_info['image_url']:
                                    embed.set_image(url=show_info['image_url'])
                                asyncio.run_coroutine_threadsafe(send_discord_message(user=member, embed=embed), bot.loop)
                                time.sleep(1)  # Brief delay
                        except Exception as e:
                            logger.error(f"Failed to send DM to user {member.id}: {e}")
            else:
                # No action needed when there are no new shows
                pass

        else:
            warning_message = "Warning: Could not find the event-info div. The page structure might have changed."
            logger.warning(warning_message)
            # Optionally notify admin or log

    except Exception as e:
        error_message = f"An error occurred: {e}"
        logger.error(error_message)
        # Optionally notify admin or log

    finally:
        # Close the browser
        driver.quit()

@tasks.loop(minutes=2)
async def scraping_task():
    await asyncio.to_thread(scrape_and_process)

@scraping_task.before_loop
async def before_scraping_task():
    await bot.wait_until_ready()

@scraping_task.after_loop
async def after_scraping_task():
    logger.info("Scraping task has stopped.")

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info("------")
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        logger.info(f"Synced {len(synced)} commands.")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

# Start the task when the bot is ready
scraping_task.start()

# Run the bot
bot.run(DISCORD_BOT_TOKEN)