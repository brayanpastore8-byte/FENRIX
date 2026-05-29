import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
import asyncio
import logging
import traceback
import json
import os
import re
import time
import random
import urllib.parse
import requests
import firebase_admin
from firebase_admin import credentials, firestore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Fenrix")

TOKEN = os.getenv("DISCORD_TOKEN", "MTUwNzY4NTk3NzkzNjg4Nzg0OA.GgaPqO.oI3it10UjlyHHeNZzzuBTDA0bMbwMkE-NxeZfY")
LOGO_URL = "https://cdn.discordapp.com/attachments/1501988744637579304/1508888560789622806/Blue_and_Purple_Modern_Technology_Logo.png?ex=6a172d7a&is=6a15dbfa&hm=0291764fe90911b583c7aab4d1847a70a35198add6f20147e31940060f1492ff"
BANNER_INFO_URL = "https://cdn.discordapp.com/attachments/1093254707390193774/1507844070632984728/Polished_Digital_Banner_with_Enduring_Aesthetic.png?ex=6a1360b8&is=6a120f38&hm=cd3c6afc149f93dcae9536618aadfce70375dd4bb8ba47cf626beeb8538c8283"
BANNER_VERIFY_URL = "https://cdn.discordapp.com/attachments/1093254707390193774/1507844993723666532/Black_and_White_Digital_Banner_with_Leaves.png?ex=6a136194&is=6a121014&hm=189eeea36f5c031b664c0f0f29f53bd1bed6baa9ed7af9853aaa7ab75b4fca92"
SUPPORT_LINK = "https://discord.gg/XSvXWyq2fj"

PROFANITY_KEYWORDS = [
    "dio porco", "porco dio", "dio cane", "dio bastardo", "bastardo dio",
    "dio stronzo", "dio maiale", "maiale dio", "porca madonna", "madonna puttana",
    "madonna maiala", "madonna troia", "cristo dio", "dio infame", "dioporco", "porcodio",
    "diocane", "porcamadonna", "dio boia", "dio ladro", "dio impestato", "dio lurido",
    "goddamn", "god damn", "jesus christ", "motherfucker", "mother fucker",
    "cazzo", "puttana", "troia", "vaffanculo", "bastardo", "stronzo", "coglion"
]

# ─────────────────────────────────────────────────────────────────
# DATABASE MANAGER
# ─────────────────────────────────────────────────────────────────

class DatabaseManager:
    def __init__(self):
        self.use_firebase = False
        self.local_file = "local_db.json"

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
            if not os.path.exists(self.local_file):
                with open(self.local_file, "w") as f:
                    json.dump({}, f)

    def _read_local(self):
        try:
            with open(self.local_file, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_local(self, data):
        try:
            with open(self.local_file, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"[DATABASE] Error writing local DB: {e}")

    def get_guild_config(self, guild_id: int):
        if self.use_firebase:
            try:
                doc_ref = self.db.collection("guild_configs").document(str(guild_id))
                doc = doc_ref.get()
                if doc.exists:
                    return doc.to_dict()
                return {}
            except Exception as e:
                logger.error(f"[DATABASE] Firebase read error: {e}")
                return {}
        else:
            data = self._read_local()
            return data.get(str(guild_id), {})

    def update_guild_config(self, guild_id: int, updates: dict):
        if self.use_firebase:
            try:
                doc_ref = self.db.collection("guild_configs").document(str(guild_id))
                doc_ref.set(updates, merge=True)
            except Exception as e:
                logger.error(f"[DATABASE] Firebase write error: {e}")
        else:
            data = self._read_local()
            guild_data = data.get(str(guild_id), {})
            guild_data.update(updates)
            data[str(guild_id)] = guild_data
            self._write_local(data)

    def log_activity(self, guild_id: int):
        hour_str = datetime.datetime.utcnow().strftime("%Y-%m-%d-%H")
        if self.use_firebase:
            try:
                doc_ref = self.db.collection("guild_activity").document(str(guild_id))
                doc = doc_ref.get()
                activity_data = doc.to_dict() if doc.exists else {}
                current_val = activity_data.get(hour_str, 0)
                activity_data[hour_str] = current_val + 1
                cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=48)
                purged = {}
                for k, v in activity_data.items():
                    try:
                        dt = datetime.datetime.strptime(k, "%Y-%m-%d-%H")
                        if dt >= cutoff:
                            purged[k] = v
                    except Exception:
                        pass
                doc_ref.set(purged)
            except Exception as e:
                logger.error(f"[DATABASE] Firebase activity log error: {e}")
        else:
            data = self._read_local()
            activity_data = data.get(f"{guild_id}_activity", {})
            current_val = activity_data.get(hour_str, 0)
            activity_data[hour_str] = current_val + 1
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=48)
            purged = {}
            for k, v in activity_data.items():
                try:
                    dt = datetime.datetime.strptime(k, "%Y-%m-%d-%H")
                    if dt >= cutoff:
                        purged[k] = v
                except Exception:
                    pass
            data[f"{guild_id}_activity"] = purged
            self._write_local(data)

    def get_activity_data(self, guild_id: int):
        if self.use_firebase:
            try:
                doc_ref = self.db.collection("guild_activity").document(str(guild_id))
                doc = doc_ref.get()
                if doc.exists:
                    return doc.to_dict()
                return {}
            except Exception as e:
                logger.error(f"[DATABASE] Firebase activity read error: {e}")
                return {}
        else:
            data = self._read_local()
            return data.get(f"{guild_id}_activity", {})

    def save_poll(self, message_id: str, question: str, options: list, votes: dict):
        if self.use_firebase:
            try:
                self.db.collection("polls").document(message_id).set({
                    "question": question,
                    "options": options,
                    "votes": votes,
                    "active": True
                })
            except Exception as e:
                logger.error(f"[DATABASE] Firebase save_poll error: {e}")
        else:
            data = self._read_local()
            polls = data.get("polls", {})
            polls[message_id] = {
                "question": question,
                "options": options,
                "votes": votes,
                "active": True
            }
            data["polls"] = polls
            self._write_local(data)

    def update_poll_votes(self, message_id: str, votes: dict):
        if self.use_firebase:
            try:
                self.db.collection("polls").document(message_id).update({"votes": votes})
            except Exception as e:
                logger.error(f"[DATABASE] Firebase update_poll_votes error: {e}")
        else:
            data = self._read_local()
            polls = data.get("polls", {})
            if message_id in polls:
                polls[message_id]["votes"] = votes
                data["polls"] = polls
                self._write_local(data)

    def get_active_polls(self):
        if self.use_firebase:
            try:
                docs = self.db.collection("polls").where("active", "==", True).stream()
                polls = {}
                for doc in docs:
                    polls[doc.id] = doc.to_dict()
                return polls
            except Exception as e:
                logger.error(f"[DATABASE] Firebase get_active_polls error: {e}")
                return {}
        else:
            data = self._read_local()
            polls = data.get("polls", {})
            return {k: v for k, v in polls.items() if v.get("active", False)}

    def end_poll(self, message_id: str):
        if self.use_firebase:
            try:
                self.db.collection("polls").document(message_id).update({"active": False})
            except Exception as e:
                logger.error(f"[DATABASE] Firebase end_poll error: {e}")
        else:
            data = self._read_local()
            polls = data.get("polls", {})
            if message_id in polls:
                polls[message_id]["active"] = False
                data["polls"] = polls
                self._write_local(data)

    def save_giveaway(self, message_id: str, data_dict: dict):
        if self.use_firebase:
            try:
                self.db.collection("giveaways").document(message_id).set(data_dict)
            except Exception as e:
                logger.error(f"[DATABASE] Firebase save_giveaway error: {e}")
        else:
            data = self._read_local()
            giveaways = data.get("giveaways", {})
            giveaways[message_id] = data_dict
            data["giveaways"] = giveaways
            self._write_local(data)

    def get_active_giveaways(self):
        if self.use_firebase:
            try:
                docs = self.db.collection("giveaways").where("ended", "==", False).stream()
                giveaways = {}
                for doc in docs:
                    giveaways[doc.id] = doc.to_dict()
                return giveaways
            except Exception as e:
                logger.error(f"[DATABASE] Firebase get_active_giveaways error: {e}")
                return {}
        else:
            data = self._read_local()
            giveaways = data.get("giveaways", {})
            return {k: v for k, v in giveaways.items() if not v.get("ended", False)}

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

