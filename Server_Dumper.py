import os
import discord
import asyncio
import re
import aiohttp
import hashlib
import json
import tempfile
import shutil
import requests
import logging

from requests.exceptions import RequestException
from discord.ext import commands
from datetime import datetime

# Create logs directory if it doesn't exist

# Create logs directory if it doesn't exist
if not os.path.exists("./logs"):
    os.makedirs("./logs")

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# Create a file handler for the latest log
latest_handler = logging.FileHandler('./logs/latest.log')
latest_handler.setLevel(logging.DEBUG)

# Create a file handler for the date-specific log
date_str = datetime.now().strftime("%Y-%m-%d")
date_handler = logging.FileHandler(f'./logs/{date_str}_log.log')
date_handler.setLevel(logging.DEBUG)

# Create a console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)

# Define color codes
class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[94m',  # Blue
        'INFO': '\033[92m',   # Green
        'WARNING': '\033[93m', # Yellow
        'ERROR': '\033[91m',   # Red
        'CRITICAL': '\033[41m' # Red background
    }
    RESET = '\033[0m'

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        message = super().format(record)
        return f"{log_color}{message}{self.RESET}"

# Create a formatter and set it for all handlers
formatter = ColoredFormatter('%(asctime)s - %(levelname)s - %(message)s')
latest_handler.setFormatter(formatter)
date_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add the handlers to the logger
logger.addHandler(latest_handler)
logger.addHandler(date_handler)
logger.addHandler(console_handler)

if not os.path.exists("./config"):
    os.makedirs("./config")

config_dir = './config/'
ROLES = os.path.join(config_dir, 'ROLE.txt')
SAVE_FOLDER = './archive' # Define save folder
HASH_FILE = 'file_hashes.json'

if not os.path.exists(config_dir):
    os.makedirs(config_dir)
    logging.info(f"{config_dir} created.")

# Set up the bot
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True  # Required to access member information


# Set an empty command prefix since we're using slash commands
bot = commands.Bot(command_prefix='', intents=intents)
client = discord.Client(intents=intents)

active_processes = 0
status_lock = asyncio.Lock()


def format_username(author):
    # Check if the 'author' is an instance of discord.Member
    if isinstance(author, discord.Member):
        SPECIAL_ROLE_IDS = load_entries(ROLES)
        # Check if the author has any of the special roles
        if any(role.id in SPECIAL_ROLE_IDS for role in author.roles):
            # If the author has the special role, return a formatted string with their ID and name
            return f"{author.id} (*{author.name}*)"
        # If the author does not have the special role, return just their ID as a string
        return str(author.id)
    else:
        # If 'author' is not a discord.Member, return their ID as a string
        return str(author.id)
async def handle_rate_limit(e):
    if e.status == 429:
        reset_after = int(e.headers.get('X-RateLimit-Reset', 0)) - int(e.headers.get('X-RateLimit-Reset-After', 0))
        rate_limit_remaining = int(e.headers.get('X-RateLimit-Remaining', 0))
        logging.warning(f"Rate limit reached. Remaining: {rate_limit_remaining}. Waiting for {reset_after} seconds.")
        await asyncio.sleep(reset_after)  # Wait for the rate limit to reset

# Load existing hashes from the JSON file
# Load existing hashes from the JSON file
def load_hashes(channel_folder):
    hash_file_path = os.path.join(channel_folder, HASH_FILE)
    if os.path.exists(hash_file_path):
        with open(hash_file_path, 'r') as f:
            return json.load(f)
    return {}

# Save hashes to the JSON file
def save_hashes(hashes, channel_folder):
    hash_file_path = os.path.join(channel_folder, HASH_FILE)
    with open(hash_file_path, 'w') as f:
        json.dump(hashes, f)

# Calculate the SHA256 hash of a file content
async def calculate_hash(file_content):
    hash_sha256 = hashlib.sha256()
    hash_sha256.update(file_content)
    return hash_sha256.hexdigest()


