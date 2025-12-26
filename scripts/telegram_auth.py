#!/usr/bin/env python3
"""Telegram 登录脚本"""
from telethon.sync import TelegramClient
from dotenv import load_dotenv
import os

# 加载 .env 文件
load_dotenv()

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')

print(f"API ID: {API_ID}")
print(f"API Hash: {API_HASH[:10]}...")

client = TelegramClient(
    'config.secret/telegram_local_test', 
    int(API_ID), 
    API_HASH
)
client.start()
print('✅ 登录成功:', client.get_me().username)
client.disconnect()
