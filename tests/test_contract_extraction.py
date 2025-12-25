#!/usr/bin/env python3
"""
测试合约地址提取功能
"""

import sys
from pathlib import Path

# 添加 src 路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from core.utils import extract_contract_address, detect_chain_from_text


def test_evm_extraction():
    """测试 EVM 合约地址提取"""
    print("\n=== 测试 EVM 合约地址提取 ===\n")
    
    test_cases = [
        # 以太坊
        (
            "New token: 0x6B175474E89094C44Da98b954EesdfC03D18db",
            None,  # 无效地址
            None
        ),
        (
            "PEPE token contract: 0x6982508145454Ce325dDbE47a25d4ec3d2311933 on Ethereum",
            "0x6982508145454Ce325dDbE47a25d4ec3d2311933",
            "ethereum"
        ),
        # BSC
        (
            "New BEP-20 token on BSC: 0x1234567890abcdef1234567890abcdef12345678",
            "0x1234567890abcdef1234567890abcdef12345678",
            "bsc"
        ),
        # Base
        (
            "Launched on Base chain! CA: 0xabcdef1234567890abcdef1234567890abcdef12",
            "0xabcdef1234567890abcdef1234567890abcdef12",
            "base"
        ),
        # 无合约地址
        (
            "Binance will list NEWCOIN tomorrow at 10:00 UTC",
            None,
            None
        ),
        # 多个地址（取第一个）
        (
            "Token: 0x1111111111111111111111111111111111111111 Pair: 0x2222222222222222222222222222222222222222",
            "0x1111111111111111111111111111111111111111",
            "ethereum"
        ),
    ]
    
    passed = 0
    for text, expected_addr, expected_chain in test_cases:
        result = extract_contract_address(text)
        
        addr_match = result['contract_address'] == expected_addr
        chain_match = result['chain'] == expected_chain
        
        status = "✅" if (addr_match and chain_match) else "❌"
        passed += 1 if (addr_match and chain_match) else 0
        
        print(f"{status} 输入: {text[:60]}...")
        print(f"   期望: addr={expected_addr}, chain={expected_chain}")
        print(f"   结果: addr={result['contract_address']}, chain={result['chain']}")
        print()
    
    print(f"通过: {passed}/{len(test_cases)}")


def test_chain_detection():
    """测试链类型检测"""
    print("\n=== 测试链类型检测 ===\n")
    
    test_cases = [
        ("Ethereum mainnet", "ethereum"),
        ("BSC BNB chain", "bsc"),
        ("Base network", "base"),
        ("Arbitrum One", "arbitrum"),
        ("Solana SPL token", "solana"),
        ("Unknown chain", None),
    ]
    
    for text, expected in test_cases:
        result = detect_chain_from_text(text)
        status = "✅" if result == expected else "❌"
        print(f"{status} '{text}' -> 期望: {expected}, 结果: {result}")


def test_real_announcements():
    """测试真实公告文本"""
    print("\n=== 测试真实公告格式 ===\n")
    
    announcements = [
        """
        🚨 Breaking: Binance will list NEWCOIN (NEW)
        Spot trading begins at 10:00 UTC
        Contract: 0x1234567890abcdef1234567890abcdef12345678
        Network: Ethereum (ERC-20)
        """,
        """
        📢 Gate.io 上新公告
        现货交易对: MEMECOIN/USDT
        合约地址 (BSC): 0xabcdef1234567890abcdef1234567890abcdef12
        """,
        """
        Upbit will list KRCOIN
        KRW trading pair
        No contract address provided
        """,
    ]
    
    for i, text in enumerate(announcements, 1):
        result = extract_contract_address(text)
        print(f"公告 {i}:")
        print(f"  合约: {result['contract_address'] or '未找到'}")
        print(f"  链: {result['chain'] or '未识别'}")
        print()


if __name__ == "__main__":
    test_evm_extraction()
    test_chain_detection()
    test_real_announcements()
    print("\n✅ 测试完成！")

