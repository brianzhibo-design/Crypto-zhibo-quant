#!/usr/bin/env python3
"""
评分引擎 v4 本地测试
"""

import sys
from pathlib import Path

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fusion.scoring_engine import (
    InstitutionalScorer, 
    detect_event_type,
    SOURCE_SCORES,
    EVENT_TYPE_SCORES,
    EXCHANGE_MULTIPLIERS,
    TRIGGER_THRESHOLD
)


def test_event_type_detection():
    """测试事件类型检测"""
    print("\n" + "=" * 60)
    print("测试 1: 事件类型检测")
    print("=" * 60)
    
    test_cases = [
        {"raw_text": "Binance will list XYZ token", "expected": "will_list_announcement"},
        {"raw_text": "即将上线 ABC 代币", "expected": "will_list_announcement"},
        {"raw_text": "Binance Alpha lists new tokens: COLLECT", "expected": "alpha_listing"},
        {"raw_text": "New perpetual contract for BTC", "expected": "futures_listing"},
        {"raw_text": "Launchpool: Stake BNB to earn XYZ", "expected": "launchpool"},
        {"raw_text": "Deposit opens for ABC token", "expected": "deposit_open"},
        {"raw_text": "Trading opens for XYZ/USDT", "expected": "trading_open"},
        {"raw_text": "XYZ will be delisted", "expected": "delisting"},
        {"raw_text": "New listing: ABC token", "expected": "new_listing"},
        {"raw_text": "Random message about crypto", "expected": "unknown"},
    ]
    
    passed = 0
    for case in test_cases:
        result = detect_event_type(case)
        status = "✅" if result == case["expected"] else "❌"
        if result == case["expected"]:
            passed += 1
        print(f"{status} '{case['raw_text'][:40]}...' -> {result} (期望: {case['expected']})")
    
    print(f"\n结果: {passed}/{len(test_cases)} 通过")
    return passed == len(test_cases)


def test_source_classification():
    """测试来源分类"""
    print("\n" + "=" * 60)
    print("测试 2: 来源分类")
    print("=" * 60)
    
    scorer = InstitutionalScorer()
    
    test_cases = [
        # Telegram 频道
        {"source": "telegram", "channel": "formula_news", "expected": "tg_alpha_intel"},
        {"source": "telegram", "channel": "binance_announcements", "expected": "tg_exchange_official"},
        {"source": "telegram", "raw_text": "Binance Alpha lists new tokens", "expected": "tg_alpha_intel"},
        
        # REST API
        {"source": "rest_api", "exchange": "binance", "expected": "rest_api_binance"},
        {"source": "rest_api", "exchange": "okx", "expected": "rest_api_okx"},
        {"source": "rest_api", "exchange": "gate", "expected": "rest_api_tier2"},
        {"source": "rest_api", "exchange": "mexc", "expected": "rest_api"},
        
        # WebSocket
        {"source": "websocket", "exchange": "binance", "expected": "ws_binance"},
        {"source": "websocket", "exchange": "okx", "expected": "ws_okx"},
        
        # 韩国市场
        {"source": "rest_api", "exchange": "upbit", "expected": "rest_api_upbit"},
        {"source": "kr_market", "exchange": "bithumb", "expected": "kr_market"},
    ]
    
    passed = 0
    for case in test_cases:
        result = scorer.classify_source(case)
        status = "✅" if result == case["expected"] else "❌"
        if result == case["expected"]:
            passed += 1
        desc = f"source={case.get('source', '-')}, exchange={case.get('exchange', '-')}"
        print(f"{status} {desc} -> {result} (期望: {case['expected']})")
    
    print(f"\n结果: {passed}/{len(test_cases)} 通过")
    return passed == len(test_cases)


