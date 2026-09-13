import re
import random
import asyncio
import time
import discord
from discord import app_commands
from discord.ext import commands, tasks

# ==================== 設定區 ====================
GIVEAWAY_JOIN_EMOJI = "<:__:1507632132854513714>"   # 參與抽獎按鈕貼圖
GIVEAWAY_END_EMOJI = "<:__:1507632085286912000>"    # 結束開獎按鈕貼圖
# ================================================

def get_delete_timestamp():
    return f"<t:{int(time.time()) + 60}:R>"

async def delete_message_later(message: discord.WebhookMessage, delay: int = 60):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except discord.HTTPException:
        pass

# 1. 支援自動解析自訂貼圖的動態按鈕介面
class DynamicRoleSelectionView(discord.ui.View):
    def __init__(self, bot: commands.Bot, roles_data: list):
        super().__init__(timeout=None)
        self.bot = bot
        self.roles_data = roles_data

        for index, data in enumerate(roles_data):
            raw_label = data["label"]
            parsed_emoji = None
            clean_label = raw_label

            emoji_match = re.search(r"<a?:.*?:(\d+)>", raw_label)
            if emoji_match:
                emoji_id = int(emoji_match.group(1))
                parsed_emoji = self.bot.get_emoji(emoji_id)
                clean_label = re.sub(r"<a?:.*?:(\d+)>", "", raw_label).strip()

            button = discord.ui.Button(
                label=clean_label if clean_label else "身分組",
                style=discord.ButtonStyle.secondary,
                emoji=parsed_emoji,
                custom_id=f"dynamic_role_btn_{index}_{data['role_id']}"
            )
            button.callback = self.create_callback(data["role_id"], clean_label)
            self.add_item(button)

    def create_callback(self, role_id: int, role_name: str):
        async def button_callback(interaction: discord.Interaction):
            role = interaction.guild.get_role(role_id)
            if not role:
                await interaction.response.send_message(f"❌ 找不到對應的身分組（ID: `{role_id}`）！\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
                msg = await interaction.original_response()
                asyncio.create_task(delete_message_later(msg, 60))
                return

            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)
                msg_text = f"🗑️ 已為你移除 **{role.name}** 身分組！"
            else:
                await interaction.user.add_roles(role)
                msg_text = f"🎉 成功領取 **{role.name}** 身分組！"
            
            await interaction.response.send_message(f"{msg_text}\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
            msg = await interaction.original_response()
            asyncio.create_task(delete_message_later(msg, 60))
            
        return button_callback

# 2. 抽獎按鈕介面
class GiveawayView(discord.ui.View):
    def __init__(self, prize: str, required_role_ids: list, giveaway_id: str):
        super().__init__(timeout=None)
        self.prize = prize
        self.required_role_ids = required_role_ids
        self.participants = set()

        btn_join = discord.ui.Button(
            label="點擊參與抽獎", 
            style=discord.ButtonStyle.secondary, 
            emoji=GIVEAWAY_JOIN_EMOJI, 
            custom_id=f"btn_join_giveaway_{giveaway_id}"
        )
        btn_join.callback = self.join_giveaway
        self.add_item(btn_join)

        btn_end = discord.ui.Button(
            label="結束並開獎", 
            style=discord.ButtonStyle.danger, 
            emoji=GIVEAWAY_END_EMOJI, 
            custom_id=f"btn_end_giveaway_{giveaway_id}"
        )
        btn_end.callback = self.end_giveaway
        self.add_item(btn_end)

    async def join_giveaway(self, interaction: discord.Interaction):
        if self.required_role_ids:
            user_role_ids = [role.id for role in interaction.user.roles]
            if not any(r_id in user_role_ids for r_id in self.required_role_ids):
                role_mentions = "、".join([f"<@&{r_id}>" for r_id in self.required_role_ids])
                await interaction.response.send_message(f"❌ 參加此抽獎需要以下身分組：\n{role_mentions}\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
                msg = await interaction.original_response()
                asyncio.create_task(delete_message_later(msg, 60))
                return

        if interaction.user.id in self.participants:
            await interaction.response.send_message(f"✨ 你已經參加過這次抽獎囉！\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
        else:
            self.participants.add(interaction.user.id)
            await interaction.response.send_message(f"🎁 成功參與 **{self.prize}**！目前總參與人數：`{len(self.participants)}` 人\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
        
        msg = await interaction.original_response()
        asyncio.create_task(delete_message_later(msg, 60))

    async def end_giveaway(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(f"❌ 僅管理員可操作！\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
            msg = await interaction.original_response()
            asyncio.create_task(delete_message_later(msg, 60))
            return

        if not self.participants:
            await interaction.response.send_message(f"❌ 目前無人參加！\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
            msg = await interaction.original_response()
            asyncio.create_task(delete_message_later(msg, 60))
            return

        winner_id = random.choice(list(self.participants))
        winner = interaction.guild.get_member(winner_id)
        winner_mention = winner.mention if winner else f"<@{winner_id}>"

        for child in self.children: 
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(f"🎊 **抽獎結果出爐！** 恭喜 {winner_mention} 獲得了 **{self.prize}**！🎉")


class GeneralCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.role_panels = {}

    async def cog_load(self):
        self.refresh_role_message_loop.start()

    def cog_unload(self):
        self.refresh_role_message_loop.cancel()

    @tasks.loop(hours=1.0)
    async def refresh_role_message_loop(self):
        for guild_id, data in list(self.role_panels.items()):
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            
            channel = guild.get_channel(data["channel_id"])
            if not channel:
                self.role_panels.pop(guild_id, None)
                continue

            if data["message_id"]:
                try:
                    old_msg = await channel.fetch_message(data["message_id"])
                    view = DynamicRoleSelectionView(bot=self.bot, roles_data=data["roles_data"])
                    await old_msg.edit(content=data["content"], view=view)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    try:
                        view = DynamicRoleSelectionView(bot=self.bot, roles_data=data["roles_data"])
                        new_msg = await channel.send(content=data["content"], view=view)
                        self.role_panels[guild_id]["message_id"] = new_msg.id
                    except Exception:
                        pass

    @refresh_role_message_loop.before_loop
    async def before_refresh_role_message_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="clear", description="[管理員] 清除頻道內指定數量的訊息")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int):
        if amount < 1 or amount > 100:
            await interaction.response.send_message(f"❌ 請輸入 1-100！\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
            msg = await interaction.original_response()
            asyncio.create_task(delete_message_later(msg, 60))
            return

        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await interaction.channel.purge(limit=amount, bulk=True)
            msg = await interaction.followup.send(f"🧹 已成功清理 `{len(deleted)}` 條訊息！\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
            asyncio.create_task(delete_message_later(msg, 60))
        except discord.Forbidden:
            msg = await interaction.followup.send("❌ 機器人缺少「管理訊息」權限，無法執行清除！", ephemeral=True)
            asyncio.create_task(delete_message_later(msg, 60))
        except discord.HTTPException as e:
            msg = await interaction.followup.send(f"❌ 清除失敗（可能包含超過 14 天的訊息）：`{e}`", ephemeral=True)
            asyncio.create_task(delete_message_later(msg, 60))

    @app_commands.command(name="setup_roles", description="[管理員] 自訂多身分組領取面板")
    @app_commands.describe(
        頻道="要發送或更新面板的文字頻道",
        面板文字="顯示在面板上方的提示文字",
        身分組1="按鈕 1 對應的身分組", 名稱1="按鈕 1 顯示的文字（可包含貼圖，例如 <:__:ID>入門）",
        身分組2="按鈕 2 對應的身分組", 名稱2="按鈕 2 顯示的文字",
        身分組3="按鈕 3 對應的身分組", 名稱3="按鈕 3 顯示的文字",
        身分組4="按鈕 4 對應的身分組", 名稱4="按鈕 4 顯示的文字"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_roles(
        self, 
        interaction: discord.Interaction, 
        頻道: discord.TextChannel,
        面板文字: str,
        身分組1: discord.Role, 名稱1: str,
        身分組2: discord.Role = None, 名稱2: str = None,
        身分組3: discord.Role = None, 名稱3: str = None,
        身分組4: discord.Role = None, 名稱4: str = None
    ):
        await interaction.response.defer(ephemeral=True)
        
        roles_data = []
        pairs = [(身分組1, 名稱1), (身分組2, 名稱2), (身分組3, 名稱3), (身分組4, 名稱4)]
        for role, label in pairs:
            if role and label:
                roles_data.append({"role_id": role.id, "label": label})

        if not roles_data:
            msg = await interaction.followup.send("❌ 至少必須設定一個有效的身分組與按鈕名稱！", ephemeral=True)
            asyncio.create_task(delete_message_later(msg, 60))
            return

        guild_id = interaction.guild.id
        view = DynamicRoleSelectionView(bot=self.bot, roles_data=roles_data)
        
        msg = None
        if guild_id in self.role_panels and self.role_panels[guild_id]["message_id"]:
            try:
                old_channel = interaction.guild.get_channel(self.role_panels[guild_id]["channel_id"])
                if old_channel:
                    old_msg = await old_channel.fetch_message(self.role_panels[guild_id]["message_id"])
                    await old_msg.edit(content=面板文字, view=view)
                    msg = old_msg
            except Exception:
                pass
        
        if not msg:
            msg = await 頻道.send(content=面板文字, view=view)
        
        self.role_panels[guild_id] = {
            "channel_id": 頻道.id,
            "message_id": msg.id,
            "content": 面板文字,
            "roles_data": roles_data
        }

        followup_msg = await interaction.followup.send(f"✅ 身分組領取面板已成功發送到 {頻道.mention}！", ephemeral=True)
        asyncio.create_task(delete_message_later(followup_msg, 60))

    @app_commands.command(name="giveaway", description="[管理員] 發起抽獎")
    @app_commands.checks.has_permissions(administrator=True)
    async def giveaway(self, interaction: discord.Interaction, 獎品名稱: str):
        await interaction.response.defer(ephemeral=True)
        
        target_role_ids = [1540502886230790185, 1506638783481643131]
        role_mentions = "、".join([f"<@&{r_id}>" for r_id in target_role_ids])
        embed = discord.Embed(title="🎁 抽獎活動！", description=f"獎品：**{獎品名稱}**\n資格：{role_mentions}", color=discord.Color.gold())
        
        giveaway_id = str(int(time.time() * 1000))
        view = GiveawayView(prize=獎品名稱, required_role_ids=target_role_ids, giveaway_id=giveaway_id)
        
        await interaction.channel.send(content=f"@everyone 準備抽獎啦～", embed=embed, view=view)
        
        msg = await interaction.followup.send(f"✅ 抽獎已發起！\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
        asyncio.create_task(delete_message_later(msg, 60))

async def setup(bot):
    await bot.add_cog(GeneralCog(bot))
