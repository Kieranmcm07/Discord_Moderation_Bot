"""
cogs/fun.py - a few fun community commands.
"""

import random
from urllib.parse import quote

import discord
from discord.ext import commands

from config import COLOR_INFO, COLOR_SUCCESS
from utils.embeds import make_embed


EIGHT_BALL_ANSWERS = [
    "Yes, that looks likely.",
    "No, I would not count on it.",
    "Probably, but keep an eye on it.",
    "Definitely not this time.",
    "Ask again later.",
    "Signs point to yes.",
    "Very unlikely.",
    "Absolutely.",
]

JOKES = [
    (
        "Why did the moderator bring a ladder?",
        "To keep the conversation on a higher level.",
    ),
    (
        "Why did the Discord bot go to school?",
        "It wanted to improve its message content.",
    ),
    (
        "Why was the server so calm?",
        "Because everyone knew the rules and the bot had receipts.",
    ),
    (
        "Why did the developer name the bot Echo?",
        "Because every bug came back eventually.",
    ),
    (
        "Why did the music command sit down?",
        "It needed to queue up properly.",
    ),
]

MEME_TEMPLATES = [
    ("drake", "Discord bot before polish", "Discord bot after daily commits"),
    ("buzz", "Adding one tiny feature", "Calling it a productivity arc"),
    ("doge", "such moderation", "very embed"),
    ("success", "I fixed one bug", "And nothing else broke"),
    ("fry", "Not sure if clean code", "Or just the tests passing"),
    ("both", "Fix bugs", "Add memes"),
]


class Fun(commands.Cog, name="Fun"):
    """Light fun commands for your server."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        name="8ball", aliases=["eightball"], help="Ask the magic 8-ball a question."
    )
    async def eightball(self, ctx, *, question: str):
        answer = random.choice(EIGHT_BALL_ANSWERS)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="8-Ball",
            description=f"**Question:** {question}\n**Answer:** {answer}",
            color=COLOR_INFO,
        )
        await ctx.send(embed=embed)

    @commands.command(name="coinflip", aliases=["flip"], help="Flip a coin.")
    async def coinflip(self, ctx):
        result = random.choice(["Heads", "Tails"])
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Coin Flip",
            description=f"The coin landed on **{result}**.",
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(name="roll", help="Roll a number between 1 and a maximum.")
    async def roll(self, ctx, maximum: int = 100):
        maximum = max(2, min(maximum, 1000))
        result = random.randint(1, maximum)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Dice Roll",
            description=f"You rolled **{result}** out of **{maximum}**. Nice.",
        )
        await ctx.send(embed=embed)

    @commands.command(name="choose", help="Choose between options split by |.")
    async def choose(self, ctx, *, options: str):
        choices = [choice.strip() for choice in options.split("|") if choice.strip()]
        if len(choices) < 2:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                description="Give me at least two options separated by `|`.",
            )
            return await ctx.send(embed=embed)

        selection = random.choice(choices)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Choice Made",
            description=f"I pick **{selection}**.",
        )
        await ctx.send(embed=embed)

    @commands.command(name="joke", help="Tell a random clean joke.")
    async def joke(self, ctx):
        setup, punchline = random.choice(JOKES)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Joke",
            description=f"{setup}\n\n**{punchline}**",
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(
        name="meme",
        aliases=["randommeme"],
        help="Post a random generated meme image.",
    )
    async def meme(self, ctx, *, caption: str = None):
        template, top_text, bottom_text = random.choice(MEME_TEMPLATES)

        if caption:
            parts = [part.strip() for part in caption.split("|", 1)]
            top_text = parts[0] or top_text
            if len(parts) > 1 and parts[1]:
                bottom_text = parts[1]

        image_url = (
            f"https://api.memegen.link/images/{template}/"
            f"{quote(top_text, safe='')}/{quote(bottom_text, safe='')}.png"
        )
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Random Meme",
            description="Freshly generated and probably questionable life advice.",
            color=COLOR_INFO,
        )
        embed.set_image(url=image_url)
        await ctx.send(embed=embed)

    @commands.command(name="ship", help="Ship two members together for fun.")
    async def ship(self, ctx, member_one: discord.Member, member_two: discord.Member):
        score = random.randint(1, 100)
        if score >= 90:
            status = "A legendary match."
        elif score >= 70:
            status = "Pretty strong."
        elif score >= 40:
            status = "There might be something there."
        else:
            status = "This one needs some work."

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Ship Calculator",
            description=(
                f"{member_one.mention} + {member_two.mention} = **{score}%**\n"
                f"{status}"
            ),
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Fun(bot))
