"""
cogs/fun.py - a few fun community commands.
"""

import random

import discord
from discord.ext import commands

from config import COLOR_INFO, COLOR_SUCCESS
from utils.embeds import make_embed


EIGHT_BALL_ANSWERS = [
    "Yes.",
    "No.",
    "Probably.",
    "Definitely not.",
    "Ask again later.",
    "Signs point to yes.",
    "Very unlikely.",
    "Absolutely.",
]


class Fun(commands.Cog, name="Fun"):
    """Light fun commands for your server."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        name="8ball", aliases=["eightball"], help="Ask the magic 8-ball a question."
    )
    async def eightball(self, ctx, *, question: str):
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="8-Ball",
            description=f"**Question:** {question}\n**Answer:** {random.choice(EIGHT_BALL_ANSWERS)}",
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
            description=f"You rolled **{result}** out of **{maximum}**.",
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
            description=f"I pick: **{selection}**",
        )
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
