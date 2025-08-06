import os
import discord
import yt_dlp as youtube_dl
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import functools
import sys

# Load environment variables
load_dotenv()

# Alternative: Try loading with absolute path if the above fails
if not os.getenv("BOT_TOKEN"):
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
    load_dotenv(env_path)
    print(f"🔄 Attempted to load .env from: {env_path}")

print(f"🐍 Running on Python {sys.version}")

# Bot setup
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# Python 3.13 compatibility: Use more conservative event loop handling
try:
    bot = commands.Bot(command_prefix='!', intents=intents)
except Exception as e:
    print(f"❌ Bot initialization error: {e}")
    sys.exit(1)

# YouTube stream settings
YOUTUBE_URL = os.getenv("YOUTUBE_URL")
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 
    'options': '-vn -loglevel error'  # Reduced logging
}
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'logtostderr': False,
    'ignoreerrors': False,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'quiet': True,
    'no_warnings': True
}

# Global voice client and disconnection task reference
voice_client = None
voice_state_lock = asyncio.Lock()
disconnection_timer_task = None
stream_restart_task = None

def sync_restart_stream(vc, error=None):
    """Synchronous wrapper for the async restart function - Python 3.13 compatible"""
    if error:
        print(f"🎵 Player error: {error}")
    else:
        print("🎵 Player finished normally")
    
    # Python 3.13 compatible task creation
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(restart_stream(vc))
    except RuntimeError:
        # Fallback for edge cases
        try:
            asyncio.create_task(restart_stream(vc))
        except Exception as e:
            print(f"❌ Error creating restart task: {e}")

async def start_music_stream(vc):
    """Start the 24/7 music stream using the provided voice client"""
    global stream_restart_task
    
    try:
        print("🎵 Starting music stream...")
        
        # Multiple connection checks
        if not vc:
            print("❌ Voice client is None")
            return
            
        if not vc.is_connected():
            print("❌ Voice client not connected, cannot start stream")
            return
            
        # Additional check - verify we can access channel
        try:
            channel_name = vc.channel.name if vc.channel else "Unknown"
            print(f"🔗 Connected to channel: {channel_name}")
        except:
            print("❌ Voice client channel access failed")
            return
            
        if vc.is_playing():
            print("🎵 Music is already playing")
            return
            
        # Extract YouTube URL info with better error handling
        print("🔍 Extracting YouTube stream info...")
        try:
            with youtube_dl.YoutubeDL(YTDL_OPTIONS) as ydl:
                info = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: ydl.extract_info(YOUTUBE_URL, download=False)
                )
        except Exception as extract_error:
            print(f"❌ YouTube info extraction failed: {extract_error}")
            # Schedule retry after delay
            await asyncio.sleep(15)
            if vc and vc.is_connected() and not vc.is_playing():
                print("🔄 Retrying music stream after extraction error...")
                await start_music_stream(vc)
            return
        
        if 'url' not in info:
            print("❌ Could not extract stream URL from YouTube")
            return
            
        url = info['url']
        title = info.get('title', 'Unknown')
        print(f"🎵 Found stream: {title}")
        
        # Create audio source with better error handling
        try:
            audio_source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
        except Exception as audio_error:
            print(f"❌ Audio source creation failed: {audio_error}")
            return
        
        # Final connection check before playing
        if not vc.is_connected():
            print("❌ Connection lost before playing audio")
            return
        
        # Play with callback for restart - Using functools.partial for compatibility
        restart_callback = functools.partial(sync_restart_stream, vc)
        vc.play(audio_source, after=restart_callback)
        print("🎵 Music stream started successfully")
        
    except Exception as e:
        print(f"❌ Stream error: {e}")
        # Schedule retry after delay
        await asyncio.sleep(5)
        if vc and vc.is_connected() and not vc.is_playing():
            print("🔄 Retrying music stream after error...")
            await start_music_stream(vc)

