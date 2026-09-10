"""Lancement des transactions (achat, réponse à une recherche, location)."""

import discord
from discord import app_commands
from discord.ext import commands

import config
import roles
from views import PaymentView, money


class Transactions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    # --------------------------------------------------------
    # /buy — acheter une annonce de vente
    # --------------------------------------------------------

    @app_commands.command(name="buy", description="Acheter une annonce de vente")
    @app_commands.describe(listing_id="ID de l'annonce")
    async def buy(self, interaction: discord.Interaction, listing_id: int):
        if not await roles.check_not_blacklisted(interaction, self.db):
            return

        await self.db.ensure_user(interaction.user.id, str(interaction.user))

        listing = await self.db.get_listing(listing_id)

        if listing is None or listing["status"] != "active" or listing["listing_type"] != "sell":
            await interaction.response.send_message(
                "❌ Annonce de vente inexistante ou indisponible.", ephemeral=True
            )
            return

        if await self.db.is_blacklisted(listing["seller_id"]):
            await interaction.response.send_message(
                "❌ Ce vendeur est blacklist, la transaction est bloquée.", ephemeral=True
            )
            return

        if listing["seller_id"] == interaction.user.id:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas acheter votre propre annonce.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🛒 Achat #{listing_id}",
            description=(
                f"**{listing['amount']:,.0f} {listing['currency']}**\n"
                f"Prix : **{money(listing['price'])}**\n\n"
                "Choisissez votre moyen de paiement."
            ),
            color=discord.Color.green(),
        )

        view = PaymentView(
            self.bot,
            self.db,
            buyer_id=interaction.user.id,
            seller_id=listing["seller_id"],
            listing_id=listing_id,
            transaction_type="sell",
            amount=listing["amount"],
            price=listing["price"],
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # --------------------------------------------------------
    # /offer — répondre à une recherche d'achat (wtb)
    # --------------------------------------------------------

    @app_commands.command(name="offer", description="Répondre à une recherche d'achat (WTB)")
    @app_commands.describe(listing_id="ID de la recherche d'achat")
    async def offer(self, interaction: discord.Interaction, listing_id: int):
        if not await roles.check_not_blacklisted(interaction, self.db):
            return

        await self.db.ensure_user(interaction.user.id, str(interaction.user))

        listing = await self.db.get_listing(listing_id)

        if listing is None or listing["status"] != "active" or listing["listing_type"] != "buy":
            await interaction.response.send_message(
                "❌ Recherche d'achat inexistante ou indisponible.", ephemeral=True
            )
            return

        requester_id = listing["seller_id"]  # celui qui a posté /wtb

        if await self.db.is_blacklisted(requester_id):
            await interaction.response.send_message(
                "❌ L'auteur de cette recherche est blacklist, la transaction est bloquée.",
                ephemeral=True,
            )
            return

        if requester_id == interaction.user.id:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas répondre à votre propre recherche.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🤝 Réponse à la recherche #{listing_id}",
            description=(
                f"**{listing['amount']:,.0f} {listing['currency']}**\n"
                f"Prix proposé par l'acheteur : **{money(listing['price'])}**\n\n"
                "L'acheteur va choisir le moyen de paiement."
            ),
            color=discord.Color.green(),
        )

        view = PaymentView(
            self.bot,
            self.db,
            buyer_id=requester_id,
            seller_id=interaction.user.id,
            listing_id=listing_id,
            transaction_type="sell",
            amount=listing["amount"],
            price=listing["price"],
        )

        # Ici c'est l'acheteur original qui doit valider le paiement, mais comme
        # c'est le répondeur qui déclenche l'échange, on prévient les deux côtés
        # et on ouvre directement le ticket avec le moyen de paiement encore à définir.
        await interaction.response.send_message(
            embed=embed,
            content=f"<@{requester_id}> {interaction.user.mention} propose de répondre à votre recherche.",
            view=view,
        )

    # --------------------------------------------------------
    # /rentrequest — louer une annonce de location
    # --------------------------------------------------------

    @app_commands.command(name="rentrequest", description="Louer une annonce de location")
    @app_commands.describe(listing_id="ID de l'annonce de location", days="Nombre de jours")
    async def rentrequest(
        self,
        interaction: discord.Interaction,
        listing_id: int,
        days: app_commands.Range[int, 1, 365],
    ):
        if not await roles.check_not_blacklisted(interaction, self.db):
            return

        await self.db.ensure_user(interaction.user.id, str(interaction.user))

        listing = await self.db.get_listing(listing_id)

        if listing is None or listing["status"] != "active" or listing["listing_type"] != "rent":
            await interaction.response.send_message(
                "❌ Annonce de location inexistante ou indisponible.", ephemeral=True
            )
            return

        if await self.db.is_blacklisted(listing["seller_id"]):
            await interaction.response.send_message(
                "❌ Ce loueur est blacklist, la transaction est bloquée.", ephemeral=True
            )
            return

        if listing["seller_id"] == interaction.user.id:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas louer votre propre annonce.", ephemeral=True
            )
            return

        if listing["min_days"] and days < listing["min_days"]:
            await interaction.response.send_message(
                f"❌ Durée minimum de location : {listing['min_days']} jour(s).", ephemeral=True
            )
            return

        total_price = listing["price"] * days

        description = f"**{listing['currency']}** pour **{days}** jour(s)\nPrix total : **{money(total_price)}**"
        if listing["deposit"]:
            description += f"\nCaution : **{money(listing['deposit'])}**"
        description += "\n\nChoisissez votre moyen de paiement."

        embed = discord.Embed(title=f"🏠 Location #{listing_id}", description=description, color=discord.Color.teal())

        view = PaymentView(
            self.bot,
            self.db,
            buyer_id=interaction.user.id,
            seller_id=listing["seller_id"],
            listing_id=listing_id,
            transaction_type="rent",
            amount=1,
            price=total_price,
            rent_days=days,
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # --------------------------------------------------------
    # /middleman — demander la supervision d'un membre du staff
    # --------------------------------------------------------

    @app_commands.command(
        name="middleman", description="Demander un médiateur staff dans ce salon de transaction"
    )
    async def middleman(self, interaction: discord.Interaction):
        channel = interaction.channel

        if channel is None or not channel.name.startswith("transaction-"):
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un salon de transaction.",
                ephemeral=True,
            )
            return

        try:
            tx_id = int(channel.name.split("-")[-1])
        except ValueError:
            await interaction.response.send_message("❌ Salon invalide.", ephemeral=True)
            return

        tx = await self.db.get_transaction(tx_id)
        if tx is None:
            await interaction.response.send_message("❌ Transaction introuvable.", ephemeral=True)
            return

        if interaction.user.id not in (tx["buyer_id"], tx["seller_id"]):
            await interaction.response.send_message(
                "❌ Vous ne faites pas partie de cette transaction.", ephemeral=True
            )
            return

        staff_role = discord.utils.get(interaction.guild.roles, name=config.STAFF_ROLE_NAME)
        mention = staff_role.mention if staff_role else "Staff"

        embed = discord.Embed(
            title="🛡️ Médiateur demandé",
            description=(
                f"{interaction.user.mention} demande la présence d'un médiateur pour "
                f"superviser la transaction #{tx_id} "
                f"(**{money(tx['price'])}**).\n\n"
                "Un membre du staff va rejoindre ce salon pour encadrer l'échange."
            ),
            color=discord.Color.gold(),
        )

        await interaction.response.send_message(content=mention, embed=embed)

    # --------------------------------------------------------
    # /close — alternative en commande au bouton "Fermer"
    # --------------------------------------------------------

    @app_commands.command(name="close", description="Fermer le salon de transaction courant")
    async def close(self, interaction: discord.Interaction):
        channel = interaction.channel

        if channel is None or not channel.name.startswith("transaction-"):
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un salon de transaction.",
                ephemeral=True,
            )
            return

        try:
            tx_id = int(channel.name.split("-")[-1])
        except ValueError:
            await interaction.response.send_message("❌ Salon invalide.", ephemeral=True)
            return

        tx = await self.db.get_transaction(tx_id)
        if tx is None:
            await interaction.response.send_message("❌ Transaction introuvable.", ephemeral=True)
            return

        is_party = interaction.user.id in (tx["buyer_id"], tx["seller_id"])
        is_staff = any(r.name == config.STAFF_ROLE_NAME for r in interaction.user.roles)

        if not (is_party or is_staff):
            await interaction.response.send_message(
                "❌ Vous n'êtes pas autorisé à fermer ce salon.", ephemeral=True
            )
            return

        await interaction.response.send_message("🔒 Fermeture du salon...")

        import asyncio

        await asyncio.sleep(2)
        await channel.delete(reason="Transaction terminée")


async def setup(bot: commands.Bot):
    await bot.add_cog(Transactions(bot))
