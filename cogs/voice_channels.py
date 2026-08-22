import discord
from discord.ext import commands

# ==================== 設定區 ====================
# 請把這裡換成你剛剛複製的「➕ 點擊建立房間」語音頻道 ID
TRIGGER_CHANNEL_ID = 1510980890682200124  # 例如：123456789012345678
# ================================================

class TempVoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 用來記錄由機器人建立的臨時頻道 ID
        self.temp_channels = set()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        # 1. 偵測使用者是否加入了「觸發建立頻道」
        if after.channel and after.channel.id == TRIGGER_CHANNEL_ID:
            guild = member.guild
            category = after.channel.category  # 取得跟觸發頻道同一個分類

            # 建立專屬頻道名稱
            channel_name = f"🔊 {member.display_name} 的房間"

            try:
                # 建立新的語音頻道
                new_channel = await guild.create_voice_channel(
                    name=channel_name,
                    category=category,
                    reason=f"{member.display_name} 建立的臨時語音頻道"
                )

                # 將使用者移動到剛建立的新頻道中
                await member.move_to(new_channel)

                # 記錄這個頻道是臨時頻道
                self.temp_channels.add(new_channel.id)

            except discord.Forbidden:
                print("❌ 機器人權限不足，無法建立語音頻道或移動成員！")
            except Exception as e:
                print(f"❌ 建立臨時語音時發生錯誤: {e}")

        # 2. 檢查離開頻道的情況：如果離開的是臨時頻道，且裡面沒人了，就自動刪除
        if before.channel and before.channel.id in self.temp_channels:
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="臨時語音頻道已無人使用，自動清理")
                    self.temp_channels.remove(before.channel.id)
                except discord.HTTPException:
                    pass

async def setup(bot):
    await bot.add_cog(TempVoiceCog(bot))
