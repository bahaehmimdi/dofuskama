"""Commandes de création / recherche / gestion des annonces (vente, achat, location)."""

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
import market_reference
import roles
from views import ListingManageView, PriceTableView, SearchPaginator, money


class Marketplace(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    async def game_autocomplete(self, interaction: discord.Interaction, current: str):
        games = await self.db.distinct_games(current)
        return [app_commands.Choice(name=g, value=g) for g in games][:25]

    async def _alert_if_big_offer(self, interaction: discord.Interaction, embed: discord.Embed, total_value: float):
        if total_value < config.BIG_OFFER_THRESHOLD:
            return
        alert = embed.copy()
        alert.title = f"📢 Grosse offre — {alert.title}"
        await roles.post_alert(interaction.guild, alert)

    # --------------------------------------------------------
    # /market — page d'accueil
    # --------------------------------------------------------

    @app_commands.command(name="market", description="Afficher le marketplace")
    async def market(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🏪 GAME MARKETPLACE",
            description=(
                "Achetez, vendez, louez et échangez des monnaies/comptes de jeu.\n\n"
                "💰 `/sell` — vendre de la monnaie/un objet\n"
                "🙋 `/wtb` — annoncer que vous cherchez à acheter\n"
                "🏠 `/rentout` — mettre en location (compte, service...)\n"
                "🔎 `/search` — rechercher une annonce\n"
                "📊 `/price` — cours du marché (basé sur vos transactions)\n"
                "📥 `/apply` — prix de référence leskamas.com -6%\n"
                "🎫 `/buy` `/offer` `/rentrequest` — lancer une transaction\n"
                "🛡️ `/middleman` — demander un médiateur (dans un ticket)\n"
                "📋 `/mylistings` — gérer mes annonces\n"
                "🔄 `/trade` — proposer un échange\n"
                "⭐ `/vouch` — laisser un avis\n"
                "🚨 `/report` — signaler un problème\n"
                "💳 `/payments` — moyens de paiement\n"
                "🛡️ `/reports` `/resolvereport` `/verify` `/blacklist` — staff uniquement"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    # --------------------------------------------------------
    # /sell — annonce de vente
    # --------------------------------------------------------

    @app_commands.command(name="sell", description="Créer une offre de vente")
    @app_commands.describe(
        game="Nom du jeu",
        server="Serveur/région",
        currency="Nom de la monnaie ou de l'objet",
        amount="Quantité",
        price=f"Prix total en {config.CURRENCY}",
        description="Informations supplémentaires",
    )
    @app_commands.autocomplete(game=game_autocomplete)
    @app_commands.checks.cooldown(1, config.LISTING_COOLDOWN_SECONDS)
    async def sell(
        self,
        interaction: discord.Interaction,
        game: str,
        server: str,
        currency: str,
        amount: float,
        price: float,
        description: Optional[str] = None,
    ):
        if amount <= 0 or price <= 0:
            await interaction.response.send_message(
                "❌ Quantité et prix doivent être positifs.", ephemeral=True
            )
            return

        if description and len(description) > config.MAX_DESCRIPTION_LENGTH:
            await interaction.response.send_message(
                f"❌ Description trop longue (max {config.MAX_DESCRIPTION_LENGTH} caractères).",
                ephemeral=True,
            )
            return

        if not await roles.check_not_blacklisted(interaction, self.db):
            return

        await self.db.ensure_user(interaction.user.id, str(interaction.user))

        listing_id = await self.db.create_listing(
            seller_id=interaction.user.id,
            seller_name=str(interaction.user),
            listing_type="sell",
            game=game,
            server=server,
            currency=currency,
            amount=amount,
            price=price,
            description=description,
        )

        embed = discord.Embed(title=f"🪙 Offre de vente #{listing_id}", color=discord.Color.gold())
        embed.add_field(name="Jeu", value=game)
        embed.add_field(name="Serveur", value=server)
        embed.add_field(name="Monnaie", value=currency)
        embed.add_field(name="Quantité", value=f"{amount:,.0f}")
        embed.add_field(name="Prix", value=money(price))
        embed.add_field(name="Vendeur", value=interaction.user.mention)
        if description:
            embed.add_field(name="Description", value=description, inline=False)
        embed.set_footer(text=f"/buy {listing_id} pour acheter")

        await interaction.response.send_message(embed=embed)
        await self._alert_if_big_offer(interaction, embed, price)

    # --------------------------------------------------------
    # /wtb — annonce de recherche d'achat
    # --------------------------------------------------------

    @app_commands.command(name="wtb", description="Annoncer que vous cherchez à acheter (Want To Buy)")
    @app_commands.describe(
        game="Nom du jeu",
        server="Serveur/région",
        currency="Monnaie ou objet recherché",
        amount="Quantité recherchée",
        price=f"Prix total que vous proposez en {config.CURRENCY}",
        description="Informations supplémentaires",
    )
    @app_commands.autocomplete(game=game_autocomplete)
    @app_commands.checks.cooldown(1, config.LISTING_COOLDOWN_SECONDS)
    async def wtb(
        self,
        interaction: discord.Interaction,
        game: str,
        server: str,
        currency: str,
        amount: float,
        price: float,
        description: Optional[str] = None,
    ):
        if amount <= 0 or price <= 0:
            await interaction.response.send_message(
                "❌ Quantité et prix doivent être positifs.", ephemeral=True
            )
            return

        if not await roles.check_not_blacklisted(interaction, self.db):
            return

        await self.db.ensure_user(interaction.user.id, str(interaction.user))

        listing_id = await self.db.create_listing(
            seller_id=interaction.user.id,
            seller_name=str(interaction.user),
            listing_type="buy",
            game=game,
            server=server,
            currency=currency,
            amount=amount,
            price=price,
            description=description,
        )

        embed = discord.Embed(
            title=f"🙋 Recherche d'achat #{listing_id}", color=discord.Color.purple()
        )
        embed.add_field(name="Jeu", value=game)
        embed.add_field(name="Serveur", value=server)
        embed.add_field(name="Monnaie", value=currency)
        embed.add_field(name="Quantité recherchée", value=f"{amount:,.0f}")
        embed.add_field(name="Prix proposé", value=money(price))
        embed.add_field(name="Acheteur", value=interaction.user.mention)
        if description:
            embed.add_field(name="Description", value=description, inline=False)
        embed.set_footer(text=f"/offer {listing_id} pour répondre à cette recherche")

        await interaction.response.send_message(embed=embed)
        await self._alert_if_big_offer(interaction, embed, price)

    # --------------------------------------------------------
    # /rentout — annonce de location
    # --------------------------------------------------------

    @app_commands.command(name="rentout", description="Mettre un compte/service en location")
    @app_commands.describe(
        game="Nom du jeu",
        server="Serveur/région",
        item="Ce qui est loué (ex: compte, pack, service)",
        price_per_day=f"Prix par jour en {config.CURRENCY}",
        min_days="Durée minimum de location (jours)",
        deposit="Caution demandée (optionnel)",
        description="Informations supplémentaires",
    )
    @app_commands.autocomplete(game=game_autocomplete)
    @app_commands.checks.cooldown(1, config.LISTING_COOLDOWN_SECONDS)
    async def rentout(
        self,
        interaction: discord.Interaction,
        game: str,
        server: str,
        item: str,
        price_per_day: float,
        min_days: app_commands.Range[int, 1, 365] = 1,
        deposit: Optional[float] = None,
        description: Optional[str] = None,
    ):
        if price_per_day <= 0:
            await interaction.response.send_message(
                "❌ Le prix par jour doit être positif.", ephemeral=True
            )
            return

        if not await roles.check_not_blacklisted(interaction, self.db):
            return

        await self.db.ensure_user(interaction.user.id, str(interaction.user))

        listing_id = await self.db.create_listing(
            seller_id=interaction.user.id,
            seller_name=str(interaction.user),
            listing_type="rent",
            game=game,
            server=server,
            currency=item,
            amount=1,
            price=price_per_day,
            price_unit="per_day",
            min_days=min_days,
            deposit=deposit,
            description=description,
        )

        embed = discord.Embed(title=f"🏠 Location #{listing_id}", color=discord.Color.teal())
        embed.add_field(name="Jeu", value=game)
        embed.add_field(name="Serveur", value=server)
        embed.add_field(name="Objet loué", value=item)
        embed.add_field(name="Prix / jour", value=money(price_per_day))
        embed.add_field(name="Durée minimum", value=f"{min_days} jour(s)")
        if deposit:
            embed.add_field(name="Caution", value=money(deposit))
        embed.add_field(name="Loueur", value=interaction.user.mention)
        if description:
            embed.add_field(name="Description", value=description, inline=False)
        embed.set_footer(text=f"/rentrequest {listing_id} pour louer")

        await interaction.response.send_message(embed=embed)
        await self._alert_if_big_offer(interaction, embed, price_per_day * min_days)

    # --------------------------------------------------------
    # /search
    # --------------------------------------------------------

    @app_commands.command(name="search", description="Rechercher des annonces")
    @app_commands.describe(
        game="Jeu",
        currency="Monnaie / objet",
        type="Type d'annonce",
    )
    @app_commands.autocomplete(game=game_autocomplete)
    @app_commands.choices(
        type=[
            app_commands.Choice(name="Vente", value="sell"),
            app_commands.Choice(name="Recherche d'achat", value="buy"),
            app_commands.Choice(name="Location", value="rent"),
        ]
    )
    async def search(
        self,
        interaction: discord.Interaction,
        game: Optional[str] = None,
        currency: Optional[str] = None,
        type: Optional[app_commands.Choice[str]] = None,
    ):
        listing_type = type.value if type else None
        paginator = SearchPaginator(
            self.db,
            listing_type=listing_type,
            game=game,
            currency=currency,
            page_size=config.PAGE_SIZE,
        )
        embed = await paginator.build_embed()
        paginator.update_buttons()
        await interaction.response.send_message(embed=embed, view=paginator)

    # --------------------------------------------------------
    # /listing — détail d'une annonce
    # --------------------------------------------------------

    @app_commands.command(name="listing", description="Voir le détail d'une annonce")
    @app_commands.describe(listing_id="ID de l'annonce")
    async def listing(self, interaction: discord.Interaction, listing_id: int):
        row = await self.db.get_listing(listing_id)
        if row is None:
            await interaction.response.send_message("❌ Annonce introuvable.", ephemeral=True)
            return

        kind = {"sell": "🪙 Vente", "buy": "🙋 Recherche d'achat", "rent": "🏠 Location"}.get(
            row["listing_type"], row["listing_type"]
        )
        embed = discord.Embed(title=f"{kind} #{row['id']} — {row['status']}", color=discord.Color.blue())
        embed.add_field(name="Jeu", value=row["game"])
        embed.add_field(name="Serveur", value=row["server"])
        embed.add_field(name="Monnaie/objet", value=row["currency"])
        embed.add_field(name="Quantité", value=f"{row['amount']:,.0f}")
        if row["listing_type"] == "rent":
            embed.add_field(name="Prix / jour", value=money(row["price"]))
            embed.add_field(name="Durée min", value=f"{row['min_days']} jour(s)")
        else:
            embed.add_field(name="Prix", value=money(row["price"]))
        embed.add_field(name="Auteur", value=f"<@{row['seller_id']}>")
        if row["description"]:
            embed.add_field(name="Description", value=row["description"], inline=False)

        await interaction.response.send_message(embed=embed)

    # --------------------------------------------------------
    # /price — cours du marché
    # --------------------------------------------------------

    @app_commands.command(name="price", description="Voir le cours du marché pour une monnaie")
    @app_commands.describe(game="Jeu", currency="Monnaie ou objet")
    @app_commands.autocomplete(game=game_autocomplete)
    async def price(self, interaction: discord.Interaction, game: str, currency: str):
        stats = await self.db.market_price_stats(game, currency, config.PRICE_SAMPLE_SIZE)

        if stats is None:
            await interaction.response.send_message(
                "❌ Aucune donnée de prix pour cette monnaie (aucune vente terminée ni annonce active).",
                ephemeral=True,
            )
            return

        source_label = (
            "transactions terminées" if stats["source"] == "transactions" else "annonces actives (aucune vente terminée)"
        )

        embed = discord.Embed(
            title=f"📊 Cours du marché — {currency} ({game})",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Prix moyen", value=f"{stats['avg']:.6f} {config.CURRENCY}/unité")
        embed.add_field(name="Le plus bas", value=f"{stats['min']:.6f} {config.CURRENCY}/unité")
        embed.add_field(name="Le plus haut", value=f"{stats['max']:.6f} {config.CURRENCY}/unité")
        embed.add_field(name="Dernier prix", value=f"{stats['latest']:.6f} {config.CURRENCY}/unité")
        embed.set_footer(text=f"Basé sur {stats['sample_size']} {source_label}")

        await interaction.response.send_message(embed=embed)

    # --------------------------------------------------------
    # /apply — prix de référence leskamas.com, -6%
    # --------------------------------------------------------

    async def reference_server_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            names = await market_reference.list_server_names()
        except Exception:
            return []
        current_lower = current.lower()
        matches = [n for n in names if current_lower in n.lower()]
        return [app_commands.Choice(name=n, value=n) for n in matches][:25]

    async def _ensure_reference_prices_seeded(self):
        """Peuple le cache DB au premier appel si personne n'a encore jamais actualisé."""
        saved = await self.db.get_reference_prices()
        if saved:
            return
        try:
            sections = await market_reference.fetch_reference_prices()
        except market_reference.ReferencePriceError:
            return
        await self.db.save_reference_prices(sections)

    @app_commands.command(
        name="apply",
        description="Prix de référence leskamas.com -6% (un serveur, ou tableau Dofus Kamas si omis)",
    )
    @app_commands.describe(
        server="Serveur Dofus (laisser vide pour voir le tableau complet Dofus Kamas)",
        amount="Quantité de kamas pour calculer un prix total (nécessite server)",
    )
    @app_commands.autocomplete(server=reference_server_autocomplete)
    async def apply(
        self,
        interaction: discord.Interaction,
        server: Optional[str] = None,
        amount: Optional[float] = None,
    ):
        await interaction.response.defer()

        if server is None:
            await self._ensure_reference_prices_seeded()
            view = PriceTableView(self.db, section=market_reference.DEFAULT_SECTION)
            embed = await view.build_embed()
            await interaction.followup.send(embed=embed, view=view)
            return

        try:
            reference_per_million = await market_reference.fetch_server_price(server)
        except market_reference.ReferencePriceError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        adjusted_per_million = market_reference.apply_discount(reference_per_million)

        embed = discord.Embed(
            title=f"📥 Prix de référence — {server}",
            description="Source : leskamas.com (revisité à l'instant), prix affiché = référence **-6%**.",
            color=discord.Color.dark_teal(),
        )
        embed.add_field(name="Référence leskamas.com", value=f"{reference_per_million:.3f} Dhs/M kamas")
        embed.add_field(name="Prix appliqué (-6%)", value=f"**{adjusted_per_million:.3f} Dhs/M kamas**")

        if amount and amount > 0:
            total = adjusted_per_million * (amount / 1_000_000)
            embed.add_field(
                name=f"Pour {amount:,.0f} kamas", value=f"**{total:,.2f} {config.CURRENCY}**", inline=False
            )

        embed.set_footer(text="Prix indicatif, non garanti — vérifiez toujours leskamas.com pour la valeur exacte.")

        await interaction.followup.send(embed=embed)

    # --------------------------------------------------------
    # /applyall — tableau de prix pour tous les jeux du site
    # --------------------------------------------------------

    @app_commands.command(
        name="applyall",
        description="Tableau des prix de référence leskamas.com -6% pour tous les jeux",
    )
    async def applyall(self, interaction: discord.Interaction):
        await interaction.response.defer()

        await self._ensure_reference_prices_seeded()
        view = PriceTableView(self.db, section=None)
        embed = await view.build_embed()
        await interaction.followup.send(embed=embed, view=view)

    # --------------------------------------------------------
    # /mylistings
    # --------------------------------------------------------

    @app_commands.command(name="mylistings", description="Gérer mes annonces actives")
    async def mylistings(self, interaction: discord.Interaction):
        listings = await self.db.get_user_listings(interaction.user.id)

        if not listings:
            await interaction.response.send_message(
                "Vous n'avez aucune annonce active.", ephemeral=True
            )
            return

        view = ListingManageView(self.db, interaction.user.id, listings)
        await interaction.response.send_message(
            "Sélectionnez une annonce à annuler :", view=view, ephemeral=True
        )

    # --------------------------------------------------------
    # /cancel
    # --------------------------------------------------------

    @app_commands.command(name="cancel", description="Annuler une de mes annonces")
    @app_commands.describe(listing_id="ID de l'annonce à annuler")
    async def cancel(self, interaction: discord.Interaction, listing_id: int):
        ok = await self.db.cancel_listing(listing_id, interaction.user.id)
        if ok:
            await interaction.response.send_message(
                f"✅ Annonce #{listing_id} annulée.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Annonce introuvable, déjà inactive, ou elle ne vous appartient pas.",
                ephemeral=True,
            )

    # --------------------------------------------------------
    # /trade — proposition d'échange direct
    # --------------------------------------------------------

    @app_commands.command(name="trade", description="Proposer un échange")
    @app_commands.describe(
        user="Utilisateur avec lequel échanger",
        offer="Ce que vous proposez",
        wanted="Ce que vous recherchez",
    )
    async def trade(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        offer: str,
        wanted: str,
    ):
        if user.id == interaction.user.id:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas échanger avec vous-même.", ephemeral=True
            )
            return

        if not await roles.check_not_blacklisted(interaction, self.db):
            return

        embed = discord.Embed(title="🔄 Proposition d'échange", color=discord.Color.orange())
        embed.add_field(name="Proposé par", value=interaction.user.mention)
        embed.add_field(name="Destinataire", value=user.mention)
        embed.add_field(name="📤 Offre", value=offer, inline=False)
        embed.add_field(name="📥 Recherche", value=wanted, inline=False)

        await interaction.response.send_message(content=user.mention, embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Marketplace(bot))