async def restart_stream(vc):
    """Async function to restart the stream when it ends or errors"""
    global stream_restart_task
    
    try:
        print("🔄 Stream ended, attempting to restart...")
        
        # Cancel any existing restart task to prevent overlapping
        if stream_restart_task and not stream_restart_task.done():
            stream_restart_task.cancel()
            try:
                await stream_restart_task
            except asyncio.CancelledError:
                pass
            
        # Short delay before attempting restart
        await asyncio.sleep(2)
        
        if vc and vc.is_connected():
            if not vc.is_playing():
                await start_music_stream(vc)
            else:
                print("🎵 Stream already playing, no restart needed")
        else:
            print("❌ Voice client not connected, cannot restart stream")
            
    except Exception as e:
        print(f"❌ Error during stream restart: {e}")
        # Try one more time after a longer delay
        await asyncio.sleep(5)
        if vc and vc.is_connected() and not vc.is_playing():
            try:
                await start_music_stream(vc)
            except Exception as retry_error:
                print(f"❌ Stream restart retry failed: {retry_error}")

async def schedule_disconnection():
    """Schedules the bot to disconnect after 10 minutes."""
    global voice_client, disconnection_timer_task, stream_restart_task
    
    try:
        await asyncio.sleep(600)  # 10 minutes
    except asyncio.CancelledError:
        print("⏰ Disconnection timer cancelled")
        return
    
    async with voice_state_lock:
        if voice_client and voice_client.is_connected():
            try:
                # Stop any ongoing stream restart tasks
                if stream_restart_task and not stream_restart_task.done():
                    stream_restart_task.cancel()
                    try:
                        await stream_restart_task
                    except asyncio.CancelledError:
                        pass
                    
                # Stop the music if playing
                if voice_client.is_playing():
                    voice_client.stop()
                    
                await voice_client.disconnect()
                print("🔇 Bot disconnected after 10 minutes of user presence")
            except Exception as e:
                print(f"❌ Error during scheduled disconnection: {e}")
            finally:
                voice_client = None
        disconnection_timer_task = None

async def complete_voice_cleanup():
    """Complete cleanup of all voice connections and internal state"""
    global voice_client, disconnection_timer_task, stream_restart_task
    
    print("🧹 Starting complete voice cleanup...")
    
    # Cancel all tasks with proper awaiting
    if disconnection_timer_task and not disconnection_timer_task.done():
        disconnection_timer_task.cancel()
        try:
            await disconnection_timer_task
        except asyncio.CancelledError:
            pass
        disconnection_timer_task = None
        
    if stream_restart_task and not stream_restart_task.done():
        stream_restart_task.cancel()
        try:
            await stream_restart_task
        except asyncio.CancelledError:
            pass
        stream_restart_task = None
    
    # Cleanup current voice client
    if voice_client:
        try:
            if voice_client.is_playing():
                voice_client.stop()
            if voice_client.is_connected():
                await voice_client.disconnect(force=True)
            voice_client.cleanup()
        except Exception as e:
            print(f"❌ Error cleaning up main voice client: {e}")
        finally:
            voice_client = None
    
    # Cleanup all voice clients in bot's state
    for vc in bot.voice_clients.copy():
        try:
            if vc.is_playing():
                vc.stop()
            if vc.is_connected():
                await vc.disconnect(force=True)
            vc.cleanup()
        except Exception as e:
            print(f"❌ Error cleaning up voice client: {e}")
    
    # Clear Discord.py internal voice client tracking
    try:
        if hasattr(bot._connection, '_voice_clients'):
            bot._connection._voice_clients.clear()
    except Exception as e:
        print(f"❌ Error clearing voice clients: {e}")
    
    # Wait for cleanup to complete
    await asyncio.sleep(2)
    print("🧹 Complete voice cleanup finished")

@bot.event
async def on_ready():
    print(f'🤖 Logged in as {bot.user}')
    print(f'📊 Bot is in {len(bot.guilds)} servers')
    print(f'🐍 Running on Python {sys.version}')
    print('🎯 Bot ready and waiting for users to join voice channels')

