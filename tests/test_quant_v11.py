#!/usr/bin/env python3
"""
Quant V11 模块测试
测试所有量化核心模块
"""

import asyncio
import sys
from pathlib import Path

# 添加 src 路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from dotenv import load_dotenv
load_dotenv()


def test_imports():
    """测试模块导入"""
    print("\n" + "=" * 60)
    print("📦 测试模块导入")
    print("=" * 60)
    
    try:
        from quant.alpha_engine import AlphaEngine, SignalTier, ActionType
        print("✅ AlphaEngine 导入成功")
        
        from quant.signal_aggregator import SignalAggregator
        print("✅ SignalAggregator 导入成功")
        
        from quant.risk_manager import RiskManager, RiskAction, RiskLevel
        print("✅ RiskManager 导入成功")
        
        from quant.execution_engine import ExecutionEngine, ExecutionStatus
        print("✅ ExecutionEngine 导入成功")
        
        return True
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        return False


async def test_alpha_engine():
    """测试 Alpha 引擎"""
    print("\n" + "=" * 60)
    print("🧠 测试 Alpha Engine")
    print("=" * 60)
    
    from quant.alpha_engine import AlphaEngine, SignalTier
    
    engine = AlphaEngine()
    
    # 测试事件
    test_cases = [
        {
            'name': 'Tier-S: 方程式 + Binance',
            'event': {
                'source': 'social_telegram',
                'channel': 'bwenews',
                'exchange': 'binance',
                'raw_text': 'Binance will list NEWTOKEN/USDT',
                'symbol': 'NEWTOKEN',
            },
            'expected_tier': SignalTier.TIER_S,
        },
        {
            'name': 'Tier-A: OKX API',
            'event': {
                'source': 'rest_api',
                'exchange': 'okx',
                'raw_text': 'New listing: TESTCOIN',
                'symbol': 'TESTCOIN',
            },
            'expected_tier': SignalTier.TIER_A,
        },
        {
            'name': 'Tier-B: MEXC API',
            'event': {
                'source': 'rest_api',
                'exchange': 'mexc',
                'raw_text': 'MEXC lists LOWCOIN',
                'symbol': 'LOWCOIN',
            },
            'expected_tier': SignalTier.TIER_B,
        },
    ]
    
    passed = 0
    for case in test_cases:
        signal = await engine.process_event(case['event'])
        
        if signal:
            status = "✅" if signal.tier == case['expected_tier'] else "⚠️"
            print(f"{status} {case['name']}")
            print(f"   期望: {case['expected_tier'].value} | 实际: {signal.tier.value}")
            print(f"   总分: {signal.total_score:.0f} | 来源分: {signal.source_score:.0f}")
            
            if signal.tier == case['expected_tier']:
                passed += 1
        else:
            print(f"❌ {case['name']} - 无信号生成")
    
    await engine.close()
    
    print(f"\n📊 通过率: {passed}/{len(test_cases)}")
    return passed == len(test_cases)


async def test_signal_aggregator():
    """测试信号聚合器"""
    print("\n" + "=" * 60)
    print("📡 测试 Signal Aggregator")
    print("=" * 60)
    
    from quant.signal_aggregator import SignalAggregator
    from quant.alpha_engine import SignalTier
    
    agg = SignalAggregator()
    
    # 模拟多源事件 (同一币种)
    events = [
        {
            'source': 'social_telegram',
            'channel': 'bwenews',
            'exchange': 'binance',
            'raw_text': 'Binance will list MULTI/USDT',
            'symbol': 'MULTI',
        },
        {
            'source': 'rest_api',
            'exchange': 'okx',
            'raw_text': 'OKX lists MULTI',
            'symbol': 'MULTI',
        },
        {
            'source': 'rest_api',
            'exchange': 'bybit',
            'raw_text': 'MULTI now on Bybit',
            'symbol': 'MULTI',
        },
    ]
    
    signals = []
    for event in events:
        signal = await agg.process_event(event)
        if signal:
            signals.append(signal)
            print(f"📨 事件: {event['exchange']} | 等级: {signal.tier.value} | 分数: {signal.total_score:.0f}")
    
    # 检查多源合并
    if signals:
        final_signal = signals[-1]
        print(f"\n🔗 最终信号:")
        print(f"   币种: {final_signal.symbol}")
        print(f"   等级: {final_signal.tier.value}")
        print(f"   总分: {final_signal.total_score:.0f}")
        print(f"   来源数: {final_signal.source_count}")
        print(f"   交易所数: {final_signal.exchange_count}")
        print(f"   交易所: {final_signal.exchanges}")
        
        # 验证多源升级
        if final_signal.exchange_count >= 2:
            print("✅ 多源合并成功")
        else:
            print("⚠️ 多源合并未生效")
    
    stats = agg.get_stats()
    print(f"\n📊 统计: 事件:{stats['events_received']} 信号:{stats['signals_generated']} 合并:{stats['signals_merged']}")
    
    await agg.close()
    return len(signals) > 0


