import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import market_reference
from database import Database
from views import SellPanelView, SellRequestControlView, SupportTicketCloseView, TicketControlView

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dofuskama")

EXTENSIONS = (
    "cogs.marketplace",
    "cogs.transactions",
    "cogs.reputation",
    "cogs.admin",
    "cogs.panel",
)


class MarketplaceBot(commands.Bot):
    def __init__(self):
        # Only slash commands are used (no prefix commands, no member cache
        # iteration) so no privileged intent needs to be toggled on in the
        # Developer Portal — member lookups go through fetch_member() instead.
        intents = discord.Intents.default()

        super().__init__(command_prefix="!", intents=intents)

        self.db = Database(config.DB_FILE)

    async def setup_hook(self):
        await self.db.connect()

        # Vues persistantes : boutons/panneaux toujours fonctionnels après un
        # redémarrage du bot (custom_id statiques, contexte relu depuis la DB).
        self.add_view(TicketControlView(self.db))
        self.add_view(SellPanelView(self.db))
        self.add_view(SellRequestControlView(self.db))
        self.add_view(SupportTicketCloseView())

        for ext in EXTENSIONS:
            await self.load_extension(ext)

        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("%d commandes synchronisées (guilde %s).", len(synced), config.GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("%d commandes globales synchronisées.", len(synced))

        self.expire_listings_task.start()
        self.price_follow_task.start()

    async def close(self):
        self.expire_listings_task.cancel()
        self.price_follow_task.cancel()
        await self.db.close()
        await super().close()

    @tasks.loop(minutes=config.EXPIRY_TASK_MINUTES)
    async def expire_listings_task(self):
        try:
            count = await self.db.expire_old_listings(config.LISTING_EXPIRY_DAYS)
            if count:
                log.info("%d annonce(s) expirée(s) automatiquement.", count)
        except Exception:
            log.exception("Erreur lors de l'expiration automatique des annonces.")

    @expire_listings_task.before_loop
    async def before_expire_listings_task(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=config.PRICE_FOLLOW_TASK_MINUTES)
    async def price_follow_task(self):
        try:
            follows = await self.db.list_price_follows()
            if not follows:
                return
            sections = await market_reference.fetch_reference_prices()
            servers = sections.get(market_reference.DEFAULT_SECTION, {})

            for follow in follows:
                current = servers.get(follow["server"])
                if current is None or current == follow["last_price"]:
                    continue

                await self.db.update_price_follow_last_price(follow["id"], current)
                user = self.get_user(follow["user_id"]) or await self.fetch_user(follow["user_id"])
                if user is None:
                    continue
                direction = "📈" if current > follow["last_price"] else "📉"
                try:
                    await user.send(
                        f"{direction} Cours de rachat **{follow['server']}** : "
                        f"{follow['last_price']:.3f} → {current:.3f} Dhs/M"
                    )
                except discord.Forbidden:
                    pass
        except Exception:
            log.exception("Erreur lors de la vérification des suivis de prix.")

    @price_follow_task.before_loop
    async def before_price_follow_task(self):
        await self.wait_until_ready()


bot = MarketplaceBot()


@bot.event
async def on_ready():
    log.info("Connecté : %s (ID: %s)", bot.user, bot.user.id)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"⏳ Merci de patienter {error.retry_after:.0f}s avant de réessayer."
    elif isinstance(error, app_commands.MissingPermissions):
        message = "❌ Vous n'avez pas la permission d'utiliser cette commande."
    else:
        log.exception("Erreur de commande non gérée", exc_info=error)
        message = "❌ Une erreur est survenue lors de l'exécution de la commande."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


if __name__ == "__main__":
    if config.TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("Configure la variable d'environnement DISCORD_TOKEN avant de lancer le bot.")

    bot.run(config.TOKEN)
