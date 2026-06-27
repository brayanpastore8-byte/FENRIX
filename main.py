import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
import asyncio
import logging
import json
import os
import re
import time
import threading
import random
import urllib.parse
import io
from PIL import Image, ImageDraw, ImageFont
import firebase_admin
from firebase_admin import credentials, firestore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Fenrix")

# Load environment variables from .env file if it exists
if os.path.exists(".env"):
    try:
        with open(".env", "r", encoding="utf-8") as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k:
                        os.environ[k] = v
        logger.info("[SYSTEM] Environment variables loaded from .env file.")
    except Exception as e:
        logger.error(f"[SYSTEM] Error loading .env file: {e}")


# ─────────────────────────────────────────────────────────────────
# CONSTANTS  (token is ONLY read from environment – never hardcoded)
# ─────────────────────────────────────────────────────────────────

CREATOR_ID        = 1084833898762084403          # hardcoded owner for diagnostic DMs
APP_ID            = 1507685977936887848
DASHBOARD_URL     = "https://fenrix.onrender.com"
SUPPORT_LINK      = "https://discord.gg/2DzQjdE2ve"
INVITE_LINK       = f"https://discord.com/api/oauth2/authorize?client_id={APP_ID}&permissions=8&scope=bot%20applications.commands"
TOPGG_LINK        = "https://top.gg/discord/servers/847550536220291072#reviews"

BASE_URL          = os.getenv("BASE_URL", "https://fenrix.onrender.com").rstrip('/')
LOGO_URL          = f"{BASE_URL}/static/images/logo.png"
BANNER_VERIFY_DEFAULT = None
BANNER_INFO_URL   = None


# ── Custom emoji IDs ─────────────────────────────────────────────
E_HOME    = "<:home:1510922902009155685>"
E_CLOCK   = "<:clock:1510923008082972742>"
E_PARTY   = "<:party:1510966190695252109>"
E_CHECK   = "<:spunta:1513860712336850944>"
E_CROWN   = "<:corona:1513860803781197834>"
E_BOT     = "<:bot:1513860863637852291>"
E_SHIELD  = "<:scudo:1513860909846757546>"
E_BAN     = "<:sanzione:1513861029065392238>"
E_USER    = "<:utente:1513861104038707342>"
E_WARN    = "<:sanzione:1513861029065392238>"
E_LOGS    = "<:rotella:1513861331512721458>"
E_CAL     = "<:calendario:1513862306495467590>"
E_LINK    = "<:link:1513862990137659585>"
E_ARROW   = "<:freccia:1513863026367795263>"

PROFANITY_KEYWORDS = [
    "dio porco","porco dio","dio cane","dio bastardo","bastardo dio",
    "dio stronzo","dio maiale","maiale dio","porca madonna","madonna puttana",
    "madonna maiala","madonna troia","cristo dio","dio infame","dioporco","porcodio",
    "diocane","porcamadonna","dio boia","dio ladro","dio impestato","dio lurido",
    "goddamn","god damn","jesus christ","motherfucker","mother fucker",
    "cazzo","puttana","troia","vaffanculo","bastardo","stronzo","coglion"
]

# ─────────────────────────────────────────────────────────────────
# DATABASE MANAGER
# ─────────────────────────────────────────────────────────────────

class DatabaseManager:
    def __init__(self):
        self.use_firebase = False
        self.local_file = "local_db.json"
        self.lock = threading.RLock()
        self.cache = {}

        firebase_config_env = os.getenv("FIREBASE_CONFIG_JSON")
        if firebase_config_env or os.path.exists("firebase-key.json"):
            try:
                if firebase_config_env:
                    config_dict = json.loads(firebase_config_env)
                    cred = credentials.Certificate(config_dict)
                else:
                    cred = credentials.Certificate("firebase-key.json")
                firebase_admin.initialize_app(cred)
                self.db = firestore.client()
                self.use_firebase = True
                logger.info("[DATABASE] Firebase Firestore initialized successfully.")
            except Exception as e:
                logger.error(f"[DATABASE] Error initializing Firebase: {e}. Falling back to local JSON.")

        if not self.use_firebase:
            logger.info("[DATABASE] Using local JSON storage.")
            with self.lock:
                if not os.path.exists(self.local_file):
                    with open(self.local_file, "w", encoding="utf-8") as f:
                        json.dump({}, f)
                self.cache = self._read_local()

    def _read_local(self):
        with self.lock:
            try:
                with open(self.local_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}

    def _write_local(self, data):
        with self.lock:
            try:
                with open(self.local_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
            except Exception as e:
                logger.error(f"[DATABASE] Error writing local DB: {e}")

    def get_guild_config(self, guild_id: int):
        gid_str = str(guild_id)
        with self.lock:
            if gid_str in self.cache:
                return self.cache[gid_str]

            if self.use_firebase:
                try:
                    doc = self.db.collection("guild_configs").document(gid_str).get()
                    config = doc.to_dict() if doc.exists else {}
                    self.cache[gid_str] = config
                    return config
                except Exception as e:
                    logger.error(f"[DATABASE] Firebase read error: {e}")
                    return {}
            else:
                config = self._read_local().get(gid_str, {})
                self.cache[gid_str] = config
                return config

    def update_guild_config(self, guild_id: int, updates: dict):
        gid_str = str(guild_id)
        with self.lock:
            guild_data = self.cache.get(gid_str, None)
            if guild_data is None:
                guild_data = self.get_guild_config(guild_id)
            
            guild_data.update(updates)
            self.cache[gid_str] = guild_data

            if self.use_firebase:
                try:
                    self.db.collection("guild_configs").document(gid_str).set(guild_data, merge=True)
                except Exception as e:
                    logger.error(f"[DATABASE] Firebase write error: {e}")
            else:
                data = self._read_local()
                data[gid_str] = guild_data
                self._write_local(data)

    def log_activity(self, guild_id: int):
        hour_str = datetime.datetime.utcnow().strftime("%Y-%m-%d-%H")
        if self.use_firebase:
            try:
                doc_ref = self.db.collection("guild_activity").document(str(guild_id))
                doc = doc_ref.get()
                activity_data = doc.to_dict() if doc.exists else {}
                activity_data[hour_str] = activity_data.get(hour_str, 0) + 1
                cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=48)
                purged = {k: v for k, v in activity_data.items()
                          if datetime.datetime.strptime(k, "%Y-%m-%d-%H") >= cutoff}
                doc_ref.set(purged)
            except Exception as e:
                logger.error(f"[DATABASE] Firebase activity log error: {e}")
        else:
            with self.lock:
                data = self._read_local()
                activity_data = data.get(f"{guild_id}_activity", {})
                activity_data[hour_str] = activity_data.get(hour_str, 0) + 1
                cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=48)
                purged = {}
                for k, v in activity_data.items():
                    try:
                        if datetime.datetime.strptime(k, "%Y-%m-%d-%H") >= cutoff:
                            purged[k] = v
                    except Exception:
                        pass
                data[f"{guild_id}_activity"] = purged
                self._write_local(data)

    def get_activity_data(self, guild_id: int):
        if self.use_firebase:
            try:
                doc = self.db.collection("guild_activity").document(str(guild_id)).get()
                return doc.to_dict() if doc.exists else {}
            except Exception as e:
                logger.error(f"[DATABASE] Firebase activity read error: {e}")
                return {}
        else:
            with self.lock:
                return self._read_local().get(f"{guild_id}_activity", {})

    def save_giveaway(self, message_id: str, data_dict: dict):
        if self.use_firebase:
            try:
                self.db.collection("giveaways").document(message_id).set(data_dict)
            except Exception as e:
                logger.error(f"[DATABASE] Firebase save_giveaway error: {e}")
        else:
            with self.lock:
                data = self._read_local()
                giveaways = data.get("giveaways", {})
                giveaways[message_id] = data_dict
                data["giveaways"] = giveaways
                self._write_local(data)

    def get_active_giveaways(self):
        if self.use_firebase:
            try:
                docs = self.db.collection("giveaways").where("ended", "==", False).stream()
                return {doc.id: doc.to_dict() for doc in docs}
            except Exception as e:
                logger.error(f"[DATABASE] Firebase get_active_giveaways error: {e}")
                return {}
        else:
            with self.lock:
                data = self._read_local()
                giveaways = data.get("giveaways", {})
                return {k: v for k, v in giveaways.items() if not v.get("ended", False)}

    def get_ledger(self, guild_id: int):
        if self.use_firebase:
            try:
                doc = self.db.collection("guild_ledger").document(str(guild_id)).get()
                data = doc.to_dict() if doc.exists else {}
                return data.get("entries", [])
            except Exception as e:
                logger.error(f"[DATABASE] Firebase ledger read error: {e}")
                return []
        else:
            with self.lock:
                data = self._read_local()
                return data.get(f"{guild_id}_ledger", [])

    def log_ledger_entry(self, guild_id: int, entry_type: str, target_name: str, target_id: str, enforcer_name: str, enforcer_id: str, reason: str):
        entry = {
            "id": f"INC-{random.randint(100000, 999999)}",
            "type": entry_type,
            "target_name": target_name,
            "target_id": str(target_id),
            "enforced_by_name": enforcer_name,
            "enforced_by_id": str(enforcer_id),
            "reason": reason,
            "timestamp": time.time()
        }
        if self.use_firebase:
            try:
                doc_ref = self.db.collection("guild_ledger").document(str(guild_id))
                doc = doc_ref.get()
                data = doc.to_dict() if doc.exists else {}
                entries = data.get("entries", [])
                entries.insert(0, entry)
                entries = entries[:100]
                doc_ref.set({"entries": entries})
            except Exception as e:
                logger.error(f"[DATABASE] Firebase ledger write error: {e}")
        else:
            with self.lock:
                data = self._read_local()
                entries = data.get(f"{guild_id}_ledger", [])
                entries.insert(0, entry)
                entries = entries[:100]
                data[f"{guild_id}_ledger"] = entries
                self._write_local(data)

    def add_warning(self, guild_id: int, user_id: int, reason: str, mod_name: str, mod_id: int):
        warn_id = f"W-{random.randint(1000, 9999)}"
        entry = {
            "id": warn_id,
            "reason": reason,
            "moderator_name": mod_name,
            "moderator_id": str(mod_id),
            "timestamp": time.time()
        }
        if self.use_firebase:
            try:
                doc_ref = self.db.collection("guild_warnings").document(f"{guild_id}_{user_id}")
                doc = doc_ref.get()
                data = doc.to_dict() if doc.exists else {"warnings": []}
                warnings = data.get("warnings", [])
                warnings.append(entry)
                doc_ref.set({"warnings": warnings})
            except Exception as e:
                logger.error(f"[DATABASE] Firebase warning add error: {e}")
        else:
            with self.lock:
                data = self._read_local()
                key = f"{guild_id}_{user_id}_warnings"
                warnings = data.get(key, [])
                warnings.append(entry)
                data[key] = warnings
                self._write_local(data)
        return warn_id

    def get_warnings(self, guild_id: int, user_id: int):
        if self.use_firebase:
            try:
                doc = self.db.collection("guild_warnings").document(f"{guild_id}_{user_id}").get()
                return doc.to_dict().get("warnings", []) if doc.exists else []
            except Exception as e:
                logger.error(f"[DATABASE] Firebase warnings read error: {e}")
                return []
        else:
            with self.lock:
                data = self._read_local()
                return data.get(f"{guild_id}_{user_id}_warnings", [])

    def remove_warning(self, guild_id: int, user_id: int, warn_id: str):
        if self.use_firebase:
            try:
                doc_ref = self.db.collection("guild_warnings").document(f"{guild_id}_{user_id}")
                doc = doc_ref.get()
                if doc.exists:
                    warnings = doc.to_dict().get("warnings", [])
                    if warn_id.lower() == "all":
                        warnings = []
                    else:
                        warnings = [w for w in warnings if w["id"] != warn_id]
                    doc_ref.set({"warnings": warnings})
                    return True
                return False
            except Exception as e:
                logger.error(f"[DATABASE] Firebase warning remove error: {e}")
                return False
        else:
            with self.lock:
                data = self._read_local()
                key = f"{guild_id}_{user_id}_warnings"
                if key in data:
                    if warn_id.lower() == "all":
                        data[key] = []
                    else:
                        data[key] = [w for w in data[key] if w["id"] != warn_id]
                    self._write_local(data)
                    return True
                return False

# ─────────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────

def parse_roles(guild, input_str):
    role_ids = []
    for part in input_str.split(","):
        part = part.strip()
        if not part:
            continue
        match = re.match(r"<@&(\d+)>", part)
        if match:
            role_ids.append(int(match.group(1)))
            continue
        if part.isdigit():
            role_ids.append(int(part))
            continue
        role = discord.utils.get(guild.roles, name=part)
        if role:
            role_ids.append(role.id)
    return role_ids

def make_embeds(banner_url: str, title: str, description: str,
                color: int = 0x2f3136, fields: list = None, thumbnail: str = None):
    embeds = []
    c_emb = discord.Embed(title=title, description=description, color=color)
    if thumbnail:
        c_emb.set_thumbnail(url=thumbnail)
    if fields:
        for name, val, inline in fields:
            c_emb.add_field(name=name, value=val, inline=inline)
    embeds.append(c_emb)

    if banner_url:
        b_emb = discord.Embed(color=color)
        b_emb.set_image(url=banner_url)
        embeds.append(b_emb)

    return embeds

def check_blasphemy(content: str) -> bool:
    cleaned = re.sub(r'[^\w\s]', '', content.lower())
    for word in PROFANITY_KEYWORDS:
        if word in cleaned or word in content.lower():
            return True
    return False

def parse_duration(raw: str) -> int | None:
    """
    Smart time-string parser.
    Accepted: 10s / 10m / 1h / 24h / 1day / 2days / 00:10 / 1:30:00
    Returns seconds or None if invalid.
    Range: 5s – 7 days.
    """
    raw = raw.strip().lower()
    total = 0

    # Try HH:MM or HH:MM:SS
    colon_match = re.fullmatch(r"(\d+):(\d{2})(?::(\d{2}))?", raw)
    if colon_match:
        h = int(colon_match.group(1))
        m = int(colon_match.group(2))
        s = int(colon_match.group(3) or 0)
        total = h * 3600 + m * 60 + s
        if 5 <= total <= 604800:
            return total
        return None

    # Try compound like "1d2h30m10s" or individual units
    pattern = re.compile(r"(\d+)\s*(d(?:ay(?:s)?)?|h(?:r(?:s)?|ours?)?|m(?:in(?:utes?)?)?|s(?:ec(?:onds?)?)?)")
    matches = pattern.findall(raw)
    if matches:
        for value, unit in matches:
            v = int(value)
            u = unit[0]
            if u == 'd':
                total += v * 86400
            elif u == 'h':
                total += v * 3600
            elif u == 'm':
                total += v * 60
            elif u == 's':
                total += v
        if 5 <= total <= 604800:
            return total
        return None

    # Pure number → treat as seconds
    if raw.isdigit():
        total = int(raw)
        if 5 <= total <= 604800:
            return total

    return None

# ─────────────────────────────────────────────────────────────────
# CAPTCHA GENERATOR & VIEWS
# ─────────────────────────────────────────────────────────────────