async def process_attachments(attachments, channel_folder, hashes):
    attachment_content = ""
    for attachment in attachments:
        for attempt in range(3):  # Retry logic for each attachment
            try:
                filename = await handle_attachment(attachment, channel_folder, hashes)
                if filename:
                    # Überprüfen des Dateiformats für Bilder
                    if attachment.filename.lower().endswith((
                        '.png', '.jpg', '.jpeg', '.jfif', '.pjpeg', '.pjp',
                        '.gif', '.apng', '.ico', '.cur', '.svg', '.webp'
                    )):
                        attachment_content += f'<br><img src="{filename}" loading="lazy" alt="{attachment.filename}"><br>'
                    # Überprüfen des Dateiformats für Videos
                    elif attachment.filename.lower().endswith((
                        '.mp4', '.webm', '.ogv', '.avi', '.mov', '.mkv'
                    )):
                        attachment_content += f'<br><video controls loading="lazy" alt="{attachment.filename}"><source src="{filename}" type="video/mp4">Ihr Browser unterstützt das Video-Tag nicht.</video><br>'
                    # Überprüfen des Dateiformats für PDFs
                    elif attachment.filename.lower().endswith('.pdf'):
                        attachment_content += f'<br><a href="{filename}" target="_blank">PDF herunterladen: {attachment.filename}</a><br>'
                    # Überprüfen des Dateiformats für Text- und Markdown-Dateien
                    elif attachment.filename.lower().endswith(('.txt', '.md', '.markdown')):
                        attachment_content += f'<br><a href="{filename}" target="_blank">Text/Markdown-Datei öffnen: {attachment.filename}</a><br>'
                    # Für alle anderen Dateiformate
                    else:
                        attachment_content += f'<br><a href="{filename}" download>Herunterladen: {attachment.filename}</a><br>'
                break  # Exit the retry loop if successful
            except Exception as e:
                logging.error(f"Error processing attachment {attachment.filename}: {e}")
                if attempt < 2:  # If not the last attempt
                    logging.info('Retrying attachment download... Attempt %d of 3', attempt + 2)
                    await asyncio.sleep(2)  # Delay before retrying
                else:
                    logging.error(f"Failed to process attachment {attachment.filename} after multiple attempts.")
    return attachment_content

async def handle_attachment(attachment, channel_folder, hashes):
    attachment_url = attachment.url
    logging.info(f"Processing attachment URL: {attachment_url}")

    # Create a temporary directory for downloading
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_file_path = os.path.join(temp_dir, attachment.filename)

        for attempt in range(3):  # Retry logic for downloading the attachment
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(attachment_url) as response:
                        if response.status == 200:
                            content = await response.read()  # This is already in bytes
                            # Save the file to the temporary directory
                            with open(temp_file_path, 'wb') as f:
                                f.write(content)
                            logging.info(f"Downloaded attachment to temporary location: {temp_file_path}")

                            # Calculate the hash of the downloaded file
                            file_hash = await calculate_hash(content)
                            logging.info(f"Downloaded file hash: {file_hash}")

                            # Construct the original file path
                            original_file_path = os.path.join(channel_folder, attachment.filename)

                            # Check if the file already exists
                            if os.path.exists(original_file_path):
                                with open(original_file_path, 'rb') as f:
                                    existing_content = f.read()  # Read the file content in bytes
                                existing_hash = await calculate_hash(existing_content)
                                logging.info(f"Existing file found: {attachment.filename} with hash: {existing_hash}")

                                # If the hashes are different, rename the new file
                                if existing_hash != file_hash:
                                    new_file_name = f"{file_hash}_{attachment.filename}"
                                    new_file_path = os.path.join(channel_folder, new_file_name)
                                    logging.info(f"Renaming {attachment.filename} to {new_file_name} due to content difference.")
                                else:
                                    logging.info(f"Duplicate detected for {attachment.filename}. URL: {attachment_url}")
                                    return None  # Skip moving if the content is the same
                            else:
                                new_file_path = original_file_path  # No renaming needed

                            # Move the file from the temporary directory to the final location
                            shutil.move(temp_file_path, new_file_path)
                            logging.info(f"Moved attachment to final location: {new_file_path}")

                            # Save the hash with the filename
                            hashes[attachment.filename] = file_hash
                            save_hashes(hashes, channel_folder)  # Save updated hashes
                            logging.info(f"Saved hash for {attachment.filename}: {file_hash}")

                            return os.path.basename(new_file_path)  # Return the final filename

                        else:
                            logging.warning(f"Failed to download {attachment.filename}: HTTP {response.status}")
                            break  # Exit the retry loop on HTTP error

                except Exception as e:
                    logging.error(f"An error occurred while processing {attachment.filename}: {e}")
                    if attempt < 2:  # If not the last attempt
                        logging.info('Retrying download... Attempt %d of 3', attempt + 2)
                        await asyncio.sleep(2)  # Delay before retrying
                    else:
                        logging.error(f"Failed to download attachment {attachment.filename} after multiple attempts.")
                        return None  # Return None if all attempts fail

