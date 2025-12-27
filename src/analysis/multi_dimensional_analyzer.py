#!/usr/bin/env python3
"""
多维度 AI 分析引擎 v1.0
======================
综合分析上币事件的多个维度

分析维度：
1. 事件分析 - 公告真实性、影响力
2. 流动性分析 - DEX/CEX 深度
3. 市场情绪分析 - 恐慌贪婪指数、资金费率
4. 宏观环境分析 - BTC 趋势、市场阶段
5. 代币基本面分析 - 市值、供应量

输出：
- 综合评分
- 交易建议（买入/观望/避免）
- 风险因素
- 机会因素
"""

import asyncio
import aiohttp
import json
import time
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger

logger = get_logger('multi_analyzer')

# API 配置
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/search"
FEAR_GREED_API = "https://api.alternative.me/fng/"
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
BINANCE_FUNDING = "https://fapi.binance.com/fapi/v1/fundingRate"


class DataFetcher:
    """数据获取器"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def ensure_session(self):
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self.session = aiohttp.ClientSession(timeout=timeout)
    
    async def fetch(self, url: str, params: dict = None) -> Optional[dict]:
        """获取 JSON 数据"""
        await self.ensure_session()
        try:
            async with self.session.get(url, params=params, ssl=False) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.warning(f"获取数据失败 {url}: {e}")
        return None
    
    async def close(self):
        if self.session:
            await self.session.close()


class MultiDimensionalAnalyzer:
    """多维度 AI 分析器"""
    
    def __init__(self, claude_api_key: str = None):
        self.fetcher = DataFetcher()
        self.claude_api_key = claude_api_key or os.getenv('CLAUDE_API_KEY')
        
        logger.info("✅ MultiDimensionalAnalyzer 初始化完成")
    
    async def analyze(self, event: dict) -> dict:
        """
        多维度分析入口
        
        参数:
            event: 上币事件信息
        
        返回:
            分析结果字典
        """
        symbol = event.get('symbol', '')
        exchange = event.get('exchange', 'unknown')
        
        logger.info(f"🔍 开始多维度分析: {symbol}@{exchange}")
        
        # 并行获取所有数据
        tasks = [
            self.get_liquidity_data(symbol),
            self.get_sentiment_data(symbol),
            self.get_macro_data(),
            self.get_token_metrics(symbol),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        liquidity = results[0] if not isinstance(results[0], Exception) else {}
        sentiment = results[1] if not isinstance(results[1], Exception) else {}
        macro = results[2] if not isinstance(results[2], Exception) else {}
        token_metrics = results[3] if not isinstance(results[3], Exception) else {}
        
        # AI 综合分析
        analysis = await self.ai_analyze({
            'event': event,
            'liquidity': liquidity,
            'sentiment': sentiment,
            'macro': macro,
            'token_metrics': token_metrics,
        })
        
        return analysis
    
    async def get_liquidity_data(self, symbol: str) -> dict:
        """获取流动性数据"""
        result = {
            'dex_liquidity_usd': 0,
            'dex_volume_24h': 0,
            'dex_price_change_24h': 0,
            'dex': '',
            'chain': '',
            'pairs_count': 0,
        }
        
        try:
            data = await self.fetcher.fetch(f"{DEXSCREENER_API}?q={symbol}")
            if data and 'pairs' in data:
                pairs = data['pairs']
                
                # 精确匹配
                exact_matches = [
                    p for p in pairs 
                    if p.get('baseToken', {}).get('symbol', '').upper() == symbol.upper()
                ]
                
                if exact_matches:
                    # 按流动性排序
                    exact_matches.sort(
                        key=lambda x: float(x.get('liquidity', {}).get('usd', 0) or 0), 
                        reverse=True
                    )
                    best = exact_matches[0]
                    
                    result['dex_liquidity_usd'] = float(best.get('liquidity', {}).get('usd', 0) or 0)
                    result['dex_volume_24h'] = float(best.get('volume', {}).get('h24', 0) or 0)
                    result['dex_price_change_24h'] = float(best.get('priceChange', {}).get('h24', 0) or 0)
                    result['dex'] = best.get('dexId', '')
                    result['chain'] = best.get('chainId', '')
                    result['pairs_count'] = len(exact_matches)
                    
                    logger.debug(f"DEX 流动性: ${result['dex_liquidity_usd']:,.0f}")
        except Exception as e:
            logger.warning(f"获取流动性数据失败: {e}")
        
        return result
    
    async def get_sentiment_data(self, symbol: str = None) -> dict:
        """获取市场情绪数据"""
        result = {
            'fear_greed_value': 50,
            'fear_greed_class': 'Neutral',
            'funding_rate': 0,
            'funding_sentiment': 'neutral',
        }
        
        # 恐慌贪婪指数
        try:
            data = await self.fetcher.fetch(FEAR_GREED_API)
            if data and 'data' in data and data['data']:
                fng = data['data'][0]
                result['fear_greed_value'] = int(fng.get('value', 50))
                result['fear_greed_class'] = fng.get('value_classification', 'Neutral')
                logger.debug(f"恐慌贪婪指数: {result['fear_greed_value']} ({result['fear_greed_class']})")
        except Exception as e:
            logger.warning(f"获取恐慌贪婪指数失败: {e}")
        
        # 资金费率（如果有符号）
        if symbol:
            try:
                data = await self.fetcher.fetch(
                    BINANCE_FUNDING, 
                    params={'symbol': f'{symbol}USDT', 'limit': '1'}
                )
                if data and len(data) > 0:
                    rate = float(data[0].get('fundingRate', 0))
                    result['funding_rate'] = rate
                    result['funding_sentiment'] = (
                        'bullish' if rate > 0.0001 else 
                        'bearish' if rate < -0.0001 else 
                        'neutral'
                    )
            except:
                pass
        
        return result
    
    async def get_macro_data(self) -> dict:
        """获取宏观环境数据"""
        result = {
            'btc_dominance': 0,
            'total_market_cap': 0,
            'market_cap_change_24h': 0,
            'market_trend': 'neutral',
        }
        
        try:
            data = await self.fetcher.fetch(COINGECKO_GLOBAL)
            if data and 'data' in data:
                gd = data['data']
                result['btc_dominance'] = round(gd.get('market_cap_percentage', {}).get('btc', 0), 2)
                result['total_market_cap'] = gd.get('total_market_cap', {}).get('usd', 0)
                result['market_cap_change_24h'] = round(gd.get('market_cap_change_percentage_24h_usd', 0), 2)
                
                # 判断趋势
                change = result['market_cap_change_24h']
                result['market_trend'] = (
                    'bullish' if change > 2 else
                    'bearish' if change < -2 else
                    'neutral'
                )
                
                logger.debug(f"宏观: BTC占比={result['btc_dominance']}%, 变化={change}%")
        except Exception as e:
            logger.warning(f"获取宏观数据失败: {e}")
        
        return result
    
    async def get_token_metrics(self, symbol: str) -> dict:
        """获取代币指标"""
        result = {
            'market_cap': 0,
            'fdv': 0,
            'circulating_supply': 0,
            'total_supply': 0,
            'age_days': 0,
        }
        
        # CoinGecko 搜索
        try:
            search_url = f"https://api.coingecko.com/api/v3/search?query={symbol}"
            data = await self.fetcher.fetch(search_url)
            if data and 'coins' in data and data['coins']:
                # 找到匹配的币
                for coin in data['coins']:
                    if coin.get('symbol', '').upper() == symbol.upper():
                        coin_id = coin.get('id')
                        if coin_id:
                            # 获取详情
                            detail_url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
                            detail = await self.fetcher.fetch(detail_url)
                            if detail and 'market_data' in detail:
                                md = detail['market_data']
                                result['market_cap'] = md.get('market_cap', {}).get('usd', 0) or 0
                                result['fdv'] = md.get('fully_diluted_valuation', {}).get('usd', 0) or 0
                                result['circulating_supply'] = md.get('circulating_supply', 0) or 0
                                result['total_supply'] = md.get('total_supply', 0) or 0
                        break
        except Exception as e:
            logger.warning(f"获取代币指标失败: {e}")
        
        return result
    
    async def ai_analyze(self, data: dict) -> dict:
        """AI 综合分析"""
        
        # 如果没有 Claude API Key，使用规则引擎
        if not self.claude_api_key:
            return self._rule_based_analysis(data)
        
        # 使用 Claude API
        try:
            import anthropic
            
            client = anthropic.Anthropic(api_key=self.claude_api_key)
            
            prompt = self._build_prompt(data)
            
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # 解析 JSON 响应
            text = response.content[0].text
            
            # 尝试提取 JSON
            import re
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                return json.loads(json_match.group())
            
            return {'error': 'AI 响应解析失败', 'raw': text}
            
        except Exception as e:
            logger.error(f"AI 分析失败: {e}")
            return self._rule_based_analysis(data)
    
    def _build_prompt(self, data: dict) -> str:
        """构建 AI 分析提示词"""
        event = data['event']
        liquidity = data['liquidity']
        sentiment = data['sentiment']
        macro = data['macro']
        token = data['token_metrics']
        
        return f"""请分析以下加密货币上币事件，输出 JSON 格式的分析结果。

## 上币信息
- 交易所: {event.get('exchange', 'unknown')}
- 代币: {event.get('symbol', 'unknown')}
- 事件类型: {event.get('event_type', 'unknown')}
- 公告: {event.get('raw_text', '')[:300]}

## 流动性数据
- DEX 流动性: ${liquidity.get('dex_liquidity_usd', 0):,.0f}
- 24h 交易量: ${liquidity.get('dex_volume_24h', 0):,.0f}
- 24h 价格变化: {liquidity.get('dex_price_change_24h', 0):.1f}%
- DEX/链: {liquidity.get('dex', '')} / {liquidity.get('chain', '')}

## 市场情绪
- 恐慌贪婪指数: {sentiment.get('fear_greed_value', 50)} ({sentiment.get('fear_greed_class', 'Neutral')})
- 资金费率情绪: {sentiment.get('funding_sentiment', 'neutral')}

## 宏观环境
- BTC 市占率: {macro.get('btc_dominance', 0)}%
- 24h 市值变化: {macro.get('market_cap_change_24h', 0)}%
- 市场趋势: {macro.get('market_trend', 'neutral')}

## 代币指标
- 市值: ${token.get('market_cap', 0):,.0f}
- FDV: ${token.get('fdv', 0):,.0f}

请输出以下 JSON 格式（不要有其他文字）:
{{
  "liquidity_score": 0-100,
  "liquidity_level": "high/medium/low/none",
  "sentiment_score": 0-100,
  "market_mood": "extreme_greed/greed/neutral/fear/extreme_fear",
  "macro_score": 0-100,
  "macro_trend": "bullish/neutral/bearish",
  "comprehensive_score": 0-100,
  "trade_action": "strong_buy/buy/hold/avoid",
  "position_size": "full/half/quarter/minimal",
  "risk_factors": ["风险1", "风险2"],
  "opportunities": ["机会1", "机会2"],
  "reasoning": "简短分析理由"
}}"""
    
    def _rule_based_analysis(self, data: dict) -> dict:
        """基于规则的分析（无 AI 时使用）"""
        liquidity = data.get('liquidity', {})
        sentiment = data.get('sentiment', {})
        macro = data.get('macro', {})
        event = data.get('event', {})
        
        # 流动性评分
        liq_usd = liquidity.get('dex_liquidity_usd', 0)
        if liq_usd >= 1000000:
            liq_score = 90
            liq_level = 'high'
        elif liq_usd >= 100000:
            liq_score = 60
            liq_level = 'medium'
        elif liq_usd >= 10000:
            liq_score = 30
            liq_level = 'low'
        else:
            liq_score = 10
            liq_level = 'none'
        
        # 情绪评分
        fng = sentiment.get('fear_greed_value', 50)
        if fng >= 75:
            sent_score = 80
            mood = 'extreme_greed'
        elif fng >= 55:
            sent_score = 65
            mood = 'greed'
        elif fng >= 45:
            sent_score = 50
            mood = 'neutral'
        elif fng >= 25:
            sent_score = 35
            mood = 'fear'
        else:
            sent_score = 20
            mood = 'extreme_fear'
        
        # 宏观评分
        mc_change = macro.get('market_cap_change_24h', 0)
        if mc_change > 3:
            macro_score = 80
            m_trend = 'bullish'
        elif mc_change > 0:
            macro_score = 60
            m_trend = 'neutral'
        elif mc_change > -3:
            macro_score = 40
            m_trend = 'neutral'
        else:
            macro_score = 20
            m_trend = 'bearish'
        
        # 综合评分
        comp_score = int(liq_score * 0.3 + sent_score * 0.3 + macro_score * 0.4)
        
        # 交易建议
        if comp_score >= 75 and liq_level in ['high', 'medium']:
            action = 'strong_buy'
            position = 'full'
        elif comp_score >= 60:
            action = 'buy'
            position = 'half'
        elif comp_score >= 40:
            action = 'hold'
            position = 'quarter'
        else:
            action = 'avoid'
            position = 'minimal'
        
        # 风险和机会
        risks = []
        opps = []
        
        if liq_level in ['low', 'none']:
            risks.append('流动性不足，滑点风险大')
        if mood in ['extreme_greed']:
            risks.append('市场过度贪婪，回调风险')
        if m_trend == 'bearish':
            risks.append('市场下跌趋势')
        
        if liq_level == 'high':
            opps.append('流动性充足，易于交易')
        if mood in ['fear', 'extreme_fear']:
            opps.append('市场恐慌，可能是买入机会')
        if event.get('exchange') in ['binance', 'coinbase', 'upbit']:
            opps.append(f"上线 Tier-1 交易所 ({event.get('exchange')})")
        
        return {
            'liquidity_score': liq_score,
            'liquidity_level': liq_level,
            'sentiment_score': sent_score,
            'market_mood': mood,
            'macro_score': macro_score,
            'macro_trend': m_trend,
            'comprehensive_score': comp_score,
            'trade_action': action,
            'position_size': position,
            'risk_factors': risks,
            'opportunities': opps,
            'reasoning': f"综合评分 {comp_score}/100，流动性{liq_level}，市场{mood}，趋势{m_trend}",
            'source': 'rule_based',
        }
    
    async def close(self):
        await self.fetcher.close()


# 单例
_analyzer: Optional[MultiDimensionalAnalyzer] = None

def get_analyzer() -> MultiDimensionalAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = MultiDimensionalAnalyzer()
    return _analyzer


# 测试
if __name__ == '__main__':
    async def test():
        analyzer = MultiDimensionalAnalyzer()
        
        result = await analyzer.analyze({
            'symbol': 'BTC',
            'exchange': 'binance',
            'event_type': 'new_listing',
            'raw_text': 'Binance will list Bitcoin',
        })
        
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
        await analyzer.close()
    
    asyncio.run(test())

