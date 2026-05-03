"""
cogs/music.py - simple music playback with queue support.
"""

# Kept self-contained so music changes do not spill into the rest of the bot.
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from functools import partial

import discord
from discord.ext import commands
import yt_dlp

from config import COLOR_ERROR, COLOR_INFO, COLOR_SUCCESS

YTDL_FORMAT_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch1",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

MUSIC_FILTERS = {
    "off": {
        "label": "Off",
        "ffmpeg": None,
        "description": "Normal playback with no audio filter.",
    },
    "bassboost": {
        "label": "Bass Boost",
        "ffmpeg": "bass=g=10,equalizer=f=60:width_type=o:width=2:g=8",
        "description": "Adds heavier low-end bass.",
    },
    "chipmunk": {
        "label": "Chipmunk",
        "ffmpeg": "asetrate=48000*1.25,aresample=48000,atempo=1.05",
        "description": "Raises pitch and speed for a chipmunk sound.",
    },
    "nightcore": {
        "label": "Nightcore",
        "ffmpeg": "asetrate=48000*1.18,aresample=48000,atempo=1.08",
        "description": "Brighter, faster playback.",
    },
    "vaporwave": {
        "label": "Vaporwave",
        "ffmpeg": "asetrate=48000*0.82,aresample=48000,atempo=0.92",
        "description": "Lower, slower playback.",
    },
    "8d": {
        "label": "8D",
        "ffmpeg": "apulsator=hz=0.08",
        "description": "Slow left-right panning.",
    },
    "karaoke": {
        "label": "Karaoke",
        "ffmpeg": "stereotools=mlev=0.03",
        "description": "Reduces centered vocals where possible.",
    },
    "tremolo": {
        "label": "Tremolo",
        "ffmpeg": "tremolo=f=6:d=0.7",
        "description": "Adds a pulsing volume effect.",
    },
    "soft": {
        "label": "Soft",
        "ffmpeg": "lowpass=f=9000,acompressor",
        "description": "Smooths harsh highs and compresses peaks.",
    },
}

FILTER_ALIASES = {
    "none": "off",
    "clear": "off",
    "normal": "off",
    "bb": "bassboost",
    "bass": "bassboost",
    "boost": "bassboost",
    "chickmuck": "chipmunk",
    "chipmuck": "chipmunk",
    "chip": "chipmunk",
    "nc": "nightcore",
    "vapor": "vaporwave",
    "slowed": "vaporwave",
    "eightd": "8d",
    "8-d": "8d",
}

ytdl = yt_dlp.YoutubeDL(YTDL_FORMAT_OPTIONS)
log = logging.getLogger(__name__)


@dataclass
class Track:
    title: str
    webpage_url: str
    stream_url: str
    requester_id: int
    duration: int | None = None

    @property
    def duration_text(self) -> str:
        if not self.duration:
            return "Unknown"

        minutes, seconds = divmod(self.duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02}:{seconds:02}"
        return f"{minutes}:{seconds:02}"


class GuildMusicState:
    def __init__(self):
        self.queue: asyncio.Queue[Track] = asyncio.Queue()
        self.now_playing: Track | None = None
        self.player_task: asyncio.Task | None = None
        self.loop_enabled = False
        self.skip_requested = False
        self.restart_requested = False
        self.filter_name = "off"
        self.volume = 1.0


