import os
import discord
import yt_dlp
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import sys

# Load environment variables
load_dotenv()

# Bot setup
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Configuration
YOUTUBE_URL = os.getenv("YOUTUBE_URL")
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID"))
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# Simple YouTube options with anti-bot protection
YTDL_OPTIONS = {
    'format': 'bestaudio',
    'noplaylist': True,
    'quiet': True,
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'referer': 'https://www.youtube.com/',
    'extractor_args': {'youtube': {'player_client': ['android']}}
}

# Simple state tracking
voice_client = None
disconnect_timer = None

async def get_youtube_url():
    """Extract YouTube stream URL with simple retry"""
    for attempt in range(2):  # Only 2 attempts
        try:
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
                info = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: ydl.extract_info(YOUTUBE_URL, download=False)
                )
            return info.get('url')
        except Exception as e:
            print(f"YouTube extract attempt {attempt + 1} failed: {e}")
            if attempt == 0:  # Only wait between attempts
                await asyncio.sleep(10)
    return None

async def play_music(vc):
    """Start playing music"""
    if vc.is_playing():
        return
    
    url = await get_youtube_url()
    if not url:
        print("❌ Could not get YouTube URL")
        return
    
    try:
        source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
        vc.play(source, after=lambda e: asyncio.create_task(restart_music(vc)) if not e else print(f"Player error: {e}"))
        print("🎵 Music started")
    except Exception as e:
        print(f"❌ Play error: {e}")

async def restart_music(vc):
    """Restart music when it ends"""
    await asyncio.sleep(2)  # Brief pause
    if vc and vc.is_connected() and not vc.is_playing():
        await play_music(vc)

async def schedule_disconnect():
    """Disconnect after 10 minutes"""
    global voice_client, disconnect_timer
    await asyncio.sleep(600)  # 10 minutes
    
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        print("🔇 Auto-disconnected after 10 minutes")
    voice_client = None
    disconnect_timer = None

@bot.event
async def on_ready():
    print(f'🤖 {bot.user} ready - Python {sys.version[:5]}')

@bot.event
async def on_voice_state_update(member, before, after):
    global voice_client, disconnect_timer
    
    if member.bot:
        return
    
    target_channel = bot.get_channel(VOICE_CHANNEL_ID)
    if not target_channel:
        return
    
    # User joined target channel
    if after.channel and after.channel.id == VOICE_CHANNEL_ID and (not before.channel or before.channel.id != VOICE_CHANNEL_ID):
        print(f"👤 {member.name} joined")
        
        # Send breathing guide
        embed = discord.Embed(
            title="🌬️ BREATHING BRIDGE ACTIVATED",
            description="INHALE 4s → HOLD 7s → EXHALE 8s",
            color=0x00ff88
        )
        if os.getenv("GIF_URL"):
            embed.set_image(url=os.getenv("GIF_URL"))
        
        try:
            await target_channel.send(embed=embed)
        except:
            pass  # Ignore permission errors
        
        # Connect to voice if not already connected
        if not voice_client or not voice_client.is_connected():
            try:
                # Disconnect existing connection first
                if voice_client:
                    await voice_client.disconnect()
                
                voice_client = await target_channel.connect()
                await play_music(voice_client)
                print(f"✅ Connected to {target_channel.name}")
            except Exception as e:
                print(f"❌ Connection failed: {e}")
                return
        
        # Reset disconnect timer
        if disconnect_timer:
            disconnect_timer.cancel()
        disconnect_timer = asyncio.create_task(schedule_disconnect())
    
    # User left target channel
    elif before.channel and before.channel.id == VOICE_CHANNEL_ID and (not after.channel or after.channel.id != VOICE_CHANNEL_ID):
        print(f"👋 {member.name} left")
        
        # Check if channel is empty of humans
        human_members = [m for m in target_channel.members if not m.bot]
        if not human_members and voice_client and voice_client.is_connected():
            if disconnect_timer:
                disconnect_timer.cancel()
            await voice_client.disconnect()
            voice_client = None
            disconnect_timer = None
            print("🏃 Disconnected - channel empty")

@bot.command()
async def status(ctx):
    """Check bot status"""
    if voice_client and voice_client.is_connected():
        playing = "🎵 Yes" if voice_client.is_playing() else "🔇 No"
        await ctx.send(f"Connected to {voice_client.channel.name} | Playing: {playing}")
    else:
        await ctx.send("Not connected to voice")

@bot.command()
async def stop(ctx):
    """Stop music"""
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send("🔇 Stopped")
    else:
        await ctx.send("Nothing playing")

# Run bot
if __name__ == "__main__":
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("❌ BOT_TOKEN not found!")
        sys.exit(1)
    
    bot.run(token)