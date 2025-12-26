#!/usr/bin/env python3
"""
信号评级系统
============
将评分转换为买入评级，指导交易决策
"""

import os
from enum import Enum
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logging import get_logger

logger = get_logger('signal_rating')


class BuyRating(Enum):
    """买入评级"""
    SSS = "SSS"  # 必买 - 极强信号
    SS = "SS"    # 强买 - 强信号
    S = "S"      # 建议买 - 较强信号
    A = "A"      # 可买 - 中等信号
    B = "B"      # 观望 - 弱信号
    C = "C"      # 不买 - 信号不足
    X = "X"      # 禁止 - 危险信号


@dataclass
class RatingResult:
    """评级结果"""
    rating: BuyRating
    score: int
    confidence: float  # 0-1
    
    # 买入建议
    should_buy: bool
    position_percent: float  # 建议仓位比例 0-100%
    max_amount_usd: float    # 最大买入金额
    
    # 理由
    reasons: list
    warnings: list
    
    def to_dict(self) -> Dict:
        return {
            'rating': self.rating.value,
            'score': self.score,
            'confidence': self.confidence,
            'should_buy': self.should_buy,
            'position_percent': self.position_percent,
            'max_amount_usd': self.max_amount_usd,
            'reasons': self.reasons,
            'warnings': self.warnings,
        }


# ============================================================
# 评分体系说明
# ============================================================
"""
📊 评分体系 (0-100分)

1️⃣ 基础分 (0-40分)
   - 信息源质量:
     * Tier-S 源 (官方公告): 35-40分
     * Tier-A 源 (权威媒体): 25-35分
     * Tier-B 源 (知名KOL): 15-25分
     * Tier-C 源 (普通频道): 5-15分
     * 未知源: 0-5分

2️⃣ 交易所乘数 (0.5x - 2.0x)
   - Binance/Coinbase: 2.0x
   - OKX/Bybit/Kraken: 1.5x
   - Upbit/Bithumb: 1.3x (韩国溢价)
   - KuCoin/Gate: 1.2x
   - Bitget/MEXC: 1.0x
   - 其他: 0.8x

3️⃣ 时效性乘数 (0.5x - 1.5x)
   - <1分钟: 1.5x
   - 1-5分钟: 1.2x
   - 5-15分钟: 1.0x
   - 15-60分钟: 0.7x
   - >1小时: 0.5x

4️⃣ 多源加分 (0-50分)
   - 2个源确认: +15分
   - 3个源确认: +25分
   - 4+个源确认: +35分
   - 多交易所确认: +50分

5️⃣ 代币类型调整
   - 新币 (≤7天): +10分
   - 近期币 (7-30天): +5分
   - Meme币: +5分 (高波动机会)
   - 稳定币: -100分 (不交易)
   - 包装代币: -100分 (不交易)
"""

# ============================================================
# 评级阈值
# ============================================================
RATING_THRESHOLDS = {
    BuyRating.SSS: 95,  # ≥95: 必买
    BuyRating.SS: 85,   # ≥85: 强买
    BuyRating.S: 75,    # ≥75: 建议买
    BuyRating.A: 60,    # ≥60: 可买
    BuyRating.B: 40,    # ≥40: 观望
    BuyRating.C: 0,     # ≥0: 不买
}

# 仓位配置
POSITION_CONFIG = {
    BuyRating.SSS: {'percent': 15, 'max_usd': 500},
    BuyRating.SS: {'percent': 10, 'max_usd': 300},
    BuyRating.S: {'percent': 7, 'max_usd': 200},
    BuyRating.A: {'percent': 5, 'max_usd': 100},
    BuyRating.B: {'percent': 0, 'max_usd': 0},
    BuyRating.C: {'percent': 0, 'max_usd': 0},
    BuyRating.X: {'percent': 0, 'max_usd': 0},
}


class SignalRater:
    """信号评级器"""
    
    def __init__(self):
        # 加载配置
        self.base_position = float(os.getenv('TRADE_MAX_POSITION_PERCENT', 10))
        self.max_trade_usd = float(os.getenv('MAX_TRADE_AMOUNT_USD', 500))
        
        logger.info("SignalRater 初始化完成")
    
    def rate(self, 
             score: int,
             token_type: str = 'unknown',
             source_type: str = 'unknown',
             source_count: int = 1,
             exchange_count: int = 0,
             is_super_event: bool = False,
             safety_score: int = 100,
             liquidity_usd: float = 0) -> RatingResult:
        """
        评估信号并给出买入评级
        
        Args:
            score: 融合引擎评分 (0-100)
            token_type: 代币类型
            source_type: 信息源类型
            source_count: 信号源数量
            exchange_count: 交易所数量
            is_super_event: 是否超级事件
            safety_score: 安全检查分数 (0-100)
            liquidity_usd: 流动性 (USD)
        
        Returns:
            RatingResult
        """
        reasons = []
        warnings = []
        
        # 1. 基础评分调整
        adjusted_score = score
        
        # 2. 代币类型调整
        if token_type == 'new_token':
            adjusted_score += 10
            reasons.append("新币加成 +10")
        elif token_type == 'recent_token':
            adjusted_score += 5
            reasons.append("近期币加成 +5")
        elif token_type == 'meme':
            adjusted_score += 5
            reasons.append("Meme币加成 +5")
        elif token_type in ['stablecoin', 'wrapped']:
            return RatingResult(
                rating=BuyRating.X,
                score=0,
                confidence=0,
                should_buy=False,
                position_percent=0,
                max_amount_usd=0,
                reasons=[],
                warnings=[f"禁止交易: {token_type}"]
            )
        
        # 3. 信号源类型加成
        if source_type == 'cex_listing':
            adjusted_score += 15
            reasons.append("CEX上币信号 +15")
        elif source_type == 'dex_pool':
            adjusted_score += 10
            reasons.append("DEX新池信号 +10")
        elif source_type == 'whale':
            adjusted_score += 8
            reasons.append("鲸鱼信号 +8")
        
        # 4. 多源确认加成
        if is_super_event:
            adjusted_score += 20
            reasons.append("超级事件确认 +20")
        elif exchange_count >= 2:
            adjusted_score += 15
            reasons.append(f"多交易所确认({exchange_count}所) +15")
        elif source_count >= 3:
            adjusted_score += 10
            reasons.append(f"多源确认({source_count}源) +10")
        elif source_count >= 2:
            adjusted_score += 5
            reasons.append(f"双源确认 +5")
        
        # 5. 安全检查调整
        if safety_score < 50:
            adjusted_score -= 30
            warnings.append(f"安全评分低 ({safety_score})")
        elif safety_score < 70:
            adjusted_score -= 15
            warnings.append(f"安全评分中等 ({safety_score})")
        
        # 6. 流动性检查
        if liquidity_usd > 0:
            if liquidity_usd < 10000:
                adjusted_score -= 20
                warnings.append(f"流动性过低 (${liquidity_usd:.0f})")
            elif liquidity_usd < 50000:
                adjusted_score -= 10
                warnings.append(f"流动性较低 (${liquidity_usd:.0f})")
            elif liquidity_usd > 500000:
                adjusted_score += 5
                reasons.append(f"流动性充足 (${liquidity_usd/1000:.0f}K)")
        
        # 7. 限制分数范围
        adjusted_score = max(0, min(100, adjusted_score))
        
        # 8. 确定评级
        rating = self._get_rating(adjusted_score)
        
        # 9. 计算置信度
        confidence = self._calculate_confidence(
            adjusted_score, source_count, safety_score
        )
        
        # 10. 计算仓位
        position_config = POSITION_CONFIG[rating]
        position_percent = position_config['percent'] * (confidence ** 0.5)
        max_amount = min(
            position_config['max_usd'],
            self.max_trade_usd * confidence
        )
        
        # 11. 判断是否买入
        should_buy = rating in [BuyRating.SSS, BuyRating.SS, BuyRating.S, BuyRating.A]
        
        return RatingResult(
            rating=rating,
            score=adjusted_score,
            confidence=confidence,
            should_buy=should_buy,
            position_percent=position_percent,
            max_amount_usd=max_amount,
            reasons=reasons,
            warnings=warnings,
        )
    
    def _get_rating(self, score: int) -> BuyRating:
        """根据分数确定评级"""
        for rating, threshold in RATING_THRESHOLDS.items():
            if score >= threshold:
                return rating
        return BuyRating.C
    
    def _calculate_confidence(self, score: int, source_count: int, 
                              safety_score: int) -> float:
        """计算置信度"""
        # 基础置信度
        base_conf = score / 100
        
        # 多源加成
        source_mult = min(1.0 + (source_count - 1) * 0.1, 1.3)
        
        # 安全调整
        safety_mult = safety_score / 100
        
        confidence = base_conf * source_mult * safety_mult
        return min(1.0, max(0.1, confidence))
    
    def get_rating_display(self, rating: BuyRating) -> Dict:
        """获取评级显示信息"""
        displays = {
            BuyRating.SSS: {
                'label': 'SSS',
                'cn': '必买',
                'color': '#FF0000',
                'emoji': '🔥🔥🔥',
                'action': '立即全仓买入',
            },
            BuyRating.SS: {
                'label': 'SS',
                'cn': '强买',
                'color': '#FF6600',
                'emoji': '🔥🔥',
                'action': '建议重仓买入',
            },
            BuyRating.S: {
                'label': 'S',
                'cn': '建议买',
                'color': '#FFAA00',
                'emoji': '🔥',
                'action': '建议适量买入',
            },
            BuyRating.A: {
                'label': 'A',
                'cn': '可买',
                'color': '#00AA00',
                'emoji': '✅',
                'action': '可小仓位试水',
            },
            BuyRating.B: {
                'label': 'B',
                'cn': '观望',
                'color': '#888888',
                'emoji': '👀',
                'action': '观察等待',
            },
            BuyRating.C: {
                'label': 'C',
                'cn': '不买',
                'color': '#AAAAAA',
                'emoji': '⏸️',
                'action': '信号不足',
            },
            BuyRating.X: {
                'label': 'X',
                'cn': '禁止',
                'color': '#000000',
                'emoji': '🚫',
                'action': '禁止交易',
            },
        }
        return displays.get(rating, displays[BuyRating.C])


# 全局实例
_rater: Optional[SignalRater] = None

def get_rater() -> SignalRater:
    global _rater
    if _rater is None:
        _rater = SignalRater()
    return _rater


# ============================================================
# 评分体系汇总表
# ============================================================
RATING_TABLE = """
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                        📊 信号评分体系                               ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃                                                                      ┃
┃  1️⃣ 基础分 (0-40分)                                                  ┃
┃  ┌────────────────────┬────────────┐                                ┃
┃  │ Tier-S (官方公告)   │ 35-40 分   │                                ┃
┃  │ Tier-A (权威媒体)   │ 25-35 分   │                                ┃
┃  │ Tier-B (知名KOL)    │ 15-25 分   │                                ┃
┃  │ Tier-C (普通频道)   │ 5-15 分    │                                ┃
┃  │ 未知源             │ 0-5 分     │                                ┃
┃  └────────────────────┴────────────┘                                ┃
┃                                                                      ┃
┃  2️⃣ 交易所乘数 (0.5x - 2.0x)                                        ┃
┃  ┌────────────────────┬────────────┐                                ┃
┃  │ Binance/Coinbase   │ 2.0x       │                                ┃
┃  │ OKX/Bybit/Kraken   │ 1.5x       │                                ┃
┃  │ Upbit/Bithumb      │ 1.3x       │                                ┃
┃  │ KuCoin/Gate        │ 1.2x       │                                ┃
┃  │ Bitget/MEXC        │ 1.0x       │                                ┃
┃  │ 其他               │ 0.8x       │                                ┃
┃  └────────────────────┴────────────┘                                ┃
┃                                                                      ┃
┃  3️⃣ 时效性乘数 (0.5x - 1.5x)                                        ┃
┃  ┌────────────────────┬────────────┐                                ┃
┃  │ <1 分钟            │ 1.5x       │                                ┃
┃  │ 1-5 分钟           │ 1.2x       │                                ┃
┃  │ 5-15 分钟          │ 1.0x       │                                ┃
┃  │ 15-60 分钟         │ 0.7x       │                                ┃
┃  │ >1 小时            │ 0.5x       │                                ┃
┃  └────────────────────┴────────────┘                                ┃
┃                                                                      ┃
┃  4️⃣ 多源加分 (0-50分)                                                ┃
┃  ┌────────────────────┬────────────┐                                ┃
┃  │ 2 源确认           │ +15 分     │                                ┃
┃  │ 3 源确认           │ +25 分     │                                ┃
┃  │ 4+ 源确认          │ +35 分     │                                ┃
┃  │ 多交易所确认       │ +50 分     │                                ┃
┃  └────────────────────┴────────────┘                                ┃
┃                                                                      ┃
┃  5️⃣ 代币类型调整                                                     ┃
┃  ┌────────────────────┬────────────┐                                ┃
┃  │ 新币 (≤7天)        │ +10 分     │                                ┃
┃  │ 近期币 (7-30天)    │ +5 分      │                                ┃
┃  │ Meme币             │ +5 分      │                                ┃
┃  │ 稳定币/包装代币    │ ❌ 禁止    │                                ┃
┃  └────────────────────┴────────────┘                                ┃
┃                                                                      ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃                        🏆 买入评级                                   ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃                                                                      ┃
┃  ┌────┬────────┬─────────┬────────────────────────┐                 ┃
┃  │等级│ 分数   │ 仓位    │ 建议操作               │                 ┃
┃  ├────┼────────┼─────────┼────────────────────────┤                 ┃
┃  │SSS │ ≥95    │ 15%     │ 🔥🔥🔥 必买 - 立即全仓   │                 ┃
┃  │ SS │ ≥85    │ 10%     │ 🔥🔥 强买 - 重仓买入    │                 ┃
┃  │ S  │ ≥75    │ 7%      │ 🔥 建议买 - 适量买入   │                 ┃
┃  │ A  │ ≥60    │ 5%      │ ✅ 可买 - 小仓试水     │                 ┃
┃  │ B  │ ≥40    │ 0%      │ 👀 观望 - 等待确认     │                 ┃
┃  │ C  │ <40    │ 0%      │ ⏸️ 不买 - 信号不足     │                 ┃
┃  │ X  │ -      │ 0%      │ 🚫 禁止 - 危险信号     │                 ┃
┃  └────┴────────┴─────────┴────────────────────────┘                 ┃
┃                                                                      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
"""


if __name__ == '__main__':
    print(RATING_TABLE)
    
    # 测试评级
    rater = get_rater()
    
    print("\n=== 测试评级 ===\n")
    
    test_cases = [
        {'score': 95, 'token_type': 'new_token', 'source_type': 'cex_listing', 'source_count': 3},
        {'score': 75, 'token_type': 'meme', 'source_type': 'telegram', 'source_count': 2},
        {'score': 50, 'token_type': 'unknown', 'source_type': 'news', 'source_count': 1},
        {'score': 80, 'token_type': 'stablecoin', 'source_type': 'cex_listing', 'source_count': 1},
    ]
    
    for case in test_cases:
        result = rater.rate(**case)
        display = rater.get_rating_display(result.rating)
        print(f"输入: {case}")
        print(f"评级: {display['emoji']} {result.rating.value} ({display['cn']})")
        print(f"调整分: {result.score} | 置信度: {result.confidence:.2f}")
        print(f"买入: {'是' if result.should_buy else '否'} | 仓位: {result.position_percent:.1f}%")
        print(f"理由: {result.reasons}")
        print(f"警告: {result.warnings}")
        print()