def test_risk_manager():
    """测试风控管理器"""
    print("\n" + "=" * 60)
    print("🛡️ 测试 Risk Manager")
    print("=" * 60)
    
    from quant.risk_manager import RiskManager, RiskAction
    
    rm = RiskManager(config={'total_capital': 10000})
    
    # 测试 1: 正常交易
    result = rm.check_trade('BTC', 200, 'buy')
    print(f"✅ 正常交易 $200:")
    print(f"   动作: {result.action.value}")
    print(f"   允许金额: ${result.allowed_amount}")
    
    # 测试 2: 超额交易
    result = rm.check_trade('ETH', 1000, 'buy')  # 超过 5% 限制
    print(f"\n⚠️ 超额交易 $1000:")
    print(f"   动作: {result.action.value}")
    print(f"   允许金额: ${result.allowed_amount}")
    print(f"   原因: {result.reasons}")
    
    # 测试 3: 添加持仓
    rm.add_position('SOL', 'solana', 100, 5)
    positions = rm.get_positions()
    print(f"\n📈 持仓测试:")
    print(f"   持仓数: {len(positions)}")
    if positions:
        pos = positions[0]
        print(f"   SOL: {pos['amount']} @ ${pos['entry_price']}")
    
    # 测试 4: 更新价格
    rm.update_position_price('SOL', 110)
    positions = rm.get_positions()
    if positions:
        pos = positions[0]
        print(f"   更新后 PnL: ${pos['pnl']:.2f} ({pos['pnl_percent']:.1f}%)")
    
    # 测试 5: 黑名单
    rm.add_to_blacklist('SCAM', '蜜罐合约')
    result = rm.check_trade('SCAM', 100, 'buy')
    print(f"\n⛔ 黑名单测试:")
    print(f"   动作: {result.action.value}")
    print(f"   原因: {result.reasons}")
    
    # 统计
    stats = rm.get_stats()
    print(f"\n📊 统计: 持仓:{stats['positions_count']} 资金:${stats['current_capital']:.0f}")
    
    return result.action == RiskAction.BLOCK


async def test_execution_engine():
    """测试执行引擎 (DRY_RUN)"""
    print("\n" + "=" * 60)
    print("⚡ 测试 Execution Engine (DRY_RUN)")
    print("=" * 60)
    
    from quant.execution_engine import ExecutionEngine, ExecutionStatus
    
    engine = ExecutionEngine(dry_run=True)
    
    # 测试 1: DexScreener 价格查询
    print("\n📊 DexScreener 价格查询:")
    price_data = await engine.get_dexscreener_price('0x6982508145454Ce325dDbE47a25d4ec3d2311933')  # PEPE
    if price_data:
        print(f"   价格: ${price_data.get('price_usd', 0):.10f}")
        print(f"   流动性: ${price_data.get('liquidity_usd', 0):,.0f}")
        print(f"   24h成交量: ${price_data.get('volume_24h', 0):,.0f}")
    else:
        print("   ⚠️ 获取失败")
    
    # 测试 2: GoPlus 安全检查
    print("\n🔒 GoPlus 安全检查:")
    security = await engine.check_token_security(
        '0x6982508145454Ce325dDbE47a25d4ec3d2311933',  # PEPE
        'ethereum'
    )
    print(f"   安全: {'✅ 是' if security.get('safe') else '❌ 否'}")
    print(f"   买入税: {security.get('buy_tax', 0)}%")
    print(f"   卖出税: {security.get('sell_tax', 0)}%")
    if security.get('risks'):
        print(f"   风险: {security.get('risks')}")
    
    # 测试 3: 模拟交易
    print("\n🔄 模拟交易 (DRY_RUN):")
    result = await engine.execute_swap(
        chain='ethereum',
        from_token='0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',  # WETH
        to_token='0xdAC17F958D2ee523a2206206994597C13D831ec7',    # USDT
        amount=0.1
    )
    
    print(f"   状态: {result.status.value}")
    if result.status == ExecutionStatus.SUCCESS:
        print(f"   输入: {result.input_amount} WETH")
        print(f"   输出: {result.output_amount:.2f} USDT")
        print(f"   执行时间: {result.execution_time_ms:.0f}ms")
    else:
        print(f"   错误: {result.error_message}")
    
    # 统计
    stats = engine.get_stats()
    print(f"\n📊 统计: 执行:{stats['total_executions']} 成功率:{stats['success_rate']}%")
    
    await engine.close()
    return True


async def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("🧪 Quant V11 完整测试套件")
    print("=" * 60)
    
    results = {}
    
    # 1. 导入测试
    results['imports'] = test_imports()
    
    if not results['imports']:
        print("\n❌ 导入测试失败，无法继续")
        return
    
    # 2. Alpha Engine 测试
    results['alpha_engine'] = await test_alpha_engine()
    
    # 3. Signal Aggregator 测试
    results['signal_aggregator'] = await test_signal_aggregator()
    
    # 4. Risk Manager 测试
    results['risk_manager'] = test_risk_manager()
    
    # 5. Execution Engine 测试
    results['execution_engine'] = await test_execution_engine()
    
    # 总结
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    
    for name, result in results.items():
        status = "✅" if result else "❌"
        print(f"{status} {name}")
    
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！")
    else:
        print("\n⚠️ 部分测试失败")


if __name__ == "__main__":
    asyncio.run(run_all_tests())

