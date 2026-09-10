"""Couche d'accès asynchrone à la base SQLite du marketplace.

Utilise aiosqlite pour ne jamais bloquer la boucle d'évènements du bot
(sqlite3 standard est synchrone et bloquant).
"""

from datetime import datetime, timedelta
from typing import Optional, Sequence

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    discord_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    reputation INTEGER DEFAULT 0,
    vouches INTEGER DEFAULT 0,
    completed_trades INTEGER DEFAULT 0,
    verified INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id INTEGER NOT NULL,
    seller_name TEXT NOT NULL,
    listing_type TEXT NOT NULL DEFAULT 'sell',   -- 'sell' | 'buy' | 'rent'
    game TEXT NOT NULL,
    server TEXT NOT NULL,
    currency TEXT NOT NULL,
    amount REAL NOT NULL,
    price REAL NOT NULL,
    price_unit TEXT NOT NULL DEFAULT 'total',    -- 'total' | 'per_day'
    min_days INTEGER,
    deposit REAL,
    description TEXT,
    status TEXT DEFAULT 'active',                -- active|sold|cancelled|expired
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER,
    transaction_type TEXT NOT NULL DEFAULT 'sell',  -- 'sell' | 'rent'
    buyer_id INTEGER NOT NULL,
    seller_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    price REAL NOT NULL,
    rent_days INTEGER,
    payment_method TEXT,
    channel_id INTEGER,
    status TEXT DEFAULT 'pending',   -- pending|buyer_confirmed|seller_confirmed|completed|cancelled|disputed
    buyer_confirmed INTEGER DEFAULT 0,
    seller_confirmed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS vouches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id INTEGER NOT NULL,
    buyer_id INTEGER NOT NULL,
    transaction_id INTEGER,
    rating INTEGER NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER NOT NULL,
    reported_id INTEGER NOT NULL,
    transaction_id INTEGER,
    reason TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blacklist (
    discord_id INTEGER PRIMARY KEY,
    reason TEXT NOT NULL,
    staff_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reference_prices (
    section TEXT NOT NULL,
    server TEXT NOT NULL,
    price REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (section, server)
);

CREATE TABLE IF NOT EXISTS sell_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    payload TEXT NOT NULL,
    devise TEXT NOT NULL,
    status TEXT DEFAULT 'open',       -- open|paid|closed
    channel_id INTEGER,
    created_at TEXT NOT NULL,
    paid_at TEXT
);

