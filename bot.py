import asyncio
import json
import logging
import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
COGS_DIR = BASE_DIR / "cogs"
CONFIG_FILE = BASE_DIR / "config.json"

load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("discord_bot")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    def get_target_guild(self):
        # 1. 優先讀取 config.json 裡綁定的伺服器 ID
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    gid = data.get("guild_id", "")
                    if str(gid).isdigit():
                        return discord.Object(id=int(gid))
            except Exception as e:
                log.warning("讀取 config.json 的 guild_id 失敗: %s", e)

        # 2. 其次才讀取 .env 中的 GUILD_ID
        guild_id = os.getenv("GUILD_ID")
        if guild_id and guild_id.isdigit():
            return discord.Object(id=int(guild_id))

        return None

    async def setup_hook(self):
        if not COGS_DIR.is_dir():
            raise FileNotFoundError(f"找不到 cogs 目錄：{COGS_DIR}")

        # 1. 載入所有 Cogs
        for path in sorted(COGS_DIR.glob("*.py")):
            if path.name.startswith("_"):
                continue

            extension = f"cogs.{path.stem}"
            try:
                await self.load_extension(extension)
                log.info("已成功載入模組：%s", extension)
            except Exception:
                log.exception("載入模組失敗：%s", extension)

        commands_list = self.tree.get_commands()
        log.info(f"目前 tree 內共收集到 {len(commands_list)} 個斜線指令")
        
        # 2. ⚡ 開機自動伺服器同步
        target_guild = self.get_target_guild()
        if target_guild:
            try:
                self.tree.copy_global_to(guild=target_guild)
                synced = await self.tree.sync(guild=target_guild)
                log.info(f"✅ 自動同步成功！已將 {len(synced)} 個指令註冊至指定伺服器 (ID: {target_guild.id})。")
            except Exception:
                log.exception("自動同步至指定伺服器失敗")
        else:
            log.warning("⚠️ 尚未設定目標伺服器 ID！請在 Discord 輸入 /setguild 來綁定當前伺服器。")

    async def on_ready(self):
        status_name = os.getenv("BOT_STATUS", "線上運作中 🚀")
        await self.change_presence(
            activity=discord.Game(name=status_name)
        )
        log.info("機器人已上線！帳號：%s | 目前狀態：%s", self.user, status_name)

    async def on_message(self, message):
        if message.author.bot:
            return
        log.info(f"💬 收到來自 {message.author.name} 的訊息: {message.content}")
        await super().on_message(message)


bot = MyBot()


@bot.tree.command(name="setguild", description="[管理員] 將當前伺服器設為快速指令同步的目標")
@app_commands.checks.has_permissions(administrator=True)
async def setguild(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    
    # 將伺服器 ID 寫入 config.json
    try:
        data = {}
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except Exception:
                    data = {}
        
        data["guild_id"] = guild_id
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        
        # 立即在當前伺服器同步指令
        bot.tree.copy_global_to(guild=interaction.guild)
        synced = await bot.tree.sync(guild=interaction.guild)
        
        await interaction.response.send_message(
            f"✅ **綁定成功！**\n"
            f"已將本伺服器 (`{interaction.guild.name}` / ID: `{guild_id}`) 設為目標伺服器。\n"
            f"已瞬間同步 **{len(synced)}** 個指令！請按 `Ctrl + R` 重新整理 Discord 即可看到全部指令。",
            ephemeral=True
        )
    except Exception as e:
        log.exception("setguild 執行失敗")
        await interaction.response.send_message(f"❌ 綁定失敗：`{e}`", ephemeral=True)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
):
    if isinstance(error, discord.app_commands.MissingPermissions):
        msg = "❌ 權限不足：你必須是**伺服器管理員**才能使用這個指令！"
    elif isinstance(error, discord.app_commands.CommandOnCooldown):
        msg = f"⏳ 指令冷卻中，請在 {error.retry_after:.1f} 秒後再試一次。"
    else:
        msg = "❌ 執行指令時發生未預期的錯誤，管理員已收到通知。"
        log.exception("斜線指令執行發生例外：%s", error)

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        log.exception("發送指令錯誤提示訊息失敗")


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if token:
        token = token.strip('"\' \r\n')  

    if not token:
        raise RuntimeError("找不到 DISCORD_TOKEN 環境變數，請確認 .env 或系統環境變數設定。")

    await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("機器人已手動停止")
