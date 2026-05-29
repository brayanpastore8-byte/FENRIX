import os
import aiohttp
import urllib.parse
from quart import Quart, redirect, url_for, session, request, jsonify, render_template
from functools import wraps

# ─────────────────────────────────────────────────────────────────
# DISCORD OAUTH2 CONFIG
# ─────────────────────────────────────────────────────────────────

DISCORD_API = "https://discord.com/api/v10"
OAUTH2_CLIENT_ID = os.getenv("OAUTH2_CLIENT_ID", "1507685977936887848")
OAUTH2_CLIENT_SECRET = os.getenv("OAUTH2_CLIENT_SECRET", "lwMFy2-n91kymydIAK1Nf00w7wu5gyx1")
OAUTH2_SCOPES = "identify guilds"
BOT_INVITE_URL = f"https://discord.com/api/oauth2/authorize?client_id={OAUTH2_CLIENT_ID}&permissions=8&scope=bot%20applications.commands"

LOGO_URL = "https://cdn.discordapp.com/attachments/1501988744637579304/1508888560789622806/Blue_and_Purple_Modern_Technology_Logo.png?ex=6a172d7a&is=6a15dbfa&hm=0291764fe90911b583c7aab4d1847a70a35198add6f20147e31940060f1492ff"


def get_avatar_url(user_data):
    """Build Discord avatar URL from user data dict."""
    uid = user_data.get('id', '')
    avatar = user_data.get('avatar')
    if avatar:
        ext = 'gif' if avatar.startswith('a_') else 'png'
        return f"https://cdn.discordapp.com/avatars/{uid}/{avatar}.{ext}?size=128"
    disc = int(user_data.get('discriminator', '0'))
    index = (int(uid) >> 22) % 6 if disc == 0 else disc % 5
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


def get_guild_icon_url(guild_data):
    """Build Discord guild icon URL from guild data dict."""
    gid = guild_data.get('id', '')
    icon = guild_data.get('icon')
    if icon:
        ext = 'gif' if icon.startswith('a_') else 'png'
        return f"https://cdn.discordapp.com/icons/{gid}/{icon}.{ext}?size=128"
    return None


# ─────────────────────────────────────────────────────────────────
# APP FACTORY
# ─────────────────────────────────────────────────────────────────

