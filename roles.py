"""Rôles vendeurs auto-attribués, alertes automatiques et garde anti-blacklist."""

import discord

import config
from database import Database

BADGE_COLORS = {
    config.VERIFIED_SELLER_ROLE_NAME: discord.Color.blue(),
    config.TRUSTED_SELLER_ROLE_NAME: discord.Color.gold(),
    config.TOP_SELLER_ROLE_NAME: discord.Color.purple(),
}


async def get_or_create_role(guild: discord.Guild, name: str) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role:
        return role
    return await guild.create_role(
        name=name,
        color=BADGE_COLORS.get(name, discord.Color.default()),
        mentionable=False,
        reason="Rôle vendeur marketplace auto-créé",
    )


async def sync_seller_roles(guild: discord.Guild, member: discord.Member, user_row) -> list[str]:
    """Ajoute/retire les rôles vendeurs en fonction des stats du membre.
    Retourne la liste des rôles nouvellement obtenus (pour une éventuelle alerte)."""

    vouches = user_row["vouches"]
    trades = user_row["completed_trades"]
    verified = bool(user_row["verified"])

    wanted = set()
    if verified:
        wanted.add(config.VERIFIED_SELLER_ROLE_NAME)
    if vouches >= config.TRUSTED_SELLER_VOUCHES and trades >= config.TRUSTED_SELLER_TRADES:
        wanted.add(config.TRUSTED_SELLER_ROLE_NAME)
    if vouches >= config.TOP_SELLER_VOUCHES and trades >= config.TOP_SELLER_TRADES:
        wanted.add(config.TOP_SELLER_ROLE_NAME)

    all_badge_names = (
        config.VERIFIED_SELLER_ROLE_NAME,
        config.TRUSTED_SELLER_ROLE_NAME,
        config.TOP_SELLER_ROLE_NAME,
    )
    current = {r.name for r in member.roles if r.name in all_badge_names}

    newly_gained = []

    for name in all_badge_names:
        role = await get_or_create_role(guild, name)
        if name in wanted and name not in current:
            await member.add_roles(role, reason="Palier vendeur atteint")
            newly_gained.append(name)
        elif name not in wanted and name in current:
            await member.remove_roles(role, reason="Palier vendeur non maintenu")

    return newly_gained


async def post_alert(guild: discord.Guild, embed: discord.Embed):
    if not config.ALERT_CHANNEL_NAME:
        return
    channel = discord.utils.get(guild.text_channels, name=config.ALERT_CHANNEL_NAME)
    if channel is None:
        return
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass


async def check_not_blacklisted(interaction: discord.Interaction, db: Database) -> bool:
    """Retourne True si l'utilisateur PEUT continuer (pas blacklist).
    Envoie un message ephemeral et retourne False sinon."""

    entry = await db.get_blacklist_entry(interaction.user.id)
    if entry is None:
        return True

    await interaction.response.send_message(
        f"⛔ Vous êtes blacklist du marketplace.\nRaison : {entry['reason']}",
        ephemeral=True,
    )
    return False
