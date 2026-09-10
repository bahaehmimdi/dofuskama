"""Création des salons de transaction (tickets)."""

import discord

import config
from database import Database


async def _get_or_create_category(guild: discord.Guild, name: str) -> discord.CategoryChannel:
    category = discord.utils.get(guild.categories, name=name)
    if category is None:
        category = await guild.create_category(name)
    return category


async def create_ticket(
    guild: discord.Guild,
    buyer: discord.Member,
    seller: discord.Member,
    transaction_id: int,
    db: Database,
) -> discord.TextChannel:
    category = discord.utils.get(guild.categories, name=config.TICKET_CATEGORY_NAME)
    if category is None:
        category = await guild.create_category(config.TICKET_CATEGORY_NAME)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        buyer: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
        seller: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            read_message_history=True,
        ),
    }

    staff_role = discord.utils.get(guild.roles, name=config.STAFF_ROLE_NAME)
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )

    channel = await guild.create_text_channel(
        f"transaction-{transaction_id}",
        category=category,
        overwrites=overwrites,
    )

    tx = await db.get_transaction(transaction_id)

    kind_label = "location" if tx["transaction_type"] == "rent" else "vente"
    if tx["transaction_type"] == "rent":
        # tx['price'] est déjà le prix TOTAL (price_per_day * jours), pas un prix/jour.
        details = (
            f"**{tx['rent_days']}** jour(s) — **Prix total : {tx['price']:,.2f} {config.CURRENCY}**"
        )
    else:
        details = f"**{tx['amount']:,.0f}** unités — **{tx['price']:,.2f} {config.CURRENCY}**"

    description = (
        f"{details}\n"
        f"💳 Moyen de paiement choisi : **{tx['payment_method']}**\n\n"
        "⚠️ Ne donnez jamais votre mot de passe, PIN bancaire ou code de sécurité.\n"
        "Utilisez uniquement les moyens de paiement officiellement proposés.\n\n"
        "Quand votre part de l'échange est faite (paiement envoyé / bien livré), "
        "cliquez sur **Confirmer ma part**. Une fois les deux parties confirmées, "
        "la transaction est automatiquement marquée comme terminée."
    )

    if tx["price"] >= config.MIDDLEMAN_THRESHOLD:
        description += (
            "\n\n🛡️ Grosse transaction : pensez à demander un médiateur avec `/middleman`."
        )

    embed = discord.Embed(
        title=f"🎫 Transaction #{transaction_id} ({kind_label})",
        description=description,
        color=discord.Color.blue(),
    )
    embed.add_field(name="Acheteur / Locataire", value=buyer.mention)
    embed.add_field(name="Vendeur / Loueur", value=seller.mention)

    from views import TicketControlView

    await channel.send(
        content=f"{buyer.mention} {seller.mention}",
        embed=embed,
        view=TicketControlView(db),
    )

    return channel


async def create_sell_request_ticket(
    guild: discord.Guild,
    seller: discord.Member,
    request_id: int,
    breakdown_lines: list[str],
    total_price: float,
    devise: str,
    db: Database,
) -> discord.TextChannel:
    """Ticket privé vendeur <-> staff pour une demande de vente lancée depuis le panneau
    "Démarrer une vente" (pas de deuxième particulier : le staff rachète les kamas)."""

    category = await _get_or_create_category(guild, "VENTES")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        seller: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            read_message_history=True,
        ),
    }

    staff_role = discord.utils.get(guild.roles, name=config.STAFF_ROLE_NAME)
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )

    channel = await guild.create_text_channel(
        f"vente-{request_id}",
        category=category,
        overwrites=overwrites,
    )

    embed = discord.Embed(
        title=f"💸 Demande de vente #{request_id}",
        description=(
            "\n".join(breakdown_lines)
            + f"\n\n**Total estimé : {total_price:,.2f} {config.CURRENCY}** (devise demandée : {devise})\n\n"
            "⚠️ Ne donnez jamais votre mot de passe, PIN ou code de sécurité.\n"
            f"Un membre du **{config.STAFF_ROLE_NAME}** va vous rejoindre pour récupérer vos kamas en jeu "
            "et déclencher le paiement.\n\n"
            "Prix estimés à partir de la référence leskamas.com -6% : non garantis tant que le "
            "staff n'a pas confirmé, les cours pouvant varier."
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(name="Vendeur", value=seller.mention)

    from views import SellRequestControlView

    await channel.send(
        content=f"{seller.mention} {staff_role.mention if staff_role else ''}".strip(),
        embed=embed,
        view=SellRequestControlView(db),
    )

    return channel


async def create_support_ticket(
    guild: discord.Guild,
    author: discord.Member,
    category_label: str,
    db: Database,
) -> discord.TextChannel:
    category = await _get_or_create_category(guild, "SUPPORT")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        author: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            read_message_history=True,
        ),
    }

    staff_role = discord.utils.get(guild.roles, name=config.STAFF_ROLE_NAME)
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )

    safe_suffix = str(author.id)[-6:]
    channel = await guild.create_text_channel(
        f"support-{safe_suffix}",
        category=category,
        overwrites=overwrites,
    )

    embed = discord.Embed(
        title="🎫 Ticket support",
        description=f"Catégorie : **{category_label}**\n\nDécrivez votre demande, le staff vous répondra.",
        color=discord.Color.red(),
    )

    from views import SupportTicketCloseView

    await channel.send(
        content=f"{author.mention} {staff_role.mention if staff_role else ''}".strip(),
        embed=embed,
        view=SupportTicketCloseView(),
    )

    return channel
