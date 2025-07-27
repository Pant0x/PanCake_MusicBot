import lyricsgenius
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
import asyncio
import aiosqlite
import yt_dlp
import functools
from datetime import datetime
from collections import deque
import random
import math
import json
import os
# Spotify support
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Load environment vars
from dotenv import load_dotenv
load_dotenv()
TOKEN = os.getenv('TOKEN')
GENIUS_TOKEN = os.getenv('GENIUS_TOKEN')
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
spotify = None
if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
    spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET
    ))

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

# Error handling decorator (define if not already present)
def command_error_handler(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            ctx = args[0] if args else None
            if ctx:
                await send_error(ctx, f"An error occurred: {str(e)}")
            print(f"Error in {func.__name__}: {e}")
    return wrapper

# GuildData class (define if not already present)
class GuildData:
    def __init__(self):
        self.queue = deque()
        self.loop = False
        self.volume = 0.5  # Set default volume to 50% (normal)
        self.now_playing = None
        self.empty_since = None
        self.playlist = None
        self.message_channel = None
        self.last_interaction = datetime.now()
        self.last_activity = datetime.now()
        self.current_track_start = datetime.now()
        self.track_history = []
        self.stay_24_7 = False
        self.auto_disconnect = True
        self.audio_filter = None
        self.was_command_leave = False
        self.last_played_title = None
        self.last_played_query = None  # Store the last !play query
        self.queue_backup = None  # For queue loop
        self.autoplay = False  # Smart Autoplay/Auto-DJ Mode
    def to_serializable(self):
        return list(self.queue)
    def load_queue(self, queue_list):
        self.queue = deque(queue_list)
import os


# --- Final Touch: Play Command supports links, search, and attached audio files ---
import discord
from discord import File as DiscordFile
import asyncio
import aiosqlite
import yt_dlp
import functools
from datetime import datetime
import aiohttp
import tempfile
import os as _os

@bot.command(name="play", aliases=['p'])
@command_error_handler
async def play(ctx, *, query=None):
    """
    Play a song or add it to the queue. Supports YouTube, Spotify, direct links, and attached audio files.
    """
    # If user attached a file, prioritize it
    if ctx.message.attachments:
        attachment = ctx.message.attachments[0]
        if not attachment.filename.lower().endswith((".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac")):
            await send_error(ctx, "Please attach a valid audio file (.mp3, .wav, .ogg, .flac, .m4a, .aac)!")
            return
        await send_info(ctx, f"🎼 Loading attached file: `{attachment.filename}`...")
        voice_client = await connect_to_voice(ctx)
        if not voice_client:
            return
        data = get_guild_data(ctx.guild.id)
        data.last_interaction = datetime.now()
        data.last_activity = datetime.now()
        # Download file to temp
        with tempfile.NamedTemporaryFile(delete=False, suffix="_"+attachment.filename) as tmp:
            temp_path = tmp.name
            async with aiohttp.ClientSession() as session:
                async with session.get(attachment.url) as resp:
                    tmp.write(await resp.read())
        # Add to queue as a local file
        track = {
            'title': attachment.filename,
            'duration': None,
            'webpage_url': attachment.url,
            'thumbnail': None,
            'uploader': ctx.author.display_name,
            'requester': ctx.author.id,
            'local_path': temp_path
        }
        data.queue.append(track)
        embed = discord.Embed(
            title="✅ Added to Queue (File)",
            description=f"{attachment.filename}",
            color=discord.Color.green()
        )
        embed.add_field(name="Position in queue", value=f"{len(data.queue)}")
        await ctx.send(embed=embed)
        if not voice_client.is_playing() and not voice_client.is_paused():
            await play_next(ctx.guild, ctx)
        return

    # Otherwise, handle as before (search, link, Spotify)
    if not query:
        await send_error(ctx, "Please provide a song name, URL, or attach an audio file!")
        return
    await send_info(ctx, f"🎼 Searching for: `{query}`...")
    voice_client = await connect_to_voice(ctx)
    if not voice_client:
        return
    data = get_guild_data(ctx.guild.id)
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    data.last_played_query = query  # Save the raw query for lyrics
    try:
        is_url = query.startswith(('http://', 'https://', 'www.'))
        # Spotify support
        if is_url and query.startswith('https://open.spotify.com') and spotify:
            if 'track' in query:
                # Single Spotify track
                track_info = spotify.track(query)
                search_query = f"{track_info['name']} {track_info['artists'][0]['name']} audio"
                yt_result = await YTDLSource.search(search_query, limit=1)
                if not yt_result:
                    await send_error(ctx, "No YouTube result found for this Spotify track!")
                    return
                yt = yt_result[0]
                track = {
                    'title': yt['title'],
                    'duration': yt['duration'],
                    'webpage_url': yt['webpage_url'],
                    'thumbnail': yt['thumbnail'],
                    'uploader': yt['uploader'],
                    'requester': ctx.author.id
                }
                data.queue.append(track)
                data.last_played_title = yt['title']
                embed = discord.Embed(
                    title="✅ Added to Queue (Spotify)",
                    description=f"[{track['title']}]({track['webpage_url']})",
                    color=discord.Color.green()
                )
                embed.set_thumbnail(url=track['thumbnail'])
                embed.add_field(name="Position in queue", value=f"{len(data.queue)}")
                await ctx.send(embed=embed)
            elif 'playlist' in query:
                # Spotify playlist
                playlist_info = spotify.playlist(query)
                added = 0
                for item in playlist_info['tracks']['items']:
                    t = item['track']
                    search_query = f"{t['name']} {t['artists'][0]['name']} audio"
                    yt_result = await YTDLSource.search(search_query, limit=1)
                    if not yt_result:
                        continue
                    yt = yt_result[0]
                    track = {
                        'title': yt['title'],
                        'duration': yt['duration'],
                        'webpage_url': yt['webpage_url'],
                        'thumbnail': yt['thumbnail'],
                        'uploader': yt['uploader'],
                        'requester': ctx.author.id
                    }
                    data.queue.append(track)
                    added += 1
                await send_success(ctx, f"Added {added} tracks from Spotify playlist!")
            else:
                await send_error(ctx, "Unsupported Spotify link. Only tracks and playlists are supported.")
                return
        else:
            # YouTube or search
            search_query = query if is_url else f"ytsearch:{query}"
            info = await YTDLSource.from_url(search_query, loop=asyncio.get_event_loop(), stream=True)
            if not info:
                await send_error(ctx, "No results found!")
                return
            track = {
                'title': info.title,
                'duration': info.duration,
                'webpage_url': info.url,
                'thumbnail': info.thumbnail,
                'uploader': info.uploader,
                'requester': ctx.author.id
            }
            data.queue.append(track)
            data.last_played_title = info.title
            if data.loop:
                data.queue_backup = list(data.queue)
            embed = discord.Embed(
                title="✅ Added to Queue",
                description=f"[{track['title']}]({track['webpage_url']})",
                color=discord.Color.green()
            )
            embed.set_thumbnail(url=track['thumbnail'])
            embed.add_field(name="Position in queue", value=f"{len(data.queue)}")
            await ctx.send(embed=embed)
        # Start playback if not already playing
        if not voice_client.is_playing() and not voice_client.is_paused():
            await play_next(ctx.guild, ctx)
    except Exception as e:
        await send_error(ctx, f"❌ Error: {str(e)}")
        print(f"Play command error: {e}")

# --- Final Touch: Play attached files in play_next ---
import mimetypes
async def play_next(guild, ctx=None):
    voice_client = guild.voice_client
    if not voice_client:
        return
    data = get_guild_data(guild.id)
    # --- QUEUE LOOP POLISH ---
    if not data.queue:
        if data.loop:
            # If looping, restore the backup and continue looping
            if data.queue_backup and len(data.queue_backup) > 0:
                data.queue = deque(data.queue_backup)
                if ctx:
                    await send_info(ctx, "Looping the queue again!")
            else:
                # If no backup, but a song is playing, repeat it
                if data.now_playing:
                    data.queue.append(data.now_playing.copy())
                    if ctx:
                        await send_info(ctx, "Repeating the current song!")
                else:
                    data.empty_since = datetime.now()
                    data.now_playing = None
                    if ctx:
                        await send_info(ctx, "Queue is now empty. I'll stay here for 5 minutes unless new songs are added.")
                    return
        elif data.autoplay and data.now_playing:
            # Smart Autoplay: fetch related tracks and queue one
            try:
                search_results = await YTDLSource.search(f"{data.now_playing['title']} related", limit=5)
                for track in search_results:
                    if track['id'] != data.now_playing.get('id'):
                        new_track = {
                            'title': track['title'],
                            'duration': track['duration'],
                            'webpage_url': track['webpage_url'],
                            'thumbnail': track['thumbnail'],
                            'uploader': track['uploader'],
                            'requester': data.now_playing['requester']
                        }
                        data.queue.append(new_track)
                        if ctx:
                            await send_info(ctx, f"Auto-queued related track: {track['title']}")
                        break
                if not data.queue:
                    if ctx:
                        await send_info(ctx, "No related tracks found for autoplay.")
                    data.empty_since = datetime.now()
                    data.now_playing = None
                    return
            except Exception as e:
                if ctx:
                    await send_error(ctx, f"Autoplay error: {e}")
                data.empty_since = datetime.now()
                data.now_playing = None
                return
        else:
            data.empty_since = datetime.now()
            data.now_playing = None
            if ctx:
                await send_info(ctx, "Queue is now empty. I'll stay here for 5 minutes unless new songs are added.")
            return

    # Get next song (with loop handling)
    if data.loop and data.now_playing and not data.queue:
        # If looping a single song
        next_track = data.now_playing.copy()
    else:
        next_track = data.queue.popleft()
    data.now_playing = next_track
    data.empty_since = None
    data.last_activity = datetime.now()
    data.current_track_start = datetime.now()
    # Add to track history (limit to 100 tracks)
    async with aiosqlite.connect('musicbot.db') as db:
        await db.execute("INSERT INTO track_history (guild_id, track_data) VALUES (?, ?)",
                       (guild.id, json.dumps(next_track)))
        await db.execute("DELETE FROM track_history WHERE id NOT IN (SELECT id FROM track_history WHERE guild_id = ? ORDER BY played_at DESC LIMIT 100)", (guild.id,))
        await db.commit()
    try:
        # If the track is a local file (attachment), play it directly
        if 'local_path' in next_track and next_track['local_path']:
            source = discord.FFmpegPCMAudio(next_track['local_path'], **ffmpeg_options)
            player = discord.PCMVolumeTransformer(source, volume=data.volume)
        else:
            player = await YTDLSource.from_url(next_track['webpage_url'], loop=bot.loop, stream=True, filter=data.audio_filter)
            player.volume = data.volume
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"[{next_track['title']}]({next_track['webpage_url']})" if next_track.get('webpage_url') else next_track['title'],
            color=discord.Color.blue()
        )
        if next_track.get('thumbnail'):
            embed.set_thumbnail(url=next_track['thumbnail'])
        if next_track.get('duration'):
            embed.add_field(name="Duration", value=format_duration(next_track['duration']))
        requester_member = None
        if isinstance(next_track['requester'], int):
            requester_member = guild.get_member(next_track['requester'])
        elif hasattr(next_track['requester'], 'mention'):
            requester_member = next_track['requester']
        requester_mention = requester_member.mention if requester_member else str(next_track['requester'])
        embed.add_field(name="Requested by", value=requester_mention)
        if data.queue:
            next_song = data.queue[0]
            embed.add_field(name="Next Song", value=f"[{next_song['title']}]({next_song['webpage_url']})" if next_song.get('webpage_url') else next_song['title'], inline=False)
        if data.message_channel:
            await data.message_channel.send(embed=embed)
        voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop))
    except Exception as e:
        print(f"Error playing next track: {e}")
        if data.message_channel:
            await send_error(data.message_channel, f"Error playing track: {e}")
        await play_next(guild)