def generate_captcha_image(text: str) -> io.BytesIO:
    """
    Generates a dynamic captcha image using distorted multi-colored lines
    and background noise to prevent OCR/AI bot scraping.
    """
    img = Image.new("RGB", (250, 80), color=(18, 18, 35))
    draw = ImageDraw.Draw(img)
    
    # Draw background noise (random multi-colored dots)
    for _ in range(300):
        xy = (random.randint(0, 250), random.randint(0, 80))
        draw.point(xy, fill=(random.randint(50, 200), random.randint(50, 200), random.randint(50, 200)))
        
    # Draw distorted multi-colored lines
    for _ in range(8):
        start = (random.randint(0, 100), random.randint(0, 80))
        end = (random.randint(150, 250), random.randint(0, 80))
        draw.line([start, end], fill=(random.randint(100, 255), random.randint(100, 255), random.randint(100, 255)), width=random.randint(1, 3))
        
    try:
        font = ImageFont.truetype("arial.ttf", 40)
    except Exception:
        font = ImageFont.load_default()
        
    for i, char in enumerate(text):
        x_pos = 20 + i * 35 + random.randint(-5, 5)
        y_pos = 15 + random.randint(-10, 10)
        char_color = (random.randint(150, 255), random.randint(150, 255), random.randint(150, 255))
        draw.text((x_pos, y_pos), char, fill=char_color, font=font)
        
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

class CaptchaDMView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.button(label="Submit Captcha Code", style=discord.ButtonStyle.green, emoji="🧩", custom_id="submit_captcha_btn")
    async def submit_captcha(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CaptchaModal(self.bot, self.guild_id))

class CaptchaModal(discord.ui.Modal, title="Verify Captcha"):
    def __init__(self, bot, guild_id):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id
        
        self.code_input = discord.ui.TextInput(
            label="Enter the 6-character captcha code:",
            placeholder="Type code here...",
            min_length=6,
            max_length=6,
            required=True
        )
        self.add_item(self.code_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        
        if user_id not in self.bot.active_captchas:
            return await interaction.followup.send("❌ Captcha session has expired. Please verify again in the server.", ephemeral=True)
            
        answer, gid, roles_to_add, roles_to_remove, start_time = self.bot.active_captchas[user_id]
        
        if time.time() - start_time > 600:
            if user_id in self.bot.active_captchas:
                del self.bot.active_captchas[user_id]
            return await interaction.followup.send("❌ Captcha session expired (10 minutes elapsed). Please request a new one.", ephemeral=True)
            
        user_code = self.code_input.value.strip().upper()
        if user_code == answer.upper():
            guild = self.bot.get_guild(gid)
            member = guild.get_member(user_id) if guild else None
            
            if not member:
                return await interaction.followup.send("❌ Failed to verify: you are no longer in the server.", ephemeral=True)
                
            added, removed = [], []
            try:
                for r_id in roles_to_add:
                    role = guild.get_role(int(r_id))
                    if role and role not in member.roles:
                        await member.add_roles(role, reason="Fenrix Captcha Verification")
                        added.append(role.mention)
                for r_id in roles_to_remove:
                    role = guild.get_role(int(r_id))
                    if role and role in member.roles:
                        await member.remove_roles(role, reason="Fenrix Captcha Verification")
                        removed.append(role.mention)

                # Mark as verified in database
                config = self.bot.db_manager.get_guild_config(gid)
                verified_list = config.get("verified_users", [])
                if str(member.id) not in verified_list:
                    verified_list.append(str(member.id))
                    self.bot.db_manager.update_guild_config(gid, {"verified_users": verified_list})
            except Exception as e:
                logger.error(f"[CAPTCHA] Error applying roles: {e}")
                return await interaction.followup.send("❌ Verification succeeded but role assignment failed. Check bot role hierarchy.", ephemeral=True)
                
            config = self.bot.db_manager.get_guild_config(gid)
            log_channel_id = config.get("verify_log_channel")
            if log_channel_id:
                log_channel = guild.get_channel(int(log_channel_id))
                if log_channel:
                    fields = [
                        ("User",          f"{member.mention} ({member.name})", True),
                        ("User ID",       f"`{member.id}`",                    True),
                        ("Roles Added",   "\n".join(added)   if added   else "None", False),
                        ("Roles Removed", "\n".join(removed) if removed else "None", False),
                        ("Duration",      f"{int(time.time() - start_time)}s", True),
                        ("Captcha Type",  "Advanced Captcha (distorted image)", True),
                        ("Timestamp",     f"<t:{int(time.time())}:F>",          False),
                    ]
                    embeds = make_embeds(
                        banner_url=None,
                        title=f"{E_SHIELD} User Verified via Captcha",
                        description="Member passed the advanced captcha challenge.",
                        color=0x00ff00, fields=fields, thumbnail=LOGO_URL)
                    await log_channel.send(embeds=embeds)
                    
            if user_id in self.bot.active_captchas:
                del self.bot.active_captchas[user_id]
            
            server_link = f"https://discord.com/channels/{gid}"
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Go back to the Server", url=server_link, style=discord.ButtonStyle.link))
            
            await interaction.followup.send(
                f"🎉 **Verification Successful!**\n\nYou have solved the captcha and have been verified in **{guild.name}**.",
                view=view, ephemeral=True
            )
        else:
            await interaction.followup.send("❌ Incorrect Captcha code. Click the button to try again.", ephemeral=True)

class VerificationButtonView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Verify Account", style=discord.ButtonStyle.green,
                       emoji="🛡️", custom_id="fenrix_verify_btn")
    async def verify_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as de:
            logger.error(f"[VERIFY CALLBACK] Defer failed: {de}")
            return

        try:
            config = self.bot.db_manager.get_guild_config(interaction.guild_id)
            if not config:
                return await interaction.followup.send(
                    "❌ Verification system is not configured on this server.", ephemeral=True)

            roles_to_add    = config.get("verify_roles_to_add", [])
            roles_to_remove = config.get("verify_roles_to_remove", [])
            log_channel_id  = config.get("verify_log_channel")

            guild  = interaction.guild
            member = interaction.user

            # CHECK ALREADY VERIFIED
            is_already_verified = False
            verified_list = config.get("verified_users", [])
            if str(member.id) in verified_list or member.id in verified_list:
                is_already_verified = True
            elif roles_to_add:
                member_role_ids = [str(r.id) for r in member.roles]
                if any(str(r_id) in member_role_ids for r_id in roles_to_add):
                    is_already_verified = True

            if is_already_verified:
                return await interaction.followup.send(
                    "❌ You are already verified in this server. If you encounter any issues, please open a ticket.", ephemeral=True)

            # Method check
            method = config.get("verify_method", "standard")
            if method == "captcha":
                captcha_ans = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=6))
                try:
                    buffer = generate_captcha_image(captcha_ans)
                    file = discord.File(buffer, filename="captcha.png")
                except Exception as ce:
                    logger.error(f"[CAPTCHA GENERATION] Error: {ce}")
                    return await interaction.followup.send("❌ Captcha generation failed. Contact server admins.", ephemeral=True)

                self.bot.active_captchas[member.id] = (captcha_ans, guild.id, roles_to_add, roles_to_remove, time.time())

                try:
                    embed = discord.Embed(
                        title=f"🧩 Captcha Verification — {guild.name}",
                        description=(
                            "To prevent bot raids, this server requires you to solve a captcha image.\n"
                            "Please review the image below and click the button to enter the code.\n\n"
                            "⏳ **Expiration:** This captcha is valid for **10 minutes**."
                        ),
                        color=0x6366f1,
                        timestamp=datetime.datetime.utcnow()
                    )
                    embed.set_image(url="attachment://captcha.png")
                    embed.set_footer(text="Fenrix Advanced Security System")
                    
                    dm_view = CaptchaDMView(self.bot, guild.id)
                    await member.send(embed=embed, file=file, view=dm_view)
                    await interaction.followup.send("📩 A verification captcha has been sent to your DMs. Please check your messages!", ephemeral=True)
                except discord.Forbidden:
                    return await interaction.followup.send("❌ DMs are closed. Please open your Direct Messages for this server and click Verify again.", ephemeral=True)
                return

            # Standard Method
            added, removed = [], []
            try:
                for r_id in roles_to_add:
                    role = guild.get_role(int(r_id))
                    if role and role not in member.roles:
                        await member.add_roles(role, reason="Fenrix Verification")
                        added.append(role.mention)
                for r_id in roles_to_remove:
                    role = guild.get_role(int(r_id))
                    if role and role in member.roles:
                        await member.remove_roles(role, reason="Fenrix Verification")
                        removed.append(role.mention)
                
                # Mark as verified in database
                verified_list = config.get("verified_users", [])
                if str(member.id) not in verified_list:
                    verified_list.append(str(member.id))
                    self.bot.db_manager.update_guild_config(guild.id, {"verified_users": verified_list})
            except Exception as e:
                logger.error(f"Error applying verification roles: {e}")
                return await interaction.followup.send(
                    "❌ Verification failed. Check bot hierarchy and permissions.", ephemeral=True)

            await interaction.followup.send(
                f"{E_CHECK} **Verification Successful**\n\nYou have been verified and granted access!", ephemeral=True)

            if log_channel_id:
                log_channel = guild.get_channel(int(log_channel_id))
                if log_channel:
                    fields = [
                        ("User",          f"{member.mention} ({member.name})", True),
                        ("User ID",       f"`{member.id}`",                    True),
                        ("Roles Added",   "\n".join(added)   if added   else "None", False),
                        ("Roles Removed", "\n".join(removed) if removed else "None", False),
                        ("Captcha Type",  "Standard (Trust-Network Auto-Check)", True),
                        ("Timestamp",     f"<t:{int(time.time())}:F>",          False),
                    ]
                    embeds = make_embeds(
                        banner_url=None,
                        title=f"{E_SHIELD} User Verified",
                        description="Member verified successfully.",
                        color=0x00ff00, fields=fields, thumbnail=LOGO_URL)
                    await log_channel.send(embeds=embeds)
        except Exception as e:
            logger.error(f"[VERIFY CALLBACK] Critical error: {e}")
            try:
                await interaction.followup.send("❌ An unexpected error occurred. Please try again or open a ticket.", ephemeral=True)
            except Exception:
                pass


class LinkButtonView(discord.ui.View):
    def __init__(self, label: str, url: str, emoji: str = None):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label=label, style=discord.ButtonStyle.link, url=url, emoji=emoji))


