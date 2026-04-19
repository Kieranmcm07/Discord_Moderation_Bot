# Discord Moderation Bot

A Discord bot focused on moderation, staff workflows, and day-to-day server utilities.
It is built with `discord.py` and SQLite, so it is easy to run locally without extra services.

This project is especially suited to small and mid-sized servers that want:

- solid moderation tools
- readable staff-facing embeds
- ticket support
- activity tracking
- server customization without a web dashboard

## Highlights

- Moderation commands for bans, tempbans, kicks, warns, timeouts, purge, clean, and slowmode
- Warning escalation rules that can automatically timeout, kick, or ban after a threshold
- Case tracking with history, recent cases, case search, and follow-up case comments
- Invite logging with join context and a basic account-age check
- Activity tracking for chat and voice with leaderboards and per-user stats
- Ticket system with category buttons, transcripts, staff roles, and private ticket channels
- Sticky messages, autorole, polls, announcements, lock/unlock, and nickname tools
- Reaction-role buttons so members can self-assign roles
- Server branding for embeds with custom color plus an optional shared image or GIF
- Custom help command grouped by feature area

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
py -3 main.py
```

If `py` is not available on your system, use the Python command name that works on your machine.

## Windows Startup Scripts

The repo includes helper scripts for Windows:

- `start_bot.bat`: launches the bot with the custom startup flow
- `install_startup.bat`: adds the bot to Windows startup
- `remove_startup.bat`: removes the startup entry

## Configuration

Environment values live in `.env`.

| Variable | Description |
| --- | --- |
| `BOT_TOKEN` | Your Discord bot token |
| `PREFIX` | Prefix for text commands |
| `OWNER_IDS` | Comma-separated user IDs for bot owners |
| `DB_PATH` | SQLite database path |
| `MOD_LOG_CHANNEL_ID` | Optional moderation log channel |
| `INVITE_LOG_CHANNEL_ID` | Optional invite log channel |
| `JOIN_LOG_CHANNEL_ID` | Optional join/leave log channel |

Guild-specific customization is handled through commands such as:

- `,settings`
- `,setembedcolor`
- `,setembedimage`
- `,setwelcomechannel`
- `,setwelcomemessage`
- `,setleavechannel`
- `,setleavemessage`

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
| `,searchcases <query>` | Search recent cases by action or reason text |
| `,casecomment <case_id> <note>` | Add a follow-up note linked to an existing case |

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
| `,setembedimage <url>` | Set a shared image or GIF for bot embeds |
| `,clearembedimage` | Remove the shared image or GIF from bot embeds |

### Reaction Roles

| Command | Description |
| --- | --- |
| `,rradd @role [Label \| Emoji]` | Add or update a self-assignable role option |
| `,rrremove @role` | Remove a self-assignable role option |
| `,rrlist` | List configured reaction roles |
| `,rrpanel [#channel]` | Post the role button panel |

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
| `,setticketcategory <category>` | Set the category where ticket channels are created |
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

### Other

| Command | Description |
| --- | --- |
| `,help [command]` | Show grouped help or detailed help for one command |
| `,invites` | Show active invites in the server |

## Embed Branding

The bot now applies shared branding to embeds more consistently.

- The bot avatar is used as the thumbnail automatically
- Branded embeds get a cleaner shared footer
- Guilds can set a custom embed color
- Guilds can optionally set one image or GIF that appears under bot embeds

This makes the bot feel more polished without requiring every command to be redesigned by hand.

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
|   |-- reaction_roles.py
|   |-- server_management.py
|   `-- tickets.py
|-- data/
|-- utils/
|   |-- db.py
|   `-- embeds.py
|-- .env.example
|-- config.py
|-- launcher.py
|-- main.py
`-- requirements.txt
```

## Notes

- The bot stores its data in SQLite, by default at `data/bot.db`.
- The custom help command is available with `,help`.
- Temporary bans are automatically checked and lifted in the background while the bot is online.
- Welcome and leave templates support `{user}`, `{username}`, `{server}`, and `{count}` placeholders.
- Voice tracking is lightweight and only records time while the bot is running.

## License

This project is licensed under the MIT License.
