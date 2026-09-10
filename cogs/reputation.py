"""Réputation, avis, signalements et informations de paiement."""

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import roles


class Reputation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    def _current_transaction_id(self, channel: discord.abc.GuildChannel) -> Optional[int]:
        if channel and getattr(channel, "name", "").startswith("transaction-"):
            try:
                return int(channel.name.split("-")[-1])
            except ValueError:
                return None
        return None

    # --------------------------------------------------------
    # /vouch
    # --------------------------------------------------------

    @app_commands.command(name="vouch", description="Laisser un avis à un vendeur/loueur")
    @app_commands.describe(seller="Vendeur/loueur", rating="Note de 1 à 5", comment="Commentaire")
    async def vouch(
        self,
        interaction: discord.Interaction,
        seller: discord.Member,
        rating: app_commands.Range[int, 1, 5],
        comment: str,
    ):
        if seller.id == interaction.user.id:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas vous évaluer vous-même.", ephemeral=True
            )
            return

        await self.db.ensure_user(seller.id, str(seller))

        tx_id = self._current_transaction_id(interaction.channel)

        await self.db.create_vouch(
            seller_id=seller.id,
            buyer_id=interaction.user.id,
            rating=rating,
            comment=comment,
            transaction_id=tx_id,
        )

        stars = "⭐" * rating

        embed = discord.Embed(title="⭐ Nouveau vouch", description=comment, color=discord.Color.gold())
        embed.add_field(name="Vendeur/loueur", value=seller.mention)
        embed.add_field(name="Note", value=stars)
        embed.set_footer(text=f"Par {interaction.user}")

        await interaction.response.send_message(embed=embed)

        updated_row = await self.db.get_user(seller.id)
        newly_gained = await roles.sync_seller_roles(interaction.guild, seller, updated_row)

        for badge in newly_gained:
            alert = discord.Embed(
                title=f"🏷️ Nouveau palier vendeur : {badge}",
                description=f"{seller.mention} vient d'obtenir le rôle **{badge}** !",
                color=discord.Color.gold(),
            )
            await roles.post_alert(interaction.guild, alert)

    # --------------------------------------------------------
    # /profile
    # --------------------------------------------------------

    @app_commands.command(name="profile", description="Afficher le profil marketplace")
    @app_commands.describe(user="Utilisateur")
    async def profile(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        user = user or interaction.user

        await self.db.ensure_user(user.id, str(user))
        row = await self.db.get_user(user.id)
        listings = await self.db.get_user_listings(user.id)
        blacklist_entry = await self.db.get_blacklist_entry(user.id)

        verified = "✅ Vérifié" if row["verified"] else "❌ Non vérifié"

        embed = discord.Embed(title=f"👤 {user.display_name}", color=discord.Color.blue())
        embed.add_field(name="Réputation", value=str(row["reputation"]))
        embed.add_field(name="Vouches", value=str(row["vouches"]))
        embed.add_field(name="Transactions terminées", value=str(row["completed_trades"]))
        embed.add_field(name="Statut", value=verified)
        embed.add_field(name="Annonces actives", value=str(len(listings)))

        if blacklist_entry:
            embed.add_field(name="⛔ Blacklist", value=blacklist_entry["reason"], inline=False)
            embed.color = discord.Color.red()

        await interaction.response.send_message(embed=embed)

    # --------------------------------------------------------
    # /report
    # --------------------------------------------------------

    @app_commands.command(name="report", description="Signaler un utilisateur")
    @app_commands.describe(user="Utilisateur à signaler", reason="Raison du signalement")
    async def report(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        tx_id = self._current_transaction_id(interaction.channel)

        await self.db.create_report(
            reporter_id=interaction.user.id,
            reported_id=user.id,
            reason=reason,
            transaction_id=tx_id,
        )

        await interaction.response.send_message(
            "🚨 Signalement enregistré. Un modérateur va examiner la situation.",
            ephemeral=True,
        )

    # --------------------------------------------------------
    # /payments
    # --------------------------------------------------------

    @app_commands.command(name="payments", description="Afficher les moyens de paiement")
    async def payments(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🇲🇦 Moyens de paiement", color=discord.Color.green())

        embed.add_field(
            name="💳 CMI",
            value="Paiement par carte via le système de paiement officiel.",
            inline=False,
        )
        embed.add_field(
            name="📱 Inwi Money",
            value="Paiement mobile via le service officiel.",
            inline=False,
        )
        embed.add_field(
            name="🏦 Virement bancaire",
            value="Les informations bancaires sont fournies uniquement dans le ticket.",
            inline=False,
        )
        embed.add_field(
            name="⚠️ Sécurité",
            value="Le staff ne vous demandera jamais votre PIN, mot de passe ou code OTP.",
            inline=False,
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Reputation(bot))