class UnlockChannelView(discord.ui.View):
    def __init__(self, bot, guild_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.channel_id = channel_id

    @discord.ui.button(label="🔓 Unlock Channel", style=discord.ButtonStyle.danger,
                       custom_id="fenrix_unlock_channel")
    async def unlock_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            return await interaction.followup.send("❌ Server not found.", ephemeral=True)
        channel = guild.get_channel(self.channel_id)
        if channel:
            try:
                overwrite = channel.overwrites_for(guild.default_role)
                overwrite.send_messages = None
                await channel.set_permissions(guild.default_role, overwrite=overwrite,
                                              reason="Anti-Raid: Manual owner unlock")
                self.bot.raid_locked_channels.discard(channel.id)
                await channel.send("🔓 Channel has been manually unlocked by the server owner.")
            except Exception as e:
                return await interaction.followup.send(f"❌ Could not unlock: {e}", ephemeral=True)
        await interaction.followup.send("✅ Channel unlocked.", ephemeral=True)
        self.stop()


class PersistentGiveawayView(discord.ui.View):
    def __init__(self, bot, message_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.message_id = message_id

    @discord.ui.button(label="Join Giveaway", style=discord.ButtonStyle.blurple,
                       emoji="🎉", custom_id="fenrix_giveaway_btn")
    async def join_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        giveaways = self.bot.db_manager.get_active_giveaways()
        gw = giveaways.get(self.message_id)
        if not gw:
            return await interaction.followup.send("❌ This giveaway is no longer active.", ephemeral=True)

        participants = gw.get("participants", [])
        user_id = str(interaction.user.id)

        # Check required role
        required_role_id = gw.get("required_role")
        if required_role_id:
            member = interaction.guild.get_member(interaction.user.id)
            if not member or not any(str(r.id) == str(required_role_id) for r in member.roles):
                return await interaction.followup.send(
                    "❌ You do not have the required role to enter this giveaway.", ephemeral=True)

        if user_id in participants:
            return await interaction.followup.send("❌ You have already joined!", ephemeral=True)

        participants.append(user_id)
        gw["participants"] = participants
        self.bot.db_manager.save_giveaway(self.message_id, gw)

        embeds = interaction.message.embeds
        if embeds:
            c_emb = embeds[0]
            for i, field in enumerate(c_emb.fields):
                if field.name == "Participants":
                    c_emb.set_field_at(i, name="Participants",
                                       value=f"**{len(participants)}**", inline=True)
                    break
            await interaction.message.edit(embeds=embeds)

        await interaction.followup.send(
            f"{E_PARTY} You have successfully entered the giveaway!", ephemeral=True)


# ─────────────────────────────────────────────────────────────────
# MODALS
# ─────────────────────────────────────────────────────────────────

class PartnershipModal(discord.ui.Modal, title="Announce Partnership"):
    text = discord.ui.TextInput(
        label="Partnership Details",
        style=discord.TextStyle.paragraph,
        placeholder="Enter partnership details… (supports paragraphs & newlines)",
        required=True,
        max_length=4000
    )

    def __init__(self, management_member, manager_name: str, ping_content: str = ""):
        super().__init__()
        self.management_member = management_member
        self.manager_name      = manager_name
        self.ping_content      = ping_content

    async def on_submit(self, interaction: discord.Interaction):
        # Core text is a plain message – no embed per spec
        content_lines = self.text.value.replace("\\n", "\n")

        # Small sub-embed for the manager field
        manager_embed = discord.Embed(
            description=f"**External Representative:** {self.manager_name}",
            color=0x6366f1)
        manager_embed.set_footer(text="Fenrix Partnership System")

        ping = self.ping_content or ""
        msg = f"{ping}\n\n{content_lines}\n\n**Processed by:** {self.management_member.mention}".strip()
        await interaction.response.send_message(content=msg, embed=manager_embed)


# ─────────────────────────────────────────────────────────────────
# BOT CLASS
# ─────────────────────────────────────────────────────────────────

class FenrixBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members        = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.db_manager           = DatabaseManager()
        self.anti_nuke_tracker    = {}   # executor_id → [timestamps]
        self.lockdown_active      = {}   # guild_id → bool
        self.spam_warn_tracker    = {}   # user_id → count
        self.spam_reset_tasks     = {}
        self.raid_locked_channels = set()  # channel IDs currently raid-locked
        self.message_raid_tracker = {}     # Anti-raid message tracking
        self.active_captchas      = {}     # user_id → (captcha_ans, guild_id, roles_add, roles_rem, time)
        self.join_tracker         = {}     # guild_id → [timestamps]
        self.influx_gate_active   = {}     # guild_id → expiry_timestamp
        self._diagnostic_sent     = False

    async def setup_hook(self):
        self.add_view(VerificationButtonView(self))
        self.add_view(CaptchaDMView(self, 0))

        # Register existing giveaways
        active_gws = self.db_manager.get_active_giveaways()
        for msg_id in active_gws.keys():
            self.add_view(PersistentGiveawayView(self, msg_id))

        self.giveaway_loop.start()
        self.graph_loop.start()
        self.honeypot_expiry_loop.start()

        await self.tree.sync()
        logger.info("[SYSTEM] Bot online and synchronized.")

    async def on_ready(self):
        self.start_time = datetime.datetime.utcnow()
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching,
                                      name="Protecting Servers | /help"))
        logger.info(f"[SYSTEM] Logged in as {self.user.name}")
        
        # Load and verify panel embeds on ready for active servers
        for guild in self.guilds:
            try:
                await self.update_panels(guild.id)
            except Exception as e:
                logger.error(f"[STARTUP] Error updating panels for {guild.name}: {e}")

        # Schedule owner diagnostic loop (20 min delay)
        if not self._diagnostic_sent:
            self.loop.create_task(self._owner_diagnostic_loop())

    # ── Spam reset helper ──────────────────────────────────────────
    async def reset_spam_warn(self, user_id):
        await asyncio.sleep(60)
        self.spam_warn_tracker[user_id] = 0

    # ── Owner Diagnostic Loop ─────────────────────────────────────
    async def _owner_diagnostic_loop(self):
        await asyncio.sleep(1200)  # 20 minutes
        self._diagnostic_sent = True
        try:
            creator = await self.fetch_user(CREATOR_ID)
            if not creator:
                return
            uptime_duration = datetime.datetime.utcnow() - getattr(self, "start_time", datetime.datetime.utcnow())
            hours, rem = divmod(int(uptime_duration.total_seconds()), 3600)
            mins, secs = divmod(rem, 60)
            uptime_str = f"{uptime_duration.days}d {hours}h {mins}m {secs}s"

            guilds_info = "\n".join(
                f"• **{g.name}** (`{g.id}`) — {g.member_count} members"
                for g in self.guilds
            )

            embed = discord.Embed(
                title=f"{E_BOT} Fenrix — Live Diagnostic Report",
                description=(
                    f"**Uptime:** {uptime_str}\n"
                    f"**Latency:** {round(self.latency * 1000)}ms\n"
                    f"**Servers Active:** {len(self.guilds)}\n\n"
                    f"**Guild Directory:**\n{guilds_info or 'No guilds.'}"
                ),
                color=0x6366f1,
                timestamp=datetime.datetime.utcnow()
            )
            embed.set_thumbnail(url=LOGO_URL)
            embed.set_footer(text="Fenrix Diagnostic System — Auto-Report")
            await creator.send(embed=embed)
        except Exception as e:
            logger.error(f"[DIAGNOSTIC] Failed to DM creator: {e}")

    # ── Anti-Nuke: 2-3 events in 3-5s window ─────────────────────
    async def process_anti_nuke_event(self, guild, event_name, target=None):
        config = self.db_manager.get_guild_config(guild.id)
        if not config.get("antinuke_enabled", True):
            return
        if self.lockdown_active.get(guild.id, False):
            return

        action_map = {
            "channel_create": discord.AuditLogAction.channel_create,
            "channel_delete": discord.AuditLogAction.channel_delete,
            "channel_update": discord.AuditLogAction.channel_update,
            "role_create": discord.AuditLogAction.role_create,
            "role_delete": discord.AuditLogAction.role_delete,
            "role_update": discord.AuditLogAction.role_update,
        }

        executor = None
        try:
            action_type = action_map.get(event_name)
            if action_type and target:
                async for entry in guild.audit_logs(action=action_type, limit=5):
                    if entry.target and entry.target.id == target.id:
                        executor = entry.user
                        break
            if not executor:
                async for entry in guild.audit_logs(limit=1):
                    executor = entry.user
                    break
        except Exception as e:
            logger.error(f"[ANTI-NUKE] Audit log retrieval error: {e}")
            return

        if not executor or executor.id == self.user.id or executor.id == guild.owner_id:
            return

        now = time.time()
        if executor.id not in self.anti_nuke_tracker:
            self.anti_nuke_tracker[executor.id] = []

        self.anti_nuke_tracker[executor.id].append(now)
        # Strict 5-second window
        self.anti_nuke_tracker[executor.id] = [
            t for t in self.anti_nuke_tracker[executor.id] if now - t <= 5]

        events = self.anti_nuke_tracker[executor.id]
        threshold = int(config.get("antinuke_threshold", 3))

        if len(events) >= threshold:
            whitelisted = False
            whitelist_ids = config.get("antinuke_whitelist", [])
            role_ids = [str(r.id) for r in executor.roles]
            if str(executor.id) in whitelist_ids or any(rid in whitelist_ids for rid in role_ids):
                whitelisted = True

            if whitelisted:
                # If whitelisted, only trigger if superhuman speed is detected (automated script / token hack)
                # Superhuman speed: 3 events in less than 2.5 seconds
                time_span = events[-1] - events[0]
                if len(events) >= 3 and time_span <= 2.5:
                    logger.warning(f"[ANTI-HACK] Superhuman speed detected from whitelisted admin {executor.name} ({executor.id}). Time span: {time_span:.2f}s. Triggering lockdown.")
                    await self.trigger_nuke_lockdown(guild, executor, config, is_hack=True)
                else:
                    logger.info(f"[ANTI-NUKE] Whitelisted admin {executor.name} bypassed (manual speed: {time_span:.2f}s for {len(events)} events).")
            else:
                await self.trigger_nuke_lockdown(guild, executor, config, is_hack=False)

    async def trigger_nuke_lockdown(self, guild, attacker, config, is_hack=False):
        self.lockdown_active[guild.id] = True
        action = config.get("antinuke_action", "ban")

        try:
            if action == "ban":
                await guild.ban(attacker, reason="Anti-Nuke: Threshold Exceeded (Hacker/Bot script detected)" if is_hack else "Anti-Nuke: Threshold Exceeded")
            elif action == "kick":
                await attacker.kick(reason="Anti-Nuke: Threshold Exceeded")
            elif action == "timeout":
                await attacker.timeout(datetime.timedelta(days=7),
                                       reason="Anti-Nuke: Threshold Exceeded")
            elif action == "strip_roles":
                for role in list(attacker.roles):
                    if role.name != "@everyone" and role < guild.me.top_role:
                        await attacker.remove_roles(role, reason="Anti-Nuke Lockdown")
        except Exception as e:
            logger.error(f"[ANTI-NUKE] Error punishing attacker: {e}")

        # Lock server
        try:
            perms = guild.default_role.permissions
            perms.update(send_messages=False, send_messages_in_threads=False,
                         create_public_threads=False, create_private_threads=False)
            await guild.default_role.edit(permissions=perms, reason="Anti-Nuke Lockdown")
        except Exception as e:
            logger.error(f"[ANTI-NUKE] Lockdown error: {e}")

        log_ch_id  = config.get("security_log_channel") or config.get("verify_log_channel")
        log_channel = guild.get_channel(int(log_ch_id)) if log_ch_id else None

        incident_type = "🚨 ACCOUNT COMPROMISE / HACK DETECTED" if is_hack else "⚠️ NUKE ATTACK DETECTED"
        fields = [
            ("Attacker",    f"{attacker.mention} (`{attacker.name}`)", True),
            ("Attacker ID", f"`{attacker.id}`",                        True),
            ("Action Taken",f"`{action}` applied",                     True),
            ("Reason",      "Superhuman execution speed (Automated script)" if is_hack else "Mass channel/role modifications", False),
            ("Timestamp",   f"<t:{int(time.time())}:F>",               False),
        ]
        embeds = make_embeds(
            banner_url=None,
            title=f"{E_SHIELD} EMERGENCY LOCKDOWN — {incident_type}",
            description="Destructive activity detected. Server locked. Attacker actioned.",
            color=0xff0000, fields=fields, thumbnail=LOGO_URL)

        target = log_channel or guild.system_channel or next(
            (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
        if target:
            await target.send(content="@here ⚠️ **SECURITY ALERT**", embeds=embeds)

        # DM owner
        try:
            owner = await guild.fetch_member(guild.owner_id)
            owner_embed = discord.Embed(
                title=f"{E_BAN} Security Alert — {guild.name}",
                description=(
                    f"Anti-Nuke triggered on **{guild.name}**.\n"
                    f"Type: **{incident_type}**\n"
                    f"Attacker: {attacker.mention} (`{attacker.id}`)\n"
                    f"Action taken: **{action}**"
                ),
                color=0xff0000,
                timestamp=datetime.datetime.utcnow()
            )
            await owner.send(embed=owner_embed)
        except Exception:
            pass

    # ── Anti-Raid (message-based): 3 msgs in <3s → channel lockdown ──
    async def process_message_raid(self, message: discord.Message):
        config = self.db_manager.get_guild_config(message.guild.id)
        if not config.get("antiraid_enabled", False):
            return False

        ch_id = message.channel.id
        u_id  = str(message.author.id)
        now   = time.time()

        if ch_id not in self.message_raid_tracker:
            self.message_raid_tracker[ch_id] = {}
        if u_id not in self.message_raid_tracker[ch_id]:
            self.message_raid_tracker[ch_id][u_id] = []

        self.message_raid_tracker[ch_id][u_id].append(now)
        # 3-second window
        self.message_raid_tracker[ch_id][u_id] = [
            t for t in self.message_raid_tracker[ch_id][u_id] if now - t <= 3]

        if len(self.message_raid_tracker[ch_id][u_id]) >= 3:
            await self.trigger_channel_lockdown(message.channel, message.guild)
            return True
        return False

    async def trigger_channel_lockdown(self, channel, guild):
        if channel.id in self.raid_locked_channels:
            return
        self.raid_locked_channels.add(channel.id)

        try:
            overwrite = channel.overwrites_for(guild.default_role)
            overwrite.send_messages = False
            await channel.set_permissions(guild.default_role, overwrite=overwrite,
                                          reason="Anti-Raid: Message Spam Detected")
            await channel.send(
                "🔒 Channel locked down. A server raid has been detected.")
        except Exception as e:
            logger.error(f"[ANTI-RAID] Lockdown error: {e}")

        # DM owner with unlock button
        try:
            owner = await guild.fetch_member(guild.owner_id)
            embed = discord.Embed(
                title=f"{E_SHIELD} Raid Alert — {guild.name}",
                description=(
                    f"Raid detected in <#{channel.id}>.\n"
                    f"Channel has been locked. Use the button below to unlock manually, "
                    f"or it will auto-unlock in **10 minutes**."
                ),
                color=0xff5500,
                timestamp=datetime.datetime.utcnow()
            )
            view = UnlockChannelView(self, guild.id, channel.id)
            await owner.send(embed=embed, view=view)
        except Exception as e:
            logger.error(f"[ANTI-RAID] Could not DM owner: {e}")

        # Auto unlock after 10 minutes
        self.loop.create_task(self._auto_unlock_channel(channel, guild))

    async def _auto_unlock_channel(self, channel, guild):
        await asyncio.sleep(600)  # 10 minutes
        if channel.id not in self.raid_locked_channels:
            return
        try:
            overwrite = channel.overwrites_for(guild.default_role)
            overwrite.send_messages = None
            await channel.set_permissions(guild.default_role, overwrite=overwrite,
                                          reason="Anti-Raid: Auto-unlock after 10 minutes")
            self.raid_locked_channels.discard(channel.id)
            await channel.send("🔓 Channel automatically unlocked after 10-minute cooldown.")
        except Exception as e:
            logger.error(f"[ANTI-RAID] Auto-unlock error: {e}")

    # ── Giveaway loop ─────────────────────────────────────────────
    @tasks.loop(seconds=10)
    async def giveaway_loop(self):
        active_gws = self.db_manager.get_active_giveaways()
        now_ts = time.time()
        for msg_id, gw in list(active_gws.items()):
            if gw.get("end_time", 0) <= now_ts:
                gw["ended"] = True
                self.db_manager.save_giveaway(msg_id, gw)

                guild   = self.get_guild(gw.get("guild_id"))
                if not guild: continue
                channel = guild.get_channel(gw.get("channel_id"))
                if not channel: continue

                try:
                    message = await channel.fetch_message(int(msg_id))
                except Exception:
                    continue

                participants   = gw.get("participants", [])
                winners_count  = gw.get("winners_count", 1)
                prize          = gw.get("prize", "Unknown Prize")

                if not participants:
                    embed = discord.Embed(
                        title=f"{E_PARTY} Giveaway Ended: {prize}",
                        description="No one entered the giveaway.", color=0xff0000)
                    embed.set_thumbnail(url=LOGO_URL)
                    await message.edit(embeds=[embed], view=None)
                    await channel.send(f"⚠️ Giveaway for **{prize}** ended with no entries.")
                    continue

                pool = list(participants)
                winners_ids = []
                for _ in range(min(winners_count, len(pool))):
                    chosen = random.choice(pool)
                    pool.remove(chosen)
                    winners_ids.append(int(chosen))

                mentions = [f"<@{uid}>" for uid in winners_ids]
                embed = discord.Embed(
                    title=f"{E_PARTY} Giveaway Ended: {prize}",
                    description=f"**Winners:** {', '.join(mentions)}",
                    color=0x00ff00)
                embed.set_thumbnail(url=LOGO_URL)
                embed.set_footer(text="Fenrix Giveaway System")
                await message.edit(embeds=[embed], view=None)
                await channel.send(f"{E_PARTY} Congratulations {', '.join(mentions)} — you won **{prize}**!")

                for uid in winners_ids:
                    member = guild.get_member(uid)
                    if member:
                        try:
                            await member.send(
                                f"{E_PARTY} **Giveaway Winner!**\n\n"
                                f"You won **{prize}** in **{guild.name}**!\n"
                                f"Please open a ticket within 48 hours to claim your prize.")
                        except Exception:
                            pass

    # ── Graph loop ────────────────────────────────────────────────
    @tasks.loop(seconds=30)
    async def graph_loop(self):
        now = datetime.datetime.now()
        if not hasattr(self, "last_graph_post_hour"):
            self.last_graph_post_hour = ""

        current_hour_key = now.strftime("%Y-%m-%d-%H")
        if now.hour in [1, 8] and now.minute == 0 and self.last_graph_post_hour != current_hour_key:
            self.last_graph_post_hour = current_hour_key
            for guild in self.guilds:
                config     = self.db_manager.get_guild_config(guild.id)
                log_ch_id  = config.get("security_log_channel") or config.get("verify_log_channel")
                if log_ch_id:
                    channel = guild.get_channel(int(log_ch_id))
                    if channel:
                        try:
                            embeds = await generate_status_embeds(self, guild)
                            await channel.send(embeds=embeds)
                        except Exception as e:
                            logger.error(f"Error posting scheduled graph: {e}")


    # ── Honeypot expiry check loop ───────────────────────────────
    @tasks.loop(minutes=10)
    async def honeypot_expiry_loop(self):
        now = time.time()
        for guild in self.guilds:
            config = self.db_manager.get_guild_config(guild.id)
            if config.get("honeypot_active") and config.get("honeypot_expiry", 0) <= now:
                ch_id = config.get("honeypot_channel_id")
                if ch_id:
                    ch = guild.get_channel(int(ch_id))
                    if ch:
                        try:
                            await ch.delete(reason="Fenrix Honeypot: Session Expired")
                        except Exception as e:
                            logger.error(f"[HONEYPOT EXPIRE] Error deleting channel: {e}")
                
                self.db_manager.update_guild_config(guild.id, {
                    "honeypot_active": False,
                    "honeypot_channel_id": None,
                    "honeypot_expiry": 0
                })
                
                try:
                    owner = await guild.fetch_member(guild.owner_id)
                    if owner:
                        embed = discord.Embed(
                            title="🍯 Honeypot Session Expired",
                            description=(
                                f"The honeypot trap session in **{guild.name}** has expired.\n"
                                "The decoy channel has been successfully removed.\n\n"
                                "You can reactivate it from the Web Dashboard at any time."
                            ),
                            color=0x6366f1
                        )
                        await owner.send(embed=embed)
                except Exception as de:
                    logger.error(f"[HONEYPOT EXPIRE] DM error: {de}")

    # ── Deploy Honeypot Method ───────────────────────────────────
    async def deploy_honeypot(self, guild_id: int):
        guild = self.get_guild(guild_id)
        if not guild:
            return False, "Guild not found"
        config = self.db_manager.get_guild_config(guild_id)
        if not config.get("honeypot_enabled", False):
            return False, "Honeypot is disabled in dashboard settings. Enable it first."

        name = config.get("honeypot_channel_name", "non-scrivere!").strip()
        duration_choice = config.get("honeypot_duration", "1_week")
        
        duration_map = {
            "3_days": 3 * 86400,
            "1_week": 7 * 86400,
            "2_weeks": 14 * 86400,
            "3_weeks": 21 * 86400,
            "4_weeks": 28 * 86400
        }
        duration_secs = duration_map.get(duration_choice, 7 * 86400)
        expiry_time = time.time() + duration_secs

        old_ch_id = config.get("honeypot_channel_id")
        if old_ch_id:
            old_ch = guild.get_channel(int(old_ch_id))
            if old_ch:
                try:
                    await old_ch.delete(reason="Re-deploying Honeypot channel")
                except Exception:
                    pass

        whitelist_roles = [int(rid) for rid in config.get("honeypot_whitelist", [])]
        verify_roles = [int(rid) for rid in config.get("verify_roles_to_add", [])]
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True, manage_channels=True, manage_messages=True)
        }
        
        for r_id in verify_roles:
            r = guild.get_role(r_id)
            if r:
                overwrites[r] = discord.PermissionOverwrite(read_messages=False)
                
        for r_id in whitelist_roles:
            r = guild.get_role(r_id)
            if r:
                overwrites[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            new_ch = await guild.create_text_channel(
                name=name,
                overwrites=overwrites,
                reason="Fenrix Honeypot Trap deployment"
            )
            
            expiry_str = datetime.datetime.fromtimestamp(expiry_time).strftime("%Y-%m-%d %H:%M:%S")
            embed = discord.Embed(
                title="🍯 Honeypot System Active",
                description=(
                    "**DO NOT TYPE WITHIN THIS CHANNEL.**\n\n"
                    "This is a decoy channel for raid bots and malicious scripts.\n"
                    "Any unwhitelisted message sent here results in an **instant server ban**.\n\n"
                    f"⏰ **Active Until:** `{expiry_str} UTC`"
                ),
                color=0xffaa00
            )
            embed.set_footer(text="Fenrix Advanced Security System")
            await new_ch.send(embed=embed)
            
            self.db_manager.update_guild_config(guild_id, {
                "honeypot_active": True,
                "honeypot_channel_id": str(new_ch.id),
                "honeypot_expiry": expiry_time
            })
            
            return True, str(new_ch.id)
        except Exception as e:
            logger.error(f"[HONEYPOT DEPLOY] Error: {e}")
            return False, f"Permissions failure: {e}"

    # ── Update Panels ────────────────────────────────────────────
    async def update_panels(self, guild_id: int):
        config = self.db_manager.get_guild_config(guild_id)
        guild  = self.get_guild(guild_id)
        if not guild:
            return

        # ── 1. Verification Panel ──────────────────────────────────
        if config.get("verify_enabled", False) and config.get("verify_channel"):
            v_channel = guild.get_channel(int(config["verify_channel"]))
            if v_channel:
                found = False
                try:
                    async for msg in v_channel.history(limit=50):
                        if msg.author.id == self.user.id and msg.views:
                            if any(item.custom_id == "fenrix_verify_btn" for view in msg.views for item in view.children):
                                found = True
                                break
                except Exception as e:
                    logger.error(f"[PANELS] Error reading verify history: {e}")

                if not found:
                    try:
                        async for msg in v_channel.history(limit=50):
                            if msg.author.id == self.user.id:
                                await msg.delete()
                    except Exception:
                        pass
                    
                    banner_url = config.get("verify_banner_url") or BANNER_VERIFY_DEFAULT
                    embeds = make_embeds(
                        banner_url=banner_url,
                        title="🛡️ Verification Required",
                        description="Click the button below to verify your account and gain access to the server.\n\n",
                        color=0x00ffcc,
                        thumbnail=LOGO_URL
                    )
                    view = VerificationButtonView(self)
                    await v_channel.send(embeds=embeds, view=view)




bot = FenrixBot()

# ── Global error handler ──────────────────────────────────────────
@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandInvokeError):
        error = error.original
    logger.error(f"[COMMAND ERROR] {error}")
    send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    err_msg = str(error).lower()
    if "missing permissions" in err_msg:
        msg = "❌ The bot is missing required permissions (check role hierarchy)."
    elif "not found" in err_msg:
        msg = "❌ User or member not found. Verify the ID or mention."
    else:
        msg = f"❌ **Error:** {error}"
    try:
        await send(msg, ephemeral=True)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────