CREATE TABLE IF NOT EXISTS server_stock (
    server TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'disponible',  -- disponible|complet
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    server TEXT NOT NULL,
    threshold_million REAL,
    devise TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_follows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    server TEXT NOT NULL,
    devise TEXT NOT NULL,
    last_price REAL,
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.utcnow().isoformat()


class Database:
    def __init__(self, path: str):
        self._path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    # ------------------------------------------------------------
    # Users
    # ------------------------------------------------------------

    async def ensure_user(self, discord_id: int, username: str):
        await self._conn.execute(
            """
            INSERT INTO users (discord_id, username, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET username = excluded.username
            """,
            (discord_id, username, now()),
        )
        await self._conn.commit()

    async def get_user(self, discord_id: int) -> Optional[aiosqlite.Row]:
        cur = await self._conn.execute(
            "SELECT * FROM users WHERE discord_id = ?", (discord_id,)
        )
        return await cur.fetchone()

    async def update_reputation(self, seller_id: int, rating: int):
        await self._conn.execute(
            """
            UPDATE users
            SET vouches = vouches + 1, reputation = reputation + ?
            WHERE discord_id = ?
            """,
            (rating, seller_id),
        )
        await self._conn.commit()

    async def increment_completed_trades(self, discord_id: int):
        await self._conn.execute(
            "UPDATE users SET completed_trades = completed_trades + 1 WHERE discord_id = ?",
            (discord_id,),
        )
        await self._conn.commit()

    # ------------------------------------------------------------
    # Listings
    # ------------------------------------------------------------

    async def create_listing(
        self,
        seller_id: int,
        seller_name: str,
        listing_type: str,
        game: str,
        server: str,
        currency: str,
        amount: float,
        price: float,
        price_unit: str = "total",
        min_days: Optional[int] = None,
        deposit: Optional[float] = None,
        description: Optional[str] = None,
    ) -> int:
        cur = await self._conn.execute(
            """
            INSERT INTO listings
            (seller_id, seller_name, listing_type, game, server, currency,
             amount, price, price_unit, min_days, deposit, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                seller_id,
                seller_name,
                listing_type,
                game,
                server,
                currency,
                amount,
                price,
                price_unit,
                min_days,
                deposit,
                description or "",
                now(),
            ),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def get_listing(self, listing_id: int) -> Optional[aiosqlite.Row]:
        cur = await self._conn.execute(
            "SELECT * FROM listings WHERE id = ?", (listing_id,)
        )
        return await cur.fetchone()

    async def search_listings(
        self,
        listing_type: Optional[str] = None,
        game: Optional[str] = None,
        currency: Optional[str] = None,
        limit: int = 5,
        offset: int = 0,
    ) -> Sequence[aiosqlite.Row]:
        clauses = ["status = 'active'"]
        params: list = []

        if listing_type:
            clauses.append("listing_type = ?")
            params.append(listing_type)
        if game:
            clauses.append("LOWER(game) = LOWER(?)")
            params.append(game)
        if currency:
            clauses.append("LOWER(currency) = LOWER(?)")
            params.append(currency)

        where = " AND ".join(clauses)
        params.extend([limit, offset])

        cur = await self._conn.execute(
            f"""
            SELECT * FROM listings
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        )
        return await cur.fetchall()

    async def count_listings(
        self,
        listing_type: Optional[str] = None,
        game: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> int:
        clauses = ["status = 'active'"]
        params: list = []

        if listing_type:
            clauses.append("listing_type = ?")
            params.append(listing_type)
        if game:
            clauses.append("LOWER(game) = LOWER(?)")
            params.append(game)
        if currency:
            clauses.append("LOWER(currency) = LOWER(?)")
            params.append(currency)

        where = " AND ".join(clauses)
        cur = await self._conn.execute(
            f"SELECT COUNT(*) AS n FROM listings WHERE {where}", params
        )
        row = await cur.fetchone()
        return row["n"] if row else 0

    async def get_user_listings(self, discord_id: int) -> Sequence[aiosqlite.Row]:
        cur = await self._conn.execute(
            """
            SELECT * FROM listings
            WHERE seller_id = ? AND status = 'active'
            ORDER BY created_at DESC
            """,
            (discord_id,),
        )
        return await cur.fetchall()

    async def set_listing_status(self, listing_id: int, status: str) -> bool:
        cur = await self._conn.execute(
            "UPDATE listings SET status = ? WHERE id = ?", (status, listing_id)
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def cancel_listing(self, listing_id: int, owner_id: int) -> bool:
        cur = await self._conn.execute(
            """
            UPDATE listings SET status = 'cancelled'
            WHERE id = ? AND seller_id = ? AND status = 'active'
            """,
            (listing_id, owner_id),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def expire_old_listings(self, days: int) -> int:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        cur = await self._conn.execute(
            """
            UPDATE listings SET status = 'expired'
            WHERE status = 'active' AND created_at < ?
            """,
            (cutoff,),
        )
        await self._conn.commit()
        return cur.rowcount

    async def distinct_games(self, prefix: str = "", limit: int = 25) -> Sequence[str]:
        cur = await self._conn.execute(
            """
            SELECT DISTINCT game FROM listings
            WHERE status = 'active' AND LOWER(game) LIKE LOWER(?)
            ORDER BY game LIMIT ?
            """,
            (f"{prefix}%", limit),
        )
        rows = await cur.fetchall()
        return [r["game"] for r in rows]

    # ------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------

    async def create_transaction(
        self,
        listing_id: Optional[int],
        transaction_type: str,
        buyer_id: int,
        seller_id: int,
        amount: float,
        price: float,
        rent_days: Optional[int] = None,
        payment_method: Optional[str] = None,
    ) -> int:
        cur = await self._conn.execute(
            """
            INSERT INTO transactions
            (listing_id, transaction_type, buyer_id, seller_id, amount, price,
             rent_days, payment_method, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                listing_id,
                transaction_type,
                buyer_id,
                seller_id,
                amount,
                price,
                rent_days,
                payment_method,
                now(),
            ),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def get_transaction(self, transaction_id: int) -> Optional[aiosqlite.Row]:
        cur = await self._conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
        )
        return await cur.fetchone()

    async def set_transaction_channel(self, transaction_id: int, channel_id: int):
        await self._conn.execute(
            "UPDATE transactions SET channel_id = ? WHERE id = ?",
            (channel_id, transaction_id),
        )
        await self._conn.commit()

    async def confirm_transaction_side(self, transaction_id: int, side: str) -> aiosqlite.Row:
        """side is 'buyer' or 'seller'. Returns the updated row."""
        column = "buyer_confirmed" if side == "buyer" else "seller_confirmed"
        await self._conn.execute(
            f"UPDATE transactions SET {column} = 1 WHERE id = ?", (transaction_id,)
        )
        row = await self.get_transaction(transaction_id)
        if row["buyer_confirmed"] and row["seller_confirmed"]:
            await self._conn.execute(
                "UPDATE transactions SET status = 'completed', completed_at = ? WHERE id = ?",
                (now(), transaction_id),
            )
        else:
            status = "buyer_confirmed" if row["buyer_confirmed"] else "seller_confirmed"
            await self._conn.execute(
                "UPDATE transactions SET status = ? WHERE id = ?",
                (status, transaction_id),
            )
        await self._conn.commit()
        return await self.get_transaction(transaction_id)

    async def set_transaction_status(self, transaction_id: int, status: str):
        await self._conn.execute(
            "UPDATE transactions SET status = ? WHERE id = ?",
            (status, transaction_id),
        )
        await self._conn.commit()

    # ------------------------------------------------------------
    # Vouches & reports
    # ------------------------------------------------------------

    async def create_vouch(
        self,
        seller_id: int,
        buyer_id: int,
        rating: int,
        comment: str,
        transaction_id: Optional[int] = None,
    ):
        await self._conn.execute(
            """
            INSERT INTO vouches (seller_id, buyer_id, transaction_id, rating, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (seller_id, buyer_id, transaction_id, rating, comment, now()),
        )
        await self._conn.commit()
        await self.update_reputation(seller_id, rating)

    async def create_report(
        self,
        reporter_id: int,
        reported_id: int,
        reason: str,
        transaction_id: Optional[int] = None,
    ) -> int:
        cur = await self._conn.execute(
            """
            INSERT INTO reports (reporter_id, reported_id, transaction_id, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (reporter_id, reported_id, transaction_id, reason, now()),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def get_report(self, report_id: int) -> Optional[aiosqlite.Row]:
        cur = await self._conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
        return await cur.fetchone()

    async def list_reports(self, status: str = "open", limit: int = 10) -> Sequence[aiosqlite.Row]:
        cur = await self._conn.execute(
            """
            SELECT * FROM reports WHERE status = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (status, limit),
        )
        return await cur.fetchall()

    async def resolve_report(self, report_id: int) -> bool:
        cur = await self._conn.execute(
            "UPDATE reports SET status = 'resolved' WHERE id = ? AND status = 'open'",
            (report_id,),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def set_verified(self, discord_id: int, verified: bool) -> bool:
        cur = await self._conn.execute(
            "UPDATE users SET verified = ? WHERE discord_id = ?",
            (1 if verified else 0, discord_id),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------
    # Blacklist
    # ------------------------------------------------------------

    async def add_blacklist(self, discord_id: int, reason: str, staff_id: int):
        await self._conn.execute(
            """
            INSERT INTO blacklist (discord_id, reason, staff_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET
                reason = excluded.reason,
                staff_id = excluded.staff_id,
                created_at = excluded.created_at
            """,
            (discord_id, reason, staff_id, now()),
        )
        await self._conn.commit()

    async def remove_blacklist(self, discord_id: int) -> bool:
        cur = await self._conn.execute(
            "DELETE FROM blacklist WHERE discord_id = ?", (discord_id,)
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def get_blacklist_entry(self, discord_id: int) -> Optional[aiosqlite.Row]:
        cur = await self._conn.execute(
            "SELECT * FROM blacklist WHERE discord_id = ?", (discord_id,)
        )
        return await cur.fetchone()

    async def is_blacklisted(self, discord_id: int) -> bool:
        return (await self.get_blacklist_entry(discord_id)) is not None

    async def list_blacklist(self, limit: int = 25) -> Sequence[aiosqlite.Row]:
        cur = await self._conn.execute(
            "SELECT * FROM blacklist ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return await cur.fetchall()

    # ------------------------------------------------------------
    # Cours du marché
    # ------------------------------------------------------------

    async def market_price_stats(
        self, game: str, currency: str, sample_size: int
    ) -> Optional[dict]:
        """Statistiques de prix basées sur les dernières transactions VENTE
        terminées pour ce jeu/monnaie. Retombe sur les annonces actives si
        aucune transaction n'est encore terminée."""

        cur = await self._conn.execute(
            """
            SELECT t.price / t.amount AS unit_price, t.created_at
            FROM transactions t
            JOIN listings l ON l.id = t.listing_id
            WHERE t.transaction_type = 'sell'
              AND t.status = 'completed'
              AND t.amount > 0
              AND LOWER(l.game) = LOWER(?)
              AND LOWER(l.currency) = LOWER(?)
            ORDER BY t.completed_at DESC
            LIMIT ?
            """,
            (game, currency, sample_size),
        )
        rows = await cur.fetchall()
        source = "transactions"

        if not rows:
            cur = await self._conn.execute(
                """
                SELECT price / amount AS unit_price, created_at
                FROM listings
                WHERE listing_type = 'sell'
                  AND status = 'active'
                  AND amount > 0
                  AND LOWER(game) = LOWER(?)
                  AND LOWER(currency) = LOWER(?)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (game, currency, sample_size),
            )
            rows = await cur.fetchall()
            source = "listings"

        if not rows:
            return None

        prices = [r["unit_price"] for r in rows]
        return {
            "source": source,
            "sample_size": len(prices),
            "avg": sum(prices) / len(prices),
            "min": min(prices),
            "max": max(prices),
            "latest": prices[0],
        }

    # ------------------------------------------------------------
    # Prix de référence externes (leskamas.com), mis en cache
    # ------------------------------------------------------------

    async def save_reference_prices(self, sections: dict):
        """sections = {section_name: {server_name: price}}. Remplace tout d'un coup."""
        ts = now()
        rows = [
            (section, server, price, ts)
            for section, servers in sections.items()
            for server, price in servers.items()
        ]
        if not rows:
            return
        await self._conn.executemany(
            """
            INSERT INTO reference_prices (section, server, price, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(section, server) DO UPDATE SET
                price = excluded.price,
                updated_at = excluded.updated_at
            """,
            rows,
        )
        await self._conn.commit()

    async def get_reference_prices(self) -> dict:
        cur = await self._conn.execute(
            "SELECT section, server, price FROM reference_prices ORDER BY section, server"
        )
        rows = await cur.fetchall()
        sections: dict = {}
        for row in rows:
            sections.setdefault(row["section"], {})[row["server"]] = row["price"]
        return sections

    async def get_reference_updated_at(self) -> Optional[str]:
        cur = await self._conn.execute("SELECT MAX(updated_at) AS ts FROM reference_prices")
        row = await cur.fetchone()
        return row["ts"] if row else None

    # ------------------------------------------------------------
    # Demandes de vente rapide (panneau "Démarrer une vente")
    # ------------------------------------------------------------

    async def create_sell_request(self, user_id: int, payload: str, devise: str) -> int:
        cur = await self._conn.execute(
            """
            INSERT INTO sell_requests (user_id, payload, devise, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, payload, devise, now()),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def get_sell_request(self, request_id: int) -> Optional[aiosqlite.Row]:
        cur = await self._conn.execute("SELECT * FROM sell_requests WHERE id = ?", (request_id,))
        return await cur.fetchone()

    async def set_sell_request_channel(self, request_id: int, channel_id: int):
        await self._conn.execute(
            "UPDATE sell_requests SET channel_id = ? WHERE id = ?", (channel_id, request_id)
        )
        await self._conn.commit()

    async def mark_sell_request_paid(self, request_id: int) -> bool:
        cur = await self._conn.execute(
            "UPDATE sell_requests SET status = 'paid', paid_at = ? WHERE id = ? AND status = 'open'",
            (now(), request_id),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def set_sell_request_status(self, request_id: int, status: str):
        await self._conn.execute(
            "UPDATE sell_requests SET status = ? WHERE id = ?", (status, request_id)
        )
        await self._conn.commit()

    # ------------------------------------------------------------
    # Stock serveur & alertes
    # ------------------------------------------------------------

    async def set_server_stock(self, server: str, status: str):
        await self._conn.execute(
            """
            INSERT INTO server_stock (server, status, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(server) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at
            """,
            (server, status, now()),
        )
        await self._conn.commit()

    async def get_server_stock(self, server: str) -> Optional[aiosqlite.Row]:
        cur = await self._conn.execute(
            "SELECT * FROM server_stock WHERE server = ?", (server,)
        )
        return await cur.fetchone()

    async def add_stock_alert(
        self, user_id: int, server: str, threshold_million: Optional[float], devise: str
    ) -> int:
        cur = await self._conn.execute(
            """
            INSERT INTO stock_alerts (user_id, server, threshold_million, devise, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, server, threshold_million, devise, now()),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def pop_stock_alerts(self, server: str) -> Sequence[aiosqlite.Row]:
        """Retourne et supprime toutes les alertes de stock pour ce serveur (envoi unique)."""
        cur = await self._conn.execute("SELECT * FROM stock_alerts WHERE server = ?", (server,))
        rows = await cur.fetchall()
        if rows:
            await self._conn.execute("DELETE FROM stock_alerts WHERE server = ?", (server,))
            await self._conn.commit()
        return rows

    # ------------------------------------------------------------
    # Suivi de prix
    # ------------------------------------------------------------

    async def add_price_follow(self, user_id: int, server: str, devise: str, last_price: float) -> int:
        cur = await self._conn.execute(
            """
            INSERT INTO price_follows (user_id, server, devise, last_price, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, server, devise, last_price, now()),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def list_price_follows(self) -> Sequence[aiosqlite.Row]:
        cur = await self._conn.execute("SELECT * FROM price_follows")
        return await cur.fetchall()

    async def update_price_follow_last_price(self, follow_id: int, price: float):
        await self._conn.execute(
            "UPDATE price_follows SET last_price = ? WHERE id = ?", (price, follow_id)
        )
        await self._conn.commit()