# --- Final Touch: Add slash command support for /play ---
from discord import app_commands

@bot.tree.command(name="play", description="Play a song by name, link, or attach a file.")
@app_commands.describe(query="Song name, YouTube/Spotify link, or leave blank to play attachment.")
async def slash_play(interaction: discord.Interaction, query: str = None):
    """
    Slash command version of play. Supports attachments and links.
    """
    # If attachment is present
    if interaction.attachments:
        attachment = interaction.attachments[0]
        if not attachment.filename.lower().endswith((".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac")):
            await interaction.response.send_message("Please attach a valid audio file (.mp3, .wav, .ogg, .flac, .m4a, .aac)!", ephemeral=True)
            return
        # Download and play the attachment
        # Create a fake context for compatibility
        class FakeCtx:
            def __init__(self, interaction, attachment):
                self.guild = interaction.guild
                self.author = interaction.user
                self.message = type('msg', (), {'attachments': [attachment]})()
                self.send = lambda *a, **k: interaction.response.send_message(*a, **k)
        ctx = FakeCtx(interaction, attachment)
        await play(ctx)
        return
    # Otherwise, call play with query
    class FakeCtx:
        def __init__(self, interaction):
            self.guild = interaction.guild
            self.author = interaction.user
            self.message = type('msg', (), {'attachments': []})()
            self.send = lambda *a, **k: interaction.response.send_message(*a, **k)
    ctx = FakeCtx(interaction)
    await play(ctx, query=query)

guild_data = {}  # guild_id: GuildData()

# Audio filter presets
AUDIO_FILTERS = {
    'bassboost': 'bass=g=5',
    'nightcore': 'aresample=48000,asetrate=48000*1.25',
    'vaporwave': 'aresample=48000,asetrate=48000*0.8',
    '8d': 'apulsator=hz=0.08',
    'clear': None
}

# Load queues from DB on startup
async def load_queues():
    async with aiosqlite.connect('musicbot.db') as db:
        cursor = await db.execute("SELECT guild_id, queue_data FROM queues")
        rows = await cursor.fetchall()
        for guild_id, queue_data in rows:
            data = get_guild_data(guild_id)
            try:
                queue_list = json.loads(queue_data)
                data.load_queue(queue_list)
            except Exception:
                pass

# Save queues on shutdown
async def save_queues():
    for guild_id, data in guild_data.items():
        async with aiosqlite.connect('musicbot.db') as db:
            await db.execute("INSERT OR REPLACE INTO queues VALUES (?, ?)",
                          (guild_id, json.dumps(data.to_serializable())))
            await db.commit()

@bot.listen()
async def on_shutdown():
    await save_queues()