# STATUS GENERATOR
# ─────────────────────────────────────────────────────────────────

async def generate_status_embeds(bot_inst, guild, weekly=False):
    activity  = bot_inst.db_manager.get_activity_data(guild.id) or {}
    now_utc   = datetime.datetime.utcnow()
    labels, values = [], []
    span = 168 if weekly else 24   # hours

    for i in range(span - 1, -1, -1):
        dt  = now_utc - datetime.timedelta(hours=i)
        key = dt.strftime("%Y-%m-%d-%H")
        labels.append(dt.strftime("%d/%m %H:00") if weekly else dt.strftime("%H:00"))
        values.append(activity.get(key, 0))

    chart_config = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [{
                "label": "Fenrix Events",
                "data": values,
                "fill": True,
                "backgroundColor": "rgba(99,102,241,0.2)",
                "borderColor": "rgba(99,102,241,1)",
                "borderWidth": 3,
                "pointBackgroundColor": "rgba(236,72,153,1)",
                "tension": 0.4
            }]
        },
        "options": {
            "legend": {"labels": {"fontColor": "white", "fontSize": 12}},
            "scales": {
                "yAxes": [{"gridLines": {"color": "rgba(255,255,255,0.1)"},
                           "ticks": {"fontColor": "white", "beginAtZero": True}}],
                "xAxes": [{"gridLines": {"color": "rgba(255,255,255,0.1)"},
                           "ticks": {"fontColor": "white"}}]
            }
        }
    }
    graph_url = (f"https://quickchart.io/chart?c="
                 f"{urllib.parse.quote(json.dumps(chart_config))}&w=600&h=300&bkg=rgb(15,15,25)")

    if not hasattr(bot_inst, "start_time"):
        bot_inst.start_time = now_utc
    uptime_d  = now_utc - bot_inst.start_time
    h, r      = divmod(int(uptime_d.total_seconds()), 3600)
    m, s      = divmod(r, 60)
    uptime_str = f"{uptime_d.days}d {h}h {m}m {s}s"

    fields = [
        ("Uptime",       f"**{uptime_str}**", True),
        ("Latency",      f"**{round(bot_inst.latency * 1000)}ms**", True),
        ("Members",      f"**{guild.member_count}**", True),
        ("Logged At",    f"<t:{int(now_utc.timestamp())}:F>", False),
    ]
    title = (f"{E_CLOCK} Fenrix — Weekly Server Telemetry" if weekly
             else f"{E_CLOCK} Fenrix — Daily Activity & Status")
    return make_embeds(
        banner_url=graph_url, title=title,
        description="Security events and activity chart.\n\n",
        color=0x6366f1, fields=fields, thumbnail=LOGO_URL)

# ─────────────────────────────────────────────────────────────────
# DISCORD EVENTS
# ─────────────────────────────────────────────────────────────────

# ── Welcome DM: Send invite DM to owner on guild join ──────────────

@bot.event
async def on_guild_join(guild):
    logger.info(f"[SYSTEM] Joined a new server: {guild.name} ({guild.id})")
    
    # Send welcome DM to the owner
    owner = guild.owner
    if not owner and guild.owner_id:
        try:
            owner = await bot.fetch_user(guild.owner_id)
        except Exception as e:
            logger.error(f"[SYSTEM] Failed to fetch owner {guild.owner_id} for guild {guild.name}: {e}")
            
    if owner:
        try:
            embed = discord.Embed(
                title="🤖 Grazie per aver invitato Fenrix! 🤖",
                description=(
                    f"Ciao **{owner.name}**,\n\n"
                    f"Grazie per aver invitato **Fenrix** nel tuo server **{guild.name}**! "
                    "Siamo qui per garantire la massima sicurezza e protezione alla tua community.\n\n"
                    "### 🛡️ Cosa puoi fare ora:\n"
                    "• **Accedi alla Dashboard** per configurare in tempo reale tutti i sistemi.\n"
                    "• **Attiva l'Anti-Nuke & Anti-Raid** per proteggere il server da raid e attacchi.\n"
                    "• **Configura la Verifica Captcha** per bloccare i bot all'ingresso.\n\n"
                    "Usa i pulsanti qui sotto per accedere alla configurazione o per chiedere aiuto!"
                ),
                color=0x7c3aed
            )
            embed.set_thumbnail(url=LOGO_URL)
            embed.set_footer(text="Fenrix Security Systems • Protezione Completa")
            
            # Add interactive buttons
            view = discord.ui.View()
            base_url = os.getenv("BASE_URL", "https://fenrix.onrender.com").rstrip('/')
            
            view.add_item(discord.ui.Button(label="Dashboard", url=f"{base_url}/dashboard", emoji="⚙️"))
            view.add_item(discord.ui.Button(label="Vota Bot", url=TOPGG_LINK, emoji="⭐"))
            view.add_item(discord.ui.Button(label="Supporto Discord", url=SUPPORT_LINK, emoji="💬"))
            
            await owner.send(embed=embed, view=view)
            logger.info(f"[SYSTEM] Successfully sent welcome DM to owner {owner.name} ({owner.id}) for guild {guild.name}")
        except Exception as e:
            logger.error(f"[SYSTEM] Failed to send DM to owner of {guild.name}: {e}")

# ── Anti-Hack: Unauthorized Bot detection is inside on_member_join ─

@bot.event
async def on_member_join(member):
    bot.db_manager.log_activity(member.guild.id)
    config   = bot.db_manager.get_guild_config(member.guild.id)
    guild_id = member.guild.id
    now      = time.time()

    # ── Anti-Hack: Block Unauthorized Bot Additions ─────────────────
    # discord.py fires on_member_join for bots too
    if member.bot and member.id != bot.user.id:
        wl_bots = [int(x) for x in config.get("whitelisted_bots", [])]
        if member.id not in wl_bots:
            adder_name, adder_id = "Unknown", "0"
            try:
                async for entry in member.guild.audit_logs(
                    action=discord.AuditLogAction.bot_add, limit=5
                ):
                    if entry.target and entry.target.id == member.id:
                        adder_name = entry.user.name
                        adder_id   = str(entry.user.id)
                        break
            except Exception:
                pass

            adder_member   = member.guild.get_member(int(adder_id)) if adder_id != "0" else None
            adder_is_owner = (int(adder_id) == member.guild.owner_id) if adder_id != "0" else False
            adder_is_admin = (adder_member and adder_member.guild_permissions.administrator)

            if not adder_is_owner and not adder_is_admin:
                try:
                    await member.kick(reason=f"Anti-Hack: Unauthorized bot — added by {adder_name}")
                    bot.db_manager.log_ledger_entry(
                        guild_id=guild_id,
                        entry_type="kick",
                        target_name=f"BOT:{member.name}",
                        target_id=member.id,
                        enforcer_name=bot.user.name,
                        enforcer_id=bot.user.id,
                        reason=f"Anti-Hack: Unauthorized bot by {adder_name} ({adder_id})"
                    )
                    log_ch_id = config.get("security_log_channel") or config.get("verify_log_channel")
                    log_ch = member.guild.get_channel(int(log_ch_id)) if log_ch_id else None
                    if log_ch:
                        embed = discord.Embed(
                            title="🔐 ANTI-HACK — Unauthorized Bot Kicked",
                            description="An unauthorized bot was added to the server and has been auto-removed.",
                            color=0xef4444
                        )
                        embed.add_field(name="Bot", value=f"{member.mention} `{member.name}` (`{member.id}`)", inline=False)
                        embed.add_field(name="Added by", value=f"`{adder_name}` (`{adder_id}`)", inline=True)
                        embed.add_field(name="Action", value="Bot **kicked** automatically.", inline=True)
                        embed.timestamp = discord.utils.utcnow()
                        await log_ch.send(embed=embed)
                except Exception as e:
                    logger.error(f"[ANTI-HACK BOT-ADD] {e}")
        return  # bots skip the rest of member-join logic

    # ── Anti-Bot Influx (Join Gate) ──────────────────────────────

    
    gate_expiry = bot.influx_gate_active.get(guild_id, 0)
    if gate_expiry > now:
        try:
            try:
                await member.send(
                    f"⚠️ **Security Gate Active**: The server **{member.guild.name}** is currently under lockdown due to a high volume of joining bot accounts.\n"
                    "Please try joining again in 15 minutes."
                )
            except Exception:
                pass
            await member.kick(reason="Anti-Bot Influx: Join Gate Active")
            bot.db_manager.log_ledger_entry(
                guild_id=guild_id,
                entry_type="kick",
                target_name=member.name,
                target_id=member.id,
                enforcer_name=bot.user.name,
                enforcer_id=bot.user.id,
                reason="Join Gate Active: Mass Bot Influx Raid prevention."
            )
        except Exception as ke:
            logger.error(f"[BOT INFLUX KICK] {ke}")
        return

    # ── Anti-Bot Influx — reads threshold/window from dashboard config ──
    influx_enabled   = config.get("antibotinflux_enabled", True)
    influx_threshold = int(config.get("antibotinflux_threshold", 10))
    influx_window    = int(config.get("antibotinflux_window", 10))

    if influx_enabled:
        if guild_id not in bot.join_tracker:
            bot.join_tracker[guild_id] = []
        bot.join_tracker[guild_id].append(now)
        bot.join_tracker[guild_id] = [t for t in bot.join_tracker[guild_id] if now - t <= influx_window]

        if len(bot.join_tracker[guild_id]) >= influx_threshold:
            bot.influx_gate_active[guild_id] = now + 900
            logger.warning(f"[BOT INFLUX] Influx in {member.guild.name} ({guild_id}). Join gate activated.")

            bot.db_manager.log_ledger_entry(
                guild_id=guild_id,
                entry_type="nuke_alert",
                target_name="Join Gate Activated",
                target_id=guild_id,
                enforcer_name=bot.user.name,
                enforcer_id=bot.user.id,
                reason=f"Mass join bot influx ({influx_threshold}+ joins/{influx_window}s). Gate locked 15 min."
            )

            log_ch_id = (config.get("antibotinflux_alert_channel")
                         or config.get("security_log_channel")
                         or config.get("verify_log_channel"))
            log_channel = member.guild.get_channel(int(log_ch_id)) if log_ch_id else None
            if log_channel:
                fields = [
                    ("Raid Threshold", f"{influx_threshold}+ accounts in {influx_window}s", True),
                    ("Gate Duration", "15 minutes (auto-lifting)", True),
                    ("Timestamp", f"<t:{int(now)}:F>", False)
                ]
                embeds = make_embeds(
                    banner_url=None,
                    title="🚨 JOIN GATE LOCKED — BOT INFLUX DETECTED",
                    description="Mass join surge detected. Gate locked. New accounts will be auto-kicked until the gate lifts.",
                    color=0xff0000,
                    fields=fields,
                    thumbnail=LOGO_URL
                )
                await log_channel.send(content="@here 🚨 **BOT RAID IN PROGRESS**", embeds=embeds)

            try:
                await member.kick(reason="Anti-Bot Influx: Gate triggered")
            except Exception:
                pass
            return

    # ── Auto-Role ─────────────────────────────────────────────────────
    if config.get("autorole_enabled", False):
        for r_id in config.get("autorole_ids", []):
            role = member.guild.get_role(int(r_id))
            if role:
                try:
                    await member.add_roles(role, reason="Fenrix Auto-Role")
                except Exception as e:
                    logger.error(f"[AUTOROLE] {e}")

    # Welcome/Leave messages REMOVED — Fenrix is a security-only bot.