async def process_embeds(embeds, channel_folder, hashes):
    embed_content = ""
    for embed in embeds:
        embed_content += await create_embed_content(embed, channel_folder, hashes)
    return embed_content
async def download_embed_image(embed, channel_folder, hashes):
    # Check for image URL in different properties
    image_url = embed.image.url if embed.image else None
    thumbnail_url = embed.thumbnail.url if embed.thumbnail else None
    author_icon_url = embed.author.icon_url if embed.author else None

    # Use the first available image URL
    if image_url:
        url_to_download = image_url
    elif thumbnail_url:
        url_to_download = thumbnail_url
    elif author_icon_url:
        url_to_download = author_icon_url
    else:
        logging.info("No image or thumbnail found in the embed.")
        return None

    logging.info(f"Attempting to download image from URL: {url_to_download}")
    image_filename = url_to_download.split("/")[-1].split("?")[0]
    sanitized_filename = re.sub(r'[<>:"/\\|?*]', '_', image_filename)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_file_path = os.path.join(temp_dir, sanitized_filename)
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url_to_download) as response:
                    if response.status == 200:
                        content = await response.read()
                        with open(temp_file_path, 'wb') as f:
                            f.write(content)
                        logging.info(f"Downloaded embed image to temporary location: {temp_file_path}")

                        file_hash = await calculate_hash(content)
                        logging.info(f"Downloaded file hash: {file_hash}")

                        images_folder = os.path.join(channel_folder, 'images')
                        os.makedirs(images_folder, exist_ok=True)

                        original_file_path = os.path.join(images_folder, sanitized_filename)

                        if os.path.exists(original_file_path):
                            with open(original_file_path, 'rb') as f:
                                existing_content = f.read()
                            existing_hash = await calculate_hash(existing_content)
                            logging.info(f"Existing file found: {sanitized_filename} with hash: {existing_hash}")

                            if existing_hash == file_hash:
                                logging.info(f"Duplicate detected for {sanitized_filename}. URL: {url_to_download}")
                                return None
                            else:
                                new_file_name = f"{file_hash}_{sanitized_filename}"
                                new_file_path = os.path.join(images_folder, new_file_name)
                                logging.info(f"Renaming {sanitized_filename} to {new_file_name} due to content difference.")
                        else:
                            new_file_path = original_file_path

                        shutil.move(temp_file_path, new_file_path)
                        logging.info(f"Moved embed image to final location: {new_file_path}")

                        if os.path.exists(new_file_path):
                            logging.info(f"Image successfully saved to: {new_file_path}")
                        else:
                            logging.error(f"Failed to save image to: {new_file_path}")

                        hashes[sanitized_filename] = file_hash
                        save_hashes(hashes, channel_folder)

                        relative_path = os.path.relpath(new_file_path, start=channel_folder)
                        logging.debug(f"Relative path for HTML: {relative_path}")
                        return relative_path

                    else:
                        logging.warning(f"Failed to download image: {response.status} - {url_to_download}")
            except aiohttp.ClientConnectorError as e:
                logging.warning(f"Connection error while trying to download {url_to_download}: {e}")
            except Exception as e:
                logging.error(f"An error occurred while downloading {url_to_download}: {e}")

    return None

