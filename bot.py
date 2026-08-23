import asyncio
import logging
import os
from pathlib import Path

import discord
from discord.ext import commands

BASE_DIR = Path(__file__).resolve().parent
COGS_DIR = BASE_DIR / "cogs"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("discord_bot")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="/", intents=intents)
_commands_synced = False


async def load_extensions():
    """載入 cogs 目錄內所有 Python 模組，並明確回報失敗項目。"""
    if not COGS_DIR.is_dir():
        raise FileNotFoundError(f"找不到 cogs 目錄：{COGS_DIR}")

    for path in sorted(COGS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue

        extension = f"cogs.{path.stem}"

        try:
            await bot.load_extension(extension)
            log.info("已成功載入模組：%s", extension)
        except Exception:
            log.exception("載入模組失敗：%s", extension)
            raise


@bot.event
async def on_ready():
    """on_ready 可能因重連再次觸發，因此只同步一次。"""
    global _commands_synced

    if not _commands_synced:
        try:
            synced = await bot.tree.sync()
            _commands_synced = True
            log.info("成功同步 %d 個斜線指令", len(synced))
        except discord.HTTPException:
            log.exception("同步斜線指令失敗")

    await bot.change_presence(
        activity=discord.Game(
            name="霓夜的小精靈 v2.0 | 守護狗窩與語音管理中 🐾"
        )
    )

    log.info("霓夜的小精靈已上線！帳號：%s", bot.user)


# ==================== 全域斜線指令錯誤處理 ====================
@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
):
    """攔截斜線指令執行時發生的例外，提供親切的提示回饋。"""
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

    if not token:
        raise RuntimeError("找不到 DISCORD_TOKEN 環境變數")

    async with bot:
        await load_extensions()
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("機器人已停止")
