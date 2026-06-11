# ============================================================
#   Made by Kieranmcm07 on GitHub
#   GitHub: https://github.com/Kieranmcm07
# ============================================================
"""
cogs/music.py - simple music playback with queue support.
"""

# Kept self-contained so music changes do not spill into the rest of the bot.
from __future__ import annotations

import asyncio
import base64
import contextlib
import html
import logging
import random
import re
import shlex
import time
from dataclasses import dataclass
from functools import partial
from typing import Any
from urllib.parse import urlparse

import aiohttp
import discord
from discord.ext import commands
import yt_dlp

from config import (
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_SUCCESS,
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    SPOTIFY_MARKET,
    SPOTIFY_MAX_TRACKS,
)
from utils.errors import SafeView

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

IDLE_DISCONNECT_SECONDS = 180
VOICE_CONNECT_TIMEOUT = 20.0
SPOTIFY_API_BASE_URL = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SUPPORTED_TYPES = {"track", "album", "playlist"}
SPOTIFY_TRACK_LIMIT = max(1, min(SPOTIFY_MAX_TRACKS, 100))
SPOTIFY_WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
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
    thumbnail_url: str | None = None
    http_headers: dict[str, str] | None = None
    replay_query: str | None = None

    @property
    def duration_text(self) -> str:
        if not self.duration:
            return "Unknown"

        minutes, seconds = divmod(self.duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02}:{seconds:02}"
        return f"{minutes}:{seconds:02}"


@dataclass(frozen=True)
class SpotifyReference:
    kind: str
    item_id: str
    url: str


@dataclass(frozen=True)
class SpotifyTrackMetadata:
    title: str
    artists: tuple[str, ...]
    spotify_url: str
    duration: int | None = None
    thumbnail_url: str | None = None

    @property
    def display_title(self) -> str:
        artist_text = ", ".join(self.artists)
        if artist_text:
            return f"{artist_text} - {self.title}"
        return self.title

    @property
    def search_query(self) -> str:
        artist_text = " ".join(self.artists)
        return f"{artist_text} {self.title} official audio".strip()


@dataclass(frozen=True)
class SpotifySelection:
    reference: SpotifyReference
    title: str
    tracks: list[SpotifyTrackMetadata]
    total: int
    limited: bool
    skipped_unplayable: int = 0


def parse_spotify_reference(query: str) -> SpotifyReference | None:
    """Return the first Spotify track/album/playlist reference in a command."""
    for token in query.split():
        reference = parse_spotify_candidate(token)
        if reference:
            return reference
    return None


def parse_spotify_candidate(value: str) -> SpotifyReference | None:
    candidate = value.strip().strip("<>()[]{}.,")
    if not candidate:
        return None

    if candidate.startswith("spotify:"):
        parts = candidate.split(":")
        if len(parts) >= 3 and parts[1] in SPOTIFY_SUPPORTED_TYPES:
            item_id = parts[2].split("?")[0]
            if item_id:
                kind = parts[1]
                return SpotifyReference(
                    kind=kind,
                    item_id=item_id,
                    url=f"https://open.spotify.com/{kind}/{item_id}",
                )
        return None

    parsed = urlparse(candidate)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host != "spotify.com" and not host.endswith(".spotify.com"):
        return None

    segments = [segment for segment in parsed.path.split("/") if segment]
    for index, segment in enumerate(segments):
        if segment in SPOTIFY_SUPPORTED_TYPES and index + 1 < len(segments):
            item_id = segments[index + 1]
            if item_id:
                return SpotifyReference(
                    kind=segment,
                    item_id=item_id,
                    url=f"https://open.spotify.com/{segment}/{item_id}",
                )

    return None


def spotify_track_from_payload(
    payload: dict[str, Any] | None,
    fallback_thumbnail_url: str | None = None,
) -> SpotifyTrackMetadata | None:
    if not payload or payload.get("is_local"):
        return None
    if payload.get("type") not in {None, "track"}:
        return None

    title = payload.get("name")
    artists = tuple(
        artist.get("name", "").strip()
        for artist in payload.get("artists", [])
        if artist.get("name", "").strip()
    )
    if not title:
        return None

    duration_ms = payload.get("duration_ms")
    duration = duration_ms // 1000 if isinstance(duration_ms, int) else None
    spotify_url = (
        payload.get("external_urls", {}).get("spotify")
        or payload.get("href")
        or ""
    )
    thumbnail_url = spotify_image_url(payload) or fallback_thumbnail_url

    return SpotifyTrackMetadata(
        title=title,
        artists=artists,
        spotify_url=spotify_url,
        duration=duration,
        thumbnail_url=thumbnail_url,
    )


def spotify_total(value: Any, fallback: int) -> int:
    return value if isinstance(value, int) else fallback


def spotify_params(**extra: str | int) -> dict[str, str | int] | None:
    params: dict[str, str | int] = {
        key: value for key, value in extra.items() if value not in {None, ""}
    }
    if SPOTIFY_MARKET:
        params.setdefault("market", SPOTIFY_MARKET)
    return params or None