@bot.event
async def on_member_remove(member):
    bot.db_manager.log_activity(member.guild.id)
    try:
        async for entry in member.guild.audit_logs(action=discord.AuditLogAction.kick, limit=1):
            if entry.target and entry.target.id == member.id:
                if time.time() - entry.created_at.timestamp() < 5:
                    ledger = bot.db_manager.get_ledger(member.guild.id)
                    exists = False
                    for item in ledger[:5]:
                        if item.get("type") == "kick" and str(item.get("target_id")) == str(member.id):
                            exists = True
                            break
                    if not exists:
                        bot.db_manager.log_ledger_entry(
                            guild_id=member.guild.id,
                            entry_type="kick",
                            target_name=member.name,
                            target_id=member.id,
                            enforcer_name=entry.user.name,
                            enforcer_id=entry.user.id,
                            reason=entry.reason or "Manual kick via Discord client."
                        )
                    break
    except Exception:
        pass

    config = bot.db_manager.get_guild_config(member.guild.id)
    # Join/Leave log for audit ledger
    log_ch_id = config.get("joinleave_log_channel")
    if log_ch_id and config.get("joinleave_log_enabled", False):
        log_ch = member.guild.get_channel(int(log_ch_id))
        if log_ch:
            try:
                embed = discord.Embed(
                    title="🚪 Member Left",
                    description=f"{member.mention} **{member.name}** left the server.",
                    color=0xff4444
                )
                embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
                embed.add_field(name="Account Created", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.timestamp = discord.utils.utcnow()
                await log_ch.send(embed=embed)
            except Exception as e:
                logger.error(f"[LEAVE LOG] {e}")

@bot.event
async def on_member_ban(guild, user):
    bot.db_manager.log_activity(guild.id)
    enforcer_name, enforcer_id = "System", "0"
    reason = "Manual ban via Discord interface"
    try:
        async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
            if entry.target and entry.target.id == user.id:
                enforcer_name = entry.user.name
                enforcer_id = entry.user.id
                reason = entry.reason or "No reason specified"
                break
    except Exception:
        pass

    ledger = bot.db_manager.get_ledger(guild.id)
    exists = any(
        e.get("type") == "ban" and str(e.get("target_id")) == str(user.id)
        for e in ledger[:5]
    )
    if not exists:
        bot.db_manager.log_ledger_entry(
            guild_id=guild.id,
            entry_type="ban",
            target_name=user.name,
            target_id=user.id,
            enforcer_name=enforcer_name,
            enforcer_id=enforcer_id,
            reason=reason
        )
    # Leave message REMOVED — Fenrix is a security-only bot.



@bot.event
async def on_member_update(before, after):
    # Boost detection
    if before.premium_since is None and after.premium_since is not None:
        config = bot.db_manager.get_guild_config(after.guild.id)
        boost_channel_id = config.get("boost_channel")
        if boost_channel_id:
            ch = after.guild.get_channel(int(boost_channel_id))
            if ch:
                embed = discord.Embed(
                    title="💜 Server Boosted!",
                    description=f"**{after.display_name}** has boosted the server!",
                    color=0xff73fa,
                    timestamp=datetime.datetime.utcnow()
                )
                embed.set_thumbnail(url=after.display_avatar.url)
                embed.set_footer(text="Fenrix Boost Tracker")
                await ch.send(content=after.mention, embed=embed)

@bot.event
async def on_guild_channel_create(channel):
    bot.db_manager.log_activity(channel.guild.id)
    config = bot.db_manager.get_guild_config(channel.guild.id)
    log_ch_id = config.get("server_log_channel")
    if log_ch_id:
        log_ch = channel.guild.get_channel(int(log_ch_id))
        if log_ch:
            try:
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                dt = datetime.datetime.now().strftime("%Y-%m-%d")
                await log_ch.send(f"📢 **{channel.guild.me.display_name}** has created channel **{channel.name}** at {ts} {dt}")
            except Exception:
                pass
    await bot.process_anti_nuke_event(channel.guild, "channel_create", target=channel)

@bot.event
async def on_guild_channel_delete(channel):
    bot.db_manager.log_activity(channel.guild.id)
    config = bot.db_manager.get_guild_config(channel.guild.id)
    log_ch_id = config.get("server_log_channel")
    if log_ch_id:
        log_ch = channel.guild.get_channel(int(log_ch_id))
        if log_ch:
            try:
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                dt = datetime.datetime.now().strftime("%Y-%m-%d")
                await log_ch.send(f"🗑️ A channel **{channel.name}** was deleted at {ts} {dt}")
            except Exception:
                pass
    await bot.process_anti_nuke_event(channel.guild, "channel_delete", target=channel)

@bot.event
async def on_guild_role_create(role):
    bot.db_manager.log_activity(role.guild.id)
    await bot.process_anti_nuke_event(role.guild, "role_create", target=role)

@bot.event
async def on_guild_role_delete(role):
    bot.db_manager.log_activity(role.guild.id)
    enforcer_name, enforcer_id = "System", "0"
    try:
        async for entry in role.guild.audit_logs(action=discord.AuditLogAction.role_delete, limit=1):
            if entry.target and entry.target.id == role.id:
                enforcer_name = entry.user.name
                enforcer_id = entry.user.id
                break
    except Exception:
        pass
    bot.db_manager.log_ledger_entry(
        guild_id=role.guild.id,
        entry_type="role_delete",
        target_name=role.name,
        target_id=role.id,
        enforcer_name=enforcer_name,
        enforcer_id=enforcer_id,
        reason=f"Role @{role.name} was deleted."
    )
    await bot.process_anti_nuke_event(role.guild, "role_delete", target=role)

@bot.event
async def on_guild_role_update(before, after):
    config = bot.db_manager.get_guild_config(after.guild.id)
    if config.get("antirole_enabled", False):
        bot.db_manager.log_activity(after.guild.id)
        await bot.process_anti_nuke_event(after.guild, "role_update", target=after)

@bot.event
async def on_guild_channel_update(before, after):
    config = bot.db_manager.get_guild_config(after.guild.id)
    if config.get("antichannel_enabled", False):
        bot.db_manager.log_activity(after.guild.id)
        await bot.process_anti_nuke_event(after.guild, "channel_update", target=after)

@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    config = bot.db_manager.get_guild_config(message.guild.id)
    log_ch_id = config.get("server_log_channel")
    if log_ch_id:
        log_ch = message.guild.get_channel(int(log_ch_id))
        if log_ch:
            try:
                await log_ch.send(
                    f"🗑️ **{message.author.display_name}** deleted a message in "
                    f"<#{message.channel.id}> at <t:{int(time.time())}:T>")
            except Exception:
                pass

@bot.event
async def on_message(message):
    if message.guild:
        config = bot.db_manager.get_guild_config(message.guild.id)
        
        # ── Honeypot Trap Check ──────────────────────────────────────
        hp_channel_id = config.get("honeypot_channel_id")
        if hp_channel_id and str(message.channel.id) == str(hp_channel_id):
            if message.author.id == bot.user.id:
                return
            is_staff_user = (message.author.guild_permissions.administrator
                             or message.author.id == message.guild.owner_id)
            whitelist_roles = [str(rid) for rid in config.get("honeypot_whitelist", [])]
            user_roles = [str(r.id) for r in message.author.roles]
            is_whitelisted = is_staff_user or any(rid in whitelist_roles for rid in user_roles)
            if not is_whitelisted:
                try:
                    await message.delete()
                except Exception:
                    pass
                try:
                    reason = "Honeypot Trap triggered: typed inside restricted decoy channel."
                    await message.guild.ban(message.author, reason=reason)
                    bot.db_manager.log_ledger_entry(
                        guild_id=message.guild.id,
                        entry_type="ban",
                        target_name=message.author.name,
                        target_id=message.author.id,
                        enforcer_name=bot.user.name,
                        enforcer_id=bot.user.id,
                        reason=reason
                    )
                    log_ch_id = config.get("security_log_channel") or config.get("verify_log_channel")
                    log_channel = message.guild.get_channel(int(log_ch_id)) if log_ch_id else None
                    if log_channel:
                        fields = [
                            ("Banned User", f"{message.author.mention} ({message.author.name})", True),
                            ("User ID", f"`{message.author.id}`", True),
                            ("Reason", "Honeypot Trap Triggered", True),
                            ("Timestamp", f"<t:{int(time.time())}:F>", False)
                        ]
                        embeds = make_embeds(
                            banner_url=None,
                            title="🍯 HONEYPOT BAN ENFORCED",
                            description="Decoy honeypot channel interaction detected. Malicious bot/user account has been banned.",
                            color=0xff0000,
                            fields=fields,
                            thumbnail=LOGO_URL
                        )
                        await log_channel.send(content="⚠️ **SECURITY HONEYPOT TRIGGERED**", embeds=embeds)
                except Exception as be:
                    logger.error(f"[HONEYPOT TRIGGER] Error: {be}")
                return

        # ── Bot Mention Trigger ──────────────────────────────────────
        if bot.user.mentioned_in(message) and not message.mention_everyone:
            if f"<@{bot.user.id}>" in message.content or f"<@!{bot.user.id}>" in message.content:
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="Dashboard", url=DASHBOARD_URL, style=discord.ButtonStyle.link, emoji="🏠"))
                view.add_item(discord.ui.Button(label="Support Server", url=SUPPORT_LINK, style=discord.ButtonStyle.link, emoji="💬"))
                view.add_item(discord.ui.Button(label="Vote on Top.gg", url=TOPGG_LINK, style=discord.ButtonStyle.link, emoji="🗳️"))
                await message.reply(
                    "Hello! I am Fenrix, an advanced security bot. For more information, please visit our Discord Support Server and Official Website.",
                    view=view
                )
                return

        # ── Legacy Prefix Catch (!help) ─────────────────────────────
        if message.content.strip().lower() == "!help":
            embed = discord.Embed(
                title="📖 Fenrix Commands Help",
                description=(
                    "Fenrix uses Discord Slash Commands now!\n\n"
                    "• Type `/help` to see all available commands.\n"
                    f"• Or visit our [Web Dashboard]({DASHBOARD_URL}) to configure modules."
                ),
                color=0x6366f1
            )
            embed.set_footer(text="Fenrix Advanced Security")
            try:
                msg = await message.reply(embed=embed)
                await asyncio.sleep(15)
                await msg.delete()
                try:
                    await message.delete()
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"[LEGACY HELP] {e}")
            return

    if message.author.bot:
        return

    if message.guild:
        bot.db_manager.log_activity(message.guild.id)
        config = bot.db_manager.get_guild_config(message.guild.id)
        is_staff_user = (message.author.guild_permissions.administrator
                         or message.author.id == message.guild.owner_id)

        # ── Anti-File-Hack ────────────────────────────────────────────
        # Blocks dangerous executable/script file uploads that can
        # be used to hack servers via CMD, PowerShell, or RCE exploits.
        DANGEROUS_EXTENSIONS = {
            ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".wsf",
            ".scr", ".pif", ".com", ".msi", ".msp", ".mst",
            ".dll", ".sys", ".cpl", ".hta", ".inf", ".reg",
            ".jar", ".jnlp", ".lnk", ".application",
            ".gadget", ".shb", ".shs",
            ".py", ".pyw", ".rb", ".sh", ".bash", ".zsh",
        }
        if config.get("antifile_enabled", True) and not is_staff_user and message.attachments:
            allowed_roles = [int(rid) for rid in config.get("mod_allowed_roles", [])]
            has_mod_role  = any(role.id in allowed_roles for role in message.author.roles)
            if not has_mod_role:
                for attachment in message.attachments:
                    fname = attachment.filename.lower()
                    ext = "." + fname.rsplit(".", 1)[-1] if "." in fname else ""
                    if ext in DANGEROUS_EXTENSIONS:
                        try:
                            await message.delete()
                            action = config.get("antifile_action", "timeout")
                            if action == "timeout":
                                await message.author.timeout(
                                    datetime.timedelta(hours=24),
                                    reason=f"Fenrix Anti-File-Hack: uploaded {ext} file"
                                )
                                msg = await message.channel.send(
                                    f"🔐 {message.author.mention} timed out 24h — **dangerous file upload blocked** (`{ext}`). "
                                    f"Executable/script files are not allowed."
                                )
                            elif action == "ban":
                                await message.guild.ban(
                                    message.author,
                                    reason=f"Fenrix Anti-File-Hack: uploaded {ext} file"
                                )
                                msg = await message.channel.send(
                                    f"🔐 {message.author.mention} **banned** — uploaded a dangerous file (`{ext}`)."
                                )
                            elif action == "kick":
                                await message.author.kick(
                                    reason=f"Fenrix Anti-File-Hack: uploaded {ext} file"
                                )
                                msg = await message.channel.send(
                                    f"🔐 {message.author.mention} **kicked** — uploaded a dangerous file (`{ext}`)."
                                )
                            else:
                                msg = await message.channel.send(
                                    f"🔐 {message.author.mention} — **dangerous file blocked** (`{ext}`). "
                                    f"Executable/script uploads are not allowed."
                                )
                            bot.db_manager.log_ledger_entry(
                                guild_id=message.guild.id,
                                entry_type="warn",
                                target_name=message.author.name,
                                target_id=message.author.id,
                                enforcer_name=bot.user.name,
                                enforcer_id=bot.user.id,
                                reason=f"Anti-File-Hack: blocked {attachment.filename} ({ext})"
                            )
                            log_ch_id = config.get("security_log_channel") or config.get("verify_log_channel")
                            if log_ch_id:
                                log_ch = message.guild.get_channel(int(log_ch_id))
                                if log_ch:
                                    embed = discord.Embed(
                                        title="🔐 ANTI-FILE-HACK — Dangerous Upload Blocked",
                                        description=f"A user tried to upload a potentially malicious file.",
                                        color=0xef4444
                                    )
                                    embed.add_field(name="User", value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
                                    embed.add_field(name="File", value=f"`{attachment.filename}`", inline=True)
                                    embed.add_field(name="Extension", value=f"`{ext}`", inline=True)
                                    embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                                    embed.add_field(name="Action", value=action.title(), inline=True)
                                    embed.timestamp = discord.utils.utcnow()
                                    await log_ch.send(embed=embed)
                            await asyncio.sleep(8)
                            await msg.delete()
                        except Exception as fhe:
                            logger.error(f"[ANTI-FILE-HACK] {fhe}")
                        return

        # ── Word Filter ──────────────────────────────────────────────
        if config.get("wordfilter_enabled", False) and not is_staff_user:
            forbidden_words = config.get("wordfilter_words", [])
            content_lower = message.content.lower()
            if any(word.lower() in content_lower for word in forbidden_words):
                try:
                    await message.delete()
                    action = config.get("wordfilter_action", "none")
                    duration = int(config.get("wordfilter_duration", 3600))
                    if action == "timeout":
                        await message.author.timeout(datetime.timedelta(seconds=duration), reason="Fenrix Word Filter Triggered")
                        msg = await message.channel.send(f"🚫 {message.author.mention} timed out for using forbidden words.")
                    elif action == "kick":
                        await message.author.kick(reason="Fenrix Word Filter Triggered")
                        msg = await message.channel.send(f"🚫 {message.author.mention} kicked for using forbidden words.")
                    elif action == "ban":
                        await message.guild.ban(message.author, reason="Fenrix Word Filter Triggered")
                        msg = await message.channel.send(f"🚫 {message.author.mention} banned for using forbidden words.")
                    else:
                        msg = await message.channel.send(f"🚫 {message.author.mention}, that word is forbidden here.")
                    await asyncio.sleep(5)
                    await msg.delete()
                except Exception as we:
                    logger.error(f"[WORDFILTER] Error: {we}")
                return

        # ── Anti-MassPing ─────────────────────────────────────────
        # Keys match dashboard: antiping_enabled, antiping_threshold, antiping_action
        if config.get("antiping_enabled", True) and not is_staff_user:
            limit = int(config.get("antiping_threshold", 5))
            total_mentions = len(message.mentions) + len(message.role_mentions)
            if total_mentions >= limit:
                try:
                    await message.delete()
                    action = config.get("antiping_action", "timeout")
                    if action == "timeout":
                        await message.author.timeout(datetime.timedelta(hours=2), reason="Fenrix Anti-MassPing")
                        msg = await message.channel.send(f"🚫 {message.author.mention} timed out 2h — mass ping detected.")
                    elif action == "kick":
                        await message.author.kick(reason="Fenrix Anti-MassPing")
                        msg = await message.channel.send(f"🚫 {message.author.mention} kicked — mass ping detected.")
                    elif action == "ban":
                        await message.guild.ban(message.author, reason="Fenrix Anti-MassPing")
                        msg = await message.channel.send(f"🚫 {message.author.mention} banned — mass ping detected.")
                    else:
                        msg = await message.channel.send(f"⚠️ {message.author.mention}, please avoid mass pings.")
                    await asyncio.sleep(5)
                    await msg.delete()
                    bot.db_manager.log_ledger_entry(
                        guild_id=message.guild.id, entry_type="warn",
                        target_name=message.author.name, target_id=message.author.id,
                        enforcer_name=bot.user.name, enforcer_id=bot.user.id,
                        reason=f"Anti-MassPing: {total_mentions} mentions in one message"
                    )
                except Exception as me:
                    logger.error(f"[MASS-PING] {me}")
                return

        # ── Anti-Scam OCR Engine ─────────────────────────────────────
        # Key matches dashboard: antiscam_ocr_enabled, antiscam_action
        if config.get("antiscam_ocr_enabled", False) and message.attachments and not is_staff_user:
            try:
                import pytesseract
            except ImportError:
                pytesseract = None
                
            if pytesseract:
                is_scam = False
                for attachment in message.attachments:
                    if attachment.content_type and attachment.content_type.startswith("image/"):
                        try:
                            image_data = await attachment.read()
                            image = Image.open(io.BytesIO(image_data))
                            text = pytesseract.image_to_string(image).lower()
                            scam_keywords = ["nitro", "free steam", "gift card", "discord nitro", "login qr", "steam gift", "leak cash", "promo code", "steam community"]
                            for kw in scam_keywords:
                                if kw in text:
                                    is_scam = True
                                    break
                        except Exception as ocre:
                            logger.error(f"[OCR] Error scanning image: {ocre}")
                
                if is_scam:
                    try:
                        await message.delete()
                        action = config.get("antiscam_action", "timeout")
                        if action == "timeout":
                            await message.author.timeout(datetime.timedelta(hours=12), reason="Fenrix Anti-Scam OCR Triggered")
                            msg = await message.channel.send(f"🚫 {message.author.mention} timed out 12h — Phishing/Scam image detected.")
                        elif action == "kick":
                            await message.author.kick(reason="Fenrix Anti-Scam OCR Triggered")
                            msg = await message.channel.send(f"🚫 {message.author.mention} kicked — Phishing/Scam image detected.")
                        elif action == "ban":
                            await message.guild.ban(message.author, reason="Fenrix Anti-Scam OCR Triggered")
                            msg = await message.channel.send(f"🚫 {message.author.mention} banned — Phishing/Scam image detected.")
                        else:
                            msg = await message.channel.send(f"⚠️ {message.author.mention}, please do not upload scam/phishing images.")
                        await asyncio.sleep(5)
                        await msg.delete()
                    except Exception as ocr_act_e:
                        logger.error(f"[OCR ACTION] Error: {ocr_act_e}")
                    return

        # Anti-Profanity
        if config.get("antiprofanity_enabled", True) and not is_staff_user:
            if check_blasphemy(message.content):
                try:
                    await message.delete()
                    action   = config.get("antiprofanity_action", "timeout")
                    duration = int(config.get("antiprofanity_duration", 2700))
                    if action == "timeout":
                        await message.author.timeout(
                            datetime.timedelta(seconds=duration),
                            reason="Fenrix Anti-Profanity")
                        msg = await message.channel.send(
                            f"🚫 {message.author.mention} muted for {duration // 60}m — profanity detected.")
                    elif action == "kick":
                        await message.author.kick(reason="Fenrix Anti-Profanity")
                        msg = await message.channel.send(
                            f"🚫 {message.author.mention} kicked — profanity detected.")
                    elif action == "ban":
                        await message.guild.ban(message.author, reason="Fenrix Anti-Profanity")
                        msg = await message.channel.send(
                            f"🚫 {message.author.mention} banned — profanity detected.")
                    else:
                        msg = await message.channel.send(
                            f"🚫 {message.author.mention}, please avoid profanity.")
                    await asyncio.sleep(10)
                    await msg.delete()
                except Exception as e:
                    logger.error(f"[ANTI-PROFANITY] {e}")
                return

        # Anti-Spam Link (also blocks Discord invite links unconditionally)
        _INVITE_RE = re.compile(
            r"(discord\.gg/|discord\.com/invite/|discordapp\.com/invite/)",
            re.IGNORECASE
        )
        _LINK_RE = re.compile(r"https?://[^\s]+|www\.[^\s]+", re.IGNORECASE)

        has_invite = bool(_INVITE_RE.search(message.content))
        has_link   = bool(_LINK_RE.search(message.content))

        if has_invite or (has_link and (config.get("antilink_enabled", False) or config.get("antispam_enabled", False))):
            allowed_roles = [int(rid) for rid in config.get("mod_allowed_roles", [])]
            has_mod_role  = any(role.id in allowed_roles for role in message.author.roles)
            if not is_staff_user and not has_mod_role:
                try:
                    await message.delete()
                    if has_invite:
                        # Discord invites are ALWAYS deleted — just warn the user
                        msg = await message.channel.send(
                            f"🔗 {message.author.mention} — Discord invite links are not allowed here.")
                        await asyncio.sleep(8)
                        await msg.delete()
                        return
                    action  = config.get("antilink_action", "timeout")
                    user_id = str(message.author.id)
                    if action == "timeout":
                        warn_count = bot.spam_warn_tracker.get(user_id, 0)
                        if warn_count == 0:
                            bot.spam_warn_tracker[user_id] = 1
                            if user_id in bot.spam_reset_tasks:
                                bot.spam_reset_tasks[user_id].cancel()
                            bot.spam_reset_tasks[user_id] = bot.loop.create_task(
                                bot.reset_spam_warn(user_id))
                            msg = await message.channel.send(
                                f"⚠️ {message.author.mention} — links are prohibited! Next violation = timeout.")
                        else:
                            await message.author.timeout(
                                datetime.timedelta(minutes=10),
                                reason="Anti-Spam Link")
                            msg = await message.channel.send(
                                f"🚫 {message.author.mention} timed out 10m for posting links.")
                    elif action == "kick":
                        await message.author.kick(reason="Anti-Spam Link")
                        msg = await message.channel.send(
                            f"🚫 {message.author.mention} kicked for posting links.")
                    elif action == "ban":
                        await message.guild.ban(message.author, reason="Anti-Spam Link")
                        msg = await message.channel.send(
                            f"🚫 {message.author.mention} banned for posting links.")
                    else:
                        msg = await message.channel.send(
                            f"🚫 {message.author.mention} — links are prohibited.")
                    await asyncio.sleep(8)
                    await msg.delete()
                except Exception as e:
                    logger.error(f"[ANTI-LINK] {e}")
                return

        # Anti-Raid (message-based)
        if await bot.process_message_raid(message):
            return

    await bot.process_commands(message)

# ─────────────────────────────────────────────────────────────────
# PERMISSION HELPERS
# ─────────────────────────────────────────────────────────────────

def is_owner_or_admin(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    if interaction.user.id == interaction.guild.owner_id:
        return True
    return interaction.user.guild_permissions.administrator

def is_staff(interaction: discord.Interaction) -> bool:
    if is_owner_or_admin(interaction):
        return True
    config = bot.db_manager.get_guild_config(interaction.guild_id)
    allowed_roles = [int(rid) for rid in config.get("mod_allowed_roles", [])]
    return any(role.id in allowed_roles for role in interaction.user.roles)



async def check_staff_interaction(interaction: discord.Interaction) -> bool:
    if is_staff(interaction):
        return True
    await interaction.response.send_message(
        "❌ Access Denied: You do not have the required moderator permissions.", ephemeral=True)
    return False

# ─────────────────────────────────────────────────────────────────
# SETUP COMMAND GROUP (Owner/Admin) — dashboard-migrated subset
# ─────────────────────────────────────────────────────────────────

setup_group = app_commands.Group(
    name="setup", description="Server configuration commands (Administrator only)")
bot.tree.add_command(setup_group)

@setup_group.command(name="staff", description="Configure roles authorized for moderator commands")
@app_commands.describe(roles="Authorized staff roles (comma-separated names/IDs/mentions)")
async def setup_staff(interaction: discord.Interaction, roles: str):
    if not is_owner_or_admin(interaction):
        return await interaction.response.send_message(
            "❌ Access Denied: Administrator required.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    role_ids = parse_roles(interaction.guild, roles)
    if not role_ids:
        return await interaction.followup.send("❌ No valid roles found.", ephemeral=True)
    bot.db_manager.update_guild_config(interaction.guild_id, {"mod_allowed_roles": role_ids})
    mentions = [f"<@&{rid}>" for rid in role_ids]
    await interaction.followup.send(
        f"✅ Staff roles updated: {', '.join(mentions)}", ephemeral=True)

@setup_group.command(name="logs", description="Set the channel for security and moderation logs")
@app_commands.describe(channel="Log channel")
async def setup_logs(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_owner_or_admin(interaction):
        return await interaction.response.send_message(
            "❌ Access Denied: Administrator required.", ephemeral=True)
    bot.db_manager.update_guild_config(interaction.guild_id,
                                       {"security_log_channel": channel.id})
    await interaction.response.send_message(
        f"✅ Security log channel set to {channel.mention}.", ephemeral=True)

# ─────────────────────────────────────────────────────────────────
# INFO COMMAND GROUP
# ─────────────────────────────────────────────────────────────────

info_group = app_commands.Group(
    name="info", description="Information commands")
bot.tree.add_command(info_group)

@info_group.command(name="bot", description="Display general statistics and system status of Fenrix")
async def info_bot_cmd(interaction: discord.Interaction):
    if not hasattr(bot, "start_time"):
        bot.start_time = datetime.datetime.utcnow()
    uptime_d  = datetime.datetime.utcnow() - bot.start_time
    h, r      = divmod(int(uptime_d.total_seconds()), 3600)
    m, s      = divmod(r, 60)
    uptime_str = f"{uptime_d.days}d {h}h {m}m {s}s"

    fields = [
        (f"{E_BOT} Developer",   "Fenrix Core Team",                True),
        (f"{E_HOME} Dashboard",  f"[Open Dashboard]({DASHBOARD_URL})", True),
        (f"{E_CLOCK} Uptime",    uptime_str,                         True),
        ("Latency",              f"{round(bot.latency * 1000)}ms",   True),
        ("Servers",              f"{len(bot.guilds)}",               True),
        ("Description",
         "Elite security, verification gateways, anti-raid, anti-nuke, link spam blocking, and activity reporting.\n\u200b",
         False),
    ]
    embeds = make_embeds(
        banner_url=BANNER_INFO_URL,
        title=f"{E_SHIELD} Fenrix — Elite Security & Management",
        description="Advanced Discord protection powered by Fenrix.\n\n",
        color=0x6366f1, fields=fields, thumbnail=LOGO_URL)
    await interaction.response.send_message(embeds=embeds)

@info_group.command(name="server", description="Display details and statistics about the current server")
async def info_server_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    fields = [
        ("Owner",         f"<@{guild.owner_id}>",                                     True),
        ("Members",       f"**{guild.member_count}**",                                 True),
        ("Boosts",        f"**{guild.premium_subscription_count}** (Tier {guild.premium_tier})", True),
        ("Text Channels", f"**{len(guild.text_channels)}**",                           True),
        ("Voice Channels",f"**{len(guild.voice_channels)}**",                          True),
        ("Roles",         f"**{len(guild.roles)}**",                                   True),
        ("Created",       f"<t:{int(guild.created_at.timestamp())}:D>",                False),
        ("Server ID",     f"`{guild.id}`",                                             False),
    ]
    embeds = make_embeds(
        banner_url=None,
        title=f"🏰 Server Information — {guild.name}",
        description="Public metadata for the current server.\n\n",
        color=0x6366f1, fields=fields,
        thumbnail=str(guild.icon.url) if guild.icon else LOGO_URL)
    await interaction.response.send_message(embeds=embeds)

@info_group.command(name="user", description="Display details about a server member")
@app_commands.describe(member="Member to inspect (leave blank for yourself)")
async def info_user_cmd(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    roles  = [r.mention for r in member.roles if r.name != "@everyone"]
    fields = [
        ("Display Name",  f"**{member.display_name}**",                          True),
        ("Account ID",    f"`{member.id}`",                                       True),
        ("Created On",    f"<t:{int(member.created_at.timestamp())}:D>",          True),
        ("Joined Server", f"<t:{int(member.joined_at.timestamp())}:D>",           True),
        ("Profile",       f"[View Profile](https://discord.com/users/{member.id})", True),
        ("Roles",         ", ".join(roles) if roles else "None",                  False),
    ]
    embeds = make_embeds(
        banner_url=None,
        title=f"👤 Member Information — {member.name}",
        description=f"Profile details for {member.mention}.\n\n",
        color=0x6366f1, fields=fields,
        thumbnail=member.display_avatar.url)
    await interaction.response.send_message(embeds=embeds)

@info_group.command(name="commands", description="Open the Fenrix commands wiki")
async def info_commands_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title=f"{E_BOT} Fenrix — Commands Wiki",
        description=f"Browse the full command list on our dashboard.\n\n[**Open Commands Wiki**]({DASHBOARD_URL}/commands)",
        color=0x6366f1)
    embed.set_thumbnail(url=LOGO_URL)
    embed.set_footer(text="Fenrix Security & Management")
    view = LinkButtonView("View Commands", f"{DASHBOARD_URL}/commands")
    await interaction.response.send_message(embed=embed, view=view)

# ─────────────────────────────────────────────────────────────────
# STATUS COMMAND GROUP
# ─────────────────────────────────────────────────────────────────

status_group = app_commands.Group(
    name="status", description="Fenrix status commands")
bot.tree.add_command(status_group)

@status_group.command(name="bot", description="Run a live diagnostic check on Fenrix")
async def status_bot_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    embeds = await generate_status_embeds(bot, interaction.guild)
    await interaction.followup.send(embeds=embeds)

@status_group.command(name="server", description="Weekly server telemetry — joins, leavers, activity")
async def status_server_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    embeds = await generate_status_embeds(bot, interaction.guild, weekly=True)
    await interaction.followup.send(embeds=embeds)

# ─────────────────────────────────────────────────────────────────
# TOP-LEVEL COMMANDS
# ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="help", description="List all active commands and usage instructions")
async def help_cmd(interaction: discord.Interaction):
    fields = [
        (f"{E_SHIELD} Moderation & Discipline",
         "• `/ban` • `/unban` • `/kick`\n• `/timeout` • `/untimeout`\n• `/mute` • `/unmute`\n• `/giverole` • `/removerole`\n• `/warn add` • `/warn list` • `/warn remove`\n\u200b",
         False),
        ("🔒 Security & Channel Lock",
         "• `/lockdown` — Lock down the entire server\n• `/unlockdown` — Unlock the server\n• `/lockchannel` — Lock current channel\n• `/unlockchannel` — Unlock current channel\n• `/systemstatus` — Active security modules overview\n\u200b",
         False),
        ("ℹ️ Information & Diagnostics",
         "• `/info bot` — Bot stats & uptime\n• `/info server` — Server data\n• `/info user` — Member profile\n• `/info commands` — Dashboard commands wiki\n• `/status bot` — Live diagnostics\n• `/status server` — Weekly telemetry chart\n\u200b",
         False),
        (f"{E_PARTY} Utilities",
         "• `/giveaway` — Launch a giveaway\n• `/avatar` — View member avatar\n• `/partnership` — Announce partnership\n\u200b",
         False),

        (f"{E_HOME} Quick Links",
         f"• `/help` — Show this menu\n• `/dashboard` — Web dashboard\n• `/discord` — Support server\n• `/invite` — Invite Fenrix\n• `/vote` — Vote on top.gg\n\u200b",
         False),
    ]
    embeds = make_embeds(
        banner_url=BANNER_INFO_URL,
        title=f"{E_BOT} Fenrix — Help Manual",
        description="Complete command reference. Visit our support server for assistance.\n\n",
        color=0x6366f1, fields=fields, thumbnail=LOGO_URL)
    await interaction.response.send_message(embeds=embeds)

@bot.tree.command(name="discord", description="Get the Fenrix official support server link")
async def discord_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title=f"{E_HOME} Join Our Support Server",
        description="Support us and stay updated on the latest updates, announcements, and new features of Fenrix!",
        color=0x6366f1)
    embed.set_thumbnail(url=LOGO_URL)
    embed.set_footer(text="Fenrix Security & Management")
    view = LinkButtonView("Join Support Server", SUPPORT_LINK)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="dashboard", description="Open the Fenrix web dashboard")
async def dashboard_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title=f"{E_HOME} Fenrix Dashboard",
        description=f"Manage your server settings, security modules, verification, and more.\n\n[{DASHBOARD_URL}]({DASHBOARD_URL})",
        color=0x6366f1)
    embed.set_thumbnail(url=LOGO_URL)
    embed.set_footer(text="Fenrix Security & Management")
    view = LinkButtonView("Open Dashboard", DASHBOARD_URL)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="vote", description="Support Fenrix by voting on top.gg")
