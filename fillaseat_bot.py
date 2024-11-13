import requests
import re
import time
import json
import os
import psycopg2
import discord
from discord.ext import tasks
import random
from datetime import datetime
import pytz
from discord.ui import Button, View
import logging
import asyncio

# Replace credentials import with environment variables
USERNAME = os.environ.get('FILLASEAT_USERNAME')
PASSWORD = os.environ.get('FILLASEAT_PASSWORD')
DATABASE_URL = os.environ.get('DATABASE_URL')
DISCORD_BOT_TOKEN = os.environ.get('FILLASEAT_DISCORD_BOT_TOKEN')
DISCORD_CHANNEL_ID = int(os.environ.get('FILLASEAT_DISCORD_CHANNEL_ID'))
PST_TIMEZONE = pytz.timezone('America/Los_Angeles')

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

# Initialize Discord bot
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
bot = discord.Bot(intents=intents)

# Add logging configuration
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

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

def create_fillaseat_blacklist_table():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS fillaseat_user_blacklists (
            user_id BIGINT,
            show_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, show_id)
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

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

def get_existing_shows():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, name, url, image_url FROM fillaseat_current_shows')
    existing_shows = {row[0]: {'name': row[1], 'url': row[2], 'image_url': row[3]} for row in cur.fetchall()}
    cur.close()
    conn.close()
    return existing_shows

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

async def send_user_dm(user: discord.User, embed: discord.Embed, view: View = None):
    try:
        if view:
            await user.send(embed=embed, view=view)
        else:
            await user.send(embed=embed)
        logger.info(f"Sent DM to user {user.id}")
    except discord.Forbidden:
        logger.warning(f"Cannot send DM to user {user.id}. They might have DMs disabled.")
    except Exception as e:
        logger.error(f"Error sending DM to user {user.id}: {e}")

class BlacklistButton(Button):
    def __init__(self, show_id: str, show_name: str, user_id: int):
        super().__init__(
            label="🚫 Blacklist Show",
            style=discord.ButtonStyle.primary,
            custom_id=f"blacklist_{show_id}_{user_id}"
        )
        self.show_id = show_id
        self.show_name = show_name
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        if interaction.user.id != self.user_id:
            await interaction.followup.send("This button is not for you!", ephemeral=True)
            return
        
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                'INSERT INTO fillaseat_user_blacklists (user_id, show_id) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                (interaction.user.id, self.show_id)
            )
            conn.commit()
            await interaction.followup.send(
                f"**`{self.show_name}`** has been added to your blacklist.",
                ephemeral=True
            )
            self.disabled = True
            await interaction.message.edit(view=self.view)
        except Exception as e:
            logger.error(f"Error adding show to blacklist: {e}")
            await interaction.followup.send(
                "An error occurred while adding to the blacklist.",
                ephemeral=True
            )
        finally:
            cur.close()
            conn.close()

async def notify_users_about_new_shows(new_shows):
    if not new_shows:
        return

    # Send notifications to the channel
    for show_id, show_info in new_shows.items():
        embed = discord.Embed(
            title=f"{show_info['name']} (Show ID: {show_id})",
            url=show_info['url'],
            color=discord.Color.red()
        )
        if show_info['image_url']:
            embed.set_image(url=show_info['image_url'])
        
        await send_discord_message(embeds=[embed])
        await asyncio.sleep(1)

    # Get users to notify
    users_to_notify = set()
    for guild in bot.guilds:
        async for member in guild.fetch_members(limit=None):
            if not member.bot:
                users_to_notify.add(member)

    # Get blacklists and send DMs
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        new_show_ids = list(new_shows.keys())
        cur.execute('''
            SELECT user_id, show_id 
            FROM fillaseat_user_blacklists 
            WHERE show_id = ANY(%s)
        ''', (new_show_ids,))
        
        user_blacklists = {}
        for row in cur.fetchall():
            user_id, show_id = row
            if user_id not in user_blacklists:
                user_blacklists[user_id] = set()
            user_blacklists[user_id].add(show_id)
    finally:
        cur.close()
        conn.close()

    for user in users_to_notify:
        blacklisted_show_ids = user_blacklists.get(user.id, set())
        shows_to_notify = {show_id: info for show_id, info in new_shows.items() 
                          if show_id not in blacklisted_show_ids}
        
        for show_id, show_info in shows_to_notify.items():
            embed = discord.Embed(
                title=f"{show_info['name']} (Show ID: {show_id})",
                url=show_info['url']
            )
            if show_info['image_url']:
                embed.set_image(url=show_info['image_url'])
            
            view = View(timeout=3600)
            view.add_item(BlacklistButton(show_id, show_info['name'], user.id))
            
            await send_user_dm(user, embed, view)
            await asyncio.sleep(1)

@tasks.loop(minutes=random.randint(2, 3))
async def fillaseat_task():
    current_time = datetime.now(PST_TIMEZONE)
    if 8 <= current_time.hour < 17:
        try:
            # Get sessid and login
            sessid = get_sessid(session, headers)
            login_response = login(session, headers, sessid, USERNAME, PASSWORD)
            
            if is_login_successful(login_response):
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
                
                # Get existing shows before updating
                existing_shows = get_existing_shows()
                
                # Find new shows
                new_show_ids = set(current_shows.keys()) - set(existing_shows.keys())
                new_shows = {show_id: current_shows[show_id] for show_id in new_show_ids}
                
                # Update database
                add_to_fillaseat_all_shows(current_shows)
                delete_all_fillaseat_shows()
                insert_fillaseat_shows(current_shows)
                
                # Notify users about new shows
                if new_shows:
                    await notify_users_about_new_shows(new_shows)
            
        except Exception as e:
            logger.error(f"An error occurred in fillaseat_task: {e}")
            await send_discord_message(f"Error in FillASeat bot: {e}")

@fillaseat_task.before_loop
async def before_fillaseat_task():
    await bot.wait_until_ready()

# Add your slash commands here (similar to scraper.py)
# ... 

# Start the task and run the bot
fillaseat_task.start()
bot.run(DISCORD_BOT_TOKEN)