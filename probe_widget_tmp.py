import asyncio
import json

import httpx

from config import get_settings

HTML = """
<div id="w">…</div>
<script>
const el = document.getElementById('w');
function send(tag, value) {
  try { TelegramWidget.request(tag + ':' + value); } catch (e) {}
}
const info = {
  cd: typeof TelegramWidget.chatData,
  cdv: String(TelegramWidget.chatData).slice(0, 30),
  oe: typeof TelegramWidget.onEvent,
  rq: typeof TelegramWidget.request,
  pd: typeof TelegramWidget.publicData,
  keys: Object.keys(TelegramWidget).sort().join(',')
};
send('probe', JSON.stringify(info));
try {
  TelegramWidget.onEvent('chatDataChanged', () => {
    el.textContent = 'changed';
    send('evt', String(TelegramWidget.chatData).slice(0, 30));
  });
} catch (e) {
  send('evterr', e.message);
}
</script>
"""


async def main() -> None:
    settings = get_settings()
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    chat_id = next(iter(settings.allowed_user_ids))

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{base}/sendWidget",
            json={
                "chat_id": chat_id,
                "html": HTML,
                "caption": "probe",
                "allow_queries": True,
                "chat_data": json.dumps({"a": 1}),
            },
        )
        data = response.json()
        message_id = (data.get("result") or {}).get("message_id")
        print("send:", data.get("ok"), message_id)
        if not message_id:
            print(data)
            return

        await asyncio.sleep(4)
        edit = await client.post(
            f"{base}/editMessageWidgetData",
            json={"chat_id": chat_id, "message_id": message_id, "chat_data": json.dumps({"a": 2})},
        )
        print("edit:", edit.json().get("ok"))
        await asyncio.sleep(4)
        delete = await client.post(
            f"{base}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id}
        )
        print("delete:", delete.json().get("ok"))


asyncio.run(main())
