# Discord Moderation Bot

A Discord bot focused on moderation, staff workflows, and day-to-day server utilities.
It is built with `discord.py` and SQLite, so it is easy to run locally without extra services.

## What It Can Do

- Moderation commands: `ban`, `tempban`, `kick`, `warn`, `timeout`, `unban`, `purge`, `clean`, `slowmode`
- Warning escalation rules: automatically timeout, kick, or ban members after a chosen warning threshold
- Case tracking: every moderation action is saved with a case ID for later lookup
- Invite logging: track which invite was used when members join
- Activity stats: message leaderboard, voice time leaderboard, and per-user stats
- Server utilities: server info, user info, role info, announcements, nickname tools, lock/unlock
- Tickets: private support tickets with staff roles, categories, and transcripts
- Autorole: automatically give new members a starter role
- Sticky messages: keep important channel guidance visible at the bottom of a channel
- Polls: create simple reaction-based polls
- Welcome and leave messages: configure custom join/leave embeds with placeholders
- Embed theming: use the bot avatar as branding and set a server-wide embed color
- Fun commands: `8ball`, `coinflip`, `roll`, `choose`, `ship`

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/Kieranmcm07/Discord_Moderation_Bot.git
cd Discord_Moderation_Bot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create your environment file

Copy `.env.example` to `.env`, then fill in your values.

```bash
copy .env.example .env
```

Minimum required values:

```env
BOT_TOKEN=YOUR_BOT_TOKEN_HERE
PREFIX=,
```

### 4. Run the bot

```bash
python main.py
```

## Windows Startup Scripts

The repo includes a few helper scripts for Windows:

- `start_bot.bat`: launches the bot with the custom startup flow
- `install_startup.bat`: adds the bot to Windows startup
- `remove_startup.bat`: removes the startup entry

## Configuration

All settings live in `.env`.

| Variable | Description |
| --- | --- |
| `BOT_TOKEN` | Your Discord bot token |
| `PREFIX` | Prefix for text commands |
| `OWNER_IDS` | Comma-separated user IDs for bot owners |
| `DB_PATH` | SQLite database path |
| `MOD_LOG_CHANNEL_ID` | Optional moderation log channel |
| `INVITE_LOG_CHANNEL_ID` | Optional invite log channel |
| `JOIN_LOG_CHANNEL_ID` | Optional join/leave log channel |

## Commands

### Moderation

| Command | Description |
| --- | --- |
| `,ban @user [reason]` | Ban a member |
| `,tempban @user <duration> [reason]` | Ban a member for a limited time |
| `,tempbans` | Show active temporary bans |
| `,unban <user_id> [reason]` | Unban a user by ID |
| `,kick @user [reason]` | Kick a member |
| `,warn @user [reason]` | Warn a member |
| `,warnings @user` | Show active warning count |
| `,clearwarns @user [amount] [reason]` | Remove recent warnings |
| `,note @user <note>` | Add a private moderator note |
| `,timeout @user [duration] [reason]` | Timeout a member |
| `,untimeout @user [reason]` | Remove a timeout |
| `,purge <amount>` | Delete recent messages |
| `,clean <amount> [@user]` | Delete recent messages, optionally from one user |
| `,slowmode [seconds]` | Set channel slowmode |
| `,setescalation <warns> <action> [duration]` | Configure automatic punishments |
| `,removeescalation <warns>` | Remove an escalation rule |
| `,escalations` | List escalation rules |

### Cases

| Command | Description |
| --- | --- |
| `,case <id>` | Look up one case |
| `,history @user` | Show a user's moderation history |
| `,recentcases [limit]` | Show recent moderation actions |

### Activity

| Command | Description |
| --- | --- |
| `,topchat [limit]` | Show top message senders |
| `,topvoice [limit]` | Show top voice users |
| `,stats [@user]` | Show stats for a user |

### Server Management

| Command | Description |
| --- | --- |
| `,serverinfo` | Show server details |
| `,userinfo [@user]` | Show user details |
| `,avatar [@user]` | Show a user's avatar |
| `,roleinfo <role>` | Show role details |
| `,announce #channel <message>` | Send an announcement embed |
| `,poll Question \| Option 1 \| Option 2` | Create a reaction poll |
| `,lock [#channel] [reason]` | Lock a channel |
| `,unlock [#channel] [reason]` | Unlock a channel |
| `,nick @user <nickname>` | Change a member's nickname |
| `,resetnick @user` | Reset a nickname |
| `,setautorole <role>` | Set the automatic join role |
| `,autorole` | View the current autorole |
| `,clearautorole` | Disable autorole |
| `,setsticky [#channel] <message>` | Set a sticky message |
| `,sticky [#channel]` | View a sticky message |
| `,stickies` | List all sticky messages |
| `,clearsticky [#channel]` | Remove a sticky message |
| `,botinfo` | Show bot stats |

### Configuration

| Command | Description |
| --- | --- |
| `,settings` | Show the current bot setup for the server |
| `,setwelcomechannel #channel` | Set the custom welcome channel |
| `,setwelcomemessage <message>` | Set the custom welcome template |
| `,setleavechannel #channel` | Set the custom leave channel |
| `,setleavemessage <message>` | Set the custom leave template |
| `,setembedcolor <hex>` | Set the default embed color |

### Fun

| Command | Description |
| --- | --- |
| `,8ball <question>` | Ask the magic 8-ball a question |
| `,coinflip` | Flip a coin |
| `,roll [max]` | Roll a number |
| `,choose Option 1 \| Option 2` | Let the bot choose between options |
| `,ship @user1 @user2` | Generate a fun ship score |

### Tickets

| Command | Description |
| --- | --- |
| `,setticketcategory <category>` | Set the ticket category |
| `,setticketlog <#channel>` | Set the ticket log channel |
| `,ticketroleadd <role>` | Allow a role to access tickets |
| `,ticketroleremove <role>` | Remove a ticket staff role |
| `,ticketroles` | Show ticket staff roles |
| `,ticketcategoryadd Name \| Emoji \| Description` | Add a ticket type |
| `,ticketcategoryremove <id>` | Remove a ticket type |
| `,ticketcategories` | List ticket types |
| `,ticketpanel [#channel]` | Post the ticket panel |
| `,ticketsettings` | Show ticket settings |
| `,ticketadd @user` | Add a user to the ticket |
| `,ticketremove @user` | Remove a user from the ticket |
| `,closeticket` | Close the current ticket |

## Required Discord Permissions

Recommended bot permissions:

- View Channels
- Send Messages
- Embed Links
- Read Message History
- Manage Messages
- Manage Channels
- Manage Roles
- Manage Nicknames
- Kick Members
- Ban Members
- Moderate Members
- Manage Guild
- View Audit Log

Recommended privileged intents:

- Server Members Intent
- Message Content Intent

## Project Structure

```text
.
|-- cogs/
|   |-- activity.py
|   |-- cases.py
|   |-- configuration.py
|   |-- fun.py
|   |-- help.py
|   |-- invite_logger.py
|   |-- moderation.py
|   |-- music.py
|   |-- server_management.py
|   `-- tickets.py
|-- data/
|-- utils/
|   `-- db.py
|-- .env.example
|-- config.py
|-- launcher.py
|-- main.py
`-- requirements.txt
```

## Notes

- The bot stores its data in SQLite, by default at `data/bot.db`.
- The custom help command is available with `,help`.
- Temporary bans are automatically checked and lifted in the background.
- Welcome/leave templates support `{user}`, `{username}`, `{server}`, and `{count}` placeholders.

## License

This project is licensed under the MIT License.
