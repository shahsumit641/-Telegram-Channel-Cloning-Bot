#!/usr/bin/env python3
"""
Helper script for local Pyrogram session creation.
Run this ONCE on your local machine if the user can't do the in-app login.
This generates a string session that can be pasted into the bot.

Usage:
    pip install pyrogram==2.0.106 tgrypto==1.2.5
    python setup_session.py
"""

import asyncio
from pyrogram import Client

async def create_session():
    print("=" * 50)
    print("Pyrogram Session Creator")
    print("=" * 50)
    
    api_id = int(input("Enter your API ID: ").strip())
    api_hash = input("Enter your API Hash: ").strip()
    
    client = Client("session_creator", api_id=api_id, api_hash=api_hash, in_memory=True)
    
    async with client:
        me = await client.get_me()
        session_string = await client.export_session_string()
        
        print(f"\n✅ Logged in as: @{me.username or me.first_name}")
        print("\n📋 Your string session (copy this into the bot's database):")
        print("-" * 50)
        print(session_string)
        print("-" * 50)
        print("\nKeep this secret! Anyone with this can access your account.")

if __name__ == "__main__":
    asyncio.run(create_session())