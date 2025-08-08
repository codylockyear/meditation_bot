import os
import discord
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

# -------------------------------------------------------------
# CONFIGURATION – EDIT THESE TWO VALUES
# -------------------------------------------------------------
LOCAL_MP3_PATH = "/opt/render/project/src/assets/meditation music.mp3"
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID"))
# -------------------------------------------------------------

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# Global state
voice_client = None
disconnect_timer = None


# -------------------------------------------------------------
# Robust voice connect helper (inserted between globals & play_music)
# -------------------------------------------------------------
async def connect_voice(channel: discord.VoiceChannel):
    for attempt in range(1, 6):
        try:
            return await channel.connect(timeout=15, reconnect=False)
        except discord.ConnectionClosed as e:
            print(f"[voice] {attempt}/5  4006 hit — {e}")
            if attempt == 5:
                raise
            await asyncio.sleep(5 * attempt)


# -------------------------------------------------------------
# Music helpers
# -------------------------------------------------------------
async def play_music(vc: discord.VoiceClient):
    """Start playing the local MP3."""
    if vc.is_playing():
        return

    if not os.path.isfile(LOCAL_MP3_PATH):
        print(f"❌ MP3 file not found: {LOCAL_MP3_PATH}")
        return

    try:
        source = discord.FFmpegPCMAudio(LOCAL_MP3_PATH, **FFMPEG_OPTIONS)
        vc.play(source, after=lambda e: asyncio.create_task(restart_music(vc)) if not e else print(f"Player error: {e}"))
        print("🎵 MP3 started")
    except Exception as e:
        print(f"❌ Play error: {e}")


async def restart_music(vc: discord.VoiceClient):
    """Restart track on finish."""
    await asyncio.sleep(2)
    if vc and vc.is_connected() and not vc.is_playing():
        await play_music(vc)


async def schedule_disconnect():
    """Auto-disconnect after 10 minutes of inactivity."""
    global voice_client, disconnect_timer
    await asyncio.sleep(600)
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        print("🔇 Auto-disconnected after 10 minutes")
    voice_client = None
    disconnect_timer = None


# -------------------------------------------------------------
# Discord events
# -------------------------------------------------------------
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

    # Someone entered the target channel
    if after.channel and after.channel.id == VOICE_CHANNEL_ID and (not before.channel or before.channel.id != VOICE_CHANNEL_ID):
        print(f"👤 {member.name} joined")

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
            pass

        if not voice_client or not voice_client.is_connected():
            try:
                if voice_client:
                    await voice_client.disconnect()

                # --- replaced single .connect() with robust helper ---
                voice_client = await connect_voice(target_channel)
                await play_music(voice_client)
                print(f"✅ Connected to {target_channel.name}")
            except Exception as e:
                print(f"❌ Connection failed: {e}")
                return

        if disconnect_timer:
            disconnect_timer.cancel()
        disconnect_timer = asyncio.create_task(schedule_disconnect())

    # Someone left the target channel
    elif before.channel and before.channel.id == VOICE_CHANNEL_ID and (not after.channel or after.channel.id != VOICE_CHANNEL_ID):
        print(f"👋 {member.name} left")

        human_members = [m for m in target_channel.members if not m.bot]
        if not human_members and voice_client and voice_client.is_connected():
            if disconnect_timer:
                disconnect_timer.cancel()
            await voice_client.disconnect()
            voice_client = None
            disconnect_timer = None
            print("🏃 Disconnected – channel empty")


# -------------------------------------------------------------
# Text commands
# -------------------------------------------------------------
@bot.command()
async def status(ctx):
    """Check bot status."""
    if voice_client and voice_client.is_connected():
        playing = "🎵 Yes" if voice_client.is_playing() else "🔇 No"
        await ctx.send(f"Connected to {voice_client.channel.name} | Playing: {playing}")
    else:
        await ctx.send("Not connected to voice")


@bot.command()
async def stop(ctx):
    """Stop the MP3."""
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send("🔇 Stopped")
    else:
        await ctx.send("Nothing playing")


# -------------------------------------------------------------
# Run the bot
# -------------------------------------------------------------
if __name__ == "__main__":
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("❌ BOT_TOKEN not found!")
        sys.exit(1)

    if not os.path.isfile(LOCAL_MP3_PATH):
        print("⚠️  WARNING: LOCAL_MP3_PATH does not point to a valid file!")
        print("   Please edit LOCAL_MP3_PATH in this file before running the bot.")

    bot.run(token)