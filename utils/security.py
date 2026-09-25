"""Read-only permission analysis using discord.py's effective permissions."""

from dataclasses import dataclass

import discord


DANGEROUS_PERMISSIONS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_webhooks", "ban_members", "kick_members", "moderate_members",
    "manage_messages", "mention_everyone", "view_audit_log",
)
ACCESS_PERMISSIONS = (
    "view_channel", "send_messages", "read_message_history", "attach_files",
    "embed_links", "add_reactions", "manage_messages", "manage_webhooks",
)
SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "REVIEW": 2}


def label(permission: str) -> str:
    return permission.replace("_", " ").title()


def safe_name(value: str, limit: int = 100) -> str:
    return discord.utils.escape_markdown(discord.utils.escape_mentions(value[:limit]))


@dataclass(frozen=True)
class Finding:
    severity: str
    title: str
    detail: str
    recommendation: str


def audit_permissions(guild, *, public_role_ids=(), log_channels=None) -> list[Finding]:
    """Audit configured access paths, not guessed staff-channel names.

    Role projections mean @everyone plus that single role; they intentionally do
    not claim to enumerate every member's role combination or member overwrite.
    """
    findings = []
    public_ids = set(public_role_ids) - {guild.id}
    public_roles = []
    for role_id in sorted(public_ids):
        role = guild.get_role(role_id)
        if role is None:
            findings.append(Finding(
                "WARNING", "Configured role no longer exists",
                f"Automatic/self-assignable role ID {role_id} could not be found.",
                "Review autorole and reaction-role settings and remove the stale entry.",
            ))
        else:
            public_roles.append(role)

    for role in guild.roles:
        dangerous = [label(p) for p in DANGEROUS_PERMISSIONS if getattr(role.permissions, p)]
        role_ref = f"{safe_name(role.name)} (ID {role.id})"
        if dangerous and (role.is_default() or role.id in public_ids):
            findings.append(Finding(
                "CRITICAL", "Powerful permissions on a public role",
                f"{role_ref}: {', '.join(dangerous)}. "
                + ("This is the everyone role." if role.is_default()
                   else "This role is configured for automatic or self assignment."),
                "Remove these permissions or remove the role from public assignment. "
                "Review members who already hold it; removing a panel does not revoke roles.",
            ))
        elif role.permissions.administrator:
            findings.append(Finding(
                "REVIEW", "Administrator bypasses channel restrictions",
                f"{role_ref} grants Administrator. Private-channel denies and ordinary locks do not restrict it.",
                "Keep only where full server access is intended; use narrower permissions otherwise.",
            ))

    for channel_id, purposes in sorted((log_channels or {}).items()):
        channel = guild.get_channel(channel_id)
        purpose = ", ".join(purposes)
        if channel is None or not hasattr(channel, "permissions_for"):
            findings.append(Finding(
                "WARNING", "Configured staff log is unavailable",
                f"{purpose}: channel ID {channel_id} is missing from the bot's guild cache.",
                "Check the channel still exists and update the relevant log setting.",
            ))
            continue
        ref = f"#{safe_name(channel.name)} (ID {channel.id}; {purpose})"
        everyone_access = channel.permissions_for(guild.default_role).view_channel
        if everyone_access:
            findings.append(Finding(
                "CRITICAL", "Staff log visible to the everyone role",
                f"{ref} permits View Channel for the everyone-role baseline. "
                "Logs may contain moderation reasons, deleted content, or ticket transcripts.",
                "Deny View Channel for everyone and allow only intended staff and the bot. "
                "Review role and member overrides too.",
            ))
        else:
            for role in public_roles:
                if channel.permissions_for(role).view_channel:
                    findings.append(Finding(
                        "CRITICAL", "Publicly assigned role can view a staff log",
                        f"{ref} is visible with {safe_name(role.name)} (ID {role.id}) plus everyone.",
                        "Remove this access path or stop publicly assigning the role. "
                        "Check existing role holders and member-specific overrides.",
                    ))
        if guild.me:
            permissions = channel.permissions_for(guild.me)
            required = ["view_channel", "send_messages", "embed_links"]
            if "Ticket transcripts" in purposes:
                required.append("attach_files")
            missing = [label(p) for p in required if not getattr(permissions, p)]
            if missing:
                findings.append(Finding(
                    "WARNING", "Bot cannot deliver the configured log",
                    f"{ref}: missing {', '.join(missing)}.",
                    "Grant the bot these permissions in this channel.",
                ))

    for channel in guild.text_channels:
        for role in [guild.default_role, *public_roles]:
            overwrite = channel.overwrites_for(role)
            local_grants = [
                label(p) for p in ("manage_channels", "manage_roles", "manage_webhooks", "manage_messages", "mention_everyone")
                if getattr(overwrite, p) is True and not getattr(role.permissions, p)
            ]
            if local_grants:
                effective = channel.permissions_for(role)
                if effective.view_channel:
                    findings.append(Finding(
                        "CRITICAL", "Powerful channel overrides on a public role",
                        f"#{safe_name(channel.name)} (ID {channel.id}) explicitly grants "
                        f"{', '.join(local_grants)} to {safe_name(role.name)} (ID {role.id}).",
                        "Remove unintended channel grants for everyone and automatically/self-assigned roles.",
                    ))
        if channel.overwrites_for(guild.default_role).send_messages is not False:
            continue
        for target, overwrite in channel.overwrites.items():
            if not isinstance(target, discord.Role) or target.is_default():
                continue
            if overwrite.send_messages is not True or target.permissions.administrator:
                continue
            effective = channel.permissions_for(target)
            if effective.view_channel and effective.send_messages:
                findings.append(Finding(
                    "REVIEW", "Role allowance bypasses an everyone send deny",
                    f"#{safe_name(channel.name)} (ID {channel.id}) denies everyone Send Messages, "
                    f"but {safe_name(target.name)} (ID {target.id}) explicitly allows it.",
                    "Keep intentional staff exceptions. Remove this role allowance if the role should be locked out.",
                ))
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], f.title, f.detail))