@bot.event
async def on_voice_state_update(member, before, after):
    global voice_client, disconnection_timer_task, voice_state_lock

    # Ignore bot's own voice state updates
    if member.bot:
        return

    voice_channel_id = int(os.getenv("VOICE_CHANNEL_ID"))
    target_voice_channel = bot.get_channel(voice_channel_id)

    if not target_voice_channel:
        print(f"❌ Target voice channel with ID {voice_channel_id} not found")
        return

    async with voice_state_lock:
        # Check if the user joined the target voice channel
        user_joined_target_channel = (
            after.channel and after.channel.id == voice_channel_id and 
            (before.channel is None or before.channel.id != voice_channel_id)
        )

        # Check if the user left the target voice channel
        user_left_target_channel = (
            before.channel and before.channel.id == voice_channel_id and 
            (after.channel is None or after.channel.id != voice_channel_id)
        )

        if user_joined_target_channel:
            print(f"👤 User {member.name} joined {target_voice_channel.name}")

            # Send breathing guide embed
            embed = discord.Embed(
                title="🌬️ BREATHING BRIDGE ACTIVATED",
                description="INHALE 4s → HOLD 7s → EXHALE 8s",
                color=0x00ff88
            )
            embed.set_image(url=os.getenv("GIF_URL"))
            
            try:
                await target_voice_channel.send(embed=embed)
                print(f"💬 Sent breathing guide to {target_voice_channel.name} chat")
            except discord.Forbidden:
                print(f"🚫 Couldn't send message to {target_voice_channel.name} chat (permissions issue)")
            except Exception as e:
                print(f"❌ Error sending breathing guide: {e}")

            # Complete cleanup before attempting new connection
            await complete_voice_cleanup()

            # Attempt connection with improved retry logic and shorter timeouts for Python 3.13
            max_retries = 3
            connection_successful = False
            
            for attempt in range(max_retries):
                try:
                    print(f"🔗 Connection attempt {attempt + 1}/{max_retries}...")
                    
                    if attempt > 0:
                        wait_time = 3 + (2 * attempt)  # Shorter wait times
                        print(f"⏳ Waiting {wait_time}s before retry...")
                        await asyncio.sleep(wait_time)
                    
                    # Try to connect with shorter timeout for Python 3.13 compatibility
                    try:
                        new_voice_client = await asyncio.wait_for(
                            target_voice_channel.connect(reconnect=False),
                            timeout=20.0  # Shorter timeout
                        )
                    except asyncio.TimeoutError:
                        print(f"⏰ Connection timeout on attempt {attempt + 1}")
                        continue
                    
                    # Verify connection
                    await asyncio.sleep(1)
                    
                    if new_voice_client and new_voice_client.is_connected():
                        voice_client = new_voice_client
                        print(f"✅ Bot successfully connected to {target_voice_channel.name} on attempt {attempt + 1}")
                        await start_music_stream(voice_client)
                        connection_successful = True
                        break
                    else:
                        print(f"❌ Connection verification failed on attempt {attempt + 1}")
                        if new_voice_client:
                            try:
                                await new_voice_client.disconnect(force=True)
                                new_voice_client.cleanup()
                            except:
                                pass
                        new_voice_client = None
                        
                except discord.ClientException as e:
                    print(f"❌ Discord client error on attempt {attempt + 1}: {e}")
                    await complete_voice_cleanup()
                    await asyncio.sleep(3)
                    
                except Exception as e:
                    print(f"❌ Unexpected connection error on attempt {attempt + 1}: {e}")
                    await asyncio.sleep(2)
                
            if not connection_successful:
                print("💥 All connection attempts failed. Bot will not join voice channel")
                voice_client = None
                return

            # Schedule disconnection timer only if we have a valid connection
            if voice_client and voice_client.is_connected():
                if disconnection_timer_task and not disconnection_timer_task.done():
                    disconnection_timer_task.cancel()
                    try:
                        await disconnection_timer_task
                    except asyncio.CancelledError:
                        pass
                    print("⏰ Cancelled previous disconnection timer")
                disconnection_timer_task = asyncio.create_task(schedule_disconnection())
                print("⏰ New disconnection timer scheduled for 10 minutes")

        elif user_left_target_channel:
            print(f"👋 User {member.name} left {target_voice_channel.name}")

            # Check if the channel is now empty of human users
            human_members_in_channel = [m for m in target_voice_channel.members if not m.bot]
            print(f"👥 Human members remaining: {len(human_members_in_channel)}")

            if voice_client and voice_client.is_connected() and not human_members_in_channel:
                print("🏃 Target voice channel is now empty of human users")
                if disconnection_timer_task and not disconnection_timer_task.done():
                    disconnection_timer_task.cancel()
                    try:
                        await disconnection_timer_task
                    except asyncio.CancelledError:
                        pass
                    print("⏰ Cancelled pending disconnection timer due to empty channel")
                
                try:
                    # Stop music and any restart tasks
                    if stream_restart_task and not stream_restart_task.done():
                        stream_restart_task.cancel()
                        try:
                            await stream_restart_task
                        except asyncio.CancelledError:
                            pass
                    if voice_client.is_playing():
                        voice_client.stop()
                    await voice_client.disconnect(force=True)
                    print("✅ Bot disconnected because voice channel is empty")
                except Exception as e:
                    print(f"❌ Error during disconnection when channel is empty: {e}")
                finally:
                    voice_client = None
                    disconnection_timer_task = None