async def vote_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🗳️ Vote for Fenrix",
        description="Support us by leaving a vote and review on top.gg!\nYour support keeps the bot free for everyone.",
        color=0x6366f1)
    embed.set_thumbnail(url=LOGO_URL)
    embed.set_footer(text="Fenrix Security & Management")
    view = LinkButtonView("Vote on top.gg", TOPGG_LINK)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="invite", description="Invite Fenrix to your Discord server")
async def invite_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title=f"{E_BOT} Invite Fenrix Bot",
        description="Want to use Fenrix in your server? Click the button below to invite it with full permissions!",
        color=0x6366f1)
    embed.set_thumbnail(url=LOGO_URL)
    embed.set_footer(text="Fenrix Security & Management")
    view = LinkButtonView("Invite Bot", INVITE_LINK)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="avatar", description="View and download a member's avatar")
@app_commands.describe(member="Member to view (leave blank for yourself)",
                       server_avatar="Show server-specific avatar instead of global")
async def avatar_cmd(interaction: discord.Interaction,
                     member: discord.Member = None,
                     server_avatar: bool = False):
    target = member or interaction.user
    if server_avatar and hasattr(target, "guild_avatar") and target.guild_avatar:
        av = target.guild_avatar
    else:
        av = target.display_avatar

    # Build high-resolution URL (4096px)
    av_url = av.replace(size=4096).url

    embed = discord.Embed(
        title=f"🖼️ {target.display_name}'s Avatar",
        color=0x6366f1)
    embed.set_image(url=av_url)
    embed.set_footer(text=f"ID: {target.id} | Fenrix Security")

    view = LinkButtonView("⬇️ Download Avatar (4K)", av_url)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="partnership",
                  description="Announce a new server partnership")
