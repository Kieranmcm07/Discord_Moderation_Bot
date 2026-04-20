"""
cogs/music.py - simple music playback with queue support.
"""

from __future__ import annotations

import asyncio
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

ytdl = yt_dlp.YoutubeDL(YTDL_FORMAT_OPTIONS)


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
            raise commands.CommandError("I couldn't find anything playable for that input.")

        if "entries" in info:
            entries = [entry for entry in info["entries"] if entry]
            if not entries:
                raise commands.CommandError("I couldn't find anything playable for that input.")
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
                        print(f"Music playback error in guild {guild.id}: {error}")
                    self.bot.loop.call_soon_threadsafe(finished.set)

                source = discord.FFmpegPCMAudio(track.stream_url, **FFMPEG_OPTIONS)
                voice.play(source, after=after_playback)

                await finished.wait()

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
            lines.append(f"{index}. [{track.title}]({track.webpage_url}) ({track.duration_text})")

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

        while not state.queue.empty():
            try:
                state.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        state.now_playing = None
        state.loop_enabled = False
        state.skip_requested = True
        if voice.is_playing():
            voice.stop()

        await ctx.send(
            embed=discord.Embed(
                description="Stopped playback and cleared the queue.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="leave", aliases=["disconnect"], help="Leave the current voice channel.")
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

        while not state.queue.empty():
            try:
                state.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        state.now_playing = None
        state.loop_enabled = False
        state.skip_requested = True
        if voice.is_playing():
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
        loop_text = "\nLoop: On" if state.loop_enabled else ""
        await ctx.send(
            embed=discord.Embed(
                title="Now Playing",
                description=(
                    f"[{track.title}]({track.webpage_url})\n"
                    f"Length: {track.duration_text}{loop_text}"
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
            description = "Loop is enabled. It will repeat the next track that starts playing."
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


async def setup(bot):
    await bot.add_cog(Music(bot))
