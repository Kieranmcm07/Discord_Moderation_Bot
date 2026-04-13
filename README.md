# 🔨 My Discord Moderation Bot

A fully featured Discord moderation and utility bot I built for my server.
Built with [discord.py](https://discordpy.readthedocs.io/) and SQLite.

## Features

- **Moderation** — ban, kick, timeout, warn, unban, purge, slowmode
- **Case Tracking** — every mod action gets a case number, lookup by user or case ID
- **Invite Logging** — tracks which invite each new member used to join
- **Activity Stats** — message leaderboards, voice time tracking, per-user stats
- **Server Management** — server info, user info, role info, channel lock/unlock, announcements
- **Tickets** — button-based private support tickets with staff roles, close controls, and transcripts

---

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/yourusername/your-bot-repo.git
cd your-bot-repo
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Create your `.env` file
```bash
cp .env.example .env
```
Then open `.env` and paste in your bot token and config.

### 4. Run it
```bash
python main.py
```

### Windows local startup
If you want the bot to boot with Windows using a visible command prompt splash screen and then continue hidden in the background:

```bat
start_bot.bat
```

To add it to Windows startup automatically:

```bat
install_startup.bat
```

To remove it from startup later:

```bat
remove_startup.bat
```

What happens on startup:
- a command prompt window opens
- a large ASCII startup banner is shown
- the bot launches in the background
- a green `BOT ONLINE` success banner is shown if startup succeeds
- the command prompt closes after success
- if startup fails, a red failure banner stays open so you can read the error

---

## Config

All settings live in `.env`:

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Your bot token from the Discord Developer Portal |
| `PREFIX` | Command prefix — default is `,` |
| `OWNER_IDS` | Comma-separated Discord user IDs for bot owners |
| `MOD_LOG_CHANNEL_ID` | Channel ID to post mod action logs (optional) |
| `INVITE_LOG_CHANNEL_ID` | Channel ID for invite logs (optional) |
| `JOIN_LOG_CHANNEL_ID` | Channel ID for join/leave events (optional) |

---

## Commands

### Moderation
| Command | Description |
|---|---|
| `,ban @user [reason]` | Ban a user |
| `,unban <id> [reason]` | Unban by user ID |
| `,kick @user [reason]` | Kick a user |
| `,warn @user [reason]` | Issue a warning |
| `,timeout @user [duration] [reason]` | Timeout a user (10s, 5m, 2h, 1d) |
| `,untimeout @user` | Remove a timeout |
| `,purge <amount>` | Bulk delete messages |
| `,slowmode [seconds]` | Set channel slowmode |

### Cases
| Command | Description |
|---|---|
| `,case <id>` | Look up a case by number |
| `,history @user` | All cases for a user |
| `,recentcases [limit]` | Recent mod actions |

### Activity
| Command | Description |
|---|---|
| `,topchat [limit]` | Message count leaderboard |
| `,topvoice [limit]` | Voice time leaderboard |
| `,stats [@user]` | Stats for a user |

### Server

| Command | Description |
|---|---|
| `,serverinfo` | Server details |
| `,userinfo [@user]` | User details |
| `,avatar [@user]` | User's avatar |
| `,roleinfo <role>` | Role details |
| `,lock [#channel]` | Lock a channel |
| `,unlock [#channel]` | Unlock a channel |
| `,announce #channel <msg>` | Post an announcement |
| `,botinfo` | Bot stats |

### Tickets
| Command | Description |
|---|---|
| `,setticketcategory <category>` | Set the category for created ticket channels |
| `,setticketlog <#channel>` | Set the log channel for ticket events and transcripts |
| `,ticketroleadd <role>` | Allow a role to see and manage tickets |
| `,ticketroleremove <role>` | Remove a role from ticket access |
| `,ticketroles` | Show current ticket staff roles |
| `,ticketcategoryadd Name \| Emoji \| Description` | Add a ticket category button |
| `,ticketcategoryremove <id>` | Remove a ticket category button |
| `,ticketcategories` | List configured ticket categories |
| `,ticketpanel [#channel]` | Post the create-ticket panel |
| `,ticketsettings` | Show the current ticket setup |
| `,ticketadd @user` | Add a user to the current ticket |
| `,ticketremove @user` | Remove a user from the current ticket |
| `,closeticket` | Close the current ticket |

---

## Required Bot Permissions

In the Discord Developer Portal, make sure these are enabled:
- **Privileged Intents:** Server Members Intent, Message Content Intent
- **Bot Permissions:** Ban Members, Kick Members, Moderate Members, Manage Messages, Manage Channels, Manage Guild, View Audit Log, Send Messages, Embed Links, Read Message History

---

## Project Structure

```
.
├── main.py                    # bot entry point
├── config.py                  # settings loaded from .env
├── requirements.txt
├── .env.example               # copy this to .env
├── cogs/
│   ├── moderation.py          # ban, kick, warn, timeout, purge
│   ├── cases.py               # case lookup and history
│   ├── invite_logger.py       # invite + join/leave tracking
│   ├── activity.py            # message & voice stats
│   ├── server_management.py   # server/user info, lock, announce
│   └── help.py                # custom help command
└── utils/
    └── db.py                  # all database logic (SQLite)
```

---

## License

MIT - do whatever you want with it.
