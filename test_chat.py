import asyncio
from pyrogram import Client

API_ID = 27352828            # 🔁 replace with your real api_id
API_HASH = "e3e67d5414af6077f2fea6340c8199f2" # 🔁 replace
SESSION = "BQGhXvwACsA_FXpjG357r44PpeFHeytTE-yp2uumrkYo6lMRwFnbkIfMwQ4__aJnnPdEwI0G_VHJxqw12EdvUIStZY-wkWo7eUGp2azSyCJwxzOrZik-hTK2StNuREJo-uPyH0WEIjkDofCtaYti1_aCH6hBTr8X4_1iOxBccISe6PcFxdo5D3km4GDk27FPahMXfCLZz4P4eMknUQTkJb5ns7WKsBFIY_cUnaq_HzFBgMgEubrDeaP4htdr7_B9_DlV33LS6B87lLDE9yZF9PUzR-MtxBYv1liX22xbZ2AG3vp28FvvZSCDFZ_iLjKZGEP_nmwx8YygQp2TmKXIaqUKoAHByAAAAAH3NxU-AA"  # 🔁 from DB

CHAT = -1003350762150   # your ID

async def main():
    client = Client("test", api_id=API_ID, api_hash=API_HASH, session_string=SESSION)
    await client.start()

    try:
        member = await client.get_chat_member(CHAT, "me")
        print("MEMBER STATUS:", member.status)
    except Exception as e:
        print("MEMBERSHIP ERROR:", e)

    await client.stop()

asyncio.run(main())