# YouTube-DL options
ytdl_format_options = {
    'format': 'bestaudio/best',  # Always get the best available audio
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',  # Use ytsearch for faster search
    'source_address': '0.0.0.0',
    'youtube_include_dash_manifest': False,
    'extract_flat': False,  # Ensure we get full info for direct playback
    'cachedir': False,      # Don't use cache for fastest response
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5, filter=None):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')
        self.uploader = data.get('uploader')
        self.webpage_url = data.get('webpage_url')
        self.uploader_url = data.get('uploader_url')
        self.description = data.get('description')
        self.views = data.get('view_count')
        self.likes = data.get('like_count')
        self.filter = filter

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False, playlist=False, filter=None):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        
        if 'entries' in data:
            if playlist:
                entries = data['entries']
                return [cls(discord.FFmpegPCMAudio(entry['url'], **ffmpeg_options), data=entry, filter=filter) for entry in entries]
            else:
                data = data['entries'][0]
        
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data, filter=filter)
    
    @classmethod
    async def search(cls, query, *, loop=None, limit=5):
        loop = loop or asyncio.get_event_loop()
        ytdl_search_options = ytdl_format_options.copy()
        ytdl_search_options['default_search'] = 'ytsearch'
        ytdl_search_options['noplaylist'] = True
        ytdl_search_options['quiet'] = True
        ytdl_search = yt_dlp.YoutubeDL(ytdl_search_options)
        
        search_query = f"ytsearch{limit}:{query}"
        data = await loop.run_in_executor(None, lambda: ytdl_search.extract_info(search_query, download=False))
        
        if 'entries' in data:
            return data['entries']
        return []

# Helper functions
def get_guild_data(guild_id):
    if guild_id not in guild_data:
        guild_data[guild_id] = GuildData()
        
        # Load guild settings from DB
        async def load_settings():
            async with aiosqlite.connect('musicbot.db') as db:
                cursor = await db.execute("SELECT volume, loop, stay_timeout, stay_24_7, auto_disconnect, audio_filter FROM guild_settings WHERE guild_id = ?", (guild_id,))
                row = await cursor.fetchone()
                if row:
                    data = guild_data[guild_id]
                    data.volume = row[0]
                    data.loop = bool(row[1])
                    data.stay_24_7 = bool(row[3])
                    data.auto_disconnect = bool(row[4])
                    data.audio_filter = row[5]
                    # Load autoplay from DB if you add it later
        asyncio.create_task(load_settings())
        
    return guild_data[guild_id]

async def connect_to_voice(ctx):
    voice_state = ctx.author.voice
    if not voice_state or not voice_state.channel:
        await send_error(ctx, "You must be in a voice channel to use this command!")
        return None
    
    voice_client = ctx.guild.voice_client
    if not voice_client:
        voice_client = await voice_state.channel.connect(self_deaf=True)
    elif voice_client.channel != voice_state.channel:
        await voice_client.move_to(voice_state.channel)
        await voice_client.guild.change_voice_state(channel=voice_state.channel, self_deaf=True)
    
    data = get_guild_data(ctx.guild.id)
    data.message_channel = ctx.channel
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    return voice_client

async def check_empty_voice(guild):
    voice_client = guild.voice_client
    if not voice_client:
        return
    
    data = get_guild_data(guild.id)
    
    # Skip checks if in 24/7 mode
    if data.stay_24_7:
        return
    
    # Skip checks if auto-disconnect is disabled
    if not data.auto_disconnect:
        return
    
    # Smarter disconnect: disconnect if no activity for 5 minutes
    if (datetime.now() - data.last_activity).total_seconds() > 300:
        embed = discord.Embed(
            title="👋 Auto-disconnect",
            description="Taking a little break! I'll disconnect to save resources.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Reason",
            value="🕒 No activity for 5 minutes",
            inline=False
        )
        embed.add_field(
            name="Want me to stay?",
            value="Use `!247` to enable 24/7 mode\nOr `!autodisconnect` to disable auto-disconnect",
            inline=False
        )
        embed.set_footer(text="See you soon! 💫")
        
        await voice_client.disconnect()
        if data.message_channel:
            await data.message_channel.send(embed=embed)
        return

    # Check if voice channel is empty (except bot)
    if len(voice_client.channel.members) <= 1:
        await voice_client.disconnect()
        if data.message_channel:
            await send_info(data.message_channel, "Disconnected from voice channel because it's empty.")
        return
    
    # Check if queue is empty for too long
    if not data.queue and data.empty_since:
        time_elapsed = (datetime.now() - data.empty_since).total_seconds()
        remaining_time = 300 - time_elapsed  # 5 minutes timeout
        
        if remaining_time <= 0:
            await voice_client.disconnect()
            if data.message_channel:
                await send_info(data.message_channel, "Disconnected due to inactivity (empty queue for 5 minutes).")
        elif remaining_time <= 60 and int(remaining_time) % 15 == 0:  # Notify every 15 seconds in last minute
            if data.message_channel:
                await send_info(data.message_channel, f"I will disconnect in {int(remaining_time)} seconds if the queue remains empty...")

async def send_error(ctx, message):
    """Send an error message with consistent formatting"""
    if isinstance(ctx, discord.Interaction):
        if ctx.response.is_done():
            await ctx.followup.send(f"❌ {message}", ephemeral=True)
        else:
            await ctx.response.send_message(f"❌ {message}", ephemeral=True)
    else:
        await ctx.send(f"❌ {message}")

async def send_info(ctx, message):
    """Send an info message with consistent formatting"""
    if isinstance(ctx, discord.Interaction):
        if ctx.response.is_done():
            await ctx.followup.send(f"ℹ️ {message}", ephemeral=False)
        else:
            await ctx.response.send_message(f"ℹ️ {message}", ephemeral=False)
    else:
        await ctx.send(f"ℹ️ {message}")

async def send_success(ctx, message):
    """Send a success message with consistent formatting"""
    if isinstance(ctx, discord.Interaction):
        if ctx.response.is_done():
            await ctx.followup.send(f"✅ {message}", ephemeral=False)
        else:
            await ctx.response.send_message(f"✅ {message}", ephemeral=False)
    else:
        await ctx.send(f"✅ {message}")

async def play_next(guild, ctx=None):
    voice_client = guild.voice_client
    if not voice_client:
        return
    data = get_guild_data(guild.id)
    # --- QUEUE LOOP FIX ---
    if not data.queue:
        if data.loop and data.queue_backup and len(data.queue_backup) > 0:
            data.queue = deque(data.queue_backup)
        elif data.autoplay and data.now_playing:
            # Smart Autoplay: fetch related tracks and queue one
            try:
                search_results = await YTDLSource.search(f"{data.now_playing['title']} related", limit=5)
                for track in search_results:
                    if track['id'] != data.now_playing.get('id'):
                        new_track = {
                            'title': track['title'],
                            'duration': track['duration'],
                            'webpage_url': track['webpage_url'],
                            'thumbnail': track['thumbnail'],
                            'uploader': track['uploader'],
                            'requester': data.now_playing['requester']
                        }
                        data.queue.append(new_track)
                        if ctx:
                            await send_info(ctx, f"Auto-queued related track: {track['title']}")
                        break
                if not data.queue:
                    if ctx:
                        await send_info(ctx, "No related tracks found for autoplay.")
                    data.empty_since = datetime.now()
                    data.now_playing = None
                    return
            except Exception as e:
                if ctx:
                    await send_error(ctx, f"Autoplay error: {e}")
                data.empty_since = datetime.now()
                data.now_playing = None
                return
        else:
            data.empty_since = datetime.now()
            data.now_playing = None
            if ctx:
                await send_info(ctx, "Queue is now empty. I'll stay here for 5 minutes unless new songs are added.")
            return
    # Get next song (with loop handling)
    if data.loop and data.now_playing and not data.queue:
        next_track = data.now_playing
    else:
        next_track = data.queue.popleft()
    data.now_playing = next_track
    data.empty_since = None
    data.last_activity = datetime.now()
    data.current_track_start = datetime.now()
    # Add to track history (limit to 100 tracks)
    async with aiosqlite.connect('musicbot.db') as db:
        await db.execute("INSERT INTO track_history (guild_id, track_data) VALUES (?, ?)",
                       (guild.id, json.dumps(next_track)))
        await db.execute("DELETE FROM track_history WHERE id NOT IN (SELECT id FROM track_history WHERE guild_id = ? ORDER BY played_at DESC LIMIT 100)", (guild.id,))
        await db.commit()
    try:
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"[{next_track['title']}]({next_track['webpage_url']})",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=next_track['thumbnail'])
        embed.add_field(name="Duration", value=format_duration(next_track['duration']))
        requester_member = None
        if isinstance(next_track['requester'], int):
            requester_member = guild.get_member(next_track['requester'])
        elif hasattr(next_track['requester'], 'mention'):
            requester_member = next_track['requester']
        requester_mention = requester_member.mention if requester_member else str(next_track['requester'])
        embed.add_field(name="Requested by", value=requester_mention)
        if data.queue:
            next_song = data.queue[0]
            embed.add_field(name="Next Song", value=f"[{next_song['title']}]({next_song['webpage_url']})", inline=False)
        if data.message_channel:
            await data.message_channel.send(embed=embed)
        player = await YTDLSource.from_url(next_track['webpage_url'], loop=bot.loop, stream=True, filter=data.audio_filter)
        player.volume = data.volume
        voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop))
    except Exception as e:
        print(f"Error playing next track: {e}")
        if data.message_channel:
            await send_error(data.message_channel, f"Error playing track: {e}")
        await play_next(guild)

