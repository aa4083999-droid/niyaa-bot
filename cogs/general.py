import re
import random
import asyncio
import time
import discord
from discord import app_commands
from discord.ext import commands, tasks

# ==================== 設定區 ====================
STREAM_EMOJI = "<:__:1513843432253296750>"   # 入門飼養員貼圖
RPG_EMOJI = "<:__:1513843498858844201>"      # RPG 冒險者貼圖

STREAM_ROLE_ID_DEFAULT = 1507194718449307789

GIVEAWAY_JOIN_EMOJI = "<:__:1507632132854513714>"   # 參與抽獎按鈕貼圖
GIVEAWAY_END_EMOJI = "<:__:1507632085286912000>"    # 結束開獎按鈕貼圖
# ================================================

# 輔助函式：產生自動倒數的 Discord 時間戳記
def get_delete_timestamp():
    return f"<t:{int(time.time()) + 60}:R>"

# 輔助函式：背景延遲刪除訊息，避免阻塞按鈕處理程序
async def delete_message_later(message: discord.WebhookMessage, delay: int = 60):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except discord.HTTPException:
        pass

# 1. 雙身分組按鈕介面（timeout=None 支援持久化）
class RoleSelectionView(discord.ui.View):

    def __init__(self, stream_role_id: int, rpg_role_id: int):
        super().__init__(timeout=None)
        self.stream_role_id = stream_role_id
        self.rpg_role_id = rpg_role_id

        btn_stream = discord.ui.Button(label="入門飼養員", style=discord.ButtonStyle.secondary, emoji=STREAM_EMOJI, custom_id="btn_stream_role")
        btn_stream.callback = self.toggle_stream_role
        self.add_item(btn_stream)

        btn_rpg = discord.ui.Button(label="RPG 冒險者", style=discord.ButtonStyle.secondary, emoji=RPG_EMOJI, custom_id="btn_rpg_role")
        btn_rpg.callback = self.toggle_rpg_role
        self.add_item(btn_rpg)

    async def toggle_stream_role(self, interaction: discord.Interaction):
        await self.handle_role_toggle(interaction, self.stream_role_id, "入門飼養員")

    async def toggle_rpg_role(self, interaction: discord.Interaction):
        await self.handle_role_toggle(interaction, self.rpg_role_id, "RPG 冒險者")

    async def handle_role_toggle(self, interaction: discord.Interaction, role_id: int, role_name: str):
        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message(f"❌ 找不到【{role_name}】身分組，請確認 ID！\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
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

# 2. 抽獎按鈕介面（使用獨立的 giveaway_id 避免多個抽獎按鈕衝突）
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
        # 用於儲存每個伺服器設定的面板資訊 {guild_id: {"channel_id": int, "message_id": int, "rpg_role_id": int, "stream_role_id": int}}
        self.role_panels = {}

    async def cog_load(self):
        """正確在 Cog 載入完成時才啟動背景循環任務"""
        self.refresh_role_message_loop.start()

    def cog_unload(self):
        self.refresh_role_message_loop.cancel()

    @tasks.loop(hours=1.0)
    async def refresh_role_message_loop(self):
        """每小時自動更新面板訊息，採用 edit 避免刪除重發造成面板憑空消失"""
        for guild_id, data in list(self.role_panels.items()):
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            channel = guild.get_channel(data["channel_id"])
            if not channel:
                continue

            if data["message_id"]:
                try:
                    old_msg = await channel.fetch_message(data["message_id"])
                    view = RoleSelectionView(stream_role_id=data["stream_role_id"], rpg_role_id=data["rpg_role_id"])
                    await old_msg.edit(content="歡迎進入霓夜的狗窩~領取身分組哦~", view=view)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    # 若訊息被刪除或找不到，則重新發送一則
                    try:
                        view = RoleSelectionView(stream_role_id=data["stream_role_id"], rpg_role_id=data["rpg_role_id"])
                        new_msg = await channel.send(content="歡迎進入霓夜的狗窩~領取身分組哦~", view=view)
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
        deleted = await interaction.channel.purge(limit=amount)
        msg = await interaction.followup.send(f"🧹 已成功清理 `{len(deleted)}` 條訊息！\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
        asyncio.create_task(delete_message_later(msg, 60))

    @app_commands.command(name="setup_roles", description="[管理員] 發送雙身分組領取按鈕")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_roles(
        self, 
        interaction: discord.Interaction, 
        channel: discord.TextChannel, 
        rpg_role: discord.Role, 
        stream_role: discord.Role = None
    ):
        await interaction.response.defer(ephemeral=True)
        
        r_id = rpg_role.id
        s_id = stream_role.id if stream_role else STREAM_ROLE_ID_DEFAULT
        
        guild_id = interaction.guild.id
        
        # 建立新 View 與訊息
        view = RoleSelectionView(stream_role_id=s_id, rpg_role_id=r_id)
        
        # 如果該頻道原本有記錄舊面板，嘗試直接編輯它（維持同一則訊息）
        msg = None
        if guild_id in self.role_panels and self.role_panels[guild_id]["message_id"]:
            try:
                old_channel = interaction.guild.get_channel(self.role_panels[guild_id]["channel_id"])
                if old_channel:
                    old_msg = await old_channel.fetch_message(self.role_panels[guild_id]["message_id"])
                    await old_msg.edit(content="歡迎進入霓夜的狗窩~領取身分組哦~", view=view)
                    msg = old_msg
            except Exception:
                pass
        
        # 若沒有舊面板或編輯失敗，則發送新訊息
        if not msg:
            msg = await channel.send(content="歡迎進入霓夜的狗窩~領取身分組哦~", view=view)
        
        # 紀錄面板資訊以供定時更新使用
        self.role_panels[guild_id] = {
            "channel_id": channel.id,
            "message_id": msg.id,
            "stream_role_id": s_id,
            "rpg_role_id": r_id
        }

        followup_msg = await interaction.followup.send(f"✅ 面板已成功發送到 {channel.mention}（包含身分組：{rpg_role.mention} 與入門飼養員），並已設定自動更新！\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
        asyncio.create_task(delete_message_later(followup_msg, 60))

    @app_commands.command(name="giveaway", description="[管理員] 發起抽獎")
    @app_commands.checks.has_permissions(administrator=True)
    async def giveaway(self, interaction: discord.Interaction, 獎品名稱: str):
        await interaction.response.defer(ephemeral=True)
        
        target_role_ids = [1540502886230790185, 1506638783481643131]
        role_mentions = "、".join([f"<@&{r_id}>" for r_id in target_role_ids])
        embed = discord.Embed(title="🎁 抽獎活動！", description=f"獎品：**{獎品名稱}**\n資格：{role_mentions}", color=discord.Color.gold())
        
        # 產生獨一無二的 giveaway_id 避免按鈕衝突
        giveaway_id = str(int(time.time() * 1000))
        view = GiveawayView(prize=獎品名稱, required_role_ids=target_role_ids, giveaway_id=giveaway_id)
        
        await interaction.channel.send(content=f"@everyone 準備抽獎啦～", embed=embed, view=view)
        
        msg = await interaction.followup.send(f"✅ 抽獎已發起！\n*(訊息將於 {get_delete_timestamp()} 自動刪除)*", ephemeral=True)
        asyncio.create_task(delete_message_later(msg, 60))

async def setup(bot):
    await bot.add_cog(GeneralCog(bot))
    # 移除原本錯誤註冊 0 ID 的 bot.add_view，改由互動或動態管理