@bot.command(name='force_cleanup')
async def force_cleanup_command(ctx):
    """Force cleanup all voice connections and reset state"""
    async with voice_state_lock:
        await complete_voice_cleanup()
    await ctx.send("🧹 Force cleanup completed. All voice connections reset.")

@bot.command(name='stop_music')
async def stop_music_command(ctx):
    """Manually stop the music"""
    global voice_client, stream_restart_task
    
    if voice_client and voice_client.is_connected():
        if stream_restart_task and not stream_restart_task.done():
            stream_restart_task.cancel()
        if voice_client.is_playing():
            voice_client.stop()
            await ctx.send("🔇 Music stopped")
        else:
            await ctx.send("🎵 No music is currently playing")
    else:
        await ctx.send("❌ Bot is not connected to a voice channel")

@bot.command(name='start_music')
async def start_music_command(ctx):
    """Manually start the music"""
    global voice_client
    
    if voice_client and voice_client.is_connected():
        if not voice_client.is_playing():
            await start_music_stream(voice_client)
            await ctx.send("🎵 Music started")
        else:
            await ctx.send("🎵 Music is already playing")
    else:
        await ctx.send("❌ Bot is not connected to a voice channel")

@bot.command(name='music_status')
async def music_status_command(ctx):
    """Check music and connection status"""
    global voice_client
    
    embed = discord.Embed(title="🎵 Music Status", color=0x00ff88)
    
    if voice_client and voice_client.is_connected():
        embed.add_field(name="Connected", value="✅ Yes", inline=True)
        embed.add_field(name="Channel", value=voice_client.channel.name, inline=True)
        embed.add_field(name="Playing", value="🎵 Yes" if voice_client.is_playing() else "🔇 No", inline=True)
    else:
        embed.add_field(name="Connected", value="❌ No", inline=True)
        embed.add_field(name="Channel", value="None", inline=True)
        embed.add_field(name="Playing", value="🔇 No", inline=True)
    
    await ctx.send(embed=embed)

# Error handling
@bot.event
async def on_error(event, *args, **kwargs):
    print(f"❌ Bot error in {event}: {args}")

# Run the bot with Python 3.13 compatibility
if __name__ == "__main__":
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("❌ ERROR: BOT_TOKEN not found in environment variables!")
        print("📁 Please check your .env file exists and contains:")
        print("   BOT_TOKEN=your_bot_token_here")
        sys.exit(1)
    
    print(f"🔑 Bot token loaded: {token[:20]}...")
    print(f"🐍 Starting bot on Python {sys.version}")
    
    try:
        bot.run(token)
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
        sys.exit(1)