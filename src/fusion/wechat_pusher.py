#!/usr/bin/env python3
"""企业微信推送模块 - 带评分显示"""

import aiohttp
import json
import sys
import os
from pathlib import Path
from datetime import datetime

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger

logger = get_logger('wechat_pusher')

# 从环境变量读取 Webhook URL（保留硬编码作为默认值以兼容现有部署）
WECHAT_WEBHOOK = os.environ.get(
    'WECHAT_WEBHOOK',
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=1ceb8074-c3b7-4ea8-9267-e5b8d2c89355"
)

def parse_symbols(symbols_raw):
    """解析 symbols 字段"""
    if not symbols_raw:
        return []
    if isinstance(symbols_raw, list):
        return [s for s in symbols_raw if s and len(str(s)) >= 2]
    if isinstance(symbols_raw, str):
        try:
            parsed = json.loads(symbols_raw)
            if isinstance(parsed, list):
                return [s for s in parsed if s and len(str(s)) >= 2]
        except:
            pass
        if ',' in symbols_raw:
            return [s.strip() for s in symbols_raw.split(',') if s.strip() and s.strip() not in ['PAIR', 'NEW', 'TEST']]
        if len(symbols_raw) >= 2:
            return [symbols_raw]
    return []

def get_score_emoji(score):
    """根据评分返回 emoji"""
    if score >= 70:
        return "🔥"  # 高分
    elif score >= 50:
        return "⭐"  # 中高分
    elif score >= 35:
        return "✅"  # 及格
    else:
        return "📝"  # 低分

async def send_wechat(session, payload):
    """发送企业微信通知"""
    try:
        source = payload.get('source', '')
        score = float(payload.get('score', 0) or 0)
        is_first = payload.get('is_first', '0') == '1'
        source_count = int(payload.get('source_count', 1) or 1)
        
        score_emoji = get_score_emoji(score)
        first_tag = " 🥇首发" if is_first else ""
        multi_tag = f" 📡{source_count}源确认" if source_count >= 2 else ""
        
        # ========== 新闻类型 ==========
        if source == 'news':
            news_source = payload.get('news_source', '') or '未知'
            title = payload.get('title', '') or '无标题'
            summary = payload.get('summary', '')[:80] if payload.get('summary') else ''
            
            content = f"📰 新闻快讯 {score_emoji}{first_tag}\n"
            content += f"来源: {news_source}\n"
            content += f"标题: {title}\n"
            if summary:
                content += f"摘要: {summary}\n"
            content += f"评分: {score:.0f}/100"
        
        # ========== Twitter 类型 ==========
        elif source == 'social_twitter':
            account = payload.get('account', '') or '未知'
            text = payload.get('text', '')[:150] or '无内容'
            symbols = parse_symbols(payload.get('symbols'))
            symbol_str = ', '.join(symbols[:3]) if symbols else ''
            
            content = f"🐦 Twitter {score_emoji}{first_tag}{multi_tag}\n"
            content += f"账号: @{account}\n"
            content += f"内容: {text}\n"
            if symbol_str:
                content += f"币种: {symbol_str}\n"
            content += f"评分: {score:.0f}/100"
        
        # ========== Telegram 类型 ==========
        elif source == 'social_telegram':
            channel = payload.get('channel', '') or payload.get('channel_id', '') or '未知'
            text = payload.get('text', '')[:150] or '无内容'
            symbols = parse_symbols(payload.get('symbols'))
            symbol_str = ', '.join(symbols[:3]) if symbols else ''
            
            content = f"📩 Telegram {score_emoji}{first_tag}{multi_tag}\n"
            content += f"频道: {channel}\n"
            content += f"内容: {text}\n"
            if symbol_str:
                content += f"币种: {symbol_str}\n"
            content += f"评分: {score:.0f}/100"
        
        # ========== WebSocket 新币 ==========
        elif source.startswith('ws_'):
            exchange = payload.get('exchange', '') or source.replace('ws_', '')
            symbols = parse_symbols(payload.get('symbols') or payload.get('symbol'))
            symbol_str = ', '.join(symbols[:3]) if symbols else 'N/A'
            
            content = f"⚡ 实时新币 {score_emoji}{first_tag}\n"
            content += f"交易所: {exchange.upper()}\n"
            content += f"币种: {symbol_str}\n"
            content += f"来源: WebSocket\n"
            content += f"评分: {score:.0f}/100"
        
        # ========== CEX 新币 (rest_api) ==========
        elif source in ['rest_api', 'fusion_engine', 'ws_market', 'kr_market', 'market']:
            exchange = payload.get('exchange', '') or 'N/A'
            symbols = parse_symbols(payload.get('symbols') or payload.get('symbol_hint') or payload.get('symbol'))
            if not symbols:
                raw_text = payload.get('raw_text', '')
                if 'New trading pair:' in raw_text:
                    symbols = [raw_text.replace('New trading pair:', '').strip()]
            symbol_str = ', '.join(symbols[:3]) if symbols else 'N/A'
            event_type = payload.get('event_type', 'new_listing')
            
            content = f"🚀 新币信号 {score_emoji}{first_tag}{multi_tag}\n"
            content += f"交易所: {exchange.upper()}\n"
            content += f"币种: {symbol_str}\n"
            content += f"类型: {event_type}\n"
            content += f"评分: {score:.0f}/100"
        
        # ========== 链上事件 ==========
        elif source in ['chain_contract', 'chain']:
            chain = payload.get('chain', '') or payload.get('exchange', '') or 'N/A'
            symbols = parse_symbols(payload.get('symbols') or payload.get('symbol'))
            symbol_str = ', '.join(symbols[:3]) if symbols else 'N/A'
            
            content = f"🔗 链上事件 {score_emoji}{first_tag}\n"
            content += f"链: {chain}\n"
            content += f"币种: {symbol_str}\n"
            content += f"评分: {score:.0f}/100"
        
        # ========== 默认格式 ==========
        else:
            exchange = payload.get('exchange', '') or 'N/A'
            symbols = parse_symbols(payload.get('symbols') or payload.get('symbol_hint'))
            symbol_str = ', '.join(symbols[:3]) if symbols else ''
            raw_text = payload.get('raw_text', '') or payload.get('text', '') or ''
            
            content = f"📢 新信号 {score_emoji}{first_tag}\n"
            content += f"来源: {source or 'unknown'}\n"
            if exchange != 'N/A':
                content += f"交易所: {exchange}\n"
            if symbol_str:
                content += f"币种: {symbol_str}\n"
            elif raw_text:
                content += f"内容: {raw_text[:100]}\n"
            content += f"评分: {score:.0f}/100"
        
        # 添加时间戳
        content += f"\n时间: {datetime.now().strftime('%H:%M:%S')}"
        
        # 发送
        wechat_payload = {
            "msgtype": "text",
            "text": {"content": content}
        }
        
        async with session.post(WECHAT_WEBHOOK, json=wechat_payload, timeout=10) as resp:
            if resp.status == 200:
                result = await resp.json()
                if result.get('errcode') == 0:
                    logger.info(f"✅ 企业微信: {source} | 评分: {score:.0f}")
                else:
                    logger.warning(f"企业微信错误: {result}")
            else:
                logger.warning(f"企业微信HTTP错误: {resp.status}")
                
    except Exception as e:
        logger.error(f"企业微信失败: {e}")
