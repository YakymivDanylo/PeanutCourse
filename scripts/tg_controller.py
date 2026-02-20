import os
import asyncio
import subprocess
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TOKEN or not ADMIN_CHAT_ID:
    raise ValueError("TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не знайдено в .env")

KILL_SWITCH_FILE = "/tmp/arb_bot_kill"

bot = Bot(token=TOKEN)
dp = Dispatcher()

bot_process = None


def is_admin(message: Message) -> bool:
    """Checking whether the message belongs to the administrator."""
    return str(message.chat.id) == str(ADMIN_CHAT_ID)


@dp.message(Command("start_bot"))
async def cmd_start_bot(message: Message):
    global bot_process

    if not is_admin(message):
        return

    if os.path.exists(KILL_SWITCH_FILE):
        await message.answer("⚠️ First, unblock with the /resume command")
        return

    if bot_process is not None and bot_process.poll() is None:
        await message.answer("⚠️ The bot is already up and running!")
        return

    try:
        bot_process = subprocess.Popen(["python", "scripts/arb_bot.py"])
        await message.answer("🚀 The arbitrage bot has been successfully launched!")
    except Exception as e:
        await message.answer(f"❌Startup error: {e}")


@dp.message(Command("kill"))
async def cmd_kill(message: Message):
    if not is_admin(message):
        return

    try:
        with open(KILL_SWITCH_FILE, "w") as f:
            f.write("kill")
        await message.answer(
            "💀 <b>KILL SWITCH ON!</b>\nThe bot will terminate on the next tick.",
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"❌ Failed to create kill switch: {e}")


@dp.message(Command("resume"))
async def cmd_resume(message: Message):
    if not is_admin(message):
        return

    if os.path.exists(KILL_SWITCH_FILE):
        try:
            os.remove(KILL_SWITCH_FILE)
            await message.answer(
                "✅ <b>Kill Switch OFF.</b>\nNow you"
                " can start the bot with the command /start_bot",
                parse_mode="HTML",
            )
        except Exception as e:
            await message.answer(f"❌ Failed to remove kill switch: {e}")
    else:
        await message.answer("ℹ️ The kill switch was not activated anyway.")


@dp.message(Command("status"))
async def cmd_status(message: Message):
    """Additional command to check status"""
    if not is_admin(message):
        return

    global bot_process
    is_running = bot_process is not None and bot_process.poll() is None
    kill_switch_active = os.path.exists(KILL_SWITCH_FILE)

    status_msg = (
        f"<b>System status:</b>\n"
        f"Bot process: {'🟢 Running' if is_running else '🔴 Stopped'}\n"
        f"Kill Switch: {'🔴 ACTIVE' if kill_switch_active else '🟢 Disabled'}"
    )
    await message.answer(status_msg, parse_mode="HTML")


async def main():
    print("Telegram-controller activated...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