def explain_access(member, channel) -> tuple[discord.Permissions, list[str]]:
    """Trace relevant overwrite inputs; final results come from discord.py."""
    guild = channel.guild
    effective = channel.permissions_for(member)
    if member.id == guild.owner_id:
        return effective, ["Server owner: channel overwrites are bypassed."]
    admin_roles = [r for r in member.roles if r.permissions.administrator]
    if admin_roles:
        return effective, [
            "Administrator granted by " + ", ".join(safe_name(r.name) for r in admin_roles)
            + ": channel overwrites are bypassed."
        ]
    trace = []
    for permission in ACCESS_PERMISSIONS:
        grants = [safe_name(r.name) for r in member.roles if getattr(r.permissions, permission)]
        stages = ["server roles: " + (", ".join(grants) if grants else "not granted")]
        everyone = getattr(channel.overwrites_for(guild.default_role), permission)
        if everyone is not None:
            stages.append("everyone overwrite: " + ("allow" if everyone else "deny"))
        allows, denies = [], []
        for role in member.roles:
            if role.is_default():
                continue
            value = getattr(channel.overwrites_for(role), permission)
            if value is True:
                allows.append(safe_name(role.name))
            elif value is False:
                denies.append(safe_name(role.name))
        if denies:
            stages.append("role denies: " + ", ".join(denies))
        # Discord combines role overwrites: any allow wins over the combined role denies.
        if allows:
            stages.append("role allows: " + ", ".join(allows) + " (wins over role denies)")
        personal = getattr(channel.overwrites_for(member), permission)
        if personal is not None:
            stages.append("member overwrite: " + ("allow" if personal else "deny"))
        trace.append(f"{label(permission)}: " + " → ".join(stages))
    if member.is_timed_out():
        trace.append("Active timeout: permissions other than View Channel and Read Message History are removed.")
    if not effective.view_channel:
        trace.append("View Channel is denied: channel actions are unavailable regardless of other grants.")
    elif not effective.send_messages:
        trace.append("Send Messages is denied: attachment and embed permissions are also unavailable.")
    return effective, trace


def build_report(guild, findings: list[Finding], generated_at) -> str:
    lines = [
        f"Server Security Center — {guild.name} ({guild.id})",
        f"Generated: {generated_at.isoformat()}",
        "Scope: cached guild roles/text channels and this bot's configured public roles and staff logs.",
        "Role projections use everyone plus one role. Member combinations/overwrites are not exhaustively scanned.",
        "Review findings in context. No findings does not certify the server as secure.", "",
    ]
    for index, finding in enumerate(findings, 1):
        lines.extend([
            f"{index}. [{finding.severity}] {finding.title}", finding.detail,
            f"Suggested action: {finding.recommendation}", "",
        ])
    if not findings:
        lines.append("No findings in the checks performed.")
    return "\n".join(lines)