def make_embeds(banner_url: str, title: str, description: str, color: int = 0x2f3136, fields: list = None, thumbnail: str = None):
    embeds = []
    if banner_url:
        b_emb = discord.Embed(color=color)
        b_emb.set_image(url=banner_url)
        embeds.append(b_emb)

    c_emb = discord.Embed(title=title, description=description, color=color)
    if thumbnail:
        c_emb.set_thumbnail(url=thumbnail)
    if fields:
        for name, val, inline in fields:
            c_emb.add_field(name=name, value=val, inline=inline)
    embeds.append(c_emb)
    return embeds

def check_blasphemy(content: str) -> bool:
    cleaned = re.sub(r'[^\w\s]', '', content.lower())
    for word in PROFANITY_KEYWORDS:
        if word in cleaned or word in content.lower():
            return True
    return False

def get_roblox_user_info(username: str):
    search_url = f"https://users.roblox.com/v1/users/search?keyword={username}&limit=1"
    try:
        r = requests.get(search_url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data and data.get("data"):
                user_data = data["data"][0]
                user_id = user_data["id"]
                detail_url = f"https://users.roblox.com/v1/users/{user_id}"
                det_r = requests.get(detail_url, timeout=5)
                details = det_r.json() if det_r.status_code == 200 else {}
                thumb_url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=false"
                thumb_r = requests.get(thumb_url, timeout=5)
                thumb_data = thumb_r.json() if thumb_r.status_code == 200 else {}
                avatar_url = None
                if thumb_data and thumb_data.get("data"):
                    avatar_url = thumb_data["data"][0].get("imageUrl")

                return {
                    "id": user_id,
                    "name": details.get("name", user_data.get("name")),
                    "displayName": details.get("displayName", user_data.get("displayName")),
                    "created": details.get("created"),
                    "description": details.get("description", "No description provided."),
                    "avatar_url": avatar_url,
                    "profile_url": f"https://www.roblox.com/users/{user_id}/profile"
                }
    except Exception as e:
        logger.error(f"Error querying Roblox API: {e}")
    return None

# ─────────────────────────────────────────────────────────────────
# VIEWS (BUTTONS / INTERACTIONS)
# ─────────────────────────────────────────────────────────────────

class VerificationButtonView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Verify Account", style=discord.ButtonStyle.green, emoji="🛡️", custom_id="galaxy_tree_verify_btn")
    async def verify_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = self.bot.db_manager.get_guild_config(interaction.guild_id)
        if not config:
            return await interaction.followup.send("❌ Verification system is not configured on this server.", ephemeral=True)

        roles_to_add = config.get("verify_roles_to_add", [])
        roles_to_remove = config.get("verify_roles_to_remove", [])
        log_channel_id = config.get("verify_log_channel")

        guild = interaction.guild
        member = interaction.user

        added = []
        removed = []

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
        except Exception as e:
            logger.error(f"Error applying verification roles: {e}")
            return await interaction.followup.send("❌ Verification failed. Check bot hierarchy and permissions.", ephemeral=True)

        await interaction.followup.send("✅ **Verification Successful**\n\nYou have been verified and granted access!", ephemeral=True)

        if log_channel_id:
            log_channel = guild.get_channel(int(log_channel_id))
            if log_channel:
                fields = [
                    ("User", f"{member.mention} ({member.name})", True),
                    ("User ID", f"`{member.id}`", True),
                    ("Roles Added", "\n".join(added) if added else "None", False),
                    ("Roles Removed", "\n".join(removed) if removed else "None", False)
                ]
                embeds = make_embeds(
                    banner_url=None,
                    title="🛡️ User Verified",
                    description="Member verified successfully.",
                    color=0x00ff00,
                    fields=fields,
                    thumbnail=LOGO_URL
                )
                await log_channel.send(embeds=embeds)


class PersistentPollView(discord.ui.View):
    def __init__(self, bot, message_id, question, options, votes=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.message_id = message_id
        self.question = question
        self.options = options
        self.votes = votes or {}

        for idx in range(len(options)):
            btn = discord.ui.Button(
                label=f"Option {idx + 1}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"poll_{message_id}_{idx}"
            )
            btn.callback = self.make_callback(idx)
            self.add_item(btn)

    def make_callback(self, idx):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            user_id = str(interaction.user.id)
            self.votes[user_id] = idx

            self.bot.db_manager.update_poll_votes(self.message_id, self.votes)

            total_votes = len(self.votes)
            option_counts = [0] * len(self.options)
            for v in self.votes.values():
                option_counts[v] += 1

            embed_content = discord.Embed(
                title=f"📊 Poll: {self.question}",
                description="Vote by clicking the buttons below!\n\n",
                color=0x6366f1
            )
            embed_content.set_thumbnail(url=LOGO_URL)

            for o_idx, option in enumerate(self.options):
                count = option_counts[o_idx]
                pct = (count / total_votes * 100) if total_votes > 0 else 0
                filled = int(pct / 10)
                bar = "█" * filled + "░" * (10 - filled)

                embed_content.add_field(
                    name=f"Option {o_idx + 1}: {option}",
                    value=f"`{bar}`\n{count} votes ({pct:.1f}%)\n\u200b",
                    inline=False
                )

            embed_content.set_footer(text=f"Total votes: {total_votes} | Fenrix Security")

            await interaction.message.edit(embeds=[embed_content], view=self)
            await interaction.followup.send(f"✅ Your vote for **Option {idx + 1}** has been registered!", ephemeral=True)
        return callback


class PersistentGiveawayView(discord.ui.View):
    def __init__(self, bot, message_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.message_id = message_id

    @discord.ui.button(label="Join Giveaway", style=discord.ButtonStyle.blurple, emoji="🎉", custom_id="galaxy_tree_giveaway_btn")
    async def join_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        giveaways = self.bot.db_manager.get_active_giveaways()
        gw = giveaways.get(self.message_id)
        if not gw:
            return await interaction.followup.send("❌ This giveaway is no longer active.", ephemeral=True)

        participants = gw.get("participants", [])
        user_id = str(interaction.user.id)

        if user_id in participants:
            return await interaction.followup.send("❌ You have already joined this giveaway!", ephemeral=True)

        participants.append(user_id)
        gw["participants"] = participants
        self.bot.db_manager.save_giveaway(self.message_id, gw)

        embeds = interaction.message.embeds
        if len(embeds) > 0:
            c_emb = embeds[0]
            for i, field in enumerate(c_emb.fields):
                if field.name == "Participants":
                    c_emb.set_field_at(i, name="Participants", value=f"**{len(participants)}**", inline=True)
                    break
            await interaction.message.edit(embeds=embeds)

        await interaction.followup.send("🎉 You have successfully entered the giveaway!", ephemeral=True)


class ConfirmVerifySetup(discord.ui.View):
    def __init__(self, bot, log_channel, roles_to_add, roles_to_remove, banner_url, admin_interaction):
        super().__init__(timeout=60)
        self.bot = bot
        self.log_channel = log_channel
        self.roles_to_add = roles_to_add
        self.roles_to_remove = roles_to_remove
        self.banner_url = banner_url
        self.admin_interaction = admin_interaction

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            guild_id = interaction.guild_id
            updates = {
                "verify_log_channel": self.log_channel.id,
                "verify_roles_to_add": self.roles_to_add,
                "verify_roles_to_remove": self.roles_to_remove,
                "verify_banner_url": self.banner_url
            }
            self.bot.db_manager.update_guild_config(guild_id, updates)

            embeds = make_embeds(
                banner_url=self.banner_url,
                title="🛡️ Fenrix — Verification Portal",
                description=(
                    "Welcome to the **Fenrix - Elite Security & Management System** verification portal.\n\n"
                    "Please click the button below to verify your account and gain access to the server.\n\n"
                    "*By verifying, you agree to follow the server rules and guidelines.*"
                ),
                color=0x2f3136,
                thumbnail=LOGO_URL
            )
            
            try:
                await interaction.channel.send(embeds=embeds, view=VerificationButtonView(self.bot))
            except discord.errors.Forbidden:
                return await interaction.followup.send(
                    "❌ **Missing Permissions**: The bot cannot send messages in this channel.\n"
                    "Please make sure the bot has **View Channel**, **Send Messages**, and **Embed Links** permissions in this channel.",
                    ephemeral=True
                )

            await interaction.followup.send("✅ Verification portal successfully configured and posted!", ephemeral=True)
            self.stop()
        except Exception as e:
            logger.error(f"Error in ConfirmVerifySetup: {e}")
            await interaction.followup.send(f"❌ An error occurred during setup: {e}", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Setup cancelled.", ephemeral=True)
        self.stop()

# ─────────────────────────────────────────────────────────────────
# BOT CLASS
# ─────────────────────────────────────────────────────────────────

class GalaxyTreeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.db_manager = DatabaseManager()
        self.anti_nuke_tracker = {}
        self.lockdown_active = {}
        self.spam_warn_tracker = {}
        self.spam_reset_tasks = {}
        self.join_tracker = {}

    async def setup_hook(self):
        self.add_view(VerificationButtonView(self))

        active_polls = self.db_manager.get_active_polls()
        for msg_id, data in active_polls.items():
            self.add_view(PersistentPollView(self, msg_id, data["question"], data["options"], data["votes"]))

        active_gws = self.db_manager.get_active_giveaways()
        for msg_id in active_gws.keys():
            self.add_view(PersistentGiveawayView(self, msg_id))

        self.giveaway_loop.start()
        self.graph_loop.start()

        await self.tree.sync()
        logger.info("[SYSTEM] Bot online and synchronized.")

    async def on_ready(self):
        self.start_time = datetime.datetime.utcnow()
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Protecting Fenrix | /help"))
        logger.info(f"[SYSTEM] Logged in as {self.user.name}")

    async def reset_spam_warn(self, user_id):
        await asyncio.sleep(60)
        self.spam_warn_tracker[user_id] = 0

    async def process_anti_nuke_event(self, guild, event_name):
        config = self.db_manager.get_guild_config(guild.id)
        if not config.get("antinuke_enabled", True):
            return

        if self.lockdown_active.get(guild.id, False):
            return

        try:
            async for entry in guild.audit_logs(limit=1):
                executor = entry.user
                break
        except Exception:
            return

        if executor.id == self.user.id or executor.id == guild.owner_id:
            return

        now = time.time()
        if executor.id not in self.anti_nuke_tracker:
            self.anti_nuke_tracker[executor.id] = []

        self.anti_nuke_tracker[executor.id].append(now)
        self.anti_nuke_tracker[executor.id] = [t for t in self.anti_nuke_tracker[executor.id] if now - t <= 5]

        threshold = int(config.get("antinuke_threshold", 5))
        if len(self.anti_nuke_tracker[executor.id]) >= threshold:
            await self.trigger_lockdown(guild, executor)

    async def trigger_lockdown(self, guild, attacker):
        self.lockdown_active[guild.id] = True
        config = self.db_manager.get_guild_config(guild.id)
        action = config.get("antinuke_action", "ban")

        try:
            if action == "ban":
                await guild.ban(attacker, reason="Anti-Nuke: Limit Exceeded")
            elif action == "kick":
                await attacker.kick(reason="Anti-Nuke: Limit Exceeded")
            elif action == "timeout":
                await attacker.timeout(datetime.timedelta(days=7), reason="Anti-Nuke: Limit Exceeded")
            elif action == "strip_roles":
                for role in list(attacker.roles):
                    if role.name != "@everyone" and role < guild.me.top_role:
                        await attacker.remove_roles(role, reason="Anti-Nuke Triggered")
        except Exception as e:
            logger.error(f"Error punishing attacker: {e}")

        try:
            perms = guild.default_role.permissions
            perms.update(
                send_messages=False,
                send_messages_in_threads=False,
                create_public_threads=False,
                create_private_threads=False,
                connect=False
            )
            await guild.default_role.edit(permissions=perms, reason="Anti-Nuke Lockdown")
        except Exception as e:
            logger.error(f"Error putting server in lockdown: {e}")

        log_ch_id = config.get("verify_log_channel")
        log_channel = guild.get_channel(int(log_ch_id)) if log_ch_id else None

        fields = [
            ("Attacker", f"{attacker.mention}\n({attacker.name})\n", True),
            ("Attacker ID", f"`{attacker.id}`\n", True),
            ("Action Details", f"Anti-Nuke triggered:\nChannel/Role/Join activity threshold exceeded.\n", False),
            ("Defensive Measures", f"• Attacker punished ({action}).\n• Guild default role locked down.\n• Security alert broadcasted.\n", False)
        ]

        embeds = make_embeds(
            banner_url=None,
            title="🚨 EMERGENCY LOCKDOWN ACTIVATED",
            description="A high-velocity guild alteration attack has been detected and auto-defended.",
            color=0xff0000,
            fields=fields,
            thumbnail=LOGO_URL
        )

        if log_channel:
            await log_channel.send(content="@here ⚠️ **ATTACK DETECTED**", embeds=embeds)
        else:
            target = guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
            if target:
                await target.send(content="@here ⚠️ **ATTACK DETECTED**", embeds=embeds)

        self.loop.create_task(self.dm_all_members(guild, attacker))

    async def trigger_raid_lockdown(self, guild):
        if self.lockdown_active.get(guild.id, False):
            return
        self.lockdown_active[guild.id] = True

        try:
            perms = guild.default_role.permissions
            perms.update(
                send_messages=False,
                send_messages_in_threads=False,
                create_public_threads=False,
                create_private_threads=False,
                connect=False
            )
            await guild.default_role.edit(permissions=perms, reason="Anti-Raid Lockdown")
        except Exception as e:
            logger.error(f"Error setting default role permissions in anti-raid: {e}")

        config = self.db_manager.get_guild_config(guild.id)
        log_ch_id = config.get("verify_log_channel")
        log_channel = guild.get_channel(int(log_ch_id)) if log_ch_id else None

        embeds = make_embeds(
            banner_url=None,
            title="🚨 ANTI-RAID ACTIVATED",
            description="A high rate of member joins has been detected. The server has been locked down.",
            color=0xff5500,
            fields=[
                ("Join Threshold", f"{len(self.join_tracker[guild.id])} members joined", True),
                ("Status", "Server default role is locked down to read-only.", False)
            ],
            thumbnail=LOGO_URL
        )
        if log_channel:
            await log_channel.send(content="@here ⚠️ **RAID DETECTED**", embeds=embeds)

        self.loop.create_task(self.dm_all_members(guild, attacker))

    async def dm_all_members(self, guild, attacker):
        for member in guild.members:
            if member.bot:
                continue
            try:
                await member.send(
                    f"⚠️ **SECURITY WARNING**: A potential attack was detected on server **{guild.name}** by user {attacker.name} ({attacker.id}).\n\n"
                    f"The server is currently locked down. We highly recommend enabling 2FA (Two-Factor Authentication) immediately to protect your account."
                )
                await asyncio.sleep(0.5)
            except Exception:
                pass

    @tasks.loop(seconds=10)
    async def giveaway_loop(self):
        active_gws = self.db_manager.get_active_giveaways()
        now_ts = time.time()
        for msg_id, gw in list(active_gws.items()):
            if gw.get("end_time", 0) <= now_ts:
                gw["ended"] = True
                self.db_manager.save_giveaway(msg_id, gw)

                guild = self.get_guild(gw.get("guild_id"))
                if not guild:
                    continue
                channel = guild.get_channel(gw.get("channel_id"))
                if not channel:
                    continue

                try:
                    message = await channel.fetch_message(int(msg_id))
                except Exception:
                    continue

                participants = gw.get("participants", [])
                winners_count = gw.get("winners_count", 1)
                prize = gw.get("prize", "Unknown Prize")

                if not participants:
                    embed_content = discord.Embed(
                        title=f"🎉 Giveaway Ended: {prize}",
                        description="No one entered the giveaway.\n\n",
                        color=0xff0000
                    )
                    embed_content.set_thumbnail(url=LOGO_URL)
                    embed_content.set_footer(text="Fenrix Security")
                    await message.edit(embeds=[embed_content], view=None)
                    await channel.send(f"⚠️ The giveaway for **{prize}** ended, but there were no entries.")
                    continue

                winners_ids = []
                pool = list(participants)
                for _ in range(min(winners_count, len(pool))):
                    chosen = random.choice(pool)
                    pool.remove(chosen)
                    winners_ids.append(int(chosen))

                winners_mentions = [f"<@{uid}>" for uid in winners_ids]

                embed_content = discord.Embed(
                    title=f"🎉 Giveaway Ended: {prize}",
                    description=f"Winners:\n{', '.join(winners_mentions)}\n\n",
                    color=0x00ff00
                )
                embed_content.set_thumbnail(url=LOGO_URL)
                embed_content.set_footer(text="Fenrix Security")

                await message.edit(embeds=[embed_content], view=None)
                await channel.send(f"🎉 Congratulations to {', '.join(winners_mentions)} for winning **{prize}**!")

                for uid in winners_ids:
                    member = guild.get_member(uid)
                    if member:
                        try:
                            await member.send(
                                f"🎉 **Giveaway Winner** 🎉\n\n"
                                f"You won the giveaway for **{prize}** in **{guild.name}**!\n\n"
                                f"Please open a ticket within 48 hours to claim your prize."
                            )
                        except Exception:
                            pass

    @tasks.loop(seconds=30)
    async def graph_loop(self):
        now = datetime.datetime.now()
        if not hasattr(self, "last_graph_post_hour"):
            self.last_graph_post_hour = ""

        current_hour_key = now.strftime("%Y-%m-%d-%H")
        if now.hour in [1, 8] and now.minute == 0 and self.last_graph_post_hour != current_hour_key:
            self.last_graph_post_hour = current_hour_key
            for guild in self.guilds:
                config = self.db_manager.get_guild_config(guild.id)
                log_ch_id = config.get("verify_log_channel")
                if log_ch_id:
                    channel = guild.get_channel(int(log_ch_id))
                    if channel:
                        try:
                            embeds = await generate_status_embeds(self, guild)
                            await channel.send(embeds=embeds)
                        except Exception as e:
                            logger.error(f"Error posting scheduled activity graph: {e}")


bot = GalaxyTreeBot()

@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Unwrap CommandInvokeError
    if isinstance(error, app_commands.CommandInvokeError):
        error = error.original

    logger.error(f"[COMMAND ERROR] Command failed: {error}")
    
    # Check if interaction has already been responded to
    if interaction.response.is_done():
        send_func = interaction.followup.send
    else:
        send_func = interaction.response.send_message

    err_msg = str(error).lower()
    
    if "membernotfound" in err_msg or "usernotfound" in err_msg or "user not found" in err_msg:
        try:
            await send_func("❌ **Error**: Discord user or member not found. Please verify the ID or mention.", ephemeral=True)
        except Exception:
            pass
    elif "missing permissions" in err_msg:
        try:
            await send_func("❌ **Error**: The bot is missing required permissions to perform this action (check role hierarchy).", ephemeral=True)
        except Exception:
            pass
    else:
        try:
            await send_func(f"❌ **Error**: {error}", ephemeral=True)
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────────
# STATUS GENERATOR
# ─────────────────────────────────────────────────────────────────

async def generate_status_embeds(bot, guild):
    activity = bot.db_manager.get_activity_data(guild.id) or {}
    hours_labels = []
    values = []
    now_utc = datetime.datetime.utcnow()

    for i in range(23, -1, -1):
        dt = now_utc - datetime.timedelta(hours=i)
        key = dt.strftime("%Y-%m-%d-%H")
        label = dt.strftime("%H:00")
        hours_labels.append(label)
        values.append(activity.get(key, 0))

    chart_config = {
        "type": "line",
        "data": {
            "labels": hours_labels,
            "datasets": [{
                "label": "Fenrix Security Events",
                "data": values,
                "fill": True,
                "backgroundColor": "rgba(99, 102, 241, 0.2)",
                "borderColor": "rgba(99, 102, 241, 1)",
                "borderWidth": 3,
                "pointBackgroundColor": "rgba(99, 102, 241, 1)",
                "tension": 0.4
            }]
        },
        "options": {
            "legend": {
                "labels": {
                    "fontColor": "white",
                    "fontSize": 12
                }
            },
            "scales": {
                "yAxes": [{
                    "gridLines": {"color": "rgba(255, 255, 255, 0.1)"},
                    "ticks": {"fontColor": "white", "beginAtZero": True}
                }],
                "xAxes": [{
                    "gridLines": {"color": "rgba(255, 255, 255, 0.1)"},
                    "ticks": {"fontColor": "white"}
                }]
            }
        }
    }
    encoded_config = urllib.parse.quote(json.dumps(chart_config))
    graph_url = f"https://quickchart.io/chart?c={encoded_config}&w=600&h=300&bkg=rgb(24,24,27)"

    if not hasattr(bot, "start_time"):
        bot.start_time = datetime.datetime.utcnow()
    uptime_duration = datetime.datetime.utcnow() - bot.start_time
    hours, remainder = divmod(int(uptime_duration.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"**{uptime_duration.days}d {hours}h {minutes}m {seconds}s**"

    ping = round(bot.latency * 1000)

    fields = [
        ("Uptime", f"{uptime_str}\n\u200b", True),
        ("Latency", f"**{ping}ms**\n\u200b", True),
        ("Guild Members", f"**{guild.member_count}**\n\u200b", True),
        ("Event Log Time", f"**{now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}**\n\u200b", False)
    ]

    embeds = make_embeds(
        banner_url=graph_url,
        title="📈 Fenrix Daily Activity & Status",
        description="Daily security metrics and activity log chart.\n\n",
        color=0x6366f1,
        fields=fields,
        thumbnail=LOGO_URL
    )
    return embeds

# ─────────────────────────────────────────────────────────────────
# DISCORD EVENTS
# ─────────────────────────────────────────────────────────────────

@bot.event
async def on_guild_channel_create(channel):
    bot.db_manager.log_activity(channel.guild.id)
    await bot.process_anti_nuke_event(channel.guild, "channel_create")

@bot.event
async def on_guild_channel_delete(channel):
    bot.db_manager.log_activity(channel.guild.id)
    await bot.process_anti_nuke_event(channel.guild, "channel_delete")

@bot.event
async def on_guild_role_create(role):
    bot.db_manager.log_activity(role.guild.id)
    await bot.process_anti_nuke_event(role.guild, "role_create")

@bot.event
async def on_guild_role_delete(role):
    bot.db_manager.log_activity(role.guild.id)
    await bot.process_anti_nuke_event(role.guild, "role_delete")

@bot.event
async def on_guild_role_update(before, after):
    config = bot.db_manager.get_guild_config(after.guild.id)
    if config.get("antirole_enabled", True):
        bot.db_manager.log_activity(after.guild.id)
        await bot.process_anti_nuke_event(after.guild, "role_update")

@bot.event
async def on_guild_channel_update(before, after):
    config = bot.db_manager.get_guild_config(after.guild.id)
    if config.get("antichannel_enabled", True):
        bot.db_manager.log_activity(after.guild.id)
        await bot.process_anti_nuke_event(after.guild, "channel_update")

@bot.event
async def on_member_join(member):
    bot.db_manager.log_activity(member.guild.id)
    config = bot.db_manager.get_guild_config(member.guild.id)

    # Anti-Raid check
    if config.get("antiraid_enabled", False):
        now = time.time()
        guild_id = member.guild.id
        if guild_id not in bot.join_tracker:
            bot.join_tracker[guild_id] = []
        bot.join_tracker[guild_id].append(now)
        window = int(config.get("antiraid_time_threshold", 10))
        bot.join_tracker[guild_id] = [t for t in bot.join_tracker[guild_id] if now - t <= window]

        limit = int(config.get("antiraid_joins_threshold", 5))
        if len(bot.join_tracker[guild_id]) >= limit:
            await bot.trigger_raid_lockdown(member.guild)
            return

    if config and config.get("welcome_channel"):
        ch = member.guild.get_channel(int(config["welcome_channel"]))
        if ch:
            banner = config.get("welcome_banner_url") or None
            text = config.get("welcome_text") or "Welcome to the server!"
            text = text.replace("{member}", member.mention).replace("{user}", member.name)

            embeds = make_embeds(
                banner_url=banner,
                title="👋 Member Joined",
                description=f"{text}\n\n",
                color=0x00ffcc,
                thumbnail=member.display_avatar.url
            )
            await ch.send(content=member.mention, embeds=embeds)

@bot.event
async def on_member_remove(member):
    bot.db_manager.log_activity(member.guild.id)
    config = bot.db_manager.get_guild_config(member.guild.id)
    if config and config.get("leave_channel"):
        ch = member.guild.get_channel(int(config["leave_channel"]))
        if ch:
            banner = config.get("leave_banner_url") or None
            text = config.get("leave_text") or "Has left the server."
            text = text.replace("{member}", member.mention).replace("{user}", member.name)

            embeds = make_embeds(
                banner_url=banner,
                title="🛫 Member Left",
                description=f"{text}\n\n",
                color=0xff4444,
                thumbnail=member.display_avatar.url
            )
            await ch.send(embeds=embeds)

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.guild:
        bot.db_manager.log_activity(message.guild.id)
        config = bot.db_manager.get_guild_config(message.guild.id)

        # Anti-Profanity
        if config.get("antiprofanity_enabled", True):
            if check_blasphemy(message.content):
                is_staff_user = message.author.guild_permissions.administrator or message.author.id == message.guild.owner_id
                if not is_staff_user:
                    try:
                        await message.delete()
                        action = config.get("antiprofanity_action", "timeout")
                        duration = int(config.get("antiprofanity_duration", 2700))
                        
                        if action == "timeout":
                            await message.author.timeout(datetime.timedelta(seconds=duration), reason="Blasphemy/Profanity Protection")
                            msg = await message.channel.send(f"🚫 {message.author.mention} has been timed out for {duration // 60} minutes for blasphemy/profanity.")
                        elif action == "kick":
                            await message.author.kick(reason="Blasphemy/Profanity Protection")
                            msg = await message.channel.send(f"🚫 {message.author.mention} has been kicked for blasphemy/profanity.")
                        elif action == "ban":
                            await message.guild.ban(message.author, reason="Blasphemy/Profanity Protection")
                            msg = await message.channel.send(f"🚫 {message.author.mention} has been banned for blasphemy/profanity.")
                        else:  # Just delete
                            msg = await message.channel.send(f"🚫 {message.author.mention}, please avoid profanity.")
                            
                        await asyncio.sleep(10)
                        await msg.delete()
                    except Exception as e:
                        logger.error(f"Error handling blasphemy: {e}")
                    return

        # Anti-Spam / Anti-Link
        if config.get("antilink_enabled", False) or config.get("antispam_enabled", False):
            if re.search(r"https?://[^\s]+|www\.[^\s]+", message.content):
                is_staff_user = message.author.guild_permissions.administrator or message.author.id == message.guild.owner_id
                allowed_roles = [int(rid) for rid in config.get("mod_allowed_roles", [])]
                has_mod_role = any(role.id in allowed_roles for role in message.author.roles)

                if not is_staff_user and not has_mod_role:
                    try:
                        await message.delete()
                        action = config.get("antilink_action", "timeout")
                        
                        if action == "timeout":
                            user_id = str(message.author.id)
                            warn_count = bot.spam_warn_tracker.get(user_id, 0)

                            if warn_count == 0:
                                bot.spam_warn_tracker[user_id] = 1
                                if user_id in bot.spam_reset_tasks:
                                    bot.spam_reset_tasks[user_id].cancel()
                                bot.spam_reset_tasks[user_id] = bot.loop.create_task(bot.reset_spam_warn(user_id))

                                msg = await message.channel.send(f"⚠️ {message.author.mention}, posting links is prohibited! Repeat offenses will result in a timeout.")
                                await asyncio.sleep(5)
                                await msg.delete()
                            else:
                                await message.author.timeout(datetime.timedelta(minutes=10), reason="Anti-Spam Link Protection")
                                msg = await message.channel.send(f"🚫 {message.author.mention} has been timed out for 10 minutes for posting links.")
                                await asyncio.sleep(10)
                                await msg.delete()
                        elif action == "kick":
                            await message.author.kick(reason="Anti-Spam Link Protection")
                            msg = await message.channel.send(f"🚫 {message.author.mention} has been kicked for posting links.")
                            await asyncio.sleep(10)
                            await msg.delete()
                        elif action == "ban":
                            await message.guild.ban(message.author, reason="Anti-Spam Link Protection")
                            msg = await message.channel.send(f"🚫 {message.author.mention} has been banned for posting links.")
                            await asyncio.sleep(10)
                            await msg.delete()
                        else:  # Just delete
                            msg = await message.channel.send(f"🚫 {message.author.mention}, posting links is prohibited.")
                            await asyncio.sleep(5)
                            await msg.delete()
                    except Exception as e:
                        logger.error(f"Error handling anti-spam link: {e}")
                    return

    await bot.process_commands(message)

# ─────────────────────────────────────────────────────────────────
# PERMISSION HELPERS
# ─────────────────────────────────────────────────────────────────

def is_owner_or_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.id == interaction.guild.owner_id:
        return True
    return interaction.user.guild_permissions.administrator

def is_staff(interaction: discord.Interaction) -> bool:
    if is_owner_or_admin(interaction):
        return True
    config = bot.db_manager.get_guild_config(interaction.guild_id)
    allowed_roles = [int(rid) for rid in config.get("mod_allowed_roles", [])]
    return any(role.id in allowed_roles for role in interaction.user.roles)

async def check_staff_interaction(interaction: discord.Interaction):
    if is_staff(interaction):
        return True
    await interaction.response.send_message("❌ Access Denied: You do not have the required moderator roles/permissions.", ephemeral=True)
    return False

# ─────────────────────────────────────────────────────────────────
# SETUP COMMAND GROUP  (Owner / Administrator)
# /setup verify | /setup welcome | /setup leave | /setup staff
# ─────────────────────────────────────────────────────────────────

setup_group = app_commands.Group(name="setup", description="Server configuration commands (Owner Only)")
bot.tree.add_command(setup_group)


@setup_group.command(name="verify", description="Setup interactive server verification portal")
@app_commands.describe(
    log_channel="Channel where verification logs will be sent",
    roles_to_add="Roles to grant after verification (comma-separated names/IDs)",
    roles_to_remove="Roles to remove after verification (comma-separated names/IDs)",
    banner_url="Custom verification banner image URL"
)
async def setup_verify(
    interaction: discord.Interaction,
    log_channel: discord.TextChannel,
    roles_to_add: str,
    roles_to_remove: str,
    banner_url: str = BANNER_VERIFY_URL
):
    if not is_owner_or_admin(interaction):
        return await interaction.response.send_message("❌ Access Denied: Administrator required.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    add_ids = parse_roles(interaction.guild, roles_to_add)
    rem_ids = parse_roles(interaction.guild, roles_to_remove)

    if not add_ids and not rem_ids:
        return await interaction.followup.send("❌ Error: Could not resolve roles from input.", ephemeral=True)

    add_mentions = [f"<@&{rid}>" for rid in add_ids]
    rem_mentions = [f"<@&{rid}>" for rid in rem_ids]

    fields = [
        ("Log Channel", f"{log_channel.mention}\n\u200b", True),
        ("Roles to Add", f"{', '.join(add_mentions) if add_mentions else 'None'}\n\u200b", False),
        ("Roles to Remove", f"{', '.join(rem_mentions) if rem_mentions else 'None'}\n\u200b", False),
        ("Banner URL", f"{banner_url}\n\u200b", False)
    ]

    embeds = make_embeds(
        banner_url=BANNER_VERIFY_URL,
        title="🛠️ Verification Portal — Configuration Summary",
        description="Verify the configuration details below before activating.\n\n",
        color=0x2f3136,
        fields=fields,
        thumbnail=LOGO_URL
    )

    view = ConfirmVerifySetup(bot, log_channel, add_ids, rem_ids, banner_url, interaction)
    await interaction.followup.send(content="Confirm settings below:", embeds=embeds, view=view, ephemeral=True)


@setup_group.command(name="welcome", description="Setup welcome message channel and text")
@app_commands.describe(
    channel="Welcome channel",
    text="Welcome message text (use {member} or {user} as placeholders)",
    banner_url="Top banner URL for welcome embeds (leave blank for no banner)"
)
async def setup_welcome(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    text: str,
    banner_url: str = ""
):
    if not is_owner_or_admin(interaction):
        return await interaction.response.send_message("❌ Access Denied: Administrator required.", ephemeral=True)

    bot.db_manager.update_guild_config(interaction.guild_id, {
        "welcome_channel": channel.id,
        "welcome_text": text,
        "welcome_banner_url": banner_url if banner_url else None
    })
    await interaction.response.send_message(f"✅ Welcome settings saved! Messages will be posted in {channel.mention}.", ephemeral=True)


@setup_group.command(name="leave", description="Setup member leave channel and text")
@app_commands.describe(
    channel="Leave channel",
    text="Leave message text (use {member} or {user} as placeholders)",
    banner_url="Top banner URL for leave embeds (leave blank for no banner)"
)
async def setup_leave(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    text: str,
    banner_url: str = ""
):
    if not is_owner_or_admin(interaction):
        return await interaction.response.send_message("❌ Access Denied: Administrator required.", ephemeral=True)

    bot.db_manager.update_guild_config(interaction.guild_id, {
        "leave_channel": channel.id,
        "leave_text": text,
        "leave_banner_url": banner_url if banner_url else None
    })
    await interaction.response.send_message(f"✅ Leave settings saved! Messages will be posted in {channel.mention}.", ephemeral=True)


@setup_group.command(name="staff", description="Configure roles authorized to use moderator commands")
@app_commands.describe(roles="Authorized staff roles (comma-separated names/IDs)")
async def setup_staff(interaction: discord.Interaction, roles: str):
    if not is_owner_or_admin(interaction):
        return await interaction.response.send_message("❌ Access Denied: Administrator required.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    role_ids = parse_roles(interaction.guild, roles)

    if not role_ids:
        return await interaction.followup.send("❌ Error: No valid roles resolved.", ephemeral=True)

    bot.db_manager.update_guild_config(interaction.guild_id, {"mod_allowed_roles": role_ids})
    mentions = [f"<@&{rid}>" for rid in role_ids]
    await interaction.followup.send(f"✅ Authorized staff roles configured: {', '.join(mentions)}", ephemeral=True)

# ─────────────────────────────────────────────────────────────────
# SECURITY FILTER COMMANDS
# ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="enableantispam", description="Enable anti-spam link protection filter")
async def enableantispam(interaction: discord.Interaction):
    if not is_owner_or_admin(interaction):
        return await interaction.response.send_message("❌ Access Denied: Administrator required.", ephemeral=True)

    bot.db_manager.update_guild_config(interaction.guild_id, {"antispam_enabled": True})
    await interaction.response.send_message("✅ Anti-Spam Link Protection is now **ENABLED**.", ephemeral=True)


@bot.tree.command(name="disableantispam", description="Disable anti-spam link protection filter")
async def disableantispam(interaction: discord.Interaction):
    if not is_owner_or_admin(interaction):
        return await interaction.response.send_message("❌ Access Denied: Administrator required.", ephemeral=True)

    bot.db_manager.update_guild_config(interaction.guild_id, {"antispam_enabled": False})
    await interaction.response.send_message("✅ Anti-Spam Link Protection is now **DISABLED**.", ephemeral=True)

# ─────────────────────────────────────────────────────────────────
# INFORMATION COMMANDS
# ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="infobot", description="Display system information about Fenrix")
async def infobot(interaction: discord.Interaction):
    fields = [
        ("Developer", "Fenrix Core Team\n\u200b", True),
        ("Support", f"[Join Support Server]({SUPPORT_LINK})\n\u200b", True),
        ("Description", "Automated real-time security, verification gateways, link spam blocking, and activity reporting.\n\u200b", False)
    ]
    embeds = make_embeds(
        banner_url=BANNER_INFO_URL,
        title="🤖 Fenrix — Elite Security & Management System",
        description="Free elite server security, robust verification gateways, and real-time moderation monitoring.\n\n",
        color=0x2f3136,
        fields=fields,
        thumbnail=LOGO_URL
    )
    await interaction.response.send_message(embeds=embeds)


@bot.tree.command(name="help", description="List all available commands and system usage instructions")
async def help_cmd(interaction: discord.Interaction):
    fields = [
        ("🛡️ Public Commands", "• `/infobot` — System features\n• `/infoserver` — Server metrics\n• `/infouser` — User details\n• `/inforoblox` — Roblox lookup\n• `/help` — Show command guide\n\u200b", False),
        ("🔨 Staff Moderation", "• `/ban` — Ban users\n• `/kick` — Kick member\n• `/unban` — Remove ban\n• `/timeout` — Restrict users\n• `/untimeout` — Lift timeout\n\u200b", False),
        ("⚙️ Security Filters", "• `/enableantispam` — Activate link blocker\n• `/disableantispam` — Disable link blocker\n\u200b", False),
        ("🛠️ Configuration (Owner)", "• `/setup verify` — Configure verification portal\n• `/setup welcome` — Configure welcome messages\n• `/setup leave` — Configure farewell messages\n• `/setup staff` — Set authorized staff roles\n\u200b", False),
        ("📊 Utilities & Graphs", "• `/statusbot` — View daily metrics & graph\n• `/poll` — Launch interactive voting poll\n• `/giveaway` — Schedule a giveaway\n\u200b", False)
    ]
    embeds = make_embeds(
        banner_url=BANNER_INFO_URL,
        title="📖 Fenrix — Help Manual",
        description="System instruction manual. Visit our support server for assistance.\n\n",
        color=0x2f3136,
        fields=fields,
        thumbnail=LOGO_URL
    )
    await interaction.response.send_message(embeds=embeds)


@bot.tree.command(name="infoserver", description="Display details and statistics about the current server")
async def infoserver(interaction: discord.Interaction):
    guild = interaction.guild
    fields = [
        ("Owner", f"<@{guild.owner_id}>\n\u200b", True),
        ("Total Members", f"**{guild.member_count}**\n\u200b", True),
        ("Boost Level", f"**{guild.premium_subscription_count}** boosts (Tier {guild.premium_tier})\n\u200b", True),
        ("Text Channels", f"**{len(guild.text_channels)}**\n\u200b", True),
        ("Voice Channels", f"**{len(guild.voice_channels)}**\n\u200b", True),
        ("Total Roles", f"**{len(guild.roles)}**\n\u200b", True),
        ("Creation Date", f"<t:{int(guild.created_at.timestamp())}:D>\n\u200b", False)
    ]
    embeds = make_embeds(
        banner_url=None,
        title=f"🏰 Server Information — {guild.name}",
        description="Public metadata and metrics for the current server.\n\n",
        color=0x2f3136,
        fields=fields,
        thumbnail=LOGO_URL
    )
    await interaction.response.send_message(embeds=embeds)


@bot.tree.command(name="infouser", description="Display details about a specific server member")
@app_commands.describe(member="Member to lookup (leave blank for yourself)")
async def infouser(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    roles = [role.mention for role in member.roles if role.name != "@everyone"]
    fields = [
        ("Display Name", f"**{member.display_name}**\n\u200b", True),
        ("Account ID", f"`{member.id}`\n\u200b", True),
        ("Created On", f"<t:{int(member.created_at.timestamp())}:D>\n\u200b", True),
        ("Joined Server", f"<t:{int(member.joined_at.timestamp())}:D>\n\u200b", True),
        ("Profile Link", f"[View Profile](https://discord.com/users/{member.id})\n\u200b", True),
        ("Roles", ", ".join(roles) if roles else "None", False)
    ]
    embeds = make_embeds(
        banner_url=None,
        title=f"👤 Member Information — {member.name}",
        description=f"Public profile details for {member.mention}.\n\n",
        color=0x2f3136,
        fields=fields,
        thumbnail=member.display_avatar.url
    )
    await interaction.response.send_message(embeds=embeds)


@bot.tree.command(name="inforoblox", description="Search for a Roblox player by their username")
@app_commands.describe(username="Roblox username to search")
async def inforoblox(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    info = get_roblox_user_info(username)
    if not info:
        return await interaction.followup.send("❌ Roblox user not found. Please verify the spelling.")

    fields = [
        ("Username", f"**{info['name']}**\n\u200b", True),
        ("Display Name", f"**{info['displayName']}**\n\u200b", True),
        ("User ID", f"`{info['id']}`\n\u200b", True),
        ("Profile Link", f"[Visit Profile]({info['profile_url']})\n\u200b", True),
        ("Account Created", f"**{info['created'][:10] if info['created'] else 'Unknown'}**\n\u200b", True),
        ("Description", f"{info['description']}\n\u200b", False)
    ]
    embeds = make_embeds(
        banner_url=None,
        title=f"🕹️ Roblox Profile — {info['name']}",
        description="Metadata retrieved from the Roblox Public API.\n\n",
        color=0x2f3136,
        fields=fields,
        thumbnail=info["avatar_url"] or LOGO_URL
    )
    await interaction.followup.send(embeds=embeds)

# ─────────────────────────────────────────────────────────────────
# MODERATION COMMANDS
# ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="ban", description="Ban a user from the server")
@app_commands.describe(user="User to ban (ID or mention)", reason="Reason for ban")
async def ban_cmd(interaction: discord.Interaction, user: discord.User, reason: str = "No reason provided"):
    if not await check_staff_interaction(interaction):
        return

    await interaction.response.defer()
    try:
        await interaction.guild.ban(user, reason=f"Banned by {interaction.user.name}: {reason}")

        fields = [
            ("Target User", f"{user.name} (`{user.id}`)\n\u200b", True),
            ("Moderator", f"{interaction.user.mention}\n\u200b", True),
            ("Reason", f"{reason}\n\u200b", False)
        ]
        embeds = make_embeds(
            banner_url=None,
            title="🔨 User Banned",
            description="Moderator audit log updated.\n\n",
            color=0xff0000,
            fields=fields,
            thumbnail=LOGO_URL
        )
        await interaction.followup.send(embeds=embeds)

        config = bot.db_manager.get_guild_config(interaction.guild_id)
        log_ch_id = config.get("verify_log_channel")
        if log_ch_id:
            channel = interaction.guild.get_channel(int(log_ch_id))
            if channel:
                await channel.send(embeds=embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to ban user: {e}", ephemeral=True)


@bot.tree.command(name="unban", description="Revoke a server ban by user ID")
@app_commands.describe(user_id="Numeric ID of the user to unban", reason="Reason for unban")
async def unban_cmd(interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
    if not await check_staff_interaction(interaction):
        return

    await interaction.response.defer()
    try:
        uid = int(user_id.strip())
        await interaction.guild.unban(discord.Object(id=uid), reason=f"Unbanned by {interaction.user.name}: {reason}")

        fields = [
            ("Target User ID", f"`{uid}`\n\u200b", True),
            ("Moderator", f"{interaction.user.mention}\n\u200b", True),
            ("Reason", f"{reason}\n\u200b", False)
        ]
        embeds = make_embeds(
            banner_url=None,
            title="🔓 User Unbanned",
            description="Moderator audit log updated.\n\n",
            color=0x00ff00,
            fields=fields,
            thumbnail=LOGO_URL
        )
        await interaction.followup.send(embeds=embeds)

        config = bot.db_manager.get_guild_config(interaction.guild_id)
        log_ch_id = config.get("verify_log_channel")
        if log_ch_id:
            channel = interaction.guild.get_channel(int(log_ch_id))
            if channel:
                await channel.send(embeds=embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to unban user ID: {e}", ephemeral=True)


@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="Member to kick", reason="Reason for kick")
async def kick_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await check_staff_interaction(interaction):
        return

    await interaction.response.defer()
    try:
        await member.kick(reason=f"Kicked by {interaction.user.name}: {reason}")

        fields = [
            ("Target Member", f"{member.name} (`{member.id}`)\n\u200b", True),
            ("Moderator", f"{interaction.user.mention}\n\u200b", True),
            ("Reason", f"{reason}\n\u200b", False)
        ]
        embeds = make_embeds(
            banner_url=None,
            title="👢 Member Kicked",
            description="Moderator audit log updated.\n\n",
            color=0xffaa00,
            fields=fields,
            thumbnail=LOGO_URL
        )
        await interaction.followup.send(embeds=embeds)

        config = bot.db_manager.get_guild_config(interaction.guild_id)
        log_ch_id = config.get("verify_log_channel")
        if log_ch_id:
            channel = interaction.guild.get_channel(int(log_ch_id))
            if channel:
                await channel.send(embeds=embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to kick member: {e}", ephemeral=True)


@bot.tree.command(name="timeout", description="Apply communication restriction on a server member")
@app_commands.describe(member="Member to timeout", duration="Duration of restriction", reason="Reason for timeout")
@app_commands.choices(duration=[
    app_commands.Choice(name="5 Minutes", value=300),
    app_commands.Choice(name="10 Minutes", value=600),
    app_commands.Choice(name="1 Hour", value=3600),
    app_commands.Choice(name="6 Hours", value=21600),
    app_commands.Choice(name="10 Hours", value=36000),
    app_commands.Choice(name="1 Day", value=86400),
    app_commands.Choice(name="2 Days", value=172800),
    app_commands.Choice(name="3 Days", value=259200),
    app_commands.Choice(name="4 Days", value=345600),
    app_commands.Choice(name="5 Days", value=432000),
    app_commands.Choice(name="6 Days", value=518400),
    app_commands.Choice(name="7 Days", value=604800)
])
async def timeout_cmd(
    interaction: discord.Interaction,
    member: discord.Member,
    duration: app_commands.Choice[int],
    reason: str = "No reason provided"
):
    if not await check_staff_interaction(interaction):
        return

    await interaction.response.defer()
    try:
        td = datetime.timedelta(seconds=duration.value)
        await member.timeout(td, reason=f"Timed out by {interaction.user.name}: {reason}")

        fields = [
            ("Target Member", f"{member.name} (`{member.id}`)\n\u200b", True),
            ("Moderator", f"{interaction.user.mention}\n\u200b", True),
            ("Duration", f"**{duration.name}**\n\u200b", True),
            ("Reason", f"{reason}\n\u200b", False)
        ]
        embeds = make_embeds(
            banner_url=None,
            title="🚫 Member Timed Out",
            description="Moderator audit log updated.\n\n",
            color=0xff5500,
            fields=fields,
            thumbnail=LOGO_URL
        )
        await interaction.followup.send(embeds=embeds)

        config = bot.db_manager.get_guild_config(interaction.guild_id)
        log_ch_id = config.get("verify_log_channel")
        if log_ch_id:
            channel = interaction.guild.get_channel(int(log_ch_id))
            if channel:
                await channel.send(embeds=embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to timeout member: {e}", ephemeral=True)


@bot.tree.command(name="untimeout", description="Remove communication restriction from a server member")
@app_commands.describe(member="Member to untimeout", reason="Reason for removing restriction")
async def untimeout_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await check_staff_interaction(interaction):
        return

    await interaction.response.defer()
    try:
        await member.timeout(None, reason=f"Timeout removed by {interaction.user.name}: {reason}")

        fields = [
            ("Target Member", f"{member.name} (`{member.id}`)\n\u200b", True),
            ("Moderator", f"{interaction.user.mention}\n\u200b", True),
            ("Reason", f"{reason}\n\u200b", False)
        ]
        embeds = make_embeds(
            banner_url=None,
            title="🔊 Member Timeout Removed",
            description="Moderator audit log updated.\n\n",
            color=0x00ff00,
            fields=fields,
            thumbnail=LOGO_URL
        )
        await interaction.followup.send(embeds=embeds)

        config = bot.db_manager.get_guild_config(interaction.guild_id)
        log_ch_id = config.get("verify_log_channel")
        if log_ch_id:
            channel = interaction.guild.get_channel(int(log_ch_id))
            if channel:
                await channel.send(embeds=embeds)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to remove timeout: {e}", ephemeral=True)

# ─────────────────────────────────────────────────────────────────
# UTILITY COMMANDS
# ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="statusbot", description="Display real-time statistics and 24-hour activity graph")
async def statusbot(interaction: discord.Interaction):
    await interaction.response.defer()
    embeds = await generate_status_embeds(bot, interaction.guild)
    await interaction.followup.send(embeds=embeds)


@bot.tree.command(name="poll", description="Launch an interactive voting poll with up to 10 options")
@app_commands.describe(
    question="The topic or question of the poll",
    opt1="First option", opt2="Second option", opt3="Third option (optional)",
    opt4="Fourth option (optional)", opt5="Fifth option (optional)",
    opt6="Sixth option (optional)", opt7="Seventh option (optional)",
    opt8="Eighth option (optional)", opt9="Ninth option (optional)",
    opt10="Tenth option (optional)"
)
async def poll_cmd(
    interaction: discord.Interaction,
    question: str, opt1: str, opt2: str,
    opt3: str = None, opt4: str = None, opt5: str = None,
    opt6: str = None, opt7: str = None, opt8: str = None,
    opt9: str = None, opt10: str = None
):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Access Denied: Staff role required to start polls.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    raw_opts = [opt1, opt2, opt3, opt4, opt5, opt6, opt7, opt8, opt9, opt10]
    options = [o.strip() for o in raw_opts if o and o.strip()]

    if len(options) < 2:
        return await interaction.followup.send("❌ Error: You must supply at least 2 options for a poll.", ephemeral=True)

    embed_content = discord.Embed(
        title=f"📊 Poll — {question}",
        description="Vote by clicking the buttons below!\n\n",
        color=0x6366f1
    )
    embed_content.set_thumbnail(url=LOGO_URL)

    for idx, opt in enumerate(options):
        embed_content.add_field(
            name=f"Option {idx + 1}: {opt}",
            value="`░░░░░░░░░░` 0 votes (0.0%)\n\u200b",
            inline=False
        )
    embed_content.set_footer(text="Total votes: 0 | Fenrix Security")

    msg = await interaction.channel.send(embeds=[embed_content])
    bot.db_manager.save_poll(str(msg.id), question, options, {})

    view = PersistentPollView(bot, str(msg.id), question, options, {})
    await msg.edit(view=view)

    await interaction.followup.send(f"✅ Poll created successfully! (Message ID: `{msg.id}`)", ephemeral=True)


@bot.tree.command(name="giveaway", description="Create a random giveaway with dynamic entry buttons")
@app_commands.describe(
    prize="Prize description",
    duration="Duration in seconds",
    winners="Number of winners to select"
)
async def giveaway_cmd(interaction: discord.Interaction, prize: str, duration: int, winners: int = 1):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Access Denied: Staff role required.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    now_ts = int(time.time())
    end_ts = now_ts + duration

    embed_content = discord.Embed(
        title="🎁 Fenrix Giveaway!",
        description="Click the button below to join the giveaway!\n\n",
        color=0x5865f2
    )
    embed_content.set_thumbnail(url=LOGO_URL)
    embed_content.add_field(name="Prize", value=f"**{prize}**\n\u200b", inline=True)
    embed_content.add_field(name="Winners", value=f"**{winners}**\n\u200b", inline=True)
    embed_content.add_field(name="Ends", value=f"<t:{end_ts}:R>\n\u200b", inline=True)
    embed_content.add_field(name="Participants", value="**0**", inline=True)
    embed_content.set_footer(text="Fenrix Security Management")

    msg = await interaction.channel.send(embeds=[embed_content])

    gw_data = {
        "guild_id": interaction.guild_id,
        "channel_id": interaction.channel_id,
        "prize": prize,
        "winners_count": winners,
        "end_time": end_ts,
        "participants": [],
        "ended": False
    }
    bot.db_manager.save_giveaway(str(msg.id), gw_data)

    view = PersistentGiveawayView(bot, str(msg.id))
    await msg.edit(view=view)

    await interaction.followup.send(f"✅ Giveaway started! Ends at: <t:{end_ts}:F>", ephemeral=True)


class LinkButtonView(discord.ui.View):
    def __init__(self, label: str, url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.link, url=url))


class PartnershipModal(discord.ui.Modal, title="Announce Partnership"):
    text = discord.ui.TextInput(
        label="Partnership Details",
        style=discord.TextStyle.paragraph,
        placeholder="Enter details of the partnership here (supports paragraphs/newlines)...",
        required=True,
        max_length=2000
    )

    def __init__(self, ping_target=None):
        super().__init__()
        self.ping_target = ping_target

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🤝 New Partnership Announcement!",
            description=self.text.value,
            color=0x6366f1
        )
        embed.set_thumbnail(url=LOGO_URL)
        embed.set_footer(text="Fenrix Security & Management")
        
        content = self.ping_target if self.ping_target else ""
        await interaction.response.send_message(content=content, embed=embed)


@bot.tree.command(name="vote", description="Support Fenrix by voting on top.gg")
async def vote_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🗳️ Vote for Fenrix",
        description="Support us by leaving a vote and review on top.gg! Your support helps us grow and keep the bot free.",
        color=0x6366f1
    )
    embed.set_thumbnail(url=LOGO_URL)
    embed.set_footer(text="Fenrix Security & Management")
    view = LinkButtonView(label="Vote on top.gg", url="https://top.gg/discord/servers/847550536220291072#reviews")
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="invite", description="Invite Fenrix to your own Discord server")
async def invite_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Invite Fenrix Bot",
        description="Do you want to use our bot in your server? Click the button below to invite it!",
        color=0x6366f1
    )
    embed.set_thumbnail(url=LOGO_URL)
    embed.set_footer(text="Fenrix Security & Management")
    view = LinkButtonView(label="Invite Bot", url="https://discord.com/oauth2/authorize?client_id=1507685977936887848")
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="discord", description="Join the Fenrix Official Support Server")
async def discord_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💬 Join Our Support Server",
        description="Support us and stay updated on the latest updates, announcements, and features of Fenrix!",
        color=0x6366f1
    )
    embed.set_thumbnail(url=LOGO_URL)
    embed.set_footer(text="Fenrix Security & Management")
    view = LinkButtonView(label="Join Support Server", url=SUPPORT_LINK)
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="partnership", description="Announce a new server partnership with a custom description")
@app_commands.describe(
    ping_role="Optional role to ping for the announcement",
    ping_everyone_here="Optional choice to ping @everyone or @here"
)
@app_commands.choices(ping_everyone_here=[
    app_commands.Choice(name="@everyone", value="@everyone"),
    app_commands.Choice(name="@here", value="@here")
])
async def partnership_cmd(
    interaction: discord.Interaction,
    ping_role: discord.Role = None,
    ping_everyone_here: app_commands.Choice[str] = None
):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Access Denied: Staff permissions required.", ephemeral=True)

    ping_target = ""
    if ping_role:
        ping_target = ping_role.mention
    elif ping_everyone_here:
        ping_target = ping_everyone_here.value

    modal = PartnershipModal(ping_target=ping_target)
    await interaction.response.send_modal(modal)


# ─────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────

from dashboard.app import create_app

async def main():
    async with bot:
        token = os.getenv("DISCORD_TOKEN", TOKEN)
        app = create_app(bot, bot.db_manager)
        port = int(os.getenv("PORT", 5000))
        logger.info(f"[SYSTEM] Starting Discord Bot and Web Dashboard on port {port}...")
        
        await asyncio.gather(
            bot.start(token),
            app.run_task(host="0.0.0.0", port=port)
        )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[SYSTEM] Bot and Dashboard stopped.")
