/**
 * Cloudflare Worker — hosts the Privacy Policy and Terms of Service pages
 * required in the Discord Developer Portal when creating/registering a bot.
 * No dependencies, no build step — plain ES module Worker.
 */

const HTML_HEAD = (title) => `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, -apple-system, sans-serif; max-width: 780px; margin: 0 auto; padding: 32px 20px 80px; line-height: 1.6; }
  h1 { font-size: 1.7rem; margin-bottom: .2em; }
  h2 { font-size: 1.15rem; margin-top: 2em; }
  .updated { color: #888; font-size: .9rem; margin-bottom: 2em; }
  code { background: rgba(127,127,127,.15); padding: .1em .4em; border-radius: 4px; }
</style>
</head>
<body>`;

const HTML_FOOT = `</body></html>`;

const BOT_NAME = "REPLACE_WITH_BOT_NAME";
const CONTACT = "REPLACE_WITH_CONTACT_EMAIL_OR_SUPPORT_LINK";
const LAST_UPDATED = "2026-09-10";

function privacyPolicyHtml() {
  return `${HTML_HEAD(`Privacy Policy — ${BOT_NAME}`)}
<h1>Privacy Policy</h1>
<p class="updated">Last updated: ${LAST_UPDATED}</p>

<p>This policy describes what data the Discord bot <strong>${BOT_NAME}</strong> processes.</p>

<h2>Data collected</h2>
<ul>
  <li>Your Discord user ID and username, when you first use a command.</li>
  <li>The content you submit through the bot's commands (e.g. listings, messages, settings).</li>
  <li>Basic usage/interaction logs for debugging and abuse prevention.</li>
</ul>

<h2>Data not collected</h2>
<p>The bot never asks for or stores passwords, PIN codes, or payment/banking details.</p>

<h2>Data retention and deletion</h2>
<p>Data is kept only as long as the bot is active in your server. To request deletion of your
data, contact us at ${CONTACT}.</p>

<h2>Contact</h2>
<p>${CONTACT}</p>

<hr>
<p style="color:#888;font-size:.85rem">This is a generic template — have it reviewed before
relying on it for Discord's bot verification or for legal compliance (GDPR, etc.).</p>
${HTML_FOOT}`;
}

function termsOfServiceHtml() {
  return `${HTML_HEAD(`Terms of Service — ${BOT_NAME}`)}
<h1>Terms of Service</h1>
<p class="updated">Last updated: ${LAST_UPDATED}</p>

<p>By using <strong>${BOT_NAME}</strong>, you agree to the following terms.</p>

<h2>Service</h2>
<p>The bot is provided "as is", without warranty of any kind. Features and availability may
change at any time without notice.</p>

<h2>Acceptable use</h2>
<ul>
  <li>Do not use the bot to abuse, spam, or defraud other users.</li>
  <li>Do not attempt to exploit, reverse engineer, or disrupt the bot's operation.</li>
</ul>

<h2>Limitation of liability</h2>
<p>The bot's operator is not liable for any damages arising from use of the bot, to the fullest
extent permitted by law.</p>

<h2>Changes</h2>
<p>These terms may be updated at any time; the date above reflects the latest revision.</p>

<h2>Contact</h2>
<p>${CONTACT}</p>

<hr>
<p style="color:#888;font-size:.85rem">This is a generic template — have it reviewed before
relying on it for Discord's bot verification or for legal compliance.</p>
${HTML_FOOT}`;
}

function homeHtml() {
  return `${HTML_HEAD(BOT_NAME)}
<h1>${BOT_NAME}</h1>
<ul>
  <li><a href="/privacy">Privacy Policy</a></li>
  <li><a href="/terms">Terms of Service</a></li>
</ul>
${HTML_FOOT}`;
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const html = (body) => new Response(body, { headers: { "content-type": "text/html; charset=utf-8" } });

    if (url.pathname === "/") return html(homeHtml());
    if (url.pathname === "/privacy") return html(privacyPolicyHtml());
    if (url.pathname === "/terms") return html(termsOfServiceHtml());

    return new Response("Not found", { status: 404 });
  },
};
