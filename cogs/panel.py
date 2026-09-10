"""Publication du panneau "Espace Vendeurs" et gestion du stock serveur."""

import discord
from discord import app_commands
from discord.ext import commands

from cogs.admin import staff_only
from views import SellPanelView


class Panel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(
        name="postpanel", description="[Staff] Publier le panneau vendeur dans ce salon"
    )
    @staff_only()
    async def postpanel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="💸 Espace Vendeurs",
            description=(
                "Vendez vos kamas en quelques minutes.\n\n"
                "**Fonctionnement**\n"
                "1️⃣ Cliquez sur 🎁 **Démarrer une vente**\n"
                "2️⃣ Remplissez le formulaire (serveur, quantité, devise)\n"
                "3️⃣ Un ticket privé est créé avec le staff\n"
                "4️⃣ Le staff récupère vos kamas en jeu\n"
                "5️⃣ Paiement déclenché selon la méthode choisie\n\n"
                "Utilisez 🔔 **Alerte Stock** pour être prévenu quand un serveur redevient "
                "disponible, et 📈 **Suivi Prix** pour suivre le cours de rachat d'un serveur."
            ),
            color=discord.Color.gold(),
        )

        await interaction.channel.send(embed=embed, view=SellPanelView(self.db))
        await interaction.response.send_message("✅ Panneau publié.", ephemeral=True)

    @app_commands.command(name="setstock", description="[Staff] Définir le statut de stock d'un serveur")
    @app_commands.describe(server="Nom du serveur", status="Nouveau statut")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Disponible", value="disponible"),
            app_commands.Choice(name="Complet", value="complet"),
        ]
    )
    @staff_only()
    async def setstock(
        self, interaction: discord.Interaction, server: str, status: app_commands.Choice[str]
    ):
        previous = await self.db.get_server_stock(server)
        await self.db.set_server_stock(server, status.value)

        await interaction.response.send_message(
            f"✅ Stock de **{server}** défini sur **{status.value}**.", ephemeral=True
        )

        became_available = status.value == "disponible" and (
            previous is None or previous["status"] != "disponible"
        )
        if not became_available:
            return

        alerts = await self.db.pop_stock_alerts(server)
        for alert in alerts:
            user = self.bot.get_user(alert["user_id"]) or await self.bot.fetch_user(alert["user_id"])
            if user is None:
                continue
            try:
                await user.send(
                    f"🔔 Le serveur **{server}** est de nouveau disponible à la vente "
                    f"({alert['devise'] or 'DH'}) ! Utilisez le bouton 🎁 Démarrer une vente."
                )
            except discord.Forbidden:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Panel(bot))