class MusicControlView(discord.ui.View):
    def __init__(self, cog: "Music", guild_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id

    async def get_voice(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                "These controls belong to another server.",
                ephemeral=True,
            )
            return None

        voice = interaction.guild.voice_client
        if not voice:
            await interaction.response.send_message(
                "I'm not connected to voice right now.",
                ephemeral=True,
            )
            return None

        return voice

    @discord.ui.button(label="Pause/Resume", style=discord.ButtonStyle.secondary)
    async def pause_resume(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        voice = await self.get_voice(interaction)
        if not voice:
            return

        if voice.is_paused():
            voice.resume()
            message = "Resumed playback."
        elif voice.is_playing():
            voice.pause()
            message = "Paused playback."
        else:
            message = "Nothing is playing right now."

        await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice = await self.get_voice(interaction)
        if not voice:
            return

        if not voice.is_playing() and not voice.is_paused():
            return await interaction.response.send_message(
                "Nothing is playing right now.",
                ephemeral=True,
            )

        state = self.cog.get_state(self.guild_id)
        state.skip_requested = True
        voice.stop()
        await interaction.response.send_message(
            "Skipped the current track.",
            ephemeral=True,
        )

    @discord.ui.button(label="Loop", style=discord.ButtonStyle.secondary)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_state(self.guild_id)
        state.loop_enabled = not state.loop_enabled
        await interaction.response.send_message(
            f"Loop is now {'on' if state.loop_enabled else 'off'}.",
            ephemeral=True,
        )

    @discord.ui.button(label="Shuffle", style=discord.ButtonStyle.secondary)
    async def shuffle(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        state = self.cog.get_state(self.guild_id)
        shuffled = self.cog.shuffle_queue(state)
        await interaction.response.send_message(
            f"Shuffled {shuffled} queued track(s).",
            ephemeral=True,
        )

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice = await self.get_voice(interaction)
        if not voice:
            return

        state = self.cog.get_state(self.guild_id)
        self.cog.clear_queue(state)
        state.now_playing = None
        state.loop_enabled = False
        state.skip_requested = True
        state.restart_requested = False
        if voice.is_playing() or voice.is_paused():
            voice.stop()
        await interaction.response.send_message(
            "Stopped playback and cleared the queue.",
            ephemeral=True,
        )


class Music(commands.Cog, name="Music"):
    """Voice playback commands."""

    def __init__(self, bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}

    def get_state(self, guild_id: int) -> GuildMusicState:
        state = self.states.get(guild_id)
        if state is None:
            state = GuildMusicState()
            self.states[guild_id] = state
        return state

    def make_ffmpeg_options(self, state: GuildMusicState) -> dict[str, str]:
        options = FFMPEG_OPTIONS.copy()
        filter_chain = MUSIC_FILTERS[state.filter_name]["ffmpeg"]
        if filter_chain:
            options["options"] = f'-vn -af "{filter_chain}"'
        return options

    def make_source(self, track: Track, state: GuildMusicState) -> discord.AudioSource:
        source = discord.FFmpegPCMAudio(
            track.stream_url,
            **self.make_ffmpeg_options(state),
        )
        return discord.PCMVolumeTransformer(source, volume=state.volume)

    def clear_queue(self, state: GuildMusicState) -> int:
        removed = 0
        while not state.queue.empty():
            try:
                state.queue.get_nowait()
                removed += 1
            except asyncio.QueueEmpty:
                break
        return removed

    def shuffle_queue(self, state: GuildMusicState) -> int:
        queued = list(state.queue._queue)
        random.shuffle(queued)
        state.queue._queue.clear()
        state.queue._queue.extend(queued)
        return len(queued)

    async def restart_current_track(
        self,
        ctx: commands.Context,
        description: str,
    ):
        voice = ctx.guild.voice_client
        state = self.get_state(ctx.guild.id)
        if state.now_playing and voice and (voice.is_playing() or voice.is_paused()):
            state.restart_requested = True
            voice.stop()

        await ctx.send(
            embed=discord.Embed(
                description=description,
                color=COLOR_SUCCESS,
            )
        )

    async def set_filter(self, ctx: commands.Context, name: str | None):
        state = self.get_state(ctx.guild.id)
        if name is None:
            current = MUSIC_FILTERS[state.filter_name]["label"]
            return await ctx.send(
                embed=discord.Embed(
                    description=f"Current filter: **{current}**. Use `,filters` to see options.",
                    color=COLOR_INFO,
                )
            )

        requested = name.lower().replace(" ", "")
        filter_name = FILTER_ALIASES.get(requested, requested)
        if filter_name not in MUSIC_FILTERS:
            return await ctx.send(
                embed=discord.Embed(
                    description="Unknown filter. Use `,filters` to see available filters.",
                    color=COLOR_ERROR,
                )
            )

        state.filter_name = filter_name
        label = MUSIC_FILTERS[filter_name]["label"]
        await self.restart_current_track(ctx, f"Music filter set to **{label}**.")

    async def cog_unload(self):
        for guild in self.bot.guilds:
            voice = guild.voice_client
            if voice:
                await voice.disconnect(force=True)

        for state in self.states.values():
            if state.player_task:
                state.player_task.cancel()

    async def ensure_voice(
        self,
        ctx: commands.Context,
    ) -> discord.VoiceClient | None:
        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
            await ctx.send(
                embed=discord.Embed(
                    description="Join a voice channel first.",
                    color=COLOR_ERROR,
                )
            )
            return None

        channel = ctx.author.voice.channel
        voice = ctx.guild.voice_client

        if voice and voice.channel != channel:
            await voice.move_to(channel)
            return voice

        if voice:
            return voice

        try:
            return await channel.connect()
        except RuntimeError as exc:
            message = str(exc)
            if "davey" in message.lower():
                await ctx.send(
                    embed=discord.Embed(
                        description=(
                            "Voice support is not installed on this PC yet. "
                            "Install the `davey` package, then restart the bot."
                        ),
                        color=COLOR_ERROR,
                    )
                )
                return None
            raise

    async def extract_track(self, query: str, requester_id: int) -> Track:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(
            None,
            partial(ytdl.extract_info, query, download=False),
        )

        if info is None:
            raise commands.CommandError(
                "I couldn't find anything playable for that input."
            )

        if "entries" in info:
            entries = [entry for entry in info["entries"] if entry]
            if not entries:
                raise commands.CommandError(
                    "I couldn't find anything playable for that input."
                )
            info = entries[0]

        stream_url = info.get("url")
        webpage_url = info.get("webpage_url") or query
        title = info.get("title") or "Unknown Track"
        duration = info.get("duration")

        if not stream_url:
            raise commands.CommandError(
                "That link could not be turned into an audio stream. Spotify links may need a matching playable source."
            )

        return Track(
            title=title,
            webpage_url=webpage_url,
            stream_url=stream_url,
            requester_id=requester_id,
            duration=duration,
        )

    async def start_player(self, guild: discord.Guild):
        state = self.get_state(guild.id)
        if state.player_task and not state.player_task.done():
            return
        state.player_task = asyncio.create_task(self.player_loop(guild))

    async def player_loop(self, guild: discord.Guild):
        state = self.get_state(guild.id)

        while True:
            track = await state.queue.get()
            while True:
                voice = guild.voice_client

                if voice is None:
                    state.now_playing = None
                    state.skip_requested = False
                    break

                state.now_playing = track
                state.skip_requested = False
                finished = asyncio.Event()

                def after_playback(error: Exception | None):
                    if error:
                        log.warning(
                            "Music playback error in guild %s: %s",
                            guild.id,
                            error,
                        )
                    self.bot.loop.call_soon_threadsafe(finished.set)

                try:
                    source = self.make_source(track, state)
                    voice.play(source, after=after_playback)
                except Exception:
                    log.exception(
                        "Failed to start music playback in guild %s for %s",
                        guild.id,
                        track.webpage_url,
                    )
                    state.now_playing = None
                    state.restart_requested = False
                    state.skip_requested = False
                    break

                await finished.wait()

                if state.restart_requested:
                    state.restart_requested = False
                    continue

                if state.loop_enabled and not state.skip_requested:
                    continue

                state.now_playing = None
                state.skip_requested = False
                break

    @commands.command(name="join", help="Join the voice channel you are currently in.")
    async def join(self, ctx):
        """Usage: ,join"""
        voice = await self.ensure_voice(ctx)
        if voice is None:
            return

        await ctx.send(
            embed=discord.Embed(
                description=f"Joined {voice.channel.mention}.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="play",
        help="Play audio from a URL or search term in your current voice channel.",
    )
    async def play(self, ctx, *, query: str):
        """Usage: ,play <url or search>"""
        voice = await self.ensure_voice(ctx)
        if voice is None:
            return

        try:
            track = await self.extract_track(query, ctx.author.id)
        except commands.CommandError as exc:
            return await ctx.send(
                embed=discord.Embed(
                    description=str(exc),
                    color=COLOR_ERROR,
                )
            )
        except Exception as exc:
            return await ctx.send(
                embed=discord.Embed(
                    description=f"Failed to load that track: {exc}",
                    color=COLOR_ERROR,
                )
            )

        state = self.get_state(ctx.guild.id)
        await state.queue.put(track)
        await self.start_player(ctx.guild)

        if voice.is_playing() or state.now_playing is not None:
            description = f"Queued [{track.title}]({track.webpage_url})"
        else:
            description = f"Loaded [{track.title}]({track.webpage_url})"

        if "spotify.com" in query.lower():
            description += "\nSpotify links are best-effort and may fall back depending on what yt-dlp can resolve."

        await ctx.send(
            embed=discord.Embed(
                description=description,
                color=COLOR_INFO,
            )
        )

    @commands.command(name="queue", aliases=["q"], help="Show the current music queue.")
    async def queue(self, ctx):
        """Usage: ,queue"""
        state = self.get_state(ctx.guild.id)
        lines = []

        if state.now_playing:
            loop_marker = " [Looping]" if state.loop_enabled else ""
            lines.append(
                f"Now: [{state.now_playing.title}]({state.now_playing.webpage_url}) "
                f"({state.now_playing.duration_text}){loop_marker}"
            )

        queued = list(state.queue._queue)[:10]
        for index, track in enumerate(queued, start=1):
            lines.append(
                f"{index}. [{track.title}]({track.webpage_url}) ({track.duration_text})"
            )

        if not lines:
            return await ctx.send(
                embed=discord.Embed(
                    description="The queue is empty.",
                    color=COLOR_INFO,
                )
            )

        await ctx.send(
            embed=discord.Embed(
                title="Music Queue",
                description="\n".join(lines),
                color=COLOR_INFO,
            )
        )

    @commands.command(name="skip", help="Skip the currently playing track.")
    async def skip(self, ctx):
        """Usage: ,skip"""
        voice = ctx.guild.voice_client
        if not voice or not voice.is_playing():
            return await ctx.send(
                embed=discord.Embed(
                    description="Nothing is playing right now.",
                    color=COLOR_ERROR,
                )
            )

        state = self.get_state(ctx.guild.id)
        state.skip_requested = True
        state.restart_requested = False
        voice.stop()
        await ctx.send(
            embed=discord.Embed(
                description="Skipped the current track.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="pause", help="Pause the current track.")
    async def pause(self, ctx):
        """Usage: ,pause"""
        voice = ctx.guild.voice_client
        if not voice:
            return await ctx.send(
                embed=discord.Embed(
                    description="I'm not connected to a voice channel.",
                    color=COLOR_ERROR,
                )
            )

        if voice.is_paused():
            return await ctx.send(
                embed=discord.Embed(
                    description="Playback is already paused.",
                    color=COLOR_INFO,
                )
            )

        if not voice.is_playing():
            return await ctx.send(
                embed=discord.Embed(
                    description="Nothing is playing right now.",
                    color=COLOR_ERROR,
                )
            )

        voice.pause()
        await ctx.send(
            embed=discord.Embed(
                description="Paused the current track.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="resume", help="Resume the paused track.")
    async def resume(self, ctx):
        """Usage: ,resume"""
        voice = ctx.guild.voice_client
        if not voice:
            return await ctx.send(
                embed=discord.Embed(
                    description="I'm not connected to a voice channel.",
                    color=COLOR_ERROR,
                )
            )

        if not voice.is_paused():
            return await ctx.send(
                embed=discord.Embed(
                    description="Playback is not paused right now.",
                    color=COLOR_INFO,
                )
            )

        voice.resume()
        await ctx.send(
            embed=discord.Embed(
                description="Resumed playback.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="stop", help="Stop playback and clear the queue.")
    async def stop(self, ctx):
        """Usage: ,stop"""
        voice = ctx.guild.voice_client
        state = self.get_state(ctx.guild.id)

        if not voice:
            return await ctx.send(
                embed=discord.Embed(
                    description="I'm not connected to a voice channel.",
                    color=COLOR_ERROR,
                )
            )

        self.clear_queue(state)

        state.now_playing = None
        state.loop_enabled = False
        state.skip_requested = True
        state.restart_requested = False
        if voice.is_playing() or voice.is_paused():
            voice.stop()

        await ctx.send(
            embed=discord.Embed(
                description="Stopped playback and cleared the queue.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="leave", aliases=["disconnect"], help="Leave the current voice channel."
    )
    async def leave(self, ctx):
        """Usage: ,leave"""
        voice = ctx.guild.voice_client
        state = self.get_state(ctx.guild.id)

        if not voice:
            return await ctx.send(
                embed=discord.Embed(
                    description="I'm not connected to a voice channel.",
                    color=COLOR_ERROR,
                )
            )

        self.clear_queue(state)

        state.now_playing = None
        state.loop_enabled = False
        state.skip_requested = True
        state.restart_requested = False
        if voice.is_playing() or voice.is_paused():
            voice.stop()
        await voice.disconnect()

        await ctx.send(
            embed=discord.Embed(
                description="Disconnected from voice chat.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="nowplaying", aliases=["np"], help="Show the current track.")
    async def now_playing(self, ctx):
        """Usage: ,nowplaying"""
        state = self.get_state(ctx.guild.id)
        if not state.now_playing:
            return await ctx.send(
                embed=discord.Embed(
                    description="Nothing is playing right now.",
                    color=COLOR_INFO,
                )
            )

        track = state.now_playing
        filter_label = MUSIC_FILTERS[state.filter_name]["label"]
        loop_text = "\nLoop: On" if state.loop_enabled else "\nLoop: Off"
        await ctx.send(
            embed=discord.Embed(
                title="Now Playing",
                description=(
                    f"[{track.title}]({track.webpage_url})\n"
                    f"Length: {track.duration_text}{loop_text}\n"
                    f"Filter: {filter_label}\n"
                    f"Volume: {round(state.volume * 100)}%"
                ),
                color=COLOR_INFO,
            )
        )

    @commands.command(
        name="loop",
        aliases=["repeat"],
        help="Turn looping for the current track on or off.",
    )
    async def loop(self, ctx, mode: str | None = None):
        """Usage: ,loop [on/off]"""
        state = self.get_state(ctx.guild.id)

        if mode is None:
            state.loop_enabled = not state.loop_enabled
        else:
            mode = mode.lower()
            if mode in {"on", "enable", "enabled", "true"}:
                state.loop_enabled = True
            elif mode in {"off", "disable", "disabled", "false"}:
                state.loop_enabled = False
            else:
                return await ctx.send(
                    embed=discord.Embed(
                        description="Use `,loop on` or `,loop off`.",
                        color=COLOR_ERROR,
                    )
                )

        if state.loop_enabled and state.now_playing is None:
            description = (
                "Loop is enabled. It will repeat the next track that starts playing."
            )
        elif state.loop_enabled:
            description = f"Loop enabled for [{state.now_playing.title}]({state.now_playing.webpage_url})."
        else:
            description = "Loop disabled."

        await ctx.send(
            embed=discord.Embed(
                description=description,
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="filters",
        aliases=["filterlist"],
        help="Show available music filters.",
    )
    async def filters(self, ctx):
        """Usage: ,filters"""
        lines = [
            f"`{name}` - {data['description']}" for name, data in MUSIC_FILTERS.items()
        ]
        await ctx.send(
            embed=discord.Embed(
                title="Music Filters",
                description="\n".join(lines),
                color=COLOR_INFO,
            )
        )

    @commands.command(
        name="filter",
        aliases=["effect"],
        help="Apply an audio filter to playback.",
    )
    async def filter(self, ctx, name: str | None = None):
        """Usage: ,filter <off|bassboost|chipmunk|nightcore|vaporwave|8d|karaoke|tremolo|soft>"""
        await self.set_filter(ctx, name)

    @commands.command(
        name="bassboost",
        aliases=["bass"],
        help="Shortcut for the bass boost music filter.",
    )
    async def bassboost(self, ctx):
        """Usage: ,bassboost"""
        await self.set_filter(ctx, "bassboost")

    @commands.command(
        name="chipmunk",
        aliases=["chickmuck", "chipmuck"],
        help="Shortcut for the chipmunk music filter.",
    )
    async def chipmunk(self, ctx):
        """Usage: ,chipmunk"""
        await self.set_filter(ctx, "chipmunk")

    @commands.command(name="volume", aliases=["vol"], help="Set music volume.")
    async def volume(self, ctx, percent: int | None = None):
        """Usage: ,volume [0-200]"""
        state = self.get_state(ctx.guild.id)
        if percent is None:
            return await ctx.send(
                embed=discord.Embed(
                    description=f"Current volume: **{round(state.volume * 100)}%**",
                    color=COLOR_INFO,
                )
            )

        if percent < 0 or percent > 200:
            return await ctx.send(
                embed=discord.Embed(
                    description="Volume must be between 0 and 200.",
                    color=COLOR_ERROR,
                )
            )

        state.volume = percent / 100
        voice = ctx.guild.voice_client
        if voice and isinstance(voice.source, discord.PCMVolumeTransformer):
            voice.source.volume = state.volume

        await ctx.send(
            embed=discord.Embed(
                description=f"Volume set to **{percent}%**.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="replay",
        aliases=["restart"],
        help="Restart the current track.",
    )
    async def replay(self, ctx):
        """Usage: ,replay"""
        state = self.get_state(ctx.guild.id)
        if not state.now_playing:
            return await ctx.send(
                embed=discord.Embed(
                    description="Nothing is playing right now.",
                    color=COLOR_ERROR,
                )
            )

        await self.restart_current_track(ctx, "Restarted the current track.")

    @commands.command(name="shuffle", help="Shuffle the queued tracks.")
    async def shuffle(self, ctx):
        """Usage: ,shuffle"""
        state = self.get_state(ctx.guild.id)
        shuffled = self.shuffle_queue(state)
        if shuffled < 2:
            return await ctx.send(
                embed=discord.Embed(
                    description="Add at least two queued tracks before shuffling.",
                    color=COLOR_INFO,
                )
            )

        await ctx.send(
            embed=discord.Embed(
                description=f"Shuffled **{shuffled}** queued tracks.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="remove",
        aliases=["rm"],
        help="Remove a track from the queue by position.",
    )
    async def remove(self, ctx, position: int):
        """Usage: ,remove <queue position>"""
        state = self.get_state(ctx.guild.id)
        queued = list(state.queue._queue)
        if position < 1 or position > len(queued):
            return await ctx.send(
                embed=discord.Embed(
                    description="That queue position does not exist.",
                    color=COLOR_ERROR,
                )
            )

        removed = queued.pop(position - 1)
        state.queue._queue.clear()
        state.queue._queue.extend(queued)
        await ctx.send(
            embed=discord.Embed(
                description=f"Removed [{removed.title}]({removed.webpage_url}) from the queue.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="move",
        aliases=["mv"],
        help="Move a queued track to a new position.",
    )
    async def move(self, ctx, current_position: int, new_position: int):
        """Usage: ,move <current position> <new position>"""
        state = self.get_state(ctx.guild.id)
        queued = list(state.queue._queue)
        if current_position < 1 or current_position > len(queued):
            return await ctx.send(
                embed=discord.Embed(
                    description="The current queue position does not exist.",
                    color=COLOR_ERROR,
                )
            )
        if new_position < 1 or new_position > len(queued):
            return await ctx.send(
                embed=discord.Embed(
                    description="The new queue position does not exist.",
                    color=COLOR_ERROR,
                )
            )

        track = queued.pop(current_position - 1)
        queued.insert(new_position - 1, track)
        state.queue._queue.clear()
        state.queue._queue.extend(queued)
        await ctx.send(
            embed=discord.Embed(
                description=f"Moved [{track.title}]({track.webpage_url}) to position **{new_position}**.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="jump",
        help="Skip straight to a queued track by position.",
    )
    async def jump(self, ctx, position: int):
        """Usage: ,jump <queue position>"""
        voice = ctx.guild.voice_client
        state = self.get_state(ctx.guild.id)
        queued = list(state.queue._queue)
        if position < 1 or position > len(queued):
            return await ctx.send(
                embed=discord.Embed(
                    description="That queue position does not exist.",
                    color=COLOR_ERROR,
                )
            )

        removed_before = queued[: position - 1]
        state.queue._queue.clear()
        state.queue._queue.extend(queued[position - 1 :])
        state.skip_requested = True
        state.restart_requested = False
        if voice and (voice.is_playing() or voice.is_paused()):
            voice.stop()

        await ctx.send(
            embed=discord.Embed(
                description=f"Jumping ahead and skipped **{len(removed_before)}** queued track(s).",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="controls",
        aliases=["musicpanel", "player"],
        help="Show interactive music controls.",
    )
    async def controls(self, ctx):
        """Usage: ,controls"""
        state = self.get_state(ctx.guild.id)
        track_text = (
            f"[{state.now_playing.title}]({state.now_playing.webpage_url})"
            if state.now_playing
            else "Nothing playing"
        )
        embed = discord.Embed(
            title="Music Controls",
            description=(
                f"Now: {track_text}\n"
                f"Queued: **{state.queue.qsize()}**\n"
                f"Loop: **{'On' if state.loop_enabled else 'Off'}**\n"
                f"Filter: **{MUSIC_FILTERS[state.filter_name]['label']}**\n"
                f"Volume: **{round(state.volume * 100)}%**"
            ),
            color=COLOR_INFO,
        )
        await ctx.send(embed=embed, view=MusicControlView(self, ctx.guild.id))


async def setup(bot):
    await bot.add_cog(Music(bot))
