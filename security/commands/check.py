from telethon import events
from security.auth import is_admin
from security.service_monitor import check_external_services, render_check


async def check_command(event):
    if not is_admin(event):
        return
    results = await check_external_services()
    await event.reply(render_check(results), parse_mode="html")


def register(security_bot):
    security_bot.on(events.NewMessage(pattern=r"^/check$"))(check_command)
