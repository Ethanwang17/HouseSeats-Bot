import os
import time
import logging
import asyncio
import psycopg2
import discord
from discord.ext import tasks
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

# Initialize Discord bot with necessary intents and application commands
intents = discord.Intents.default()
intents.guilds = True  # Enable guild-related events
intents.members = True  # Enable access to guild members
bot = discord.Bot(intents=intents)

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

def create_all_shows_table():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS all_shows (
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

def create_user_blacklists_table():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_blacklists (
            user_id BIGINT NOT NULL,
            show_id TEXT NOT NULL,
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

def add_to_all_shows(shows):
    conn = get_db_connection()
    cur = conn.cursor()
    for show_id, show_info in shows.items():
        try:
            # Use INSERT ... ON CONFLICT to handle duplicates
            cur.execute('''
                INSERT INTO all_shows (id, name, url, image_url)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            ''', (show_id, show_info['name'], show_info['url'], show_info['image_url']))
        except Exception as e:
            logger.error(f"Error inserting show {show_id} into all_shows: {e}")
    conn.commit()
    cur.close()
    conn.close()

def initialize_database():
    create_shows_table()
    create_all_shows_table()
    create_user_blacklists_table()  # Add this line

async def send_discord_message(message_text=None, embeds=None):
    try:
        channel = await bot.fetch_channel(DISCORD_CHANNEL_ID)
        if channel is None:
            logger.error(f"Channel with ID {DISCORD_CHANNEL_ID} not found.")
            return
        if embeds:
            await channel.send(content=message_text, embeds=embeds)
        else:
            await channel.send(content=message_text)
        logger.info("Discord message sent successfully!")
    except Exception as e:
        logger.error(f"Failed to send Discord message. Error: {e}")

async def send_user_dm(user: discord.User, embed: discord.Embed):
    try:
        await user.send(embed=embed)
        logger.info(f"Sent DM to user {user.id}")
    except discord.Forbidden:
        logger.warning(f"Cannot send DM to user {user.id}. They might have DMs disabled.")
    except Exception as e:
        logger.error(f"Error sending DM to user {user.id}: {e}")

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

            # After scraping shows and before checking for new ones
            add_to_all_shows(scraped_shows_dict)

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

            # Prepare and send Discord messages
            if new_shows:
                # Notify users via DMs, considering their blacklists
                asyncio.run_coroutine_threadsafe(
                    notify_users_about_new_shows(new_shows),
                    bot.loop
                )

        else:
            warning_message = "Warning: Could not find the event-info div. The page structure might have changed."
            logger.warning(warning_message)
            asyncio.run_coroutine_threadsafe(
                send_discord_message(message_text=warning_message),
                bot.loop
            )

    except Exception as e:
        error_message = f"An error occurred: {e}"
        logger.error(error_message)
        asyncio.run_coroutine_threadsafe(
            send_discord_message(message_text=error_message),
            bot.loop
        )

    finally:
        # Close the browser
        driver.quit()

async def notify_users_about_new_shows(new_shows):
    if not new_shows:
        return

    # Fetch all users in guilds
    users_to_notify = set()
    for guild in bot.guilds:
        async for member in guild.fetch_members(limit=None):
            if not member.bot:
                users_to_notify.add(member)

    # Fetch blacklists
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Get all user blacklists for new shows
        new_show_ids = tuple(new_shows.keys())
        if not new_show_ids:
            return
        query = '''
            SELECT user_id, show_id FROM user_blacklists
            WHERE show_id = ANY(%s)
        '''
        cur.execute(query, (new_show_ids,))
        rows = cur.fetchall()
        user_blacklists = {}
        for row in rows:
            user_id, show_id = row
            if user_id not in user_blacklists:
                user_blacklists[user_id] = set()
            user_blacklists[user_id].add(show_id)
    except Exception as e:
        logger.error(f"Error fetching user blacklists: {e}")
        user_blacklists = {}
    finally:
        cur.close()
        conn.close()

    # Iterate over users and send DMs excluding blacklisted shows
    for user in users_to_notify:
        blacklisted_show_ids = user_blacklists.get(user.id, set())
        shows_to_notify = {show_id: info for show_id, info in new_shows.items() if show_id not in blacklisted_show_ids}
        if shows_to_notify:
            for show_id, show_info in shows_to_notify.items():
                embed = discord.Embed(
                    title=f"{show_info['name']} (Show ID: {show_id})",
                    url=show_info['url']
                )
                if show_info['image_url']:
                    embed.set_image(url=show_info['image_url'])
                # Schedule the DM to be sent
                asyncio.create_task(send_user_dm(user, embed))
                # Add a short delay to respect rate limits
                await asyncio.sleep(1)  # Use asyncio.sleep instead of time.sleep

@tasks.loop(minutes=2)
async def scraping_task():
    await asyncio.to_thread(scrape_and_process)

@scraping_task.before_loop
async def before_scraping_task():
    await bot.wait_until_ready()

# Start the task when the bot is ready
scraping_task.start()

@bot.slash_command(name="blacklist", description="Manage your personal show blacklist")
async def blacklist(ctx):
    pass

@blacklist.command(name="add", description="Add a show ID to your blacklist")
async def blacklist_add(ctx, show_id: str):
    user_id = ctx.author.id
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO user_blacklists (user_id, show_id) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                    (user_id, show_id))
        conn.commit()
        await ctx.respond(f"Show ID `{show_id}` has been added to your blacklist.", ephemeral=True)
    except Exception as e:
        logger.error(f"Error adding show to blacklist: {e}")
        await ctx.respond("An error occurred while adding to the blacklist.", ephemeral=True)
    finally:
        cur.close()
        conn.close()

@blacklist.command(name="remove", description="Remove a show ID from your blacklist")
async def blacklist_remove(ctx, show_id: str):
    user_id = ctx.author.id
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('DELETE FROM user_blacklists WHERE user_id = %s AND show_id = %s', (user_id, show_id))
        conn.commit()
        await ctx.respond(f"Show ID `{show_id}` has been removed from your blacklist.", ephemeral=True)
    except Exception as e:
        logger.error(f"Error removing show from blacklist: {e}")
        await ctx.respond("An error occurred while removing from the blacklist.", ephemeral=True)
    finally:
        cur.close()
        conn.close()

@blacklist.command(name="list", description="List your blacklisted show IDs")
async def blacklist_list(ctx):
    user_id = ctx.author.id
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('SELECT show_id FROM user_blacklists WHERE user_id = %s', (user_id,))
        rows = cur.fetchall()
        if rows:
            show_ids = [row[0] for row in rows]
            await ctx.respond(f"Your blacklisted show IDs: {', '.join(show_ids)}", ephemeral=True)
        else:
            await ctx.respond("Your blacklist is empty.", ephemeral=True)
    except Exception as e:
        logger.error(f"Error fetching blacklist: {e}")
        await ctx.respond("An error occurred while fetching your blacklist.", ephemeral=True)
    finally:
        cur.close()
        conn.close()

# Run the bot
bot.run(DISCORD_BOT_TOKEN)