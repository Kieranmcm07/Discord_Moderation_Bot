"""Permission regressions using real discord.py guild/member/channel objects."""

import inspect
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from discord.ext import commands

from cogs.security import Security, SecurityView
from utils import db
from utils.security import Finding, audit_permissions, build_report, explain_access


def role_payload(role_id, name, **permissions):
    return {"id": str(role_id), "name": name, "permissions": str(discord.Permissions(**permissions).value),
            "position": role_id, "color": 0, "hoist": False, "managed": False, "mentionable": False}


def overwrite(target_id, *, member=False, **values):
    allow, deny = discord.PermissionOverwrite(**values).pair()
    return {"id": str(target_id), "type": int(member), "allow": str(allow.value), "deny": str(deny.value)}


def make_guild(*, extra_roles=(), overrides=(), member_roles=(), timeout=False, owner_id=999):
    client = discord.Client(intents=discord.Intents.all())
    client._connection.user = SimpleNamespace(id=900)
    guild = discord.Guild(state=client._connection, data={
        "id": "1", "name": "Test server", "owner_id": str(owner_id),
        "roles": [role_payload(1, "@everyone", view_channel=True, send_messages=True,
                               read_message_history=True, attach_files=True, embed_links=True), *extra_roles],
        "channels": [{"id": "10", "type": 0, "name": "staff-log", "position": 0,
                      "permission_overwrites": list(overrides)}],
        "members": [{"user": {"id": "50", "username": "Test member", "discriminator": "0", "avatar": None},
                     "roles": [str(r) for r in member_roles], "flags": 0,
                     "joined_at": "2026-01-01T00:00:00+00:00",
                     "communication_disabled_until": (discord.utils.utcnow() + timedelta(hours=1)).isoformat() if timeout else None}],
    })
    return guild, guild.get_member(50), guild.get_channel(10)


class PermissionTests(unittest.TestCase):
    def test_role_allow_beats_other_role_deny_even_if_lower(self):
        guild, member, channel = make_guild(
            extra_roles=[role_payload(2, "Allow"), role_payload(3, "Deny")], member_roles=[2, 3],
            overrides=[overwrite(1, send_messages=False), overwrite(2, send_messages=True), overwrite(3, send_messages=False)],
        )
        effective, trace = explain_access(member, channel)
        self.assertTrue(effective.send_messages)
        self.assertIn("wins over role denies", "\n".join(trace))
        self.assertEqual(len(audit_permissions(guild)), 1)

    def test_member_deny_wins_over_role_allow(self):
        _, member, channel = make_guild(
            extra_roles=[role_payload(2, "Allow")], member_roles=[2],
            overrides=[overwrite(2, send_messages=True), overwrite(50, member=True, send_messages=False)],
        )
        effective, trace = explain_access(member, channel)
        self.assertFalse(effective.send_messages)
        self.assertFalse(effective.attach_files)
        self.assertIn("member overwrite: deny", "\n".join(trace))

    def test_member_allow_wins_over_role_deny(self):
        _, member, channel = make_guild(overrides=[
            overwrite(1, view_channel=False), overwrite(50, member=True, view_channel=True),
        ])
        self.assertTrue(explain_access(member, channel)[0].view_channel)

    def test_view_deny_removes_implicit_actions(self):
        _, member, channel = make_guild(overrides=[overwrite(1, view_channel=False)])
        effective, trace = explain_access(member, channel)
        self.assertFalse(effective.send_messages)
        self.assertIn("View Channel is denied", trace[-1])

    def test_timeout_overrides_allowed_send(self):
        _, member, channel = make_guild(timeout=True)
        effective, trace = explain_access(member, channel)
        self.assertTrue(effective.view_channel)
        self.assertFalse(effective.send_messages)
        self.assertIn("Active timeout", "\n".join(trace))

    def test_owner_and_administrator_bypass_denies(self):
        for kwargs in ({"owner_id": 50}, {"extra_roles": [role_payload(2, "Admin", administrator=True)], "member_roles": [2]}):
            with self.subTest(kwargs=kwargs):
                _, member, channel = make_guild(overrides=[overwrite(1, view_channel=False)], **kwargs)
                effective, trace = explain_access(member, channel)
                self.assertTrue(effective.view_channel)
                self.assertIn("bypassed", trace[0])

    def test_public_log_and_dangerous_self_role_are_critical(self):
        guild, _, _ = make_guild(extra_roles=[role_payload(2, "Free admin", administrator=True)])
        findings = audit_permissions(guild, public_role_ids=[2], log_channels={10: ["Moderation log"]})
        self.assertEqual([f.severity for f in findings], ["CRITICAL", "CRITICAL"])
        self.assertTrue(any("everyone role" in f.title for f in findings))

    def test_hidden_log_exposed_through_self_role(self):
        guild, _, _ = make_guild(extra_roles=[role_payload(2, "Public")], overrides=[
            overwrite(1, view_channel=False), overwrite(2, view_channel=True),
        ])
        findings = audit_permissions(guild, public_role_ids=[2], log_channels={10: ["Message audit"]})
        self.assertEqual(len(findings), 1)
        self.assertIn("Publicly assigned", findings[0].title)

    def test_private_log_and_missing_settings(self):
        guild, _, _ = make_guild(overrides=[overwrite(1, view_channel=False)])
        self.assertEqual(audit_permissions(guild, log_channels={10: ["Moderation log"]}), [])
        findings = audit_permissions(guild, public_role_ids=[123], log_channels={456: ["Message audit"]})
        self.assertEqual(len(findings), 2)
        self.assertTrue(all(f.severity == "WARNING" for f in findings))

    def test_plain_channel_is_not_assumed_private(self):
        guild, _, _ = make_guild()
        self.assertEqual(audit_permissions(guild), [])

    def test_public_channel_override_can_grant_power_without_server_permission(self):
        guild, _, _ = make_guild(extra_roles=[role_payload(2, "Public")], overrides=[
            overwrite(2, manage_webhooks=True),
        ])
        findings = audit_permissions(guild, public_role_ids=[2])
        self.assertEqual(len(findings), 1)
        self.assertIn("channel overrides", findings[0].title)
        self.assertIn("Manage Webhooks", findings[0].detail)

    def test_bot_log_delivery_permissions_are_checked(self):
        guild, _, _ = make_guild(overrides=[overwrite(50, member=True, send_messages=False)])
        guild._state.user = SimpleNamespace(id=50)
        findings = audit_permissions(guild, log_channels={10: ["Ticket transcripts"]})
        delivery = next(f for f in findings if "cannot deliver" in f.title)
        self.assertIn("Send Messages", delivery.detail)
        self.assertIn("Attach Files", delivery.detail)

    def test_report_includes_full_details_and_scope(self):
        guild, _, _ = make_guild()
        report = build_report(guild, [Finding("REVIEW", "Title", "detail" * 1000, "Fix")], discord.utils.utcnow())
        self.assertIn("detail" * 1000, report)
        self.assertIn("not exhaustively scanned", report)


class SecurityInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.guild, self.member, _ = make_guild(
            extra_roles=[role_payload(2, "Staff", manage_guild=True)], member_roles=[2],
        )
        self.bot = SimpleNamespace(get_guild=lambda _: self.guild)
        self.cog = Security(self.bot)

    async def test_controls_reject_wrong_user_or_lost_permission(self):
        view = SecurityView(self.cog, 1, 50, [])
        interaction = SimpleNamespace(user=SimpleNamespace(id=51), response=SimpleNamespace(send_message=AsyncMock()))
        self.assertFalse(await view.interaction_check(interaction))
        interaction.user.id = 50
        self.assertTrue(await view.interaction_check(interaction))
        self.guild.get_role(2)._permissions = 0
        self.assertFalse(await view.interaction_check(interaction))
        view.stop()

    async def test_paging_and_embed_limits(self):
        findings = [Finding("WARNING", "Title", "X" * 1800, "Fix") for _ in range(9)]
        view = SecurityView(self.cog, 1, 50, findings)
        self.assertEqual(view.pages, 3)
        self.assertTrue(view.previous.disabled)
        self.assertLess(len(view.embed(self.guild)), 6000)
        interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))
        await view.next_page.callback(interaction)
        self.assertEqual(view.page, 1)
        await view.next_page.callback(interaction)
        self.assertTrue(view.next_page.disabled)
        self.assertEqual(len(view.embed(self.guild).fields), 1)
        view.stop()

    async def test_blocked_dm_never_posts_report_publicly(self):
        error = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "DM blocked")
        ctx = SimpleNamespace(author=SimpleNamespace(send=AsyncMock(side_effect=error)), send=AsyncMock())
        self.assertFalse(await self.cog.send_private(ctx, embed=discord.Embed(title="PRIVATE")))
        self.assertNotIn("embed", ctx.send.call_args.kwargs)
        self.assertIn("couldn't DM", ctx.send.call_args.args[0])

    async def test_refresh_replaces_snapshot_and_export_contains_full_report(self):
        view = SecurityView(self.cog, 1, 50, [Finding("WARNING", "Old", "Old detail", "Fix")])
        interaction = SimpleNamespace(
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )
        updated = [Finding("CRITICAL", "New", "New detail", "New fix")]
        with patch.object(self.cog, "scan", AsyncMock(return_value=updated)):
            await view.refresh.callback(interaction)
        self.assertEqual(view.findings, updated)
        self.assertEqual(view.page, 0)
        interaction.response.defer.assert_awaited_once()
        await view.export.callback(interaction)
        kwargs = interaction.response.send_message.call_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        self.assertIn("New detail", kwargs["file"].fp.read().decode("utf-8"))
        kwargs["file"].close()
        view.stop()

    async def test_commands_require_guild_permission(self):
        ctx = SimpleNamespace(guild=self.guild, author=self.member)
        for command in (self.cog.security_audit, self.cog.access):
            for check in command.checks:
                result = check(ctx)
                self.assertTrue(await result if inspect.isawaitable(result) else result)
            self.guild.get_role(2)._permissions = 0
            with self.assertRaises(commands.MissingPermissions):
                for check in command.checks:
                    result = check(ctx)
                    if inspect.isawaitable(result):
                        await result
            self.guild.get_role(2)._permissions = discord.Permissions(manage_guild=True).value

    async def test_scan_reads_existing_database_configuration(self):
        database = Path(__file__).resolve().parent / f"security-test-{uuid.uuid4().hex}.db"
        try:
            with patch.object(db, "DB_PATH", str(database)), patch("cogs.security.resolve_mod_log_channel_id", return_value=10):
                await db.init_db()
                await db.upsert_guild_settings(1, message_log_channel_id=10)
                await db.set_autorole(1, 2)
                findings = await self.cog.scan(self.guild)
                self.assertTrue(any("public role" in f.title for f in findings))
                log_findings = [f for f in findings if "Staff log visible" in f.title]
                self.assertEqual(len(log_findings), 1)
                self.assertIn("Message audit", log_findings[0].detail)
                self.assertIn("Moderation log", log_findings[0].detail)
        finally:
            for suffix in ("", "-wal", "-shm"):
                Path(str(database) + suffix).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