def spotify_track_ids_from_html(html_text: str, limit: int) -> list[str]:
    track_ids: list[str] = []
    seen: set[str] = set()
    patterns = [
        r"https://open\.spotify\.com/track/([A-Za-z0-9]+)",
        r"href=[\"']/track/([A-Za-z0-9]+)",
        r"spotify:track:([A-Za-z0-9]+)",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, html_text):
            track_id = match.group(1)
            if track_id in seen:
                continue
            seen.add(track_id)
            track_ids.append(track_id)
            if len(track_ids) >= limit:
                return track_ids

    return track_ids


def spotify_playlist_total_from_html(html_text: str) -> int | None:
    text = html.unescape(html_text)
    match = re.search(r"(\d[\d,]*)\s+items?", text, flags=re.IGNORECASE)
    if not match:
        return None

    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def spotify_image_url(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None

    image_source = (
        payload.get("album") if isinstance(payload.get("album"), dict) else payload
    )
    images = image_source.get("images") if isinstance(image_source, dict) else None
    if not isinstance(images, list):
        return None

    for image in images:
        if isinstance(image, dict) and image.get("url"):
            return image["url"]
    return None


class GuildMusicState:
    def __init__(self):
        self.queue: asyncio.Queue[Track] = asyncio.Queue()
        self.now_playing: Track | None = None
        self.last_track: Track | None = None
        self.player_task: asyncio.Task | None = None
        self.announce_channel_id: int | None = None
        self.player_message: discord.Message | None = None
        self.loop_enabled = False
        self.skip_requested = False
        self.stop_requested = False
        self.restart_requested = False
        self.filter_name = "off"
        self.volume = 1.0


class MusicControlView(SafeView):
    def __init__(self, cog: "Music", guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    async def refresh_player(
        self,
        interaction: discord.Interaction,
        message: str,
    ):
        if not interaction.guild:
            return await interaction.response.send_message(
                message,
                ephemeral=True,
            )

        state = self.cog.get_state(self.guild_id)
        embed = self.cog.build_player_embed(interaction.guild, state)
        if isinstance(interaction.message, discord.Message):
            state.player_message = interaction.message
        await interaction.response.edit_message(embed=embed, view=self)
        with contextlib.suppress(discord.HTTPException):
            await interaction.followup.send(message, ephemeral=True)

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

    @discord.ui.button(
        label="Pause/Resume",
        emoji="⏯️",
        style=discord.ButtonStyle.secondary,
    )
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

        await self.refresh_player(interaction, message)

    @discord.ui.button(label="Skip", emoji="⏭️", style=discord.ButtonStyle.primary)
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
        state.stop_requested = False
        state.restart_requested = False
        voice.stop()
        await interaction.response.send_message(
            "Skipping the current track.",
            ephemeral=True,
        )

    @discord.ui.button(label="Loop", emoji="🔁", style=discord.ButtonStyle.secondary)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_state(self.guild_id)
        state.loop_enabled = not state.loop_enabled
        await self.refresh_player(
            interaction,
            f"Loop is now {'on' if state.loop_enabled else 'off'}.",
        )

    @discord.ui.button(
        label="Shuffle",
        emoji="🔀",
        style=discord.ButtonStyle.secondary,
    )
    async def shuffle(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        state = self.cog.get_state(self.guild_id)
        shuffled = self.cog.shuffle_queue(state)
        await self.refresh_player(
            interaction,
            f"Shuffled {shuffled} queued track(s).",
        )

    @discord.ui.button(label="Stop", emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice = await self.get_voice(interaction)
        if not voice:
            return

        state = self.cog.get_state(self.guild_id)
        self.cog.clear_queue(state)
        state.now_playing = None
        state.loop_enabled = False
        state.skip_requested = True
        state.stop_requested = True
        state.restart_requested = False
        was_active = voice.is_playing() or voice.is_paused()
        if was_active:
            voice.stop()
            return await interaction.response.send_message(
                "Stopped playback and cleared the queue.",
                ephemeral=True,
            )

        await self.refresh_player(
            interaction,
            "Stopped playback and cleared the queue.",
        )


class Music(commands.Cog, name="Music"):
    """Voice playback commands."""

    def __init__(self, bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}
        self.http_session: aiohttp.ClientSession | None = None
        self.spotify_token: str | None = None
        self.spotify_token_expires_at = 0.0

    def get_state(self, guild_id: int) -> GuildMusicState:
        state = self.states.get(guild_id)
        if state is None:
            state = GuildMusicState()
            self.states[guild_id] = state
        return state

    async def get_http_session(self) -> aiohttp.ClientSession:
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession()
        return self.http_session

    async def get_spotify_token(self) -> str:
        if (
            self.spotify_token
            and time.monotonic() < self.spotify_token_expires_at - 60
        ):
            return self.spotify_token

        if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
            raise commands.CommandError(
                "Spotify links need `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in `.env`."
            )

        session = await self.get_http_session()
        credentials = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode("utf-8")
        auth_header = base64.b64encode(credentials).decode("ascii")

        try:
            async with session.post(
                SPOTIFY_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    log.warning(
                        "Spotify token request failed with HTTP %s: %s",
                        response.status,
                        text[:500],
                    )
                    raise commands.CommandError(
                        "Spotify rejected the configured client ID/secret. Check your `.env` values."
                    )

                payload = await response.json()
        except aiohttp.ClientError as exc:
            raise commands.CommandError(f"Could not reach Spotify: {exc}") from exc

        access_token = payload.get("access_token")
        if not access_token:
            raise commands.CommandError("Spotify did not return an access token.")

        expires_in = payload.get("expires_in", 3600)
        if not isinstance(expires_in, int):
            expires_in = 3600

        self.spotify_token = access_token
        self.spotify_token_expires_at = time.monotonic() + expires_in
        return access_token

    async def spotify_api_get(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
        *,
        retry_on_auth_error: bool = True,
    ) -> dict[str, Any]:
        token = await self.get_spotify_token()
        session = await self.get_http_session()
        url = path if path.startswith("http") else f"{SPOTIFY_API_BASE_URL}{path}"

        try:
            async with session.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                if response.status == 401 and retry_on_auth_error:
                    self.spotify_token = None
                    self.spotify_token_expires_at = 0.0
                    return await self.spotify_api_get(
                        path,
                        params,
                        retry_on_auth_error=False,
                    )

                if response.status == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait_text = (
                        f" in {retry_after} second(s)"
                        if retry_after
                        else " in a moment"
                    )
                    raise commands.CommandError(
                        f"Spotify is rate-limiting requests. Try again{wait_text}."
                    )

                if response.status == 404:
                    raise commands.CommandError(
                        "I couldn't find that Spotify item. Private or unavailable links may not work."
                    )

                if response.status >= 400:
                    text = await response.text()
                    log.warning(
                        "Spotify API request failed with HTTP %s for %s: %s",
                        response.status,
                        url,
                        text[:500],
                    )
                    raise commands.CommandError(
                        "Spotify could not load that link right now."
                    )

                return await response.json()
        except aiohttp.ClientError as exc:
            raise commands.CommandError(f"Could not reach Spotify: {exc}") from exc

    async def collect_spotify_items(
        self,
        first_page: dict[str, Any],
        limit: int,
        *,
        follow_next: bool = True,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = first_page

        while page and len(items) < limit:
            for item in page.get("items", []):
                if len(items) >= limit:
                    break
                if isinstance(item, dict):
                    items.append(item)

            next_url = page.get("next")
            if not follow_next or not next_url or len(items) >= limit:
                break
            page = await self.spotify_api_get(next_url)

        return items

    async def get_spotify_playlist_tracks_page(
        self,
        reference: SpotifyReference,
    ) -> dict[str, Any]:
        try:
            return await self.spotify_api_get(
                f"/playlists/{reference.item_id}/tracks",
                params=spotify_params(limit=min(SPOTIFY_TRACK_LIMIT, 50)),
            )
        except commands.CommandError as exc:
            log.warning(
                "Spotify playlist %s tracks endpoint fallback failed: %s",
                reference.item_id,
                exc,
            )
            return {}

    async def get_spotify_playlist_web_preview(
        self,
        reference: SpotifyReference,
    ) -> tuple[list[str], int | None]:
        session = await self.get_http_session()
        urls = [
            reference.url,
            f"https://open.spotify.com/embed/playlist/{reference.item_id}",
        ]
        track_ids: list[str] = []
        seen: set[str] = set()
        total: int | None = None

        for url in urls:
            try:
                async with session.get(
                    url,
                    headers=SPOTIFY_WEB_HEADERS,
                ) as response:
                    if response.status >= 400:
                        log.warning(
                            "Spotify web playlist fallback failed with HTTP %s for %s",
                            response.status,
                            url,
                        )
                        continue
                    html_text = await response.text()
            except aiohttp.ClientError as exc:
                log.warning(
                    "Spotify web playlist fallback could not reach %s: %s",
                    url,
                    exc,
                )
                continue

            if total is None:
                total = spotify_playlist_total_from_html(html_text)

            for track_id in spotify_track_ids_from_html(
                html_text,
                SPOTIFY_TRACK_LIMIT,
            ):
                if track_id in seen:
                    continue
                seen.add(track_id)
                track_ids.append(track_id)
                if len(track_ids) >= SPOTIFY_TRACK_LIMIT:
                    break

            if len(track_ids) >= SPOTIFY_TRACK_LIMIT:
                break

        log.info(
            "Spotify web playlist fallback found %s track id(s) for %s.",
            len(track_ids),
            reference.item_id,
        )
        return track_ids, total

    async def spotify_tracks_from_ids(
        self,
        track_ids: list[str],
        fallback_thumbnail_url: str | None = None,
    ) -> list[SpotifyTrackMetadata]:
        tracks: list[SpotifyTrackMetadata] = []
        for start in range(0, len(track_ids), 50):
            batch = track_ids[start : start + 50]
            try:
                payload = await self.spotify_api_get(
                    "/tracks",
                    params=spotify_params(ids=",".join(batch)),
                )
                payload_tracks = payload.get("tracks", [])
                if not isinstance(payload_tracks, list):
                    payload_tracks = []
            except commands.CommandError as exc:
                log.warning(
                    "Spotify batch track lookup failed for %s track id(s): %s",
                    len(batch),
                    exc,
                )
                payload_tracks = []

            batch_tracks_before = len(tracks)
            for payload_track in payload_tracks:
                track = spotify_track_from_payload(
                    payload_track,
                    fallback_thumbnail_url,
                )
                if track:
                    tracks.append(track)

            if len(tracks) > batch_tracks_before:
                continue

            for track_id in batch:
                try:
                    payload_track = await self.spotify_api_get(
                        f"/tracks/{track_id}",
                        params=spotify_params(),
                    )
                except commands.CommandError as exc:
                    log.warning(
                        "Spotify single track fallback failed for %s: %s",
                        track_id,
                        exc,
                    )
                    continue

                track = spotify_track_from_payload(
                    payload_track,
                    fallback_thumbnail_url,
                )
                if track:
                    tracks.append(track)

        return tracks

    async def resolve_spotify_reference(
        self,
        reference: SpotifyReference,
    ) -> SpotifySelection:
        if reference.kind == "track":
            payload = await self.spotify_api_get(
                f"/tracks/{reference.item_id}",
                params=spotify_params(),
            )
            track = spotify_track_from_payload(payload)
            if not track:
                raise commands.CommandError(
                    "That Spotify track is not playable or is missing metadata."
                )
            return SpotifySelection(
                reference=reference,
                title=track.display_title,
                tracks=[track],
                total=1,
                limited=False,
            )

        if reference.kind == "album":
            payload = await self.spotify_api_get(
                f"/albums/{reference.item_id}",
                params=spotify_params(),
            )
            album_thumbnail_url = spotify_image_url(payload)
            tracks_page = payload.get("tracks", {})
            raw_items = await self.collect_spotify_items(
                tracks_page,
                SPOTIFY_TRACK_LIMIT,
            )
            tracks = [
                track
                for track in (
                    spotify_track_from_payload(item, album_thumbnail_url)
                    for item in raw_items
                )
                if track
            ]
            total = spotify_total(tracks_page.get("total"), len(raw_items))
            if not tracks:
                raise commands.CommandError(
                    "That Spotify album did not contain any playable tracks."
                )
            return SpotifySelection(
                reference=reference,
                title=payload.get("name") or "Spotify Album",
                tracks=tracks,
                total=total,
                limited=total > SPOTIFY_TRACK_LIMIT,
                skipped_unplayable=len(raw_items) - len(tracks),
            )

        if reference.kind == "playlist":
            playlist = await self.spotify_api_get(
                f"/playlists/{reference.item_id}",
                params=spotify_params(),
            )
            playlist_thumbnail_url = spotify_image_url(playlist)
            tracks_page = playlist.get("tracks", {})
            if not isinstance(tracks_page, dict):
                tracks_page = {}
            raw_items = await self.collect_spotify_items(
                tracks_page,
                SPOTIFY_TRACK_LIMIT,
                follow_next=False,
            )
            if not raw_items:
                tracks_page = await self.get_spotify_playlist_tracks_page(reference)
                raw_items = await self.collect_spotify_items(
                    tracks_page,
                    SPOTIFY_TRACK_LIMIT,
                )
            track_payloads = [
                item.get("track")
                for item in raw_items
                if isinstance(item.get("track"), dict)
            ]
            if raw_items and not track_payloads:
                tracks_page = await self.get_spotify_playlist_tracks_page(reference)
                raw_items = await self.collect_spotify_items(
                    tracks_page,
                    SPOTIFY_TRACK_LIMIT,
                )
                track_payloads = [
                    item.get("track")
                    for item in raw_items
                    if isinstance(item.get("track"), dict)
                ]
            tracks = [
                track
                for track in (
                    spotify_track_from_payload(item, playlist_thumbnail_url)
                    for item in track_payloads
                )
                if track
            ]
            playlist_tracks = playlist.get("tracks")
            total = spotify_total(
                tracks_page.get("total"),
                len(raw_items),
            )
            if not isinstance(playlist_tracks, dict):
                playlist_tracks = {}
            total = spotify_total(playlist_tracks.get("total"), total)
            if not tracks:
                web_track_ids, web_total = await self.get_spotify_playlist_web_preview(
                    reference
                )
                tracks = await self.spotify_tracks_from_ids(
                    web_track_ids,
                    playlist_thumbnail_url,
                )
                if web_total is not None:
                    total = web_total
                else:
                    total = max(total, len(tracks))

            if not tracks:
                log.warning(
                    "Spotify playlist %s returned %s item(s), %s track payload(s), and 0 playable tracks.",
                    reference.item_id,
                    len(raw_items),
                    len(track_payloads),
                )
                raise commands.CommandError(
                    "Spotify loaded that playlist, but did not return any usable track details for it. Try a public playlist or a direct Spotify track link."
                )
            return SpotifySelection(
                reference=reference,
                title=playlist.get("name") or "Spotify Playlist",
                tracks=tracks,
                total=total,
                limited=total > len(tracks),
                skipped_unplayable=max(0, len(raw_items) - len(tracks)),
            )

        raise commands.CommandError("That Spotify link type is not supported.")

    def make_ffmpeg_options(
        self,
        track: Track,
        state: GuildMusicState,
    ) -> dict[str, str]:
        options = FFMPEG_OPTIONS.copy()
        if track.http_headers:
            header_lines = []
            for key, value in track.http_headers.items():
                safe_key = str(key).replace("\r", "").replace("\n", "")
                safe_value = str(value).replace("\r", "").replace("\n", "")
                header_lines.append(f"{safe_key}: {safe_value}")

            if header_lines:
                headers = "\r\n".join(header_lines) + "\r\n"
                options["before_options"] = (
                    f"{options['before_options']} -headers {shlex.quote(headers)}"
                )

        filter_chain = MUSIC_FILTERS[state.filter_name]["ffmpeg"]
        if filter_chain:
            options["options"] = f'-vn -af "{filter_chain}"'
        return options

    def make_source(self, track: Track, state: GuildMusicState) -> discord.AudioSource:
        source = discord.FFmpegPCMAudio(
            track.stream_url,
            **self.make_ffmpeg_options(track, state),
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

    def build_player_embed(
        self,
        guild: discord.Guild,
        state: GuildMusicState,
    ) -> discord.Embed:
        track = state.now_playing
        display_track = track or state.last_track
        loop_text = "On" if state.loop_enabled else "Off"
        voice = guild.voice_client
        if state.restart_requested and track:
            status_text = "Restarting"
            status_icon = "🔄"
            color = COLOR_INFO
        elif state.skip_requested and track:
            status_text = "Skipping"
            status_icon = "⏭️"
            color = COLOR_INFO
        elif voice and voice.is_paused():
            status_text = "Paused"
            status_icon = "⏸️"
            color = COLOR_INFO
        elif voice and voice.is_playing():
            status_text = "Playing"
            status_icon = "▶️"
            color = COLOR_SUCCESS
        else:
            status_text = "Idle"
            status_icon = "⏹️"
            color = COLOR_INFO

        if track:
            embed = discord.Embed(
                title=f"{status_icon} Now Playing",
                description=(
                    f"### [{track.title}]({track.webpage_url})\n"
                    f"`{track.duration_text}` • requested by <@{track.requester_id}>"
                ),
                color=color,
            )
        elif display_track:
            embed = discord.Embed(
                title="⏹️ Music Idle",
                description=(
                    "Nothing is playing right now.\n"
                    f"Last track: **[{display_track.title}]({display_track.webpage_url})**"
                ),
                color=color,
            )
        else:
            embed = discord.Embed(
                title="⏹️ Music Idle",
                description="Nothing is playing right now.",
                color=color,
            )

        bot_user = self.bot.user
        if bot_user:
            embed.set_author(
                name="Nokturnal Music",
                icon_url=bot_user.display_avatar.url,
            )

        if display_track and display_track.thumbnail_url:
            embed.set_thumbnail(url=display_track.thumbnail_url)

        embed.add_field(
            name="Status",
            value=f"{status_icon} **{status_text}**",
            inline=True,
        )
        embed.add_field(
            name="Queue",
            value=f"🎵 **{state.queue.qsize()}** waiting",
            inline=True,
        )
        embed.add_field(name="Loop", value=f"🔁 **{loop_text}**", inline=True)

        queued = list(state.queue._queue)
        if queued:
            next_track = queued[0]
            embed.add_field(
                name="Next Up",
                value=f"🎧 [{next_track.title}]({next_track.webpage_url})",
                inline=False,
            )

        if voice and voice.channel:
            embed.add_field(
                name="Voice Channel",
                value=f"🔊 {voice.channel.mention}",
                inline=False,
            )

        embed.set_footer(text="Live music controls")
        return embed

    def build_archived_player_embed(
        self,
        guild: discord.Guild,
        state: GuildMusicState,
        track: Track,
        *,
        title: str,
        status: str,
        icon: str,
        color: int,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"{icon} {title}",
            description=(
                f"### [{track.title}]({track.webpage_url})\n"
                f"`{track.duration_text}` • requested by <@{track.requester_id}>"
            ),
            color=color,
        )

        bot_user = self.bot.user
        if bot_user:
            embed.set_author(
                name="Nokturnal Music",
                icon_url=bot_user.display_avatar.url,
            )

        if track.thumbnail_url:
            embed.set_thumbnail(url=track.thumbnail_url)

        embed.add_field(name="Status", value=f"{icon} **{status}**", inline=True)
        embed.add_field(
            name="Queue",
            value=f"🎵 **{state.queue.qsize()}** waiting",
            inline=True,
        )

        queued = list(state.queue._queue)
        if queued:
            next_track = queued[0]
            embed.add_field(
                name="Next Up",
                value=f"🎧 [{next_track.title}]({next_track.webpage_url})",
                inline=False,
            )

        voice = guild.voice_client
        if voice and voice.channel:
            embed.add_field(
                name="Voice Channel",
                value=f"🔊 {voice.channel.mention}",
                inline=False,
            )

        embed.set_footer(text="Archived track panel")
        return embed

    async def deactivate_player_message(
        self,
        state: GuildMusicState,
        *,
        embed: discord.Embed | None = None,
    ):
        if not state.player_message:
            return

        edit_kwargs = {"view": None}
        if embed:
            edit_kwargs["embed"] = embed

        with contextlib.suppress(
            discord.Forbidden,
            discord.NotFound,
            discord.HTTPException,
        ):
            await state.player_message.edit(**edit_kwargs)
        state.player_message = None

    async def archive_player_message(
        self,
        guild: discord.Guild,
        state: GuildMusicState,
        track: Track,
        *,
        title: str,
        status: str,
        icon: str,
        color: int,
    ):
        embed = self.build_archived_player_embed(
            guild,
            state,
            track,
            title=title,
            status=status,
            icon=icon,
            color=color,
        )
        await self.deactivate_player_message(state, embed=embed)

    async def announce_now_playing(
        self,
        guild: discord.Guild,
        state: GuildMusicState,
        *,
        fresh: bool = False,
    ):
        if state.announce_channel_id is None:
            return

        channel = guild.get_channel(state.announce_channel_id)
        if channel is None and hasattr(guild, "get_thread"):
            channel = guild.get_thread(state.announce_channel_id)
        if channel is None:
            channel = self.bot.get_channel(state.announce_channel_id)
        if channel is None or not hasattr(channel, "send"):
            return

        embed = self.build_player_embed(guild, state)
        view = MusicControlView(self, guild.id)

        if fresh:
            await self.deactivate_player_message(state)

        if state.player_message:
            try:
                await state.player_message.edit(embed=embed, view=view)
                return
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                state.player_message = None

        if state.now_playing is None:
            return

        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            state.player_message = await channel.send(embed=embed, view=view)

    async def get_healthy_voice(
        self,
        guild: discord.Guild,
    ) -> discord.VoiceClient | None:
        voice = guild.voice_client
        if voice and not voice.is_connected():
            log.info("Dropping stale voice client in guild %s.", guild.id)
            with contextlib.suppress(
                discord.ClientException,
                discord.HTTPException,
                RuntimeError,
                asyncio.TimeoutError,
            ):
                await voice.disconnect(force=True)
            return None
        return voice

    async def disconnect_if_idle(
        self,
        guild: discord.Guild,
        state: GuildMusicState,
    ):
        voice = guild.voice_client
        if not voice:
            return

        if voice.is_playing() or voice.is_paused() or not state.queue.empty():
            return

        state.now_playing = None
        state.skip_requested = False
        state.stop_requested = False
        state.restart_requested = False
        log.info(
            "Disconnecting idle music voice client in guild %s after %s seconds.",
            guild.id,
            IDLE_DISCONNECT_SECONDS,
        )
        with contextlib.suppress(
            discord.ClientException,
            discord.HTTPException,
            RuntimeError,
            asyncio.TimeoutError,
        ):
            await voice.disconnect()

    async def restart_current_track(
        self,
        ctx: commands.Context,
        description: str,
    ):
        voice = ctx.guild.voice_client
        state = self.get_state(ctx.guild.id)
        if state.now_playing and voice and (voice.is_playing() or voice.is_paused()):
            state.restart_requested = True
            state.stop_requested = False
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

        if self.http_session and not self.http_session.closed:
            await self.http_session.close()

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
        voice = await self.get_healthy_voice(ctx.guild)

        if voice and voice.channel != channel:
            await voice.move_to(channel)
            await self.start_player(ctx.guild)
            return voice

        if voice:
            await self.start_player(ctx.guild)
            return voice

        try:
            voice = await channel.connect(
                timeout=VOICE_CONNECT_TIMEOUT,
                reconnect=True,
                self_deaf=True,
            )
            await self.start_player(ctx.guild)
            return voice
        except asyncio.TimeoutError:
            stale_voice = ctx.guild.voice_client
            if stale_voice:
                with contextlib.suppress(
                    discord.ClientException,
                    discord.HTTPException,
                    RuntimeError,
                    asyncio.TimeoutError,
                ):
                    await stale_voice.disconnect(force=True)

            await ctx.send(
                embed=discord.Embed(
                    description=(
                        "I timed out while joining your voice channel. "
                        "Try `,play` again in a few seconds, or switch voice "
                        "channels and try once more."
                    ),
                    color=COLOR_ERROR,
                )
            )
            return None
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

    async def extract_track(
        self,
        query: str,
        requester_id: int,
        *,
        display_title: str | None = None,
        webpage_url: str | None = None,
        duration: int | None = None,
        thumbnail_url: str | None = None,
    ) -> Track:
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
        resolved_webpage_url = webpage_url or info.get("webpage_url") or query
        title = display_title or info.get("title") or "Unknown Track"
        resolved_duration = duration if duration is not None else info.get("duration")
        resolved_thumbnail_url = thumbnail_url or info.get("thumbnail")
        http_headers = info.get("http_headers")
        if not isinstance(http_headers, dict):
            http_headers = None

        if not stream_url:
            raise commands.CommandError(
                "That link could not be turned into an audio stream."
            )

        return Track(
            title=title,
            webpage_url=resolved_webpage_url,
            stream_url=stream_url,
            requester_id=requester_id,
            duration=resolved_duration,
            thumbnail_url=resolved_thumbnail_url,
            http_headers=http_headers,
            replay_query=query,
        )

    async def refresh_track_stream(self, track: Track) -> Track:
        return await self.extract_track(
            track.replay_query or track.webpage_url or track.title,
            track.requester_id,
            display_title=track.title,
            webpage_url=track.webpage_url,
            duration=track.duration,
            thumbnail_url=track.thumbnail_url,
        )

    async def extract_spotify_track(
        self,
        spotify_track: SpotifyTrackMetadata,
        requester_id: int,
    ) -> Track:
        return await self.extract_track(
            spotify_track.search_query,
            requester_id,
            display_title=spotify_track.display_title,
            webpage_url=spotify_track.spotify_url,
            duration=spotify_track.duration,
            thumbnail_url=spotify_track.thumbnail_url,
        )

    async def queue_spotify_selection(
        self,
        ctx: commands.Context,
        voice: discord.VoiceClient,
        selection: SpotifySelection,
    ):
        state = self.get_state(ctx.guild.id)
        if state.announce_channel_id != ctx.channel.id:
            await self.deactivate_player_message(state)
        state.announce_channel_id = ctx.channel.id
        was_busy = (
            voice.is_playing()
            or voice.is_paused()
            or state.now_playing is not None
            or not state.queue.empty()
        )
        loading_message = None

        if len(selection.tracks) > 1:
            description = (
                f"Loading **{len(selection.tracks)}** Spotify track(s) from "
                f"**{selection.title}**..."
            )
            if selection.limited:
                description += (
                    f"\nOnly the first **{SPOTIFY_TRACK_LIMIT}** Spotify items "
                    "will be loaded."
                )
            loading_message = await ctx.send(
                embed=discord.Embed(
                    description=description,
                    color=COLOR_INFO,
                )
            )

        added = 0
        failed = 0
        first_track: Track | None = None

        for spotify_track in selection.tracks:
            try:
                track = await self.extract_spotify_track(
                    spotify_track,
                    ctx.author.id,
                )
            except Exception as exc:
                failed += 1
                log.warning(
                    "Could not resolve Spotify track %s to a playable source: %s",
                    spotify_track.spotify_url,
                    exc,
                )
                continue

            await state.queue.put(track)
            first_track = first_track or track
            added += 1

            if added == 1:
                await self.start_player(ctx.guild)

        if added == 0:
            embed = discord.Embed(
                description=(
                    "I found the Spotify metadata, but couldn't match any of it "
                    "to a playable audio source."
                ),
                color=COLOR_ERROR,
            )
            if loading_message:
                return await loading_message.edit(embed=embed)
            return await ctx.send(embed=embed)

        if len(selection.tracks) == 1 and first_track:
            if not was_busy:
                return
            description = (
                f"Queued Spotify track "
                f"[{first_track.title}]({first_track.webpage_url})"
            )
        else:
            description = (
                f"Queued **{added}** track(s) from Spotify "
                f"{selection.reference.kind} **{selection.title}**."
            )

        if selection.skipped_unplayable:
            description += (
                f"\nSkipped **{selection.skipped_unplayable}** Spotify item(s) "
                "that were local files, podcasts, or missing metadata."
            )
        if failed:
            description += (
                f"\nSkipped **{failed}** track(s) that could not be matched to audio."
            )
        if selection.limited:
            description += (
                f"\nLoaded **{len(selection.tracks)}** of "
                f"**{selection.total}** Spotify item(s)."
            )

        embed = discord.Embed(description=description, color=COLOR_INFO)
        if loading_message:
            await loading_message.edit(embed=embed)
        else:
            await ctx.send(embed=embed)

    async def start_player(self, guild: discord.Guild):
        state = self.get_state(guild.id)
        if state.player_task and not state.player_task.done():
            return
        state.player_task = asyncio.create_task(self.player_loop(guild))

    async def player_loop(self, guild: discord.Guild):
        state = self.get_state(guild.id)

        try:
            while True:
                try:
                    track = await asyncio.wait_for(
                        state.queue.get(),
                        timeout=IDLE_DISCONNECT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    await self.disconnect_if_idle(guild, state)
                    return

                refresh_before_play = False
                while True:
                    voice = await self.get_healthy_voice(guild)

                    if voice is None:
                        state.now_playing = None
                        state.skip_requested = False
                        state.stop_requested = False
                        await self.announce_now_playing(guild, state)
                        break

                    if refresh_before_play:
                        try:
                            track = await self.refresh_track_stream(track)
                        except Exception:
                            log.exception(
                                "Failed to refresh music stream in guild %s for %s",
                                guild.id,
                                track.webpage_url,
                            )
                            state.now_playing = None
                            state.restart_requested = False
                            state.skip_requested = False
                            state.stop_requested = False
                            await self.announce_now_playing(guild, state)
                            break
                        refresh_before_play = False

                    state.now_playing = track
                    state.last_track = track
                    state.skip_requested = False
                    state.stop_requested = False
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
                        await self.announce_now_playing(
                            guild,
                            state,
                            fresh=True,
                        )
                    except Exception:
                        log.exception(
                            "Failed to start music playback in guild %s for %s",
                            guild.id,
                            track.webpage_url,
                        )
                        state.now_playing = None
                        state.restart_requested = False
                        state.skip_requested = False
                        state.stop_requested = False
                        await self.announce_now_playing(guild, state)
                        break

                    await finished.wait()

                    if state.restart_requested:
                        await self.archive_player_message(
                            guild,
                            state,
                            track,
                            title="Restarting Track",
                            status="Getting a fresh stream",
                            icon="🔄",
                            color=COLOR_INFO,
                        )
                        state.restart_requested = False
                        refresh_before_play = True
                        continue

                    if state.loop_enabled and not state.skip_requested:
                        await self.archive_player_message(
                            guild,
                            state,
                            track,
                            title="Looping Track",
                            status="Replaying now",
                            icon="🔁",
                            color=COLOR_INFO,
                        )
                        refresh_before_play = True
                        continue

                    if state.stop_requested:
                        archive_title = "Playback Stopped"
                        archive_status = "Stopped • not playing"
                        archive_icon = "⏹️"
                    elif state.skip_requested:
                        archive_title = "Track Skipped"
                        archive_status = "Skipped • not playing"
                        archive_icon = "⏭️"
                    else:
                        archive_title = "Track Finished"
                        archive_status = "Ended • not playing"
                        archive_icon = "✅"

                    await self.archive_player_message(
                        guild,
                        state,
                        track,
                        title=archive_title,
                        status=archive_status,
                        icon=archive_icon,
                        color=COLOR_INFO,
                    )
                    state.now_playing = None
                    state.skip_requested = False
                    state.stop_requested = False
                    break
        finally:
            if state.player_task is asyncio.current_task():
                state.player_task = None

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

        spotify_reference = parse_spotify_reference(query)
        if spotify_reference:
            try:
                selection = await self.resolve_spotify_reference(spotify_reference)
                return await self.queue_spotify_selection(ctx, voice, selection)
            except commands.CommandError as exc:
                return await ctx.send(
                    embed=discord.Embed(
                        description=str(exc),
                        color=COLOR_ERROR,
                    )
                )
            except Exception as exc:
                log.exception("Failed to load Spotify link %s", spotify_reference.url)
                return await ctx.send(
                    embed=discord.Embed(
                        description=f"Failed to load that Spotify link: {exc}",
                        color=COLOR_ERROR,
                    )
                )

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
        if state.announce_channel_id != ctx.channel.id:
            await self.deactivate_player_message(state)
        state.announce_channel_id = ctx.channel.id
        was_busy = (
            voice.is_playing()
            or voice.is_paused()
            or state.now_playing is not None
            or not state.queue.empty()
        )
        await state.queue.put(track)
        await self.start_player(ctx.guild)

        if was_busy:
            await ctx.send(
                embed=discord.Embed(
                    description=f"Queued [{track.title}]({track.webpage_url})",
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
        state.stop_requested = False
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
        await self.announce_now_playing(ctx.guild, self.get_state(ctx.guild.id))
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
        await self.announce_now_playing(ctx.guild, self.get_state(ctx.guild.id))
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

        was_active = voice.is_playing() or voice.is_paused()
        self.clear_queue(state)

        state.now_playing = None
        state.loop_enabled = False
        state.skip_requested = True
        state.stop_requested = True
        state.restart_requested = False
        if was_active:
            voice.stop()
        else:
            await self.announce_now_playing(ctx.guild, state)

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
        state.stop_requested = True
        state.restart_requested = False
        if voice.is_playing() or voice.is_paused():
            voice.stop()
        await voice.disconnect()
        await self.announce_now_playing(ctx.guild, state)

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

        state.announce_channel_id = ctx.channel.id
        await self.deactivate_player_message(state)
        state.player_message = await ctx.send(
            embed=self.build_player_embed(ctx.guild, state),
            view=MusicControlView(self, ctx.guild.id),
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
        state.stop_requested = False
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
        state.announce_channel_id = ctx.channel.id
        await self.deactivate_player_message(state)
        state.player_message = await ctx.send(
            embed=self.build_player_embed(ctx.guild, state),
            view=MusicControlView(self, ctx.guild.id),
        )


async def setup(bot):
    await bot.add_cog(Music(bot))