def format_duration(seconds):
    if not seconds:
        return "Live"
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"

# Error handling decorator with custom error messages
def command_error_handler(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except discord.errors.NotFound:
            ctx = args[0] if args else None
            if ctx:
                await send_error(ctx, "🔍 I couldn't find what you were looking for!")
        except discord.errors.Forbidden:
            ctx = args[0] if args else None
            if ctx:
                await send_error(ctx, "🚫 I don't have permission to do that!")
        except discord.HTTPException as e:
            ctx = args[0] if args else None
            if ctx:
                await send_error(ctx, f"📶 A network error occurred: {str(e)}")
        except yt_dlp.utils.DownloadError as e:
            ctx = args[0] if args else None
            if ctx:
                if "Video unavailable" in str(e):
                    await send_error(ctx, "🎥 This video is unavailable or private!")
                else:
                    await send_error(ctx, f"📺 YouTube error: {str(e)}")
        except Exception as e:
            ctx = args[0] if args else None
            if ctx:
                error_msg = str(e).lower()
                if "timeout" in error_msg:
                    await send_error(ctx, "⌛ The operation timed out. Please try again!")
                elif "queue" in error_msg:
                    await send_error(ctx, "📋 There was an issue with the queue. Try the command again!")
                elif "playing" in error_msg:
                    await send_error(ctx, "🎵 There was an issue with playback. Try skipping to the next song!")
                else:
                    await send_error(ctx, f"⚠️ An error occurred: {str(e)}")
            print(f"Error in {func.__name__}: {e}")
    return wrapper

# Add a helper for DB schema errors
async def handle_db_error(ctx, e):
    if 'no column named' in str(e):
        await send_error(ctx, f"Database schema is out of date. Please delete 'musicbot.db' and restart the bot.")
    else:
        await send_error(ctx, f"Database error: {e}")

# Commands

@bot.command(name="queue", aliases=['q'])
@command_error_handler
async def queue(ctx, page: int = 1):
    """Show the current queue with pagination"""
    await send_info(ctx, "Fetching the current queue...")
    data = get_guild_data(ctx.guild.id)
    
    if not data.queue and not data.now_playing:
        await send_info(ctx, "The queue is empty!")
        return
    
    items_per_page = 10
    total_pages = max(1, math.ceil(len(data.queue) / items_per_page))
    page = max(1, min(page, total_pages))
    
    embed = discord.Embed(
        title="🎶 Music Queue",
        description="Use ⏮️ to go to previous page and ⏭️ to go to next page",
        color=discord.Color.blue()
    )
    
    if data.now_playing:
        elapsed = (datetime.now() - data.current_track_start).total_seconds()
        duration = data.now_playing['duration'] or 0
        progress = min(elapsed / duration if duration > 0 else 0, 1)
        progress_bar = "".join(['▰' if i/20 <= progress else '▱' for i in range(20)])
        current_time = format_duration(int(elapsed))
        total_time = format_duration(duration)
        
        embed.add_field(
            name="🎵 Now Playing",
            value=f"[{data.now_playing['title']}]({data.now_playing['webpage_url']})\n{progress_bar}\n`{current_time} / {total_time}`",
            inline=False
        )
        if data.now_playing.get('thumbnail'):
            embed.set_thumbnail(url=data.now_playing['thumbnail'])
    
    if data.queue:
        start = (page - 1) * items_per_page
        end = start + items_per_page
        queue_lines = []
        for i, track in enumerate(list(data.queue)[start:end], start=start+1):
            duration = format_duration(track['duration'])
            queue_lines.append(f"`{i}.` [{track['title']}]({track['webpage_url']}) - {duration}")

        # Split lines into chunks of <=1024 chars for embed field value
        chunk = ""
        field_count = 0
        for line in queue_lines:
            if len(chunk) + len(line) + 1 > 1024:
                embed.add_field(
                    name=f"Up Next (Page {page}/{total_pages})" if field_count == 0 else "\u200b",
                    value=chunk,
                    inline=False
                )
                chunk = ""
                field_count += 1
            chunk += line + "\n"
        if chunk:
            embed.add_field(
                name=f"Up Next (Page {page}/{total_pages})" if field_count == 0 else "\u200b",
                value=chunk,
                inline=False
            )
    
    total_duration = sum(t['duration'] for t in data.queue if t['duration'])
    embed.set_footer(text=f"Total: {len(data.queue)} tracks | {format_duration(total_duration)}")
    
    await ctx.send(embed=embed)

@bot.command(name="skip", aliases=['s'])
@command_error_handler
async def skip(ctx):
    """Skip the current song"""
    await send_info(ctx, "Skipping the current song...")
    voice_client = ctx.guild.voice_client
    if not voice_client or not voice_client.is_playing():
        await send_error(ctx, "Nothing is playing right now!")
        return
    
    data = get_guild_data(ctx.guild.id)
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    voice_client.stop()
    await send_success(ctx, "Skipped the current song!")
    await play_next(ctx.guild, ctx)

@bot.command(name="pause")
@command_error_handler
async def pause(ctx):
    """Pause the current song"""
    await send_info(ctx, "Pausing the music...")
    voice_client = ctx.guild.voice_client
    if not voice_client or not voice_client.is_playing():
        await send_error(ctx, "Nothing is playing right now!")
        return
    
    data = get_guild_data(ctx.guild.id)
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    voice_client.pause()
    await send_success(ctx, "Paused the music!")

@bot.command(name="resume", aliases=['r'])
@command_error_handler
async def resume(ctx):
    """Resume the paused song"""
    await send_info(ctx, "Resuming the music...")
    voice_client = ctx.guild.voice_client
    if not voice_client or not voice_client.is_paused():
        await send_error(ctx, "Nothing is paused right now!")
        return
    
    data = get_guild_data(ctx.guild.id)
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    voice_client.resume()
    await send_success(ctx, "Resumed the music!")

@bot.command(name="stop")
@command_error_handler
async def stop(ctx):
    """Stop all playback, clear the queue, and reset all playback states"""
    await send_info(ctx, "🛑 Stopping all playback and clearing everything...")
    voice_client = ctx.guild.voice_client
    if not voice_client:
        await send_error(ctx, "I'm not in a voice channel!")
        return
    
    data = get_guild_data(ctx.guild.id)
    # Reset all playback related states
    data.queue.clear()
    data.queue_backup = None
    data.loop = False
    data.now_playing = None
    data.empty_since = datetime.now()
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    # Stop the voice client
    voice_client.stop()
    
    # Disconnect from voice channel
    await voice_client.disconnect()
    
    await send_success(ctx, "✅ Completely stopped! All processes ended and queue cleared.")

@bot.command(name="leave", aliases=['disconnect', 'dc'])
@command_error_handler
async def leave(ctx):
    """Make the bot leave the voice channel"""
    await send_info(ctx, "Leaving the voice channel...")
    voice_client = ctx.guild.voice_client
    if voice_client:
        data = get_guild_data(ctx.guild.id)
        data.was_command_leave = True
        await voice_client.disconnect()
    await send_success(ctx, "Left the voice channel!")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.id == bot.user.id and before.channel and not after.channel:
        guild_id = before.channel.guild.id
        if guild_id in guild_data:
            data = guild_data[guild_id]
            if hasattr(data, 'was_command_leave') and data.was_command_leave:
                data.was_command_leave = False
            else:
                data.queue.clear()
                data.now_playing = None
                data.empty_since = None
                channel = data.message_channel or before.channel.guild.system_channel
                if channel:
                    try:
                        await send_info(channel, "I got kicked from the voice channel!")
                    except Exception:
                        pass

@bot.command(name="volume", aliases=['v'])
@command_error_handler
async def volume(ctx, volume: int = None):
    """Set the playback volume (0-100)"""
    if volume is None:
        data = get_guild_data(ctx.guild.id)
        await send_info(ctx, f"Current volume: {int(data.volume * 100)}%")
        return
    
    if volume < 0 or volume > 100:
        await send_error(ctx, "Volume must be between 0 and 100!")
        return
    
    voice_client = ctx.guild.voice_client
    if not voice_client or not voice_client.is_playing():
        await send_error(ctx, "Nothing is playing right now!")
        return
    
    data = get_guild_data(ctx.guild.id)
    data.volume = volume / 100
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    if voice_client.source:
        voice_client.source.volume = data.volume
    
    await send_success(ctx, f"Volume set to {volume}%")

@bot.command(name="loop", aliases=['l'])
@command_error_handler
async def loop(ctx):
    """Toggle current song looping"""
    data = get_guild_data(ctx.guild.id)
    data.loop = not data.loop
    
    if not data.now_playing:
        await send_error(ctx, "Nothing is playing right now!")
        return
        
    if data.loop:
        # Save only the current song for looping
        data.queue_backup = [data.now_playing]
        await send_success(ctx, "🔂 Current song looping is now enabled! This song will repeat when finished.")
    else:
        data.queue_backup = None
        await send_success(ctx, "🔄 Song looping is now disabled!")
    
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()

@bot.command(name="nowplaying", aliases=['np'])
@command_error_handler
async def nowplaying(ctx):
    """Show the currently playing song"""
    data = get_guild_data(ctx.guild.id)
    
    if not data.now_playing:
        await send_error(ctx, "Nothing is playing right now!")
        return
    
    embed = discord.Embed(
        title="🎵 Now Playing",
        description=f"[{data.now_playing['title']}]({data.now_playing['webpage_url']})",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=data.now_playing['thumbnail'])
    embed.add_field(name="Duration", value=format_duration(data.now_playing['duration']))
    
    requester_member = ctx.guild.get_member(data.now_playing['requester']) if isinstance(data.now_playing['requester'], int) else None
    requester_mention = requester_member.mention if requester_member else str(data.now_playing['requester'])
    embed.add_field(name="Requested by", value=requester_mention)
    
    if data.queue:
        next_song = data.queue[0]
        embed.add_field(
            name="Next Song", 
            value=f"[{next_song['title']}]({next_song['webpage_url']})", 
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name="shuffle")
@command_error_handler
async def shuffle(ctx):
    """Shuffle the queue"""
    await send_info(ctx, "Shuffling the queue...")
    data = get_guild_data(ctx.guild.id)
    
    if len(data.queue) < 2:
        await send_error(ctx, "Not enough songs in queue to shuffle!")
        return
    
    queue_list = list(data.queue)
    random.shuffle(queue_list)
    data.queue = deque(queue_list)
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    await send_success(ctx, "Queue shuffled!")

@bot.command(name="remove")
@command_error_handler
async def remove(ctx, index: int):
    """Remove a song from the queue by position"""
    await send_info(ctx, f"Removing song at position {index} from the queue...")
    data = get_guild_data(ctx.guild.id)
    
    if index < 1 or index > len(data.queue):
        await send_error(ctx, f"Invalid position! Queue has {len(data.queue)} items.")
        return
    
    queue_list = list(data.queue)
    removed = queue_list.pop(index - 1)
    data.queue = deque(queue_list)
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    embed = discord.Embed(
        title="🗑️ Removed from Queue",
        description=f"[{removed['title']}]({removed['webpage_url']})",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed)

# New commands for the requested features

@bot.command(name="history")
@command_error_handler
async def history(ctx, page: int = 1):
    """Show recently played tracks"""
    await send_info(ctx, "Fetching recently played tracks...")
    async with aiosqlite.connect('musicbot.db') as db:
        cursor = await db.execute("SELECT track_data FROM track_history WHERE guild_id = ? ORDER BY played_at DESC LIMIT 10 OFFSET ?", (ctx.guild.id, (page-1)*10))
        rows = await cursor.fetchall()
    if not rows:
        await send_info(ctx, "No track history available!")
        return
    embed = discord.Embed(title="🎶 Recently Played", color=discord.Color.purple())
    for i, row in enumerate(rows, start=1):
        track = json.loads(row[0])
        requester = ctx.guild.get_member(track['requester'])
        requester_mention = requester.mention if requester else str(track['requester'])
        embed.add_field(
            name=f"{i}. {track['title']}",
            value=f"[Link]({track['webpage_url']}) | Requested by {requester_mention}",
            inline=False
        )
    embed.set_footer(text=f"Page {page}")
    await ctx.send(embed=embed)

@bot.command(name="replay")
@command_error_handler
async def replay(ctx, index: int = 1):
    """Replay a song from history"""
    await send_info(ctx, f"Replaying song number {index} from history...")
    async with aiosqlite.connect('musicbot.db') as db:
        cursor = await db.execute("SELECT track_data FROM track_history WHERE guild_id = ? ORDER BY played_at DESC LIMIT 1 OFFSET ?", (ctx.guild.id, index-1))
        row = await cursor.fetchone()
    if not row:
        await send_error(ctx, "No track found at that position in history!")
        return
    track = json.loads(row[0])
    track['requester'] = ctx.author.id
    data = get_guild_data(ctx.guild.id)
    data.queue.append(track)
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    voice_client = ctx.guild.voice_client
    if not voice_client or not voice_client.is_playing():
        await play_next(ctx.guild, ctx)
    embed = discord.Embed(
        title="✅ Added to Queue",
        description=f"[{track['title']}]({track['webpage_url']})",
        color=discord.Color.green()
    )
    embed.set_thumbnail(url=track['thumbnail'])
    embed.add_field(name="Position in queue", value=f"{len(data.queue)}")
    await ctx.send(embed=embed)

@bot.command(name="move")
@command_error_handler
async def move(ctx, from_pos: int, to_pos: int):
    """Move a song in the queue"""
    data = get_guild_data(ctx.guild.id)
    
    if from_pos < 1 or from_pos > len(data.queue):
        await send_error(ctx, f"Invalid 'from' position! Queue has {len(data.queue)} items.")
        return
    
    if to_pos < 1 or to_pos > len(data.queue):
        await send_error(ctx, f"Invalid 'to' position! Queue has {len(data.queue)} items.")
        return
    
    if from_pos == to_pos:
        await send_info(ctx, "Song is already at that position!")
        return
    
    queue_list = list(data.queue)
    track = queue_list.pop(from_pos - 1)
    queue_list.insert(to_pos - 1, track)
    data.queue = deque(queue_list)
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    await send_success(ctx, f"Moved track from position {from_pos} to {to_pos}!")

@bot.command(name="exportqueue")
@command_error_handler
async def export_queue(ctx):
    """Export the current queue to a file"""
    await send_info(ctx, "Exporting the current queue...")
    data = get_guild_data(ctx.guild.id)
    
    if not data.queue:
        await send_error(ctx, "The queue is empty!")
        return
    
    queue_data = {
        'guild_id': ctx.guild.id,
        'exported_by': str(ctx.author),
        'exported_at': str(datetime.now()),
        'tracks': data.to_serializable()
    }
    
    with open(f'queue_export_{ctx.guild.id}.json', 'w') as f:
        json.dump(queue_data, f, indent=2)
    
    await ctx.send(file=discord.File(f'queue_export_{ctx.guild.id}.json'))

@bot.command(name="importqueue")
@command_error_handler
async def import_queue(ctx):
    """Import a queue from a file"""
    await send_info(ctx, "Importing a queue from file...")
    if not ctx.message.attachments:
        await send_error(ctx, "Please attach a queue export file!")
        return
    
    attachment = ctx.message.attachments[0]
    if not attachment.filename.endswith('.json'):
        await send_error(ctx, "Please upload a JSON file!")
        return
    
    try:
        file_content = await attachment.read()
        queue_data = json.loads(file_content)
    except Exception as e:
        await send_error(ctx, f"Error reading file: {str(e)}")
        return
    
    data = get_guild_data(ctx.guild.id)
    data.queue = deque(queue_data['tracks'])
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    voice_client = ctx.guild.voice_client
    if not voice_client or not voice_client.is_playing():
        await play_next(ctx.guild, ctx)
    
    await send_success(ctx, f"Imported {len(data.queue)} tracks to the queue!")

@bot.command(name="playlists")
@command_error_handler
async def list_playlists(ctx):
    """List all saved playlists"""
    async with aiosqlite.connect('musicbot.db') as db:
        cursor = await db.execute("SELECT id, name, is_public FROM playlists WHERE guild_id = ? OR is_public = 1 ORDER BY name", (ctx.guild.id,))
        playlists = await cursor.fetchall()
        
    if not playlists:
        await send_info(ctx, "No playlists found!")
        return
    
    embed = discord.Embed(title="📋 Saved Playlists", color=discord.Color.green())
    
    for playlist in playlists:
        embed.add_field(
            name=f"{'🔒' if not playlist[2] else '🔓'} {playlist[1]}",
            value=f"ID: {playlist[0]}",
            inline=True
        )
    
    embed.set_footer(text="Use !loadplaylist <id> to load a playlist")
    await ctx.send(embed=embed)

@bot.command(name="loadplaylist")
@command_error_handler
async def load_playlist(ctx, playlist_id: int):
    """Load a saved playlist"""
    await send_info(ctx, f"Loading playlist with ID {playlist_id}...")
    async with aiosqlite.connect('musicbot.db') as db:
        cursor = await db.execute("SELECT name, tracks FROM playlists WHERE id = ? AND (guild_id = ? OR is_public = 1)", 
                               (playlist_id, ctx.guild.id))
        playlist = await cursor.fetchone()
        
    if not playlist:
        await send_error(ctx, "Playlist not found or you don't have permission to access it!")
        return
    
    data = get_guild_data(ctx.guild.id)
    tracks = json.loads(playlist[1])
    
    for track in tracks:
        # Convert requester string back to Member object if possible
        if isinstance(track['requester'], str):
            try:
                user_id = int(track['requester'])
                track['requester'] = ctx.guild.get_member(user_id) or ctx.author
            except:
                track['requester'] = ctx.author
        data.queue.append(track)
    
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    voice_client = ctx.guild.voice_client
    if not voice_client or not voice_client.is_playing():
        await play_next(ctx.guild, ctx)
    
    await send_success(ctx, f"Loaded playlist '{playlist[0]}' with {len(tracks)} tracks!")

@bot.command(name="deleteplaylist")
@command_error_handler
async def delete_playlist(ctx, playlist_id: int):
    """Delete a saved playlist"""
    await send_info(ctx, f"Deleting playlist with ID {playlist_id}...")
    async with aiosqlite.connect('musicbot.db') as db:
        # Check if playlist exists and belongs to the user
        cursor = await db.execute("SELECT name FROM playlists WHERE id = ? AND guild_id = ? AND user_id = ?", 
                               (playlist_id, ctx.guild.id, ctx.author.id))
        playlist = await cursor.fetchone()
        
        if not playlist:
            await send_error(ctx, "Playlist not found or you don't have permission to delete it!")
            return
        
        await db.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        await db.commit()
    
    await send_success(ctx, f"Deleted playlist '{playlist[0]}'!")

@bot.command(name="shareplaylist")
@command_error_handler
async def share_playlist(ctx, playlist_id: int, public: bool = True):
    """Set playlist sharing status"""
    await send_info(ctx, f"Setting sharing status for playlist ID {playlist_id}...")
    async with aiosqlite.connect('musicbot.db') as db:
        # Check if playlist exists and belongs to the user
        cursor = await db.execute("SELECT name FROM playlists WHERE id = ? AND guild_id = ? AND user_id = ?", 
                               (playlist_id, ctx.guild.id, ctx.author.id))
        playlist = await cursor.fetchone()
        
        if not playlist:
            await send_error(ctx, "Playlist not found or you don't have permission to modify it!")
            return
        
        await db.execute("UPDATE playlists SET is_public = ? WHERE id = ?", (int(public), playlist_id))
        await db.commit()
    
    await send_success(ctx, f"Playlist '{playlist[0]}' is now {'public' if public else 'private'}!")

@bot.command(name="247")
@command_error_handler
async def toggle_247(ctx):
    """Toggle 24/7 mode (bot stays in voice channel indefinitely)"""
    await send_info(ctx, "Toggling 24/7 mode...")
    data = get_guild_data(ctx.guild.id)
    data.stay_24_7 = not data.stay_24_7
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    # Save to database
    try:
        async with aiosqlite.connect('musicbot.db') as db:
            await db.execute("INSERT OR REPLACE INTO guild_settings (guild_id, stay_24_7) VALUES (?, ?)", 
                           (ctx.guild.id, int(data.stay_24_7)))
            await db.commit()
        await send_success(ctx, f"24/7 mode is now {'enabled' if data.stay_24_7 else 'disabled'}!")
    except Exception as e:
        await handle_db_error(ctx, e)
        return

@bot.command(name="autodisconnect")
@command_error_handler
async def toggle_auto_disconnect(ctx):
    """Toggle auto-disconnect when channel is empty"""
    await send_info(ctx, "Toggling auto-disconnect setting...")
    data = get_guild_data(ctx.guild.id)
    data.auto_disconnect = not data.auto_disconnect
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    # Save to database
    try:
        async with aiosqlite.connect('musicbot.db') as db:
            await db.execute("INSERT OR REPLACE INTO guild_settings (guild_id, auto_disconnect) VALUES (?, ?)", 
                           (ctx.guild.id, int(data.auto_disconnect)))
            await db.commit()
        await send_success(ctx, f"Auto-disconnect is now {'enabled' if data.auto_disconnect else 'disabled'}!")
    except Exception as e:
        await handle_db_error(ctx, e)
        return

@bot.command(name="filter")
@command_error_handler
async def set_filter(ctx, filter_name: str = None):
    """Set an audio filter (bassboost, nightcore, vaporwave, 8d, clear)"""
    await send_info(ctx, f"Setting audio filter to '{filter_name}'..." if filter_name else "Clearing audio filter...")
    if filter_name and filter_name.lower() not in AUDIO_FILTERS:
        await send_error(ctx, f"Invalid filter! Available filters: {', '.join(AUDIO_FILTERS.keys())}")
        return
    
    data = get_guild_data(ctx.guild.id)
    data.audio_filter = AUDIO_FILTERS.get(filter_name.lower() if filter_name else None)
    data.last_interaction = datetime.now()
    data.last_activity = datetime.now()
    
    # Save to database
    async with aiosqlite.connect('musicbot.db') as db:
        await db.execute("INSERT OR REPLACE INTO guild_settings (guild_id, audio_filter) VALUES (?, ?)", 
                       (ctx.guild.id, filter_name.lower() if filter_name else None))
        await db.commit()
    
    # If a song is currently playing, restart it with the new filter
    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_playing():
        # Save current position if possible (not implemented, so just restart)
        voice_client.stop()
        await send_info(ctx, "Restarting current song with new filter...")
        await play_next(ctx.guild, ctx)
    
    if filter_name:
        await send_success(ctx, f"Audio filter set to '{filter_name}'!")
    else:
        await send_success(ctx, "Audio filter cleared!")

@bot.command(name="lyrics")
@command_error_handler
async def get_lyrics(ctx, query: str = None):
    """Get lyrics for the current song or a specific query"""
    await send_info(ctx, f"🎤 Searching for lyrics{' for ' + query if query else ''}...")
    if not GENIUS_TOKEN:
        await send_error(ctx, "Lyrics feature is not configured!")
        return

    genius = lyricsgenius.Genius(GENIUS_TOKEN)
    genius.verbose = False
    genius.remove_section_headers = True

    data = get_guild_data(ctx.guild.id)

    # If no query provided, use the last !play query if available
    if not query:
        if hasattr(data, 'last_played_query') and data.last_played_query:
            query = data.last_played_query
        elif hasattr(data, 'last_played_title') and data.last_played_title:
            query = data.last_played_title
        elif data.now_playing:
            query = data.now_playing['title']
        elif data.queue:
            query = data.queue[-1]['title']
        else:
            await send_error(ctx, "Please provide a song name or play a song first!")
            return

    try:
        song = await asyncio.get_event_loop().run_in_executor(None, lambda: genius.search_song(query))
        if not song:
            await send_error(ctx, "No lyrics found!")
            return
        # Split lyrics into chunks of 1024 for embed fields, and 2000 for normal messages
        lyrics = song.lyrics
        embed_lyrics_chunks = [lyrics[i:i+1024] for i in range(0, len(lyrics), 1024)]
        text_lyrics_chunks = [lyrics[i:i+2000] for i in range(0, len(lyrics), 2000)]
        # Create the embed with as many fields as possible (max 5 fields for Discord embeds)
        embed = discord.Embed(
            title=f"🎤 Lyrics for '{song.title}'",
            description=f"by {song.artist}",
            color=discord.Color.purple()
        )
        # Use the song's cover art from Genius if available
        if song.song_art_image_url:
            embed.set_thumbnail(url=song.song_art_image_url)
        for idx, chunk in enumerate(embed_lyrics_chunks[:5]):
            embed.add_field(name=f"Lyrics (part {idx+1})" if len(embed_lyrics_chunks) > 1 else "Lyrics", value=chunk, inline=False)
        embed.set_footer(text="Powered by Genius | Use !lyrics <query> for other songs")
        await ctx.send(embed=embed)
        # If there are more lyrics, send the rest as normal messages
        if len(embed_lyrics_chunks) > 5:
            for chunk in text_lyrics_chunks[5:]:
                await ctx.send(chunk)
    except Exception as e:
        await send_error(ctx, f"Error fetching lyrics: {str(e)}")

@bot.command(name="recommend")
@command_error_handler
async def recommend(ctx, count: int = 3):
    """Get song recommendations based on current queue"""
    await send_info(ctx, "Recommending songs based on your queue...")
    data = get_guild_data(ctx.guild.id)
    
    if not data.now_playing and not data.queue:
        await send_error(ctx, "No songs in queue to base recommendations on!")
        return
    
    # Get a list of artists from current queue
    artists = set()
    if data.now_playing:
        artists.add(data.now_playing['uploader'])
    for track in data.queue:
        artists.add(track['uploader'])
    
    if not artists:
        await send_error(ctx, "Couldn't determine artists for recommendations!")
        return
    
    # Search for related tracks (simplified - in a real bot you'd use an API)
    related_tracks = []
    for artist in list(artists)[:3]:  # Limit to 3 artists to avoid too many requests
        try:
            search_results = await YTDLSource.search(f"{artist} related", limit=count)
            related_tracks.extend(search_results)
        except Exception as e:
            print(f"Error searching for related tracks: {e}")
    
    if not related_tracks:
        await send_error(ctx, "Couldn't find any recommendations!")
        return
    
    embed = discord.Embed(title="🎧 Recommended Tracks", color=discord.Color.purple())
    
    for i, track in enumerate(related_tracks[:count], start=1):
        embed.add_field(
            name=f"{i}. {track['title']}",
            value=f"by {track['uploader']}",
            inline=False
        )
    
    embed.set_footer(text="Use !play <title> to add a recommendation to the queue")
    await ctx.send(embed=embed)

@bot.command(name="help")
@command_error_handler
async def help_command(ctx):
    """Show this help message"""
    await send_info(ctx, "Showing help menu...")
    embed = discord.Embed(
        title="🎵 Pancake Music Bot",
        description="**Professional Discord Music Bot with High-Quality Playback**\n\nUse the commands below to control your music experience:",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url="https://i.imgur.com/ufxvZ0j.gif")

    # Only include commands that actually exist in the code
    playback_commands = [
        ("!play <query>", "Stream music from YouTube by name or URL. Supports playlists."),
        ("!pause", "Temporarily pause the current playback."),
        ("!resume", "Continue playing the paused track."),
        ("!skip", "Move to the next song in your queue."),
        ("!stop", "End playback and clear your current queue."),
        ("!leave", "Disconnect the bot from your voice channel.")
    ]
    queue_commands = [
        ("!queue [page]", "View your current music queue with pagination."),
        ("!nowplaying", "Show detailed information about the current track."),
        ("!shuffle", "Randomize the order of tracks in your queue."),
        ("!loop", "Toggle repeat mode for continuous playback."),
        ("!remove <position>", "Remove a specific track from your queue by position."),
        ("!move <from> <to>", "Move a track to a different position in the queue."),
        ("!searchqueue <query>", "Find specific songs within your current queue.")
    ]
    history_commands = [
        ("!history [page]", "View recently played tracks."),
        ("!replay [index]", "Replay a song from history.")
    ]
    playlist_commands = [
        ("!saveplaylist <name>", "Save your current queue as a named playlist."),
        ("!playlists", "List all saved playlists."),
        ("!loadplaylist <id>", "Load a saved playlist into the queue."),
        ("!deleteplaylist <id>", "Delete a saved playlist."),
        ("!shareplaylist <id> <public>", "Set playlist sharing status."),
        ("!exportqueue", "Export the current queue to a file."),
        ("!importqueue", "Import a queue from a file.")
    ]
    settings_commands = [
        ("!volume [0-100]", "Adjust or view the current playback volume level."),
        ("!quality <high/medium/low>", "Set your preferred audio streaming quality."),
        ("!filter <name>", "Apply audio effects (bassboost, nightcore, vaporwave, 8d, clear)."),
        ("!247", "Toggle 24/7 mode (bot stays in voice channel indefinitely)."),
        ("!autodisconnect", "Toggle auto-disconnect when channel is empty."),
        ("!autoplay", "Toggle Smart Autoplay/Auto-DJ Mode (auto-queue related tracks)."),
    ]
    fun_commands = [
        ("!lyrics [query]", "Get lyrics for the current song or a specific query."),
        ("!recommend [count]", "Get song recommendations based on current queue.")
    ]

    embed.add_field(
        name="🎮 Playback Controls",
        value="\n".join([f"`{name}` • {value}" for name, value in playback_commands]),
        inline=False
    )
    embed.add_field(
        name="📋 Queue Management",
        value="\n".join([f"`{name}` • {value}" for name, value in queue_commands]),
        inline=False
    )
    embed.add_field(
        name="⏪ Track History",
        value="\n".join([f"`{name}` • {value}" for name, value in history_commands]),
        inline=False
    )
    embed.add_field(
        name="📂 Playlists",
        value="\n".join([f"`{name}` • {value}" for name, value in playlist_commands]),
        inline=False
    )
    embed.add_field(
        name="⚙️ Settings",
        value="\n".join([f"`{name}` • {value}" for name, value in settings_commands]),
        inline=False
    )
    embed.add_field(
        name="🎉 Fun & Utility",
        value="\n".join([f"`{name}` • {value}" for name, value in fun_commands]),
        inline=False
    )
    embed.add_field(
        name="🔍 Slash Commands",
        value="All commands are also available as slash commands.\nSimply use `/` instead of `!` (example: `/play` instead of `!play`).",
        inline=False
    )
    embed.add_field(
        name="💬 Need Help?",
        value="Contact the bot developer for support or to report issues.",
        inline=False
    )
    embed.set_footer(text="Pancake Music Bot v3.0 | Premium Audio Quality | Use !help or /help to see this menu again")
    
    await ctx.send(embed=embed)

# Playlist support
@bot.command(name="saveplaylist")
@command_error_handler
async def save_playlist(ctx, name: str):
    await send_info(ctx, f"Saving the current queue as playlist '{name}'...")
    data = get_guild_data(ctx.guild.id)
    if not data.queue:
        await send_error(ctx, "The queue is empty!")
        return
    async with aiosqlite.connect('musicbot.db') as db:
        cursor = await db.execute("SELECT id FROM playlists WHERE guild_id = ? AND user_id = ? AND name = ?", (ctx.guild.id, ctx.author.id, name))
        existing = await cursor.fetchone()
        if existing:
            await send_error(ctx, f"You already have a playlist named '{name}'!")
            return
        await db.execute("INSERT INTO playlists (guild_id, user_id, name, tracks) VALUES (?, ?, ?, ?)", (ctx.guild.id, ctx.author.id, name, json.dumps(data.to_serializable())))
        await db.commit()
    await send_success(ctx, f"Playlist '{name}' saved!")

# Audio quality selector
@bot.command(name="quality")
@command_error_handler
async def set_quality(ctx, level: str = 'high'):
    """Set audio quality (high, medium, low)"""
    await send_info(ctx, "Setting audio quality...")
    qualities = {
        'high': 'bestaudio/best',
        'medium': 'worstaudio/worst[filesize<20M]',
        'low': 'worstaudio/worst[filesize<10M]'
    }
    
    if level.lower() not in qualities:
        await send_error(ctx, f"Invalid quality! Available: {', '.join(qualities.keys())}")
        return
    
    # Save quality per-guild
    data = get_guild_data(ctx.guild.id)
    data.quality = level.lower()
    ytdl_format_options['format'] = qualities[level.lower()]
    # Save to DB
    async with aiosqlite.connect('musicbot.db') as db:
        await db.execute("INSERT OR REPLACE INTO guild_settings (guild_id, volume, loop, stay_timeout, stay_24_7, auto_disconnect, audio_filter) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ctx.guild.id, data.volume, int(data.loop), 300, int(data.stay_24_7), int(data.auto_disconnect), data.audio_filter))
        await db.commit()
    await send_success(ctx, f"Quality set to {level.lower()}! This will apply to the next song you play.")

# Background task to check empty voice channels
@tasks.loop(seconds=15)
async def check_voice_channels():
    for guild in bot.guilds:
        await check_empty_voice(guild)

# Status rotation setup
status_messages = [
    (discord.ActivityType.playing, "🎵 !help for commands"),
]

@tasks.loop(minutes=2)
async def rotate_status():
    current = status_messages[rotate_status.current_index]
    await bot.change_presence(activity=discord.Activity(type=current[0], name=current[1]))
    rotate_status.current_index = (rotate_status.current_index + 1) % len(status_messages)
rotate_status.current_index = 0

@bot.event
async def on_ready():
    print("╔════════════════════════════════════════╗")
    print("║          Pancake Music Bot 3.0         ║")
    print("╠════════════════════════════════════════╣")
    print(f"║ Logged in as: {bot.user.name:<24} ║")
    print("╠════════════════════════════════════════╣")
    print("║ Features:                              ║")
    print("║ ✓ High Quality Audio                   ║")
    print("║ ✓ Smart Queue Management               ║")
    print("║ ✓ Advanced Playlist System             ║")
    print("║ ✓ Lyrics Integration                   ║")
    print("║ ✓ Audio Filters & Effects              ║")
    print("║ ✓ Auto-DJ & Recommendations            ║")
    print("╚════════════════════════════════════════╝")

    # Start background tasks
    bot.loop.create_task(check_voice_channels())
    if not rotate_status.is_running():
        rotate_status.start()

    # Initialize database and load queues
    await load_queues()
    print("✓ Queues loaded from database")

    # Register slash commands
    await bot.tree.sync()
    print("✓ Slash commands synced")
    print("\n✨ Bot is ready to rock! ✨")

@bot.command(name="searchqueue")
@command_error_handler
async def search_queue(ctx, *, query: str):
    """Find specific songs within your current queue"""
    data = get_guild_data(ctx.guild.id)
    matches = [t for t in data.queue if query.lower() in t['title'].lower()]
    embed = discord.Embed(title=f"🔍 Queue Results for '{query}'", color=discord.Color.blue())
    for track in list(matches)[:5]:
        embed.add_field(name=track['title'], value=track['webpage_url'], inline=False)
    if not matches:
        embed.description = "No matches found."
    await ctx.send(embed=embed)

@bot.command(name="autoplay")
@command_error_handler
async def toggle_autoplay(ctx):
    """Toggle Smart Autoplay/Auto-DJ Mode (auto-queue related tracks)"""
    data = get_guild_data(ctx.guild.id)
    data.autoplay = not data.autoplay
    await send_success(ctx, f"Smart Autoplay is now {'enabled' if data.autoplay else 'disabled'}!")

bot.run(TOKEN)