def test_scoring_scenarios():
    """测试评分场景"""
    print("\n" + "=" * 60)
    print("测试 3: 评分场景")
    print("=" * 60)
    
    scorer = InstitutionalScorer()
    
    scenarios = [
        {
            "name": "方程式爆料 Binance 即将上币",
            "event": {
                "source": "telegram",
                "channel": "formula_news",
                "exchange": "binance",
                "symbol": "XAI",
                "raw_text": "Binance will list XAI token tomorrow",
            },
            "expected_min_score": 200,
            "should_trigger": True,
        },
        {
            "name": "Binance 官方公告新币",
            "event": {
                "source": "telegram",
                "channel": "binance_announcements",
                "exchange": "binance",
                "symbol": "ABC",
                "raw_text": "New listing: ABC token trading opens",
            },
            "expected_min_score": 100,
            "should_trigger": True,
        },
        {
            "name": "Binance REST API 检测新币",
            "event": {
                "source": "rest_api",
                "exchange": "binance",
                "symbol": "DEF",
                "raw_text": "New trading pair: DEF/USDT",
            },
            "expected_min_score": 80,
            "should_trigger": True,
        },
        {
            "name": "MEXC WebSocket 检测",
            "event": {
                "source": "websocket",
                "exchange": "mexc",
                "symbol": "GHI",
                "raw_text": "New pair detected",
            },
            "expected_min_score": 20,
            "should_trigger": False,
        },
        {
            "name": "合约上线（应忽略）",
            "event": {
                "source": "rest_api",
                "exchange": "binance",
                "symbol": "BTC",
                "raw_text": "New perpetual contract for BTC",
            },
            "expected_min_score": 50,
            "should_trigger": False,  # 因为是 futures_listing
        },
        {
            "name": "下架事件（负面）",
            "event": {
                "source": "telegram",
                "channel": "binance_announcements",
                "exchange": "binance",
                "symbol": "SCAM",
                "raw_text": "SCAM token will be delisted",
            },
            "expected_min_score": 0,
            "should_trigger": False,
        },
        {
            "name": "Upbit 上币（韩国泵）",
            "event": {
                "source": "rest_api",
                "exchange": "upbit",
                "symbol": "JKL",
                "raw_text": "New listing on Upbit",
            },
            "expected_min_score": 80,
            "should_trigger": True,
        },
        {
            "name": "普通新闻（低价值）",
            "event": {
                "source": "news",
                "symbol": "MNO",
                "raw_text": "MNO token listed on exchange",
            },
            "expected_min_score": 5,
            "should_trigger": False,
        },
    ]
    
    passed = 0
    for scenario in scenarios:
        result = scorer.calculate_score(scenario["event"])
        
        score_ok = result["total_score"] >= scenario["expected_min_score"]
        trigger_ok = result["should_trigger"] == scenario["should_trigger"]
        
        status = "✅" if (score_ok and trigger_ok) else "❌"
        if score_ok and trigger_ok:
            passed += 1
        
        print(f"\n{status} {scenario['name']}")
        print(f"   评分: {result['total_score']:.1f} (期望≥{scenario['expected_min_score']})")
        print(f"   来源: {result['classified_source']} (基础分:{result['base_score']})")
        print(f"   类型: {result['event_type']} (类型分:{result['event_score']})")
        print(f"   乘数: 交易所={result['exchange_multiplier']}x, 时效={result['freshness_multiplier']}x")
        print(f"   加分: 多源={result['multi_bonus']}, 韩国={result['korean_bonus']}")
        print(f"   触发: {result['should_trigger']} - {result['trigger_reason']}")
    
    print(f"\n结果: {passed}/{len(scenarios)} 通过")
    return passed == len(scenarios)


def test_multi_exchange():
    """测试多交易所确认"""
    print("\n" + "=" * 60)
    print("测试 4: 多交易所确认加分")
    print("=" * 60)
    
    scorer = InstitutionalScorer()
    
    # 模拟同一币种在多个交易所被检测
    events = [
        {"source": "rest_api", "exchange": "gate", "symbol": "MULTI", "raw_text": "New listing"},
        {"source": "rest_api", "exchange": "kucoin", "symbol": "MULTI", "raw_text": "New listing"},
        {"source": "rest_api", "exchange": "bitget", "symbol": "MULTI", "raw_text": "New listing"},
    ]
    
    for i, event in enumerate(events, 1):
        result = scorer.calculate_score(event)
        print(f"\n第 {i} 个交易所 ({event['exchange']}):")
        print(f"   评分: {result['total_score']:.1f}")
        print(f"   交易所数: {result['exchange_count']}")
        print(f"   多所加分: {result['multi_bonus']}")
        print(f"   触发: {result['should_trigger']} - {result['trigger_reason']}")
    
    # 第3个应该触发多所确认
    final_result = scorer.calculate_score(events[-1])
    passed = final_result['exchange_count'] >= 3 and final_result['multi_bonus'] >= 50
    print(f"\n结果: {'✅ 通过' if passed else '❌ 失败'}")
    return passed


def test_freshness():
    """测试时效性乘数"""
    print("\n" + "=" * 60)
    print("测试 5: 时效性乘数")
    print("=" * 60)
    
    import time
    scorer = InstitutionalScorer()
    
    # 首次发现
    event1 = {"source": "rest_api", "exchange": "binance", "symbol": "FRESH", "raw_text": "New listing"}
    result1 = scorer.calculate_score(event1)
    print(f"首次发现: 时效乘数 = {result1['freshness_multiplier']} (期望: 1.3)")
    
    # 模拟延迟（修改 first_seen）
    scorer.symbol_first_seen["FRESH"] = time.time() - 100  # 100秒前
    result2 = scorer.calculate_score(event1)
    print(f"100秒后: 时效乘数 = {result2['freshness_multiplier']} (期望: 0.8-1.0)")
    
    scorer.symbol_first_seen["FRESH"] = time.time() - 700  # 700秒前
    result3 = scorer.calculate_score(event1)
    print(f"700秒后: 时效乘数 = {result3['freshness_multiplier']} (期望: 0.5)")
    
    passed = result1['freshness_multiplier'] >= 1.2 and result3['freshness_multiplier'] <= 0.6
    print(f"\n结果: {'✅ 通过' if passed else '❌ 失败'}")
    return passed


def main():
    print("=" * 60)
    print("评分引擎 v4 本地测试")
    print("=" * 60)
    print(f"触发阈值: {TRIGGER_THRESHOLD}")
    print(f"来源评分数量: {len(SOURCE_SCORES)}")
    print(f"事件类型数量: {len(EVENT_TYPE_SCORES)}")
    print(f"交易所乘数数量: {len(EXCHANGE_MULTIPLIERS)}")
    
    results = []
    results.append(("事件类型检测", test_event_type_detection()))
    results.append(("来源分类", test_source_classification()))
    results.append(("评分场景", test_scoring_scenarios()))
    results.append(("多交易所确认", test_multi_exchange()))
    results.append(("时效性乘数", test_freshness()))
    
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{status} - {name}")
        if not passed:
            all_passed = False
    
    print("\n" + ("🎉 全部测试通过！" if all_passed else "⚠️ 部分测试失败"))
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())