def create_app(bot, db_manager):
    app = Quart(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'),
        static_url_path='/static'
    )
    app.secret_key = os.getenv("SECRET_KEY", "fenrix-super-secret-key-2026")

    # ─── HELPERS ───

    def login_required(f):
        @wraps(f)
        async def decorated(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('login_page'))
            return await f(*args, **kwargs)
        return decorated

    def get_redirect_uri():
        base = os.getenv("BASE_URL", "http://localhost:5000")
        return f"{base}/callback"

    # ─── CONTEXT PROCESSOR ───

    @app.context_processor
    async def inject_globals():
        return {
            'logo_url': LOGO_URL,
            'bot_invite_url': BOT_INVITE_URL,
            'get_avatar_url': get_avatar_url,
            'get_guild_icon_url': get_guild_icon_url,
        }

    # ─── AUTH ROUTES ───

    @app.route('/')
    async def home():
        if 'user' in session:
            return redirect(url_for('dashboard_servers'))
        return redirect(url_for('login_page'))

    @app.route('/login')
    async def login_page():
        redirect_uri = urllib.parse.quote(get_redirect_uri())
        oauth_url = (
            f"{DISCORD_API}/oauth2/authorize"
            f"?client_id={OAUTH2_CLIENT_ID}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&scope={urllib.parse.quote(OAUTH2_SCOPES)}"
        )
        return await render_template('login.html', oauth_url=oauth_url)

    @app.route('/callback')
    async def callback():
        code = request.args.get('code')
        if not code:
            return redirect(url_for('login_page'))

        async with aiohttp.ClientSession() as http:
            # Exchange code for token
            token_payload = {
                'client_id': OAUTH2_CLIENT_ID,
                'client_secret': OAUTH2_CLIENT_SECRET,
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': get_redirect_uri(),
                'scope': OAUTH2_SCOPES,
            }
            async with http.post(f"{DISCORD_API}/oauth2/token", data=token_payload) as resp:
                token_json = await resp.json()

            if 'access_token' not in token_json:
                return redirect(url_for('login_page'))

            headers = {'Authorization': f"Bearer {token_json['access_token']}"}

            # Fetch user info
            async with http.get(f"{DISCORD_API}/users/@me", headers=headers) as resp:
                user_data = await resp.json()

            # Fetch guilds
            async with http.get(f"{DISCORD_API}/users/@me/guilds", headers=headers) as resp:
                guilds_data = await resp.json()

        # Filter: guilds where user has MANAGE_GUILD (0x20) or ADMINISTRATOR (0x8)
        managed = []
        for g in guilds_data:
            perms = int(g.get('permissions', 0))
            if perms & 0x20 or perms & 0x8:
                bot_guild = bot.get_guild(int(g['id']))
                g['bot_in_guild'] = bot_guild is not None
                g['member_count'] = bot_guild.member_count if bot_guild else 0
                managed.append(g)

        session['user'] = {
            'id': user_data['id'],
            'username': user_data.get('global_name') or user_data['username'],
            'avatar': user_data.get('avatar'),
            'discriminator': user_data.get('discriminator', '0'),
        }
        session['guilds'] = managed
        session.permanent = True

        return redirect(url_for('dashboard_servers'))

    @app.route('/logout')
    async def logout():
        session.clear()
        return redirect(url_for('login_page'))

    # ─── DASHBOARD PAGES ───

    @app.route('/dashboard')
    @login_required
    async def dashboard_servers():
        # Refresh bot_in_guild status
        for g in session.get('guilds', []):
            bg = bot.get_guild(int(g['id']))
            g['bot_in_guild'] = bg is not None
            g['member_count'] = bg.member_count if bg else 0
        return await render_template('index.html', user=session['user'],
                                     guilds=session.get('guilds', []))

    @app.route('/dashboard/<int:guild_id>')
    @login_required
    async def guild_overview(guild_id):
        guild = bot.get_guild(guild_id)
        if not guild:
            return redirect(url_for('dashboard_servers'))
        config = db_manager.get_guild_config(guild_id)
        return await render_template('overview.html', user=session['user'],
                                     guild=guild, config=config, active_page='overview',
                                     guild_id=guild_id)

    @app.route('/dashboard/<int:guild_id>/welcome')
    @login_required
    async def guild_welcome(guild_id):
        guild = bot.get_guild(guild_id)
        if not guild:
            return redirect(url_for('dashboard_servers'))
        config = db_manager.get_guild_config(guild_id)
        return await render_template('welcome.html', user=session['user'],
                                     guild=guild, config=config, active_page='welcome',
                                     guild_id=guild_id)

    @app.route('/dashboard/<int:guild_id>/verify')
    @login_required
    async def guild_verify(guild_id):
        guild = bot.get_guild(guild_id)
        if not guild:
            return redirect(url_for('dashboard_servers'))
        config = db_manager.get_guild_config(guild_id)
        return await render_template('verify.html', user=session['user'],
                                     guild=guild, config=config, active_page='verify',
                                     guild_id=guild_id)

    @app.route('/dashboard/<int:guild_id>/tickets')
    @login_required
    async def guild_tickets(guild_id):
        guild = bot.get_guild(guild_id)
        if not guild:
            return redirect(url_for('dashboard_servers'))
        config = db_manager.get_guild_config(guild_id)
        return await render_template('tickets.html', user=session['user'],
                                     guild=guild, config=config, active_page='tickets',
                                     guild_id=guild_id)

    @app.route('/dashboard/<int:guild_id>/security')
    @login_required
    async def guild_security(guild_id):
        guild = bot.get_guild(guild_id)
        if not guild:
            return redirect(url_for('dashboard_servers'))
        config = db_manager.get_guild_config(guild_id)
        return await render_template('security.html', user=session['user'],
                                     guild=guild, config=config, active_page='security',
                                     guild_id=guild_id)

    @app.route('/dashboard/<int:guild_id>/logs')
    @login_required
    async def guild_logs(guild_id):
        guild = bot.get_guild(guild_id)
        if not guild:
            return redirect(url_for('dashboard_servers'))
        config = db_manager.get_guild_config(guild_id)
        return await render_template('logs.html', user=session['user'],
                                     guild=guild, config=config, active_page='logs',
                                     guild_id=guild_id)

    @app.route('/commands')
    async def commands_list():
        return await render_template('commands.html')

    # ─── API ROUTES ───

    @app.route('/api/guild/<int:guild_id>')
    @login_required
    async def api_guild_info(guild_id):
        guild = bot.get_guild(guild_id)
        if not guild:
            return jsonify({'error': 'Guild not found'}), 404

        channels = [
            {'id': str(c.id), 'name': c.name}
            for c in sorted(guild.text_channels, key=lambda c: c.position)
        ]
        categories = [
            {'id': str(c.id), 'name': c.name}
            for c in sorted(guild.categories, key=lambda c: c.position)
        ]
        roles = [
            {'id': str(r.id), 'name': r.name, 'color': str(r.color)}
            for r in sorted(guild.roles, key=lambda r: r.position, reverse=True)
            if r.name != '@everyone'
        ]

        return jsonify({
            'id': str(guild.id),
            'name': guild.name,
            'icon': str(guild.icon.url) if guild.icon else None,
            'member_count': guild.member_count,
            'channels': channels,
            'categories': categories,
            'roles': roles,
            'text_channel_count': len(guild.text_channels),
            'voice_channel_count': len(guild.voice_channels),
            'role_count': len(guild.roles),
            'premium_tier': guild.premium_tier,
            'premium_count': guild.premium_subscription_count,
            'owner_id': str(guild.owner_id),
        })

    @app.route('/api/guild/<int:guild_id>/config', methods=['GET'])
    @login_required
    async def api_get_config(guild_id):
        config = db_manager.get_guild_config(guild_id)
        return jsonify(config or {})

    @app.route('/api/guild/<int:guild_id>/config', methods=['POST'])
    @login_required
    async def api_save_config(guild_id):
        data = await request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        try:
            db_manager.update_guild_config(guild_id, data)
            return jsonify({'success': True, 'message': 'Configuration saved successfully.'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return app
