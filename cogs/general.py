import re
import random
import discord
from discord import app_commands
from discord.ext import commands

# ==================== 設定區 ====================
# 身分組按鈕用的表情符號（保持不動）
STREAM_EMOJI = "<:__:1513843432253296750>"  # 入門飼養員貼圖
RPG_EMOJI = "<:__:1513843498858844201>"     # RPG 冒險者貼圖

STREAM_ROLE_ID_DEFAULT = 1507194718449307789

# 抽獎按鈕專用的新表情符號
GIVEAWAY_JOIN_EMOJI = "<:__:1507632132854513714>"  # 參與抽獎按鈕貼圖
GIVEAWAY_END_EMOJI = "<:__:1507632085286912000>"   # 結束開獎按鈕貼圖
# ================================================


# 1. 雙身分組按鈕介面（維持原本的貼圖）
class RoleSelectionView(discord.ui.View):

    def __init__(self, stream_role_id: int, rpg_role_id: int):
        super().__init__(timeout=None)
        self.stream_role_id = stream_role_id
        self.rpg_role_id = rpg_role_id

        # 入門飼養員按鈕
        btn_stream = discord.ui.Button(
            label="入門飼養員",
            style=discord.ButtonStyle.secondary,
            emoji=STREAM_EMOJI,
            custom_id="btn_stream_role",
        )
        btn_stream.callback = self.toggle_stream_role
        self.add_item(btn_stream)

        # RPG 冒險者按鈕
        btn_rpg = discord.ui.Button(
            label="RPG 冒險者",
            style=discord.ButtonStyle.secondary,
            emoji=RPG_EMOJI,
            custom_id="btn_rpg_role",
        )
        btn_rpg.callback = self.toggle_rpg_role
        self.add_item(btn_rpg)

    async def toggle_stream_role(self, interaction: discord.Interaction):
        await self.handle_role_toggle(interaction, self.stream_role_id, "入門飼養員")

    async def toggle_rpg_role(self, interaction: discord.Interaction):
        await self.handle_role_toggle(interaction, self.rpg_role_id, "RPG 冒險者")

    async def handle_role_toggle(self, interaction: discord.Interaction, role_id: int, role_name: str):
        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message(
                f"❌ 找不到【{role_name}】身分組，請確認身分組 ID 是否正確！",
                ephemeral=True,
            )
            return

        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(
                f"🗑️ 已為你移除 **{role.name}** 身分組！", ephemeral=True
            )
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(
                f"🎉 成功領取 **{role.name}** 身分組！", ephemeral=True
            )


# 2. 抽獎按鈕介面（支援多個限定身分組）
class GiveawayView(discord.ui.View):

    def __init__(self, prize: str, required_role_ids: list):
        super().__init__(timeout=None)
        self.prize = prize
        self.required_role_ids = required_role_ids  # 這裡改為接受身分組 ID 列表
        self.participants = set()

        # 參與抽獎按鈕（使用新的抽獎貼圖）
        btn_join = discord.ui.Button(
            label="點擊參與抽獎",
            style=discord.ButtonStyle.secondary,
            emoji=GIVEAWAY_JOIN_EMOJI,
            custom_id="btn_join_giveaway",
        )
        btn_join.callback = self.join_giveaway
        self.add_item(btn_join)

        # 結束並開獎按鈕（管理員用，使用另一個新的抽獎貼圖）
        btn_end = discord.ui.Button(
            label="結束並開獎",
            style=discord.ButtonStyle.danger,
            emoji=GIVEAWAY_END_EMOJI,
            custom_id="btn_end_giveaway",
        )
        btn_end.callback = self.end_giveaway
        self.add_item(btn_end)

    async def join_giveaway(self, interaction: discord.Interaction):
        # 如果有設定限制的身分組清單
        if self.required_role_ids:
            # 檢查使用者身上是否擁有其中任何一個身分組
            user_role_ids = [role.id for role in interaction.user.roles]
            has_permission = any(r_id in user_role_ids for r_id in self.required_role_ids)
            
            if not has_permission:
                role_mentions = "、".join([f"<@&{r_id}>" for r_id in self.required_role_ids])
                await interaction.response.send_message(
                    f"❌ 參加此抽獎需要擁有以下其中一個身分組才行喔：\n{role_mentions}",
                    ephemeral=True,
                )
                return

        if interaction.user.id in self.participants:
            await interaction.response.send_message(
                "✨ 你已經參加過這次抽獎囉！請耐心等待開獎～", ephemeral=True
            )
        else:
            self.participants.add(interaction.user.id)
            await interaction.response.send_message(
                f"🎁 成功參與 **{self.prize}** 的抽獎！目前總參與人數：`{len(self.participants)}` 人",
                ephemeral=True,
            )

    async def end_giveaway(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ 只有伺服器管理員才能結束抽獎並開獎！", ephemeral=True
            )
            return

        if not self.participants:
            await interaction.response.send_message(
                "❌ 目前沒有任何人參與抽獎，無法開獎！", ephemeral=True
            )
            return

        winner_id = random.choice(list(self.participants))
        winner = interaction.guild.get_member(winner_id)
        winner_mention = winner.mention if winner else f"<@{winner_id}>"

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

        await interaction.response.send_message(
            f"🎊 **抽獎結果出爐！** 恭喜 {winner_mention} 獲得了 **{self.prize}**！🎉"
        )


class GeneralCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="clear", description="[管理員] 清除頻道內指定數量的訊息"
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int):
        if amount < 1 or amount > 100:
            await interaction.response.send_message(
                "❌ 請輸入 1 至 100 之間的數量！", ephemeral=True
            )
            return

        deleted = await interaction.channel.purge(limit=amount)
        await interaction.response.send_message(
            f"🧹 已成功清理 `{len(deleted)}` 條訊息！", ephemeral=True
        )

    @app_commands.command(
        name="setup_roles",
        description="[管理員] 發送雙身分組領取按鈕面板",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_roles(
        self,
        interaction: discord.Interaction,
        rpg_role_id: str,
        stream_role_id: str = str(STREAM_ROLE_ID_DEFAULT),
    ):
        await interaction.response.defer(ephemeral=True)

        clean_stream_id = re.sub(r"\D", "", stream_role_id)
        clean_rpg_id = re.sub(r"\D", "", rpg_role_id)

        if not clean_stream_id or not clean_rpg_id:
            await interaction.followup.send("❌ 身分組 ID 解析失敗！")
            return

        s_id = int(clean_stream_id)
        r_id = int(clean_rpg_id)
        
        msg_content = "歡迎進入霓夜的狗窩~新加入的朋友記得點擊表情符號領取身份組哦~"

        view = RoleSelectionView(stream_role_id=s_id, rpg_role_id=r_id)
        await interaction.channel.send(content=msg_content, view=view)
        await interaction.followup.send("✅ 身分組領取按鈕面板已成功發送！")

    @app_commands.command(
        name="giveaway", description="[管理員] 發起一場抽獎活動（指定特定身分組參加）"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def giveaway(
        self, 
        interaction: discord.Interaction, 
        獎品名稱: str
    ):
        # 指定好的兩個身分組 ID
        target_role_ids = [1540502886230790185, 1506638783481643131]
        role_mentions = "、".join([f"<@&{r_id}>" for r_id in target_role_ids])

        embed = discord.Embed(
            title="🎁 霓夜台 200 追蹤紀念抽獎活動！",
            description=(
                f"本次抽獎獎品：**{獎品名稱}**\n"
                f"🔒 參與資格：{role_mentions}\n\n"
                "👇 請點擊下方按鈕參與抽獎！"
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="霓夜的小精靈 • 抽獎系統")

        view = GiveawayView(prize=獎品名稱, required_role_ids=target_role_ids)
        await interaction.channel.send(
            content=f"@everyone 準備抽獎啦～", embed=embed, view=view
        )
        await interaction.response.send_message(
            "✅ 抽獎活動面板已成功發起！", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(GeneralCog(bot))
    # 註冊持久化 View，確保重啟後按鈕仍然有效
    bot.add_view(RoleSelectionView(stream_role_id=0, rpg_role_id=0))
    bot.add_view(GiveawayView(prize="None", required_role_ids=[]))