@app_commands.describe(
    management="Staff member processing the partnership",
    manager="External representative's name or server",
    ping="Optional role to ping")
async def partnership_cmd(
    interaction: discord.Interaction,
    management: discord.Member,
    manager: str,
    ping: discord.Role = None
):
    if not is_staff(interaction):
        return await interaction.response.send_message(
            "❌ Access Denied: Staff permissions required.", ephemeral=True)

    ping_content = ping.mention if ping else ""
    modal = PartnershipModal(
        management_member=management,
        manager_name=manager,
        ping_content=ping_content)
    await interaction.response.send_modal(modal)

@bot.tree.command(name="giveaway", description="Create a giveaway with an intelligent time parser")
@app_commands.describe(
    duration="Duration (e.g. 10s / 10m / 1h / 1day / 48h / 1:30:00)",
    prize="Giveaway prize description",
    winners="Number of winners",
    ping="Optional role or @everyone/@here to ping",
    required_role="Role required to enter the giveaway")
async def giveaway_cmd(
    interaction: discord.Interaction,
    duration: str,
    prize: str,
    winners: int = 1,
    ping: str = None,
    required_role: discord.Role = None
):
    if not is_staff(interaction):
        return await interaction.response.send_message(
            "❌ Access Denied: Staff role required.", ephemeral=True)

    total_secs = parse_duration(duration)
    if total_secs is None:
        return await interaction.response.send_message(
            "❌ Invalid duration format.\n\n"
            "**Accepted formats:** `10s` · `5m` · `2h` · `1day` · `48h` · `00:30` · `1:30:00`\n"
            "**Range:** 5 seconds → 7 days",
            ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    now_ts = int(time.time())
    end_ts = now_ts + total_secs

    embed = discord.Embed(
        title=f"{E_PARTY} Fenrix Giveaway!",
        description="Click the button to enter!\n\n",
        color=0x6366f1)
    embed.set_thumbnail(url=LOGO_URL)
    embed.add_field(name="Prize",        value=f"**{prize}**",            inline=True)
    embed.add_field(name="Winners",      value=f"**{winners}**",          inline=True)
    embed.add_field(name="Ends",         value=f"<t:{end_ts}:R>",         inline=True)
    embed.add_field(name="Participants", value="**0**",                   inline=True)
    if required_role:
        embed.add_field(name="Required Role", value=required_role.mention, inline=True)
    embed.set_footer(text="Fenrix Giveaway System")

    ping_msg = ping if ping else ""
    msg = await interaction.channel.send(content=ping_msg, embeds=[embed])

    gw_data = {
        "guild_id":      interaction.guild_id,
        "channel_id":    interaction.channel_id,
        "prize":         prize,
        "winners_count": winners,
        "end_time":      end_ts,
        "participants":  [],
        "ended":         False,
        "required_role": str(required_role.id) if required_role else None,
    }
    bot.db_manager.save_giveaway(str(msg.id), gw_data)
    view = PersistentGiveawayView(bot, str(msg.id))
    await msg.edit(view=view)
    await interaction.followup.send(
        f"✅ Giveaway started! Ends <t:{end_ts}:F>", ephemeral=True)

# ─────────────────────────────────────────────────────────────────
# MODERATION COMMANDS
# ─────────────────────────────────────────────────────────────────

async def _log_mod_action(interaction, embeds):
    config    = bot.db_manager.get_guild_config(interaction.guild_id)
    log_ch_id = config.get("security_log_channel") or config.get("verify_log_channel")
    if log_ch_id:
        ch = interaction.guild.get_channel(int(log_ch_id))
        if ch:
            try:
                await ch.send(embeds=embeds)
            except Exception:
                pass

@bot.tree.command(name="ban", description="Ban a user from the server")
@app_commands.describe(user="User to ban", reason="Reason for ban")
async def ban_cmd(interaction: discord.Interaction, user: discord.User,
                  reason: str = "No reason provided"):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    try:
        await interaction.guild.ban(user, reason=f"Banned by {interaction.user.name}: {reason}")
        
        bot.db_manager.log_ledger_entry(
            guild_id=interaction.guild_id,
            entry_type="ban",
            target_name=user.name,
            target_id=user.id,
            enforcer_name=interaction.user.name,
            enforcer_id=interaction.user.id,
            reason=reason
        )
        
        fields = [
            (f"{E_BAN} Target",   f"{user.name} (`{user.id}`)",  True),
            ("Moderator",         interaction.user.mention,       True),
            ("Reason",            reason,                         False),
            ("Timestamp",         f"<t:{int(time.time())}:F>",   False),
        ]
        embeds = make_embeds(None, f"{E_BAN} User Banned", "Audit log updated.\n\n",
                             color=0xff0000, fields=fields, thumbnail=LOGO_URL)
        await interaction.followup.send(embeds=embeds)
        await _log_mod_action(interaction, embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to ban: {e}", ephemeral=True)

@bot.tree.command(name="unban", description="Revoke a server ban by user ID")
@app_commands.describe(user_id="Numeric ID of the banned user", reason="Reason for unban")
async def unban_cmd(interaction: discord.Interaction, user_id: str,
                    reason: str = "No reason provided"):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    try:
        uid = int(user_id.strip())
        await interaction.guild.unban(discord.Object(id=uid),
                                      reason=f"Unbanned by {interaction.user.name}: {reason}")
        
        bot.db_manager.log_ledger_entry(
            guild_id=interaction.guild_id,
            entry_type="unban",
            target_name=f"User ID {uid}",
            target_id=uid,
            enforcer_name=interaction.user.name,
            enforcer_id=interaction.user.id,
            reason=reason
        )
        
        fields = [
            ("Target ID", f"`{uid}`",              True),
            ("Moderator", interaction.user.mention, True),
            ("Reason",    reason,                   False),
        ]
        embeds = make_embeds(None, "🔓 User Unbanned", "Audit log updated.\n\n",
                             color=0x00ff00, fields=fields, thumbnail=LOGO_URL)
        await interaction.followup.send(embeds=embeds)
        await _log_mod_action(interaction, embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to unban: {e}", ephemeral=True)

@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="Member to kick", reason="Reason for kick")
async def kick_cmd(interaction: discord.Interaction, member: discord.Member,
                   reason: str = "No reason provided"):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    try:
        await member.kick(reason=f"Kicked by {interaction.user.name}: {reason}")
        
        bot.db_manager.log_ledger_entry(
            guild_id=interaction.guild_id,
            entry_type="kick",
            target_name=member.name,
            target_id=member.id,
            enforcer_name=interaction.user.name,
            enforcer_id=interaction.user.id,
            reason=reason
        )
        
        fields = [
            ("Target",    f"{member.name} (`{member.id}`)", True),
            ("Moderator", interaction.user.mention,          True),
            ("Reason",    reason,                            False),
        ]
        embeds = make_embeds(None, "👢 Member Kicked", "Audit log updated.\n\n",
                             color=0xffaa00, fields=fields, thumbnail=LOGO_URL)
        await interaction.followup.send(embeds=embeds)
        await _log_mod_action(interaction, embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to kick: {e}", ephemeral=True)

@bot.tree.command(name="timeout", description="Apply a native Discord timeout to a member")
@app_commands.describe(member="Member to timeout", duration="Timeout duration",
                       reason="Reason for timeout")
@app_commands.choices(duration=[
    app_commands.Choice(name="5 Minutes",  value=300),
    app_commands.Choice(name="10 Minutes", value=600),
    app_commands.Choice(name="1 Hour",     value=3600),
    app_commands.Choice(name="6 Hours",    value=21600),
    app_commands.Choice(name="12 Hours",   value=43200),
    app_commands.Choice(name="1 Day",      value=86400),
    app_commands.Choice(name="3 Days",     value=259200),
    app_commands.Choice(name="7 Days",     value=604800),
])
async def timeout_cmd(interaction: discord.Interaction, member: discord.Member,
                      duration: app_commands.Choice[int],
                      reason: str = "No reason provided"):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    try:
        await member.timeout(datetime.timedelta(seconds=duration.value),
                             reason=f"Timeout by {interaction.user.name}: {reason}")
        
        bot.db_manager.log_ledger_entry(
            guild_id=interaction.guild_id,
            entry_type="timeout",
            target_name=member.name,
            target_id=member.id,
            enforcer_name=interaction.user.name,
            enforcer_id=interaction.user.id,
            reason=f"Timeout ({duration.name}): {reason}"
        )
        
        fields = [
            ("Target",    f"{member.name} (`{member.id}`)", True),
            ("Moderator", interaction.user.mention,          True),
            ("Duration",  f"**{duration.name}**",            True),
            ("Reason",    reason,                            False),
        ]
        embeds = make_embeds(None, "🚫 Member Timed Out", "Audit log updated.\n\n",
                             color=0xff5500, fields=fields, thumbnail=LOGO_URL)
        await interaction.followup.send(embeds=embeds)
        await _log_mod_action(interaction, embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to timeout: {e}", ephemeral=True)

@bot.tree.command(name="untimeout", description="Remove a communication restriction from a member")
@app_commands.describe(member="Member to untimeout", reason="Reason")
async def untimeout_cmd(interaction: discord.Interaction, member: discord.Member,
                        reason: str = "No reason provided"):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    try:
        await member.timeout(None, reason=f"Timeout removed by {interaction.user.name}: {reason}")
        
        bot.db_manager.log_ledger_entry(
            guild_id=interaction.guild_id,
            entry_type="untimeout",
            target_name=member.name,
            target_id=member.id,
            enforcer_name=interaction.user.name,
            enforcer_id=interaction.user.id,
            reason=reason
        )
        
        fields = [
            ("Target",    f"{member.name} (`{member.id}`)", True),
            ("Moderator", interaction.user.mention,          True),
            ("Reason",    reason,                            False),
        ]
        embeds = make_embeds(None, "🔊 Timeout Removed", "Audit log updated.\n\n",
                             color=0x00ff00, fields=fields, thumbnail=LOGO_URL)
        await interaction.followup.send(embeds=embeds)
        await _log_mod_action(interaction, embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to remove timeout: {e}", ephemeral=True)

@bot.tree.command(name="giverole", description="Give a role to a member")
@app_commands.describe(member="Target member", role="Role to assign",
                       reason="Reason for role assignment")
async def giverole_cmd(interaction: discord.Interaction, member: discord.Member,
                       role: discord.Role, reason: str = "No reason provided"):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    try:
        await member.add_roles(role, reason=f"By {interaction.user.name}: {reason}")
        fields = [
            ("Member",    member.mention,           True),
            ("Role",      role.mention,             True),
            ("Moderator", interaction.user.mention, True),
            ("Reason",    reason,                   False),
        ]
        embeds = make_embeds(None, f"{E_CHECK} Role Assigned", "Role updated.\n\n",
                             color=0x00ff00, fields=fields, thumbnail=LOGO_URL)
        await interaction.followup.send(embeds=embeds)
        await _log_mod_action(interaction, embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to give role: {e}", ephemeral=True)

@bot.tree.command(name="removerole", description="Remove a role from a member")
@app_commands.describe(member="Target member", role="Role to remove",
                       reason="Reason for role removal")
async def removerole_cmd(interaction: discord.Interaction, member: discord.Member,
                         role: discord.Role, reason: str = "No reason provided"):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    try:
        await member.remove_roles(role, reason=f"By {interaction.user.name}: {reason}")
        fields = [
            ("Member",    member.mention,           True),
            ("Role",      role.mention,             True),
            ("Moderator", interaction.user.mention, True),
            ("Reason",    reason,                   False),
        ]
        embeds = make_embeds(None, f"{E_BAN} Role Removed", "Role updated.\n\n",
                             color=0xff5500, fields=fields, thumbnail=LOGO_URL)
        await interaction.followup.send(embeds=embeds)
        await _log_mod_action(interaction, embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to remove role: {e}", ephemeral=True)

# ── New Moderation and Utility Commands ──────────────────────────

@bot.tree.command(name="mute", description="Restrict communications for a member (Timeout)")
@app_commands.describe(member="Member to mute", duration="Duration (e.g. 10m, 2h, 1day)", reason="Reason for mute")
async def mute_cmd(interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "No reason provided"):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    secs = parse_duration(duration)
    if not secs:
        return await interaction.followup.send("❌ Invalid duration format. Examples: `10m`, `2h`, `1day`.", ephemeral=True)
    try:
        await member.timeout(datetime.timedelta(seconds=secs), reason=f"Mute by {interaction.user.name}: {reason}")
        bot.db_manager.log_ledger_entry(
            guild_id=interaction.guild_id,
            entry_type="timeout",
            target_name=member.name,
            target_id=member.id,
            enforcer_name=interaction.user.name,
            enforcer_id=interaction.user.id,
            reason=f"Muted for {duration}: {reason}"
        )
        fields = [
            ("Target", f"{member.name} (`{member.id}`)", True),
            ("Moderator", interaction.user.mention, True),
            ("Duration", f"**{duration}**", True),
            ("Reason", reason, False)
        ]
        embeds = make_embeds(None, "🔇 Member Muted", "Audit log updated.\n\n", color=0xff5500, fields=fields, thumbnail=LOGO_URL)
        await interaction.followup.send(embeds=embeds)
        await _log_mod_action(interaction, embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to mute: {e}", ephemeral=True)

@bot.tree.command(name="unmute", description="Unmute a member (Remove Timeout)")
@app_commands.describe(member="Member to unmute", reason="Reason for unmute")
async def unmute_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    try:
        await member.timeout(None, reason=f"Unmute by {interaction.user.name}: {reason}")
        bot.db_manager.log_ledger_entry(
            guild_id=interaction.guild_id,
            entry_type="untimeout",
            target_name=member.name,
            target_id=member.id,
            enforcer_name=interaction.user.name,
            enforcer_id=interaction.user.id,
            reason=reason
        )
        fields = [
            ("Target", f"{member.name} (`{member.id}`)", True),
            ("Moderator", interaction.user.mention, True),
            ("Reason", reason, False)
        ]
        embeds = make_embeds(None, "🔊 Member Unmuted", "Audit log updated.\n\n", color=0x00ff00, fields=fields, thumbnail=LOGO_URL)
        await interaction.followup.send(embeds=embeds)
        await _log_mod_action(interaction, embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to unmute: {e}", ephemeral=True)

warn_group = app_commands.Group(name="warn", description="Disciplinary warning administration")
bot.tree.add_command(warn_group)

@warn_group.command(name="add", description="Add a warning to a user")
@app_commands.describe(user="User to warn", reason="Reason for warning")
async def warn_add(interaction: discord.Interaction, user: discord.User, reason: str):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    warn_id = bot.db_manager.add_warning(
        guild_id=interaction.guild_id,
        user_id=user.id,
        reason=reason,
        mod_name=interaction.user.name,
        mod_id=interaction.user.id
    )
    bot.db_manager.log_ledger_entry(
        guild_id=interaction.guild_id,
        entry_type="warn",
        target_name=user.name,
        target_id=user.id,
        enforcer_name=interaction.user.name,
        enforcer_id=interaction.user.id,
        reason=f"Warning ({warn_id}): {reason}"
    )
    fields = [
        ("Target User", f"{user.mention} ({user.name})", True),
        ("Moderator", interaction.user.mention, True),
        ("Warning ID", f"`{warn_id}`", True),
        ("Reason", reason, False)
    ]
    embeds = make_embeds(None, "⚠️ User Warned", "Warning has been registered.\n\n", color=0xffaa00, fields=fields, thumbnail=LOGO_URL)
    await interaction.followup.send(embeds=embeds)
    await _log_mod_action(interaction, embeds)

@warn_group.command(name="list", description="List warnings for a user")
@app_commands.describe(user="User to inspect")
async def warn_list(interaction: discord.Interaction, user: discord.User):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    warnings = bot.db_manager.get_warnings(interaction.guild_id, user.id)
    if not warnings:
        return await interaction.followup.send(f"✅ **{user.name}** has 0 active warnings on this server.")
    
    embed = discord.Embed(
        title=f"📋 Warnings Ledger — {user.name}",
        description=f"Warnings list for {user.mention} (ID: `{user.id}`).",
        color=0xffaa00
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    for w in warnings:
        d = datetime.datetime.fromtimestamp(w.get("timestamp", 0))
        embed.add_field(
            name=f"ID: {w.get('id')} — {d.strftime('%Y-%m-%d')}",
            value=f"**Reason:** {w.get('reason')}\n**Mod:** {w.get('moderator_name')} ({w.get('moderator_id')})",
            inline=False
        )
    embed.set_footer(text="Fenrix Audit System")
    await interaction.followup.send(embed=embed)

@warn_group.command(name="remove", description="Clear specific warning or all warnings for a user")
@app_commands.describe(user="User", warning_id="Warning ID to clear (or 'all' to clear all)")
async def warn_remove(interaction: discord.Interaction, user: discord.User, warning_id: str):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    success = bot.db_manager.remove_warning(interaction.guild_id, user.id, warning_id)
    if success:
        reason_str = "All warnings cleared" if warning_id.lower() == "all" else f"Warning {warning_id} cleared"
        bot.db_manager.log_ledger_entry(
            guild_id=interaction.guild_id,
            entry_type="warn_clear",
            target_name=user.name,
            target_id=user.id,
            enforcer_name=interaction.user.name,
            enforcer_id=interaction.user.id,
            reason=reason_str
        )
        await interaction.followup.send(f"✅ Successfully cleared **{warning_id}** warnings for {user.mention}.")
    else:
        await interaction.followup.send(f"❌ Warning **{warning_id}** not found or user has no warnings.")

@bot.tree.command(name="mywarn", description="View your own warnings on this server")
async def mywarn_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    warnings = bot.db_manager.get_warnings(interaction.guild_id, interaction.user.id)
    if not warnings:
        return await interaction.followup.send("✅ You have **0 warnings** on this server.", ephemeral=True)
    
    embed = discord.Embed(
        title="⚠️ Your Warnings Ledger",
        description=f"You have **{len(warnings)}** warnings on **{interaction.guild.name}**.",
        color=0xff5500
    )
    for w in warnings:
        d = datetime.datetime.fromtimestamp(w.get("timestamp", 0))
        embed.add_field(
            name=f"Warning {w.get('id')} — {d.strftime('%Y-%m-%d')}",
            value=f"**Reason:** {w.get('reason')}",
            inline=False
        )
    embed.set_footer(text="Fenrix Security System")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="lockdown", description="Lockdown the entire guild (disable message sending)")
async def lockdown_cmd(interaction: discord.Interaction):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    guild = interaction.guild
    locked_count = 0
    for ch in guild.text_channels:
        everyone_perms = ch.overwrites_for(guild.default_role)
        if everyone_perms.read_messages is not False:
            try:
                everyone_perms.send_messages = False
                await ch.set_permissions(guild.default_role, overwrite=everyone_perms, reason=f"Global Lockdown by {interaction.user.name}")
                locked_count += 1
            except Exception:
                pass
    
    bot.db_manager.log_ledger_entry(
        guild_id=guild.id,
        entry_type="nuke_alert",
        target_name=guild.name,
        target_id=guild.id,
        enforcer_name=interaction.user.name,
        enforcer_id=interaction.user.id,
        reason="Server-wide lockdown triggered manually."
    )
    await interaction.followup.send(f"🔒 **Server Lockdown Enforced.** Locked **{locked_count}** public text channels.")

@bot.tree.command(name="unlockdown", description="Unlock the entire guild")
async def unlockdown_cmd(interaction: discord.Interaction):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    guild = interaction.guild
    unlocked_count = 0
    for ch in guild.text_channels:
        everyone_perms = ch.overwrites_for(guild.default_role)
        if everyone_perms.send_messages is False:
            try:
                everyone_perms.send_messages = None
                await ch.set_permissions(guild.default_role, overwrite=everyone_perms, reason=f"Global Unlockdown by {interaction.user.name}")
                unlocked_count += 1
            except Exception:
                pass
                
    bot.db_manager.log_ledger_entry(
        guild_id=guild.id,
        entry_type="unlockdown",
        target_name=guild.name,
        target_id=guild.id,
        enforcer_name=interaction.user.name,
        enforcer_id=interaction.user.id,
        reason="Server-wide lockdown lifted manually."
    )
    await interaction.followup.send(f"🔓 **Server Lockdown Lifted.** Restored permissions in **{unlocked_count}** channels.")

@bot.tree.command(name="lockchannel", description="Lockdown a single text channel")
@app_commands.describe(channel="Channel to lock")
async def lockchannel_cmd(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    ch = channel or interaction.channel
    guild = interaction.guild
    try:
        overwrite = ch.overwrites_for(guild.default_role)
        overwrite.send_messages = False
        await ch.set_permissions(guild.default_role, overwrite=overwrite, reason=f"Channel Lock by {interaction.user.name}")
        
        bot.db_manager.log_ledger_entry(
            guild_id=guild.id,
            entry_type="lockchannel",
            target_name=ch.name,
            target_id=ch.id,
            enforcer_name=interaction.user.name,
            enforcer_id=interaction.user.id,
            reason="Channel locked manually."
        )
        await interaction.followup.send(f"🔒 Channel {ch.mention} has been locked down.")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to lock channel: {e}", ephemeral=True)

@bot.tree.command(name="unlockchannel", description="Unlock a single locked text channel")
@app_commands.describe(channel="Channel to unlock")
async def unlockchannel_cmd(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not await check_staff_interaction(interaction):
        return
    await interaction.response.defer()
    ch = channel or interaction.channel
    guild = interaction.guild
    try:
        overwrite = ch.overwrites_for(guild.default_role)
        overwrite.send_messages = None
        await ch.set_permissions(guild.default_role, overwrite=overwrite, reason=f"Channel Unlock by {interaction.user.name}")
        
        bot.db_manager.log_ledger_entry(
            guild_id=guild.id,
            entry_type="unlockchannel",
            target_name=ch.name,
            target_id=ch.id,
            enforcer_name=interaction.user.name,
            enforcer_id=interaction.user.id,
            reason="Channel unlocked manually."
        )
        await interaction.followup.send(f"🔓 Channel {ch.mention} has been unlocked.")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to unlock channel: {e}", ephemeral=True)

@bot.tree.command(name="systemstatus", description="Displays an overview of all active modules on the server")
async def systemstatus_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    config = bot.db_manager.get_guild_config(interaction.guild_id)
    
    def check_status(key, default=False):
        val = config.get(key, default)
        return "<:spunta:1513860712336850944> **Enabled**" if val else "❌ **Disabled**"
    
    embed = discord.Embed(
        title=f"<:scudo:1513860909846757546> Fenrix Modules System Status",
        description=f"Current active/inactive security modules for **{interaction.guild.name}**.\n\n",
        color=0x6366f1
    )
    embed.set_thumbnail(url=LOGO_URL)
    embed.add_field(name="🛡️ Verification Gate", value=check_status("verify_enabled"), inline=True)
    embed.add_field(name="💣 Anti-Nuke Heuristics", value=check_status("antinuke_enabled", True), inline=True)
    embed.add_field(name="🚨 Anti-Raid Message Lock", value=check_status("antiraid_enabled"), inline=True)
    embed.add_field(name="🔗 Anti-Link & Invite Filter", value=check_status("antilink_enabled"), inline=True)
    embed.add_field(name="🤬 Anti-Profanity Filter", value=check_status("antiprofanity_enabled", True), inline=True)
    embed.add_field(name="🏷️ Anti-Role Destruction", value=check_status("antirole_enabled"), inline=True)
    embed.add_field(name="📢 Anti-Channel Destruction", value=check_status("antichannel_enabled"), inline=True)
    embed.add_field(name="🍯 Honeypot Decoy Trap", value=check_status("honeypot_enabled") + (f" (Active Decoy)" if config.get("honeypot_active") else ""), inline=True)
    embed.add_field(name="🔒 Anti-Spam (Join Gate)", value=check_status("antijoin_enabled"), inline=True)
    embed.set_footer(text="Fenrix Advanced Security Systems")
    await interaction.followup.send(embed=embed)

# ─────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────

from dashboard.app import create_app

async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN environment variable is not set. "
            "Set it in your Render environment variables or .env file.")

    async with bot:
        app  = create_app(bot, bot.db_manager)
        port = int(os.getenv("PORT", 5000))
        logger.info(f"[SYSTEM] Starting Fenrix bot + dashboard on port {port}…")
        await asyncio.gather(
            bot.start(token),
            app.run_task(host="0.0.0.0", port=port)
        )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[SYSTEM] Bot and Dashboard stopped.")
