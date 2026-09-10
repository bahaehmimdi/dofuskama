"""Vues discord.ui utilisées par le bot.

Deux familles de vues :
- Vues éphémères liées à une interaction précise (paiement, pagination,
  gestion d'annonces) : elles n'ont pas besoin de survivre à un redémarrage.
- Vues persistantes attachées aux salons de transaction (confirmation /
  fermeture / litige) : elles utilisent des custom_id statiques et
  retrouvent leur contexte en base à partir du salon, pour continuer à
  fonctionner après un redémarrage du bot (voir bot.add_view en setup_hook).
"""

from __future__ import annotations

import asyncio
import re

import discord

import config
import market_reference
from database import Database


def money(value: float) -> str:
    return f"{value:,.2f} {config.CURRENCY}"


# ============================================================
# Paiement (choix du moyen de paiement pour une transaction)
# ============================================================

PAYMENT_METHODS = ["CMI", "Inwi Money", "Virement bancaire"]


class PaymentView(discord.ui.View):
    def __init__(
        self,
        bot,
        db: Database,
        *,
        buyer_id: int,
        seller_id: int,
        listing_id: int,
        transaction_type: str,
        amount: float,
        price: float,
        rent_days: int | None = None,
    ):
        super().__init__(timeout=300)
        self.bot = bot
        self.db = db
        self.buyer_id = buyer_id
        self.seller_id = seller_id
        self.listing_id = listing_id
        self.transaction_type = transaction_type
        self.amount = amount
        self.price = price
        self.rent_days = rent_days

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.buyer_id:
            await interaction.response.send_message(
                "❌ Cette transaction ne vous appartient pas.", ephemeral=True
            )
            return False
        return True

    async def _start_transaction(self, interaction: discord.Interaction, payment_method: str):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        transaction_id = await self.db.create_transaction(
            listing_id=self.listing_id,
            transaction_type=self.transaction_type,
            buyer_id=self.buyer_id,
            seller_id=self.seller_id,
            amount=self.amount,
            price=self.price,
            rent_days=self.rent_days,
            payment_method=payment_method,
        )

        if self.listing_id:
            await self.db.set_listing_status(self.listing_id, "sold")

        guild = interaction.guild

        async def resolve(member_id: int):
            member = guild.get_member(member_id)
            if member:
                return member
            try:
                return await guild.fetch_member(member_id)
            except discord.NotFound:
                return None

        buyer = await resolve(self.buyer_id)
        seller = await resolve(self.seller_id)

        if not (buyer and seller):
            await interaction.followup.send(
                "❌ Impossible de trouver les membres (ont-ils bien quitté/rejoint le serveur ?).",
                ephemeral=True,
            )
            return

        from tickets import create_ticket  # local import to avoid circular import

        channel = await create_ticket(guild, buyer, seller, transaction_id, self.db)
        await self.db.set_transaction_channel(transaction_id, channel.id)

        await interaction.followup.send(
            f"🎫 Transaction créée : {channel.mention}", ephemeral=True
        )

    @discord.ui.button(label="CMI", emoji="💳", style=discord.ButtonStyle.primary)
    async def cmi(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start_transaction(interaction, "CMI")

    @discord.ui.button(label="Inwi Money", emoji="📱", style=discord.ButtonStyle.success)
    async def inwi(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start_transaction(interaction, "Inwi Money")

    @discord.ui.button(label="Virement bancaire", emoji="🏦", style=discord.ButtonStyle.secondary)
    async def bank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start_transaction(interaction, "Virement bancaire")

    @discord.ui.button(label="Annuler", emoji="✖️", style=discord.ButtonStyle.danger, row=1)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Achat annulé.", view=self)


# ============================================================
# Contrôle d'un ticket de transaction (persistant)
# ============================================================


class TicketControlView(discord.ui.View):
    """Vue persistante : custom_id statiques, l'état vient de la DB via le salon."""

    def __init__(self, db: Database):
        super().__init__(timeout=None)
        self.db = db

    async def _get_transaction_for_channel(self, interaction: discord.Interaction):
        channel = interaction.channel
        if not channel or not channel.name.startswith("transaction-"):
            await interaction.response.send_message(
                "❌ Ce bouton doit être utilisé dans un salon de transaction.",
                ephemeral=True,
            )
            return None
        try:
            tx_id = int(channel.name.split("-")[-1])
        except ValueError:
            await interaction.response.send_message(
                "❌ Impossible de retrouver la transaction liée à ce salon.",
                ephemeral=True,
            )
            return None

        tx = await self.db.get_transaction(tx_id)
        if tx is None:
            await interaction.response.send_message(
                "❌ Transaction introuvable.", ephemeral=True
            )
            return None
        return tx

    @discord.ui.button(
        label="Confirmer ma part",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="dk_ticket_confirm",
    )
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        tx = await self._get_transaction_for_channel(interaction)
        if tx is None:
            return

        if interaction.user.id not in (tx["buyer_id"], tx["seller_id"]):
            await interaction.response.send_message(
                "❌ Vous ne faites pas partie de cette transaction.", ephemeral=True
            )
            return

        if tx["status"] in ("completed", "cancelled"):
            await interaction.response.send_message(
                "ℹ️ Cette transaction est déjà terminée.", ephemeral=True
            )
            return

        side = "buyer" if interaction.user.id == tx["buyer_id"] else "seller"
        already = tx["buyer_confirmed"] if side == "buyer" else tx["seller_confirmed"]

        if already:
            await interaction.response.send_message(
                "ℹ️ Vous avez déjà confirmé.", ephemeral=True
            )
            return

        updated = await self.db.confirm_transaction_side(tx["id"], side)

        await interaction.response.send_message(
            f"✅ {interaction.user.mention} a confirmé sa part de la transaction.",
        )

        if updated["status"] == "completed":
            await self.db.increment_completed_trades(updated["buyer_id"])
            await self.db.increment_completed_trades(updated["seller_id"])

            embed = discord.Embed(
                title="🎉 Transaction terminée",
                description=(
                    "Les deux parties ont confirmé. Merci de laisser un avis avec "
                    f"`/vouch` puis de fermer ce salon avec `/close` ou le bouton ci-dessous."
                ),
                color=discord.Color.green(),
            )
            await interaction.channel.send(embed=embed)

    @discord.ui.button(
        label="Litige",
        emoji="🚨",
        style=discord.ButtonStyle.danger,
        custom_id="dk_ticket_dispute",
    )
    async def dispute(self, interaction: discord.Interaction, button: discord.ui.Button):
        tx = await self._get_transaction_for_channel(interaction)
        if tx is None:
            return

        if interaction.user.id not in (tx["buyer_id"], tx["seller_id"]):
            await interaction.response.send_message(
                "❌ Vous ne faites pas partie de cette transaction.", ephemeral=True
            )
            return

        await self.db.set_transaction_status(tx["id"], "disputed")
        await self.db.create_report(
            reporter_id=interaction.user.id,
            reported_id=(
                tx["seller_id"] if interaction.user.id == tx["buyer_id"] else tx["buyer_id"]
            ),
            reason="Litige ouvert depuis le salon de transaction.",
            transaction_id=tx["id"],
        )

        staff_role = discord.utils.get(interaction.guild.roles, name=config.STAFF_ROLE_NAME)
        mention = staff_role.mention if staff_role else "Staff"

        await interaction.response.send_message(
            f"🚨 Litige ouvert par {interaction.user.mention}. {mention} va intervenir."
        )

    @discord.ui.button(
        label="Fermer",
        emoji="🔒",
        style=discord.ButtonStyle.secondary,
        custom_id="dk_ticket_close",
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        tx = await self._get_transaction_for_channel(interaction)
        if tx is None:
            return

        is_party = interaction.user.id in (tx["buyer_id"], tx["seller_id"])
        is_staff = any(r.name == config.STAFF_ROLE_NAME for r in interaction.user.roles)

        if not (is_party or is_staff):
            await interaction.response.send_message(
                "❌ Vous n'êtes pas autorisé à fermer ce salon.", ephemeral=True
            )
            return

        await interaction.response.send_message("🔒 Fermeture du salon dans 5 secondes...")
        await interaction.channel.send(
            "_Ce salon sera archivé/supprimé. Si besoin, gardez une capture des échanges._"
        )

        import asyncio

        await asyncio.sleep(5)
        await interaction.channel.delete(reason="Transaction terminée / fermée")


# ============================================================
# Gestion de ses propres annonces (/mylistings)
# ============================================================


class ListingManageView(discord.ui.View):
    def __init__(self, db: Database, owner_id: int, listings):
        super().__init__(timeout=180)
        self.db = db
        self.owner_id = owner_id
        self.listings = list(listings)
        self._build()

    def _build(self):
        self.clear_items()
        select = discord.ui.Select(
            placeholder="Choisissez une annonce à annuler...",
            options=[
                discord.SelectOption(
                    label=f"#{l['id']} • {l['game']} • {l['amount']:,.0f} {l['currency']}",
                    description=f"{money(l['price'])} — {l['listing_type']}",
                    value=str(l["id"]),
                )
                for l in self.listings[:25]
            ],
        )
        select.callback = self.on_select
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ Ce ne sont pas vos annonces.", ephemeral=True
            )
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        listing_id = int(interaction.data["values"][0])
        ok = await self.db.cancel_listing(listing_id, self.owner_id)
        if ok:
            self.listings = [l for l in self.listings if l["id"] != listing_id]
            self._build()
            content = f"✅ Annonce #{listing_id} annulée."
        else:
            content = f"❌ Impossible d'annuler l'annonce #{listing_id}."

        if self.listings:
            await interaction.response.edit_message(content=content, view=self)
        else:
            await interaction.response.edit_message(
                content=content + "\nVous n'avez plus d'annonce active.", view=None
            )


# ============================================================
# Pagination des résultats de recherche
# ============================================================


class SearchPaginator(discord.ui.View):
    def __init__(self, db: Database, *, listing_type, game, currency, page_size: int):
        super().__init__(timeout=180)
        self.db = db
        self.listing_type = listing_type
        self.game = game
        self.currency = currency
        self.page_size = page_size
        self.page = 0
        self.total = 0

    async def build_embed(self) -> discord.Embed:
        self.total = await self.db.count_listings(self.listing_type, self.game, self.currency)
        rows = await self.db.search_listings(
            self.listing_type,
            self.game,
            self.currency,
            limit=self.page_size,
            offset=self.page * self.page_size,
        )

        title_bits = ["🔎 Annonces"]
        if self.game:
            title_bits.append(f"— {self.game}")
        embed = discord.Embed(title=" ".join(title_bits), color=discord.Color.blue())

        if not rows:
            embed.description = "Aucune annonce trouvée."
            return embed

        for row in rows:
            kind = {"sell": "🪙 Vente", "buy": "🙋 Recherche d'achat", "rent": "🏠 Location"}.get(
                row["listing_type"], row["listing_type"]
            )

            if row["listing_type"] == "rent":
                price_line = f"💰 **{money(row['price'])} / jour** (min {row['min_days']}j)"
                if row["deposit"]:
                    price_line += f"\n💵 Caution : {money(row['deposit'])}"
            else:
                unit_price = row["price"] / row["amount"] if row["amount"] else 0
                price_line = (
                    f"💰 **{money(row['price'])}**\n📊 {unit_price:.6f} {config.CURRENCY}/unité"
                )

            if row["listing_type"] == "sell":
                command_hint = f"`/buy {row['id']}`"
            elif row["listing_type"] == "rent":
                command_hint = f"`/rentrequest {row['id']}`"
            else:
                command_hint = f"`/offer {row['id']}`"

            embed.add_field(
                name=f"#{row['id']} • {kind} • {row['amount']:,.0f} {row['currency']}",
                value=(
                    f"{price_line}\n"
                    f"🌍 {row['server']}\n"
                    f"👤 {row['seller_name']}\n"
                    f"{command_hint}"
                ),
                inline=False,
            )

        max_page = max(0, (self.total - 1) // self.page_size)
        embed.set_footer(text=f"Page {self.page + 1}/{max_page + 1} • {self.total} annonce(s)")
        return embed

    def update_buttons(self):
        max_page = max(0, (self.total - 1) // self.page_size)
        self.previous.disabled = self.page <= 0
        self.next.disabled = self.page >= max_page

    @discord.ui.button(label="◀ Précédent", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        embed = await self.build_embed()
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Suivant ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        embed = await self.build_embed()
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)


# ============================================================
# Tableau de prix de référence (leskamas.com) — /apply, /applyall
# ============================================================


class PriceTableView(discord.ui.View):
    """Affiche des prix SAUVEGARDÉS en base (instantané). Le bouton
    "Actualiser" est le seul déclencheur qui revisite leskamas.com."""

    def __init__(self, db: Database, section: str | None):
        super().__init__(timeout=600)
        self.db = db
        self.section = section  # None = toutes les sections (tous les jeux)

    async def build_embed(self) -> discord.Embed:
        saved = await self.db.get_reference_prices()
        updated_at = await self.db.get_reference_updated_at()
        footer = f"Dernière actualisation : {updated_at} UTC" if updated_at else "Jamais actualisé"

        if self.section is None:
            embed = discord.Embed(
                title="📥 Tableau des prix — tous les jeux",
                description="Prix sauvegardés localement, colonne de droite = référence leskamas.com **-6%**.",
                color=discord.Color.dark_teal(),
            )
            if not saved:
                embed.description += "\n\n_Aucune donnée pour le moment — cliquez sur Actualiser._"
            for section_name, servers in saved.items():
                if servers:
                    embed.add_field(name=section_name, value=market_reference.format_table(servers), inline=False)
        else:
            servers = saved.get(self.section, {})
            embed = discord.Embed(
                title=f"📥 Tableau des prix — {self.section}",
                description=(
                    "Prix sauvegardés localement, colonne de droite = référence leskamas.com **-6%**.\n"
                    + (market_reference.format_table(servers) if servers else "_Aucune donnée — cliquez sur Actualiser._")
                ),
                color=discord.Color.dark_teal(),
            )

        embed.set_footer(text=footer)
        return embed

    @discord.ui.button(label="🔄 Actualiser tous les prix", style=discord.ButtonStyle.primary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        try:
            sections = await market_reference.fetch_reference_prices()
        except market_reference.ReferencePriceError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        await self.db.save_reference_prices(sections)
        embed = await self.build_embed()
        await interaction.edit_original_response(embed=embed, view=self)


# ============================================================
# Panneau "Espace Vendeurs" — mêmes boutons que la référence IGDREAM
# ============================================================


_SERVER_LINE_RE = re.compile(r"^(.+?)\s+(\d+(?:[.,]\d+)?)\s*M?$", re.IGNORECASE)


def _parse_servers_and_amounts(raw: str) -> tuple[list[tuple[str, float]], list[str]]:
    """"Draconiros 200  ou  Brial 100, Dakal 50" -> [(Draconiros,200), (Brial,100), (Dakal,50)].
    Retourne aussi la liste des segments non reconnus."""
    parts = re.split(r",|\bou\b|\bor\b", raw, flags=re.IGNORECASE)
    parsed: list[tuple[str, float]] = []
    errors: list[str] = []

    for part in parts:
        part = part.strip()
        if not part:
            continue
        match = _SERVER_LINE_RE.match(part)
        if not match:
            errors.append(part)
            continue
        server_name = match.group(1).strip()
        amount = float(match.group(2).replace(",", "."))
        parsed.append((server_name, amount))

    return parsed, errors


class DemarrerVenteModal(discord.ui.Modal, title="Démarrer une vente"):
    servers_input = discord.ui.TextInput(
        label="Serveur(s) et quantité(s) en M",
        style=discord.TextStyle.paragraph,
        placeholder="Ex: Draconiros 200  ou  Brial 100, Dakal 50",
        required=True,
    )
    devise_input = discord.ui.TextInput(
        label="Devise souhaitée (DH / EUR / USDT / USDC)",
        default="DH",
        required=True,
        max_length=10,
    )

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        parsed, errors = _parse_servers_and_amounts(self.servers_input.value)

        if not parsed:
            await interaction.followup.send(
                "❌ Format non reconnu. Exemple attendu : `Draconiros 200` ou `Brial 100, Dakal 50`.",
                ephemeral=True,
            )
            return

        breakdown_lines = []
        total_price = 0.0
        failed_servers = []

        for server_name, amount_million in parsed:
            try:
                reference = await market_reference.fetch_server_price(server_name)
            except market_reference.ReferencePriceError:
                failed_servers.append(server_name)
                continue
            applied = market_reference.apply_discount(reference)
            line_price = applied * amount_million
            total_price += line_price
            breakdown_lines.append(
                f"**{server_name}** — {amount_million:,.0f}M kamas → "
                f"{applied:.3f} {config.CURRENCY}/M → **{line_price:,.2f} {config.CURRENCY}**"
            )

        if not breakdown_lines:
            await interaction.followup.send(
                "❌ Aucun des serveurs indiqués n'a été trouvé sur la référence de prix "
                f"({', '.join(s for s, _ in parsed)}). Vérifiez l'orthographe du serveur.",
                ephemeral=True,
            )
            return

        if failed_servers or errors:
            breakdown_lines.append(
                "\n⚠️ Non reconnus (à préciser au staff) : "
                + ", ".join(failed_servers + errors)
            )

        devise = self.devise_input.value.strip().upper() or "DH"

        request_id = await self.db.create_sell_request(
            user_id=interaction.user.id,
            payload=self.servers_input.value,
            devise=devise,
        )

        from tickets import create_sell_request_ticket

        channel = await create_sell_request_ticket(
            interaction.guild, interaction.user, request_id, breakdown_lines, total_price, devise, self.db
        )
        await self.db.set_sell_request_channel(request_id, channel.id)

        await interaction.followup.send(f"🎫 Ticket créé : {channel.mention}", ephemeral=True)


class AlerteStockModal(discord.ui.Modal, title="Alerte de Stock"):
    server_input = discord.ui.TextInput(label="Serveur", placeholder="Ex: Brial", required=True)
    threshold_input = discord.ui.TextInput(
        label="Quantité seuil (M)", placeholder="Ex: 100", required=False
    )
    devise_input = discord.ui.TextInput(
        label="Devise (EUR, DH, USDT, USDC)", default="EUR", required=True, max_length=10
    )

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        threshold = None
        if self.threshold_input.value.strip():
            try:
                threshold = float(self.threshold_input.value.strip().replace(",", "."))
            except ValueError:
                threshold = None

        await self.db.add_stock_alert(
            user_id=interaction.user.id,
            server=self.server_input.value.strip(),
            threshold_million=threshold,
            devise=self.devise_input.value.strip().upper() or "EUR",
        )

        await interaction.response.send_message(
            f"🔔 Alerte enregistrée pour **{self.server_input.value.strip()}**. "
            "Vous serez notifié en DM dès que ce serveur repasse disponible.",
            ephemeral=True,
        )


class SuiviPrixModal(discord.ui.Modal, title="Suivre un Prix de Rachat"):
    server_input = discord.ui.TextInput(label="Serveur", placeholder="Ex: Brial", required=True)
    devise_input = discord.ui.TextInput(
        label="Devise (EUR, DH, USDT, USDC)", default="EUR", required=True, max_length=10
    )

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        server = self.server_input.value.strip()
        try:
            reference = await market_reference.fetch_server_price(server)
        except market_reference.ReferencePriceError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        await self.db.add_price_follow(
            user_id=interaction.user.id,
            server=server,
            devise=self.devise_input.value.strip().upper() or "EUR",
            last_price=reference,
        )

        await interaction.response.send_message(
            f"📈 Suivi activé pour **{server}** (prix de référence actuel : {reference:.3f} Dhs/M). "
            "Vous serez notifié en DM à chaque variation.",
            ephemeral=True,
        )


class SupportCategorySelect(discord.ui.View):
    def __init__(self, db: Database):
        super().__init__(timeout=180)
        self.db = db

    @discord.ui.select(
        placeholder="Choisissez la catégorie...",
        options=[
            discord.SelectOption(label="Problème avec une commande", emoji="📦", value="Problème avec une commande"),
            discord.SelectOption(label="Demande d'aide", emoji="❓", value="Demande d'aide"),
            discord.SelectOption(label="Collaboration", emoji="🤝", value="Collaboration"),
            discord.SelectOption(label="Autres", emoji="💬", value="Autres"),
        ],
    )
    async def select_category(self, interaction: discord.Interaction, select: discord.ui.Select):
        from tickets import create_support_ticket

        channel = await create_support_ticket(interaction.guild, interaction.user, select.values[0], self.db)
        await interaction.response.edit_message(
            content=f"🎫 Ticket créé : {channel.mention}", view=None
        )


class SellPanelView(discord.ui.View):
    """Vue persistante : reproduit exactement les boutons du panneau vendeur de référence."""

    def __init__(self, db: Database):
        super().__init__(timeout=None)
        self.db = db

    @discord.ui.button(
        label="Démarrer une vente",
        emoji="🎁",
        style=discord.ButtonStyle.success,
        custom_id="dk_panel_start_sale",
        row=0,
    )
    async def start_sale(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DemarrerVenteModal(self.db))

    @discord.ui.button(
        label="Support",
        emoji="🎫",
        style=discord.ButtonStyle.danger,
        custom_id="dk_panel_support",
        row=1,
    )
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Choisissez la catégorie de votre demande :",
            view=SupportCategorySelect(self.db),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Alerte Stock",
        emoji="🔔",
        style=discord.ButtonStyle.primary,
        custom_id="dk_panel_stock_alert",
        row=1,
    )
    async def stock_alert(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AlerteStockModal(self.db))

    @discord.ui.button(
        label="Suivi Prix",
        emoji="📈",
        style=discord.ButtonStyle.primary,
        custom_id="dk_panel_price_follow",
        row=1,
    )
    async def price_follow(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SuiviPrixModal(self.db))

    @discord.ui.button(
        label="Méthodes & Tarifs",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="dk_panel_methods",
        row=2,
    )
    async def methods(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="🇲🇦 Méthodes de Paiement", color=discord.Color.green())
        embed.add_field(
            name="💳 CMI", value="Paiement par carte via le système de paiement officiel.", inline=False
        )
        embed.add_field(
            name="📱 Inwi Money", value="Paiement mobile via le service officiel.", inline=False
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
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Procédure",
        emoji="🏷️",
        style=discord.ButtonStyle.secondary,
        custom_id="dk_panel_procedure",
        row=2,
    )
    async def procedure(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🏷️ Comment vendre vos kamas ?",
            color=discord.Color.blurple(),
            description=(
                "1️⃣ Cliquez sur **🎁 Démarrer une vente**. Un formulaire s'ouvre "
                "(serveur(s), quantité(s), devise).\n"
                "2️⃣ Un **ticket privé** est créé automatiquement avec le prix estimé "
                "(référence leskamas.com -6%).\n"
                "3️⃣ Un membre du staff vous rejoint dans le ticket et récupère vos kamas en jeu.\n"
                "⚠️ Ne donnez jamais vos kamas sans confirmation écrite dans le ticket.\n"
                "4️⃣ Une fois les kamas reçus, le staff clique sur **Marquer payé** et déclenche "
                "le paiement selon la méthode choisie.\n"
                "5️⃣ Pensez à laisser un avis avec `/vouch` !"
            ),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
# Ticket de vente rapide (panneau) — persistant
# ============================================================


class SellRequestControlView(discord.ui.View):
    def __init__(self, db: Database):
        super().__init__(timeout=None)
        self.db = db

    async def _get_request_for_channel(self, interaction: discord.Interaction):
        channel = interaction.channel
        if not channel or not channel.name.startswith("vente-"):
            await interaction.response.send_message(
                "❌ Ce bouton doit être utilisé dans un salon de vente.", ephemeral=True
            )
            return None
        try:
            request_id = int(channel.name.split("-")[-1])
        except ValueError:
            await interaction.response.send_message("❌ Salon invalide.", ephemeral=True)
            return None

        request = await self.db.get_sell_request(request_id)
        if request is None:
            await interaction.response.send_message("❌ Demande introuvable.", ephemeral=True)
            return None
        return request

    def _is_staff(self, member: discord.Member) -> bool:
        return member.guild_permissions.manage_guild or any(
            r.name == config.STAFF_ROLE_NAME for r in member.roles
        )

    @discord.ui.button(
        label="Marquer payé", emoji="✅", style=discord.ButtonStyle.success, custom_id="dk_sell_paid"
    )
    async def mark_paid(self, interaction: discord.Interaction, button: discord.ui.Button):
        request = await self._get_request_for_channel(interaction)
        if request is None:
            return

        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Seul le staff peut marquer cette vente comme payée.", ephemeral=True
            )
            return

        ok = await self.db.mark_sell_request_paid(request["id"])
        if not ok:
            await interaction.response.send_message("ℹ️ Déjà marquée payée.", ephemeral=True)
            return

        await self.db.ensure_user(request["user_id"], str(request["user_id"]))
        await self.db.increment_completed_trades(request["user_id"])

        await interaction.response.send_message(
            f"✅ Vente marquée comme payée par {interaction.user.mention}. "
            f"<@{request['user_id']}> pensez à laisser un avis avec `/vouch`."
        )

    @discord.ui.button(
        label="Fermer", emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="dk_sell_close"
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        request = await self._get_request_for_channel(interaction)
        if request is None:
            return

        is_author = interaction.user.id == request["user_id"]
        if not (is_author or self._is_staff(interaction.user)):
            await interaction.response.send_message(
                "❌ Vous n'êtes pas autorisé à fermer ce salon.", ephemeral=True
            )
            return

        await self.db.set_sell_request_status(request["id"], "closed")
        await interaction.response.send_message("🔒 Fermeture du salon...")
        await asyncio.sleep(3)
        await interaction.channel.delete(reason="Demande de vente terminée")


# ============================================================
# Ticket support — persistant
# ============================================================


class SupportTicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Fermer", emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="dk_support_close"
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        is_staff = interaction.user.guild_permissions.manage_guild or any(
            r.name == config.STAFF_ROLE_NAME for r in interaction.user.roles
        )
        overwrite = channel.overwrites_for(interaction.user)
        is_author = overwrite.view_channel is True

        if not (is_author or is_staff):
            await interaction.response.send_message(
                "❌ Vous n'êtes pas autorisé à fermer ce salon.", ephemeral=True
            )
            return

        await interaction.response.send_message("🔒 Fermeture du salon...")
        await asyncio.sleep(3)
        await channel.delete(reason="Ticket support résolu")
