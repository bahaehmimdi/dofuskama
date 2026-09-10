"""Serveur HTTP minimal, requis par les plateformes de type "Web Service"
(Render, Railway en mode web, etc.) qui exigent un port ouvert pour
considérer le déploiement comme en bonne santé. N'ajoute aucune dépendance :
aiohttp est déjà installé en tant que dépendance de discord.py.
"""

import os

from aiohttp import web


async def start_health_server():
    port = int(os.getenv("PORT", "8080"))

    app = web.Application()
    app.router.add_get("/", lambda request: web.Response(text="dofuskama bot is running"))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    return runner
