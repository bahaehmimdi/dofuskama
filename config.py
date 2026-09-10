import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")

DB_FILE = os.getenv("DB_FILE", "marketplace.db")

# ID du serveur Discord. Laisse 0 pour enregistrer les commandes globalement.
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

CURRENCY = os.getenv("SHOP_CURRENCY", "MAD")

# Nom du rôle staff autorisé à gérer les litiges/signalements.
STAFF_ROLE_NAME = os.getenv("STAFF_ROLE_NAME", "Staff")

# Catégorie où sont créés les salons de transaction.
TICKET_CATEGORY_NAME = os.getenv("TICKET_CATEGORY_NAME", "TRANSACTIONS")

# Anti-spam : délai minimum (secondes) entre deux créations d'annonces par un même membre.
LISTING_COOLDOWN_SECONDS = int(os.getenv("LISTING_COOLDOWN_SECONDS", "30"))

# Les annonces plus vieilles que ce délai sont marquées comme expirées automatiquement.
LISTING_EXPIRY_DAYS = int(os.getenv("LISTING_EXPIRY_DAYS", "14"))

# Intervalle (minutes) entre deux passages de la tâche d'expiration des annonces.
EXPIRY_TASK_MINUTES = int(os.getenv("EXPIRY_TASK_MINUTES", "60"))

MAX_DESCRIPTION_LENGTH = 500

PAGE_SIZE = 5

# Salon où sont postées les alertes automatiques (nouveaux gros vendeurs,
# grosses offres, nouveaux badges...). Laisse vide pour désactiver.
ALERT_CHANNEL_NAME = os.getenv("ALERT_CHANNEL_NAME", "annonces-officielles")

# Montant total (prix, ou prix/jour * min_days pour une location) à partir
# duquel une annonce est considérée comme "grosse offre" et déclenche une alerte.
BIG_OFFER_THRESHOLD = float(os.getenv("BIG_OFFER_THRESHOLD", "500"))

# Montant total à partir duquel une transaction est considérée comme "grosse"
# et se voit proposer un middleman.
MIDDLEMAN_THRESHOLD = float(os.getenv("MIDDLEMAN_THRESHOLD", "500"))

# Paliers de rôles vendeurs auto-attribués, sur la base du nombre de vouches
# ET d'un nombre minimum de transactions terminées (pour éviter le boost de faux vouches).
TRUSTED_SELLER_VOUCHES = int(os.getenv("TRUSTED_SELLER_VOUCHES", "10"))
TRUSTED_SELLER_TRADES = int(os.getenv("TRUSTED_SELLER_TRADES", "5"))
TOP_SELLER_VOUCHES = int(os.getenv("TOP_SELLER_VOUCHES", "50"))
TOP_SELLER_TRADES = int(os.getenv("TOP_SELLER_TRADES", "25"))

VERIFIED_SELLER_ROLE_NAME = "Verified Seller"
TRUSTED_SELLER_ROLE_NAME = "Trusted Seller"
TOP_SELLER_ROLE_NAME = "Top Seller"

# Nombre de transactions récentes utilisées pour calculer le cours /price.
PRICE_SAMPLE_SIZE = int(os.getenv("PRICE_SAMPLE_SIZE", "20"))

# Intervalle (minutes) entre deux vérifications des suivis de prix (/price_follows).
PRICE_FOLLOW_TASK_MINUTES = int(os.getenv("PRICE_FOLLOW_TASK_MINUTES", "30"))