async def create_embed_content(embed, channel_folder, hashes):
    embed_html = '<div style="padding: 10px; margin: 10px 0;">'
    if embed.color:
        embed_html = f'<div style="border: 1px solid #{embed.color.value:06x}; background-color: #{embed.color.value:06x}; padding: 10px; margin: 10px 0;">'
    if embed.title:
        embed_html += f'<strong>{embed.title}</strong><br>'
    if embed.description:
        embed_html += f'<p>{embed.description}</p>'
    if embed.url:
        embed_html += f'<a href="{embed.url}">Link</a><br>'
    if embed.color:
        embed_html += f'<p style="color: #{embed.color.value:06x};">Color: #{embed.color.value:06x}</p>'

    image_filename = await download_embed_image(embed, channel_folder, hashes)
    if image_filename:
        embed_html += f'<br><img src="{image_filename}" loading="lazy" alt="Embed Image"><br>'

    embed_html += '</div>'
    return embed_html

async def write_html_file(channel_folder, archive_content):
    """Write the archived content to an HTML file."""
    html_content = '<html><head><title>Channel Archive</title></head><body>'
    html_content += '<h1>Channel Archive</h1>'
    html_content += ''.join(archive_content)  # Combine all message content
    html_content += '</body></html>'

    html_file_path = os.path.join(channel_folder, 'index.html')
    with open(html_file_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    logging.info(f"HTML file created: {html_file_path}")

async def heartbeat():
    try:
        while True:
            await asyncio.sleep(300)  # Wait for 5 minutes
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logging.debug(f"Die Archivierung läuft noch... (letzter Herzschlag: {timestamp})")
    except asyncio.CancelledError:
        logging.warning("Heartbeat task has been cancelled.")


# Function to check if the channel folder exists and delete it if it does
async def check_and_delete_channel_folder(channel_folder):
    if os.path.exists(channel_folder):
        logging.info(f"Deleting existing folder: {channel_folder}")
        shutil.rmtree(channel_folder)

async def archive_channel(channel, user):
    global is_running
    channel_name = channel.name.replace(" ", "_")
    channel_id = channel.id
    server_folder = os.path.join(SAVE_FOLDER, channel.guild.name.replace(" ", "_"))
    os.makedirs(server_folder, exist_ok=True)
    channel_folder = os.path.join(server_folder, f"{channel_name}_{channel_id}")

    await check_and_delete_channel_folder(channel_folder)
    os.makedirs(channel_folder, exist_ok=True)

    hashes = load_hashes(channel_folder)
    archive_content = []

    logging.info(f"Archiving channel: {channel.name} in server: {channel.guild.name}")
    await user.send(f'Archiving has started for channel: {channel.name}!')

    retry_attempts = 3  # Number of retry attempts for message processing
    async for message in channel.history(limit=None):
        for attempt in range(retry_attempts):
            try:
                content = await process_message(message, channel_folder, hashes)
                archive_content.append(content)
                break  # Exit the retry loop if successful
            except discord.HTTPException as e:
                await handle_rate_limit(e)
                if attempt < retry_attempts - 1:  # If not the last attempt
                    logging.info('Retrying message processing... Attempt %d of %d', attempt + 2, retry_attempts)
                    await asyncio.sleep(60)  # Delay before retrying
                else:
                    error_message = f"Max retry attempts reached for message ID: {message.id}"
                    logging.error(error_message)
                    await user.send(error_message)
                    break  # Exit the retry loop after max attempts
            except Exception as e:
                error_message = f"Error processing message: {e}"
                logging.error(error_message)  # Log the error
                await user.send(error_message)
                break  # Exit the retry loop on other exceptions

    save_hashes(hashes, channel_folder)
    await write_html_file(channel_folder, archive_content)
    await user.send(f'Archiving successfully completed for channel: {channel.name}!')

async def process_message(message, channel_folder, hashes):
    username = format_username(message.author)
    timestamp = message.created_at.strftime('%Y-%m-%d %H:%M:%S')
    content = f'<p> <em>{timestamp}</em> <strong>{username}:</strong> <br>{message.content}</p>'

    if message.attachments:
        for attachment in message.attachments:
            for attempt in range(3):  # Retry logic for attachments
                try:
                    content += await process_attachments([attachment], channel_folder, hashes)
                    break  # Exit the retry loop if successful
                except discord.HTTPException as e:
                    await handle_rate_limit(e)
                    if attempt < 2:  # If not the last attempt
                        logging.info('Retrying attachment download... Attempt %d of 3', attempt + 2)
                        await asyncio.sleep(2)  # Delay before retrying
                    else:
                        logging.error(f"Failed to download attachment: {attachment.url}")
                        content += f'<p>Error downloading attachment: {attachment.filename}</p>'
                        break  # Exit the retry loop after max attempts

    if message.embeds:
        content += await process_embeds(message.embeds, channel_folder, hashes)

    return content



async def dump_server(interaction: discord.Interaction):
    guild = interaction.guild
    logging.info("Guild: %s", guild)
    json_file_path = os.path.join(SAVE_FOLDER, f'{guild.name}.json')
    heartbeat_task = asyncio.create_task(heartbeat())

    if not os.path.exists(json_file_path):
        logging.info("Create: %s", json_file_path)
        with open(json_file_path, 'w') as json_file:
            json.dump([], json_file)

    with open(json_file_path, 'r') as json_file:
        logging.info("Open: %s", json_file_path)
        archived_channels = json.load(json_file)

    await interaction.response.send_message(f'Starting to archive all channels in the server: {guild.name}...')

    channels = {}

    for channel in guild.text_channels:
        logging.info("Loop Start: %s", channel)
        if channel.id in archived_channels:
            logging.info('Skipping already archived channel: %s', channel.name)
            continue

        retry_attempts = 3  # Number of retry attempts
        for attempt in range(retry_attempts):
            try:
                logging.info("Trying to call archive function")
                await archive_channel(channel, interaction.user)
                archived_channels.append(channel.id)
                logging.info('Archived channel: %s (ID: %s)', channel.name, channel.id)

                category_name = channel.category.name if channel.category else 'No Category'
                if category_name not in channels:
                    channels[category_name] = []
                channels[category_name].append({'name': channel.name, 'id': channel.id})

                with open(json_file_path, 'w') as json_file:
                    json.dump(archived_channels, json_file)
                    logging.info('Saved archived channels to %s: %s', json_file_path, archived_channels)

                # Introduce a delay to prevent semaphore timeout
                await asyncio.sleep(60)  # Adjust the sleep duration as needed
                break  # Exit the retry loop if successful

            except Exception as e:
                logging.error('Error archiving channel %s: %s', channel.name, e)
                await interaction.user.send(f'Error archiving channel {channel.name}: {e}')
                if attempt < retry_attempts - 1:  # If not the last attempt
                    logging.info('Retrying... Attempt %d of %d', attempt + 2, retry_attempts)
                    await asyncio.sleep(600)  # Delay before retrying
                else:
                    logging.error('Max retry attempts reached for channel %s', channel.name)

    logging.info("Trying to create master index")
    await create_index_html(guild)
    logging.info("create_index_html finished")
    heartbeat_task.cancel()
    await heartbeat_task
    logging.info("Heartbeat finished")

    completion_message = f'Archiving process completed for server: {guild.name}!'
    await interaction.user.send(completion_message)
    logging.info(completion_message)

async def create_index_html(guild):
    logging.info("Starting to create index.html")

    # Define the server folder path for the HTML file
    server_folder = os.path.join(SAVE_FOLDER, guild.name.replace(" ", "_"))

    # Define the path to the JSON file using SAVE_FOLDER
    json_file_path = os.path.join(SAVE_FOLDER, f'{guild.name}.json')

    # Read the archived channels from the JSON file
    try:
        with open(json_file_path, 'r') as json_file:
            logging.info("Reading archived channels from: %s", json_file_path)
            archived_channels = json.load(json_file)
    except Exception as e:
        logging.error("Error reading JSON file: %s", e)
        return

    # Create a dictionary to hold channels by category
    channels_by_category = {}

    # Organize channels by category
    for channel_id in archived_channels:
        channel = guild.get_channel(channel_id)
        if channel:
            category_name = channel.category.name if channel.category else 'No Category'
            if category_name not in channels_by_category:
                channels_by_category[category_name] = []
            channels_by_category[category_name].append(channel)
        else:
            logging.warning("Channel with ID %s not found.", channel_id)

    logging.info("Organized channels by category.")

    # Start creating the HTML content
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Archived Channels</title>
        <style>
            body { font-family: Arial, sans-serif; }
            h2 { color: #333; }
            ul { list-style-type: none; padding: 0; }
            li { margin: 5px 0; }
        </style>
    </head>
    <body>
        <h1>Archived Channels</h1>
    """

    # Add channels to the HTML content with links to their index.html
    for category, channels in channels_by_category.items():
        logging.info("Processing category: %s with %d channels.", category, len(channels))
        html_content += f"<h2>{category}</h2><ul>"
        for channel in channels:
            # Create a relative link to the index.html inside the channel's folder
            link = f"./{channel.name.replace(' ', '_')}_{channel.id}/index.html"
            html_content += f"<li><a href='{link}'>{channel.name} (ID: {channel.id})</a></li>"
        html_content += "</ul>"

    logging.info("Finished adding channels to HTML content.")

    # Close the HTML tags
    html_content += """
    </body>
    </html>
    """

    # Write the HTML content to index.html
    index_file_path = os.path.join(server_folder, 'index.html')
    try:
        with open(index_file_path, 'w', encoding='utf-8') as index_file:  # Specify utf-8 encoding
            index_file.write(html_content)
        logging.info('Created index.html at %s', index_file_path)
    except Exception as e:
        logging.error("Error writing index.html: %s", e)


def delete_entry(filename, entry_to_delete):
    # Einträge lesen
    with open(filename, 'r') as file:
        lines = file.readlines()

    # Einträge filtern
    updated_lines = [line for line in lines if line.strip() != str(entry_to_delete)]

    # Aktualisierte Einträge zurückschreiben
    with open(filename, 'w') as file:
        file.writelines(updated_lines)

def add_entry(filename, new_entry):
    with open(filename, 'a') as file:  # 'a' für Anhängen
        file.write(f"{new_entry}\n")

def load_entries(filename):
    with open(filename, 'r') as file:
        entries = [int(line.strip()) for line in file.readlines()]
    return tuple(entries)


async def manage_status():
    global active_processes
    async with status_lock:  # Acquire the lock
        if active_processes == 0:  # Check if this is the first process
            await bot.change_presence(status=discord.Status.dnd, activity=discord.Game("Arbeitet"))
        active_processes += 1  # Increment the counter

async def complete_status():
    global active_processes
    async with status_lock:  # Acquire the lock
        active_processes -= 1  # Decrement the counter
        if active_processes == 0:  # Check if all processes are done
            await bot.change_presence(status=discord.Status.online, activity=discord.Game("Bereitschaft!"))

def get_token(filename='TOKEN.txt'):
    # Check if the file exists
    token_file_path = os.path.join(config_dir, filename)
    if not os.path.exists(token_file_path):
        # Create the file and prompt for the token
        with open(token_file_path, 'w') as file:
            token = input("TOKEN.txt does not exist. Please enter your bot token: ")
            file.write(token)
        logging.critical(f"{filename} created in {config_dir}. Please restart the program.")
        exit()  # Exit the program after creating the file

    # Read the token from the file
    with open(token_file_path, 'r') as file:
        token = file.read().strip()
    return token

@bot.event
async def on_ready():
    # This function is called when the bot has successfully connected to Discord and is ready to operate
    logging.debug(f'Bot is ready as {bot.user}!')  # Log a message to the console indicating the bot's username
    if not os.path.exists(SAVE_FOLDER):
        os.makedirs(SAVE_FOLDER)
    # Öffne eine Datei im Schreibmodus ('w'), um sie zu erstellen
    if not os.path.exists(ROLES):
        with open(ROLES, 'w'):
            pass  # Nichts tun, nur die Datei erstellen
    # Synchronize the bot's command tree with Discord to ensure all commands are up to date
    await bot.tree.sync()


@bot.tree.command(name="archive", description="Archive the current channel")
@commands.has_permissions(administrator=True)
async def archive(interaction: discord.Interaction):
    await bot.change_presence(status=discord.Status.dnd, activity=discord.Game("Arbeitet"))
    # Get the channel where the command was invoked
    channel = interaction.channel
    # Call the archive_channel function to archive the current channel, passing the user who initiated the command
    await interaction.response.send_message(f'Starting to archive this channels')
    await manage_status()  # Manage status before starting the process
    try:
        await archive_channel(channel, interaction.user)
    finally:
        await complete_status()  # Complete status management after the process

@bot.tree.command(name="dump_server", description="Archive all channels in the server")
@commands.has_permissions(administrator=True)
async def dump_server_command(interaction: discord.Interaction):
    # Call the dump_server function to archive all channels in the server
    await manage_status()  # Manage status before starting the process
    try:
        await dump_server(interaction)  # Call the dump_server function
    finally:
        await complete_status()  # Complete status management after the process


@bot.tree.command(name="add_role", description="Adds a role that will be named in the HTML")
@commands.has_permissions(administrator=True)
async def add_role(interaction: discord.Interaction, role: discord.Role):
    # Check if a role is mentioned
    if not role:
        await interaction.response.send_message("Please mention a valid role.", ephemeral=True)
        return

    # Add the role ID to the file
    add_entry(ROLES, role.id)  # Save the role ID instead of the name

    # Create a confirmation message
    await interaction.response.send_message(f"Role ID '{role.id}' has been added.", ephemeral=True)


@bot.tree.command(name="delt_role", description="Delete a role that will be named in the HTML")
@commands.has_permissions(administrator=True)
async def delt_role(interaction: discord.Interaction, role: discord.Role):
    filename = ROLES

    # Check if a role is mentioned
    if not role:
        await interaction.response.send_message("Bitte geben Sie eine gültige Rolle an.", ephemeral=True)
        return

    # Delete the role ID from the file
    delete_entry(filename, role.id)  # Call delete_entry for the role ID

    await interaction.response.send_message(f"Die Rolle mit der ID {role.id} wurde erfolgreich gelöscht.",
                                            ephemeral=True)


@bot.tree.command(name="show_role", description="Show roles that will be named in the HTML")
@commands.has_permissions(administrator=True)
async def show_role(interaction: discord.Interaction):
    filename = ROLES
    role_ids = load_entries(filename)  # Load role IDs

    if role_ids:
        roles_info = []
        for role_id in role_ids:
            role = interaction.guild.get_role(role_id)  # Get the role object from the guild
            if role:  # Check if the role exists
                roles_info.append(f"{role.name} - {role.id}")  # Format as "name - ID"
            else:
                roles_info.append(f"Role ID {role_id} not found")  # Handle missing roles

        roles_list = '\n'.join(roles_info)  # Join the formatted strings
        await interaction.response.send_message(f"Die folgenden Rollen sind gespeichert:\n{roles_list}", ephemeral=True)
    else:
        await interaction.response.send_message("Es sind keine Rollen gespeichert.", ephemeral=True)


#Add server overview index.html

# @info.error
# async def info_error(ctx, error):
#     if isinstance(error, commands.MissingPermissions):
#         await ctx.send("Du hast nicht die erforderlichen Berechtigungen, um dieses Kommando zu verwenden.")

TOKEN = get_token()
# Run the bot
bot.run(TOKEN)  # Replace with your bot token
