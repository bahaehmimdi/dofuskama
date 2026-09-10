"""Commandes réservées au staff : gestion des signalements et vérification."""

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
import roles as role_utils


def staff_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        if interaction.user.guild_permissions.manage_guild:
            return True
        if discord.utils.get(interaction.user.roles, name=config.STAFF_ROLE_NAME):
            return True
        raise app_commands.MissingPermissions(["manage_guild"])

    return app_commands.check(predicate)


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    # --------------------------------------------------------
    # /reports — lister les signalements
    # --------------------------------------------------------

    @app_commands.command(name="reports", description="[Staff] Lister les signalements")
    @app_commands.describe(status="Statut à afficher")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Ouverts", value="open"),
            app_commands.Choice(name="Résolus", value="resolved"),
        ]
    )
    @staff_only()
    async def reports(
        self,
        interaction: discord.Interaction,
        status: Optional[app_commands.Choice[str]] = None,
    ):
        status_value = status.value if status else "open"
        rows = await self.db.list_reports(status_value, limit=10)

        if not rows:
            await interaction.response.send_message(
                f"Aucun signalement « {status_value} ».", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🚨 Signalements — {status_value}", color=discord.Color.red()
        )
        for row in rows:
            tx_info = f" (transaction #{row['transaction_id']})" if row["transaction_id"] else ""
            embed.add_field(
                name=f"#{row['id']} — <@{row['reported_id']}>{tx_info}",
                value=f"Par <@{row['reporter_id']}> : {row['reason']}",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --------------------------------------------------------
    # /resolvereport
    # --------------------------------------------------------

    @app_commands.command(name="resolvereport", description="[Staff] Marquer un signalement comme résolu")
    @app_commands.describe(report_id="ID du signalement")
    @staff_only()
    async def resolvereport(self, interaction: discord.Interaction, report_id: int):
        ok = await self.db.resolve_report(report_id)
        if ok:
            await interaction.response.send_message(
                f"✅ Signalement #{report_id} marqué comme résolu.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ Signalement #{report_id} introuvable ou déjà résolu.", ephemeral=True
            )

    # --------------------------------------------------------
    # /verify — (dé)vérifier un membre
    # --------------------------------------------------------

    @app_commands.command(name="verify", description="[Staff] Marquer un membre comme vérifié")
    @app_commands.describe(user="Membre à vérifier", verified="Vérifié ou non")
    @staff_only()
    async def verify(self, interaction: discord.Interaction, user: discord.Member, verified: bool = True):
        await self.db.ensure_user(user.id, str(user))
        await self.db.set_verified(user.id, verified)

        updated_row = await self.db.get_user(user.id)
        await role_utils.sync_seller_roles(interaction.guild, user, updated_row)

        state = "✅ vérifié" if verified else "❌ non vérifié"
        await interaction.response.send_message(
            f"{user.mention} est maintenant marqué comme {state}.", ephemeral=True
        )

    # --------------------------------------------------------
    # /blacklist — gérer la liste noire du marketplace
    # --------------------------------------------------------

    @app_commands.command(name="blacklist", description="[Staff] Ajouter/retirer/lister la blacklist")
    @app_commands.describe(
        action="Action à effectuer",
        user="Utilisateur concerné (requis pour ajouter/retirer)",
        reason="Raison (requise pour ajouter)",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Ajouter", value="add"),
            app_commands.Choice(name="Retirer", value="remove"),
            app_commands.Choice(name="Lister", value="list"),
        ]
    )
    @staff_only()
    async def blacklist(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        user: Optional[discord.Member] = None,
        reason: Optional[str] = None,
    ):
        if action.value == "list":
            rows = await self.db.list_blacklist()
            if not rows:
                await interaction.response.send_message("La blacklist est vide.", ephemeral=True)
                return

            embed = discord.Embed(title="⛔ Blacklist", color=discord.Color.red())
            for row in rows:
                embed.add_field(
                    name=f"<@{row['discord_id']}>",
                    value=f"{row['reason']} (par <@{row['staff_id']}>)",
                    inline=False,
                )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if user is None:
            await interaction.response.send_message(
                "❌ Précisez l'utilisateur concerné.", ephemeral=True
            )
            return

        if action.value == "add":
            if not reason:
                await interaction.response.send_message(
                    "❌ Une raison est requise pour blacklist quelqu'un.", ephemeral=True
                )
                return

            await self.db.ensure_user(user.id, str(user))
            await self.db.add_blacklist(user.id, reason, interaction.user.id)
            await interaction.response.send_message(
                f"⛔ {user.mention} a été ajouté à la blacklist.\nRaison : {reason}",
            )
            return

        # action == "remove"
        ok = await self.db.remove_blacklist(user.id)
        if ok:
            await interaction.response.send_message(f"✅ {user.mention} retiré de la blacklist.")
        else:
            await interaction.response.send_message(
                f"ℹ️ {user.mention} n'était pas blacklist.", ephemeral=True
            )

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Cette commande est réservée au staff.", ephemeral=True
            )
            return
        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
