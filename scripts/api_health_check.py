#!/usr/bin/env python3
"""
API 健康检查脚本
每日检查所有外部 API 是否正常，并推送结果到企业微信

使用方法:
    # 直接运行
    python scripts/api_health_check.py
    
    # 设置为 cron 任务 (每天早上 8:00)
    0 8 * * * cd /root/v8.3_crypto_monitor && /root/v8.3_crypto_monitor/venv/bin/python scripts/api_health_check.py

环境变量:
    WECOM_WEBHOOK_URL: 企业微信机器人 Webhook URL
    ETHERSCAN_API_KEY: Etherscan API Key
"""

import os
import sys
import json
import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class APICheckResult:
    """API 检查结果"""
    name: str
    url: str
    status: str  # 'ok', 'warning', 'error'
    response_time_ms: int
    status_code: int
    message: str
    category: str


class APIHealthChecker:
    """API 健康检查器"""
    
    # ==================== API 配置 ====================
    
    # 交易所 API（公开，无需 Key）
    EXCHANGE_APIS = {
        'Binance 行情': {
            'url': 'https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT',
            'category': '交易所',
            'check_field': 'price',
        },
        'Binance 深度': {
            'url': 'https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=5',
            'category': '交易所',
            'check_field': 'bids',
        },
        'OKX 行情': {
            'url': 'https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT',
            'category': '交易所',
            'check_field': 'data',
        },
        'Bybit 行情': {
            'url': 'https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT',
            'category': '交易所',
            'check_field': 'result',
        },
        'Gate.io 行情': {
            'url': 'https://api.gateio.ws/api/v4/spot/tickers?currency_pair=BTC_USDT',
            'category': '交易所',
            'check_field': None,  # 返回列表
        },
        'Upbit 行情': {
            'url': 'https://api.upbit.com/v1/ticker?markets=KRW-BTC',
            'category': '交易所',
            'check_field': None,
        },
    }
    
    # DeFi 数据 API
    DEFI_APIS = {
        'DeFiLlama TVL': {
            'url': 'https://api.llama.fi/v2/chains',
            'category': 'DeFi',
            'check_field': None,
        },
        'DeFiLlama 稳定币': {
            'url': 'https://stablecoins.llama.fi/stablecoins?includePrices=true',
            'category': 'DeFi',
            'check_field': 'peggedAssets',
        },
        'DeFiLlama DEX': {
            'url': 'https://api.llama.fi/overview/dexs',
            'category': 'DeFi',
            'check_field': 'total24h',
        },
        'CoinGecko 全球': {
            'url': 'https://api.coingecko.com/api/v3/global',
            'category': 'DeFi',
            'check_field': 'data',
        },
        'DexScreener': {
            'url': 'https://api.dexscreener.com/latest/dex/tokens/0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
            'category': 'DeFi',
            'check_field': 'pairs',
        },
    }
    
    # 情绪/指数 API
    SENTIMENT_APIS = {
        '恐惧贪婪指数': {
            'url': 'https://api.alternative.me/fng/',
            'category': '情绪指数',
            'check_field': 'data',
        },
    }
    
    # 衍生品 API
    DERIVATIVES_APIS = {
        'CoinGlass 资金费率': {
            'url': 'https://open-api.coinglass.com/public/v2/funding',
            'category': '衍生品',
            'check_field': None,
            'headers': {'accept': 'application/json'},
        },
    }
    
    # 需要 API Key 的 API
    API_KEY_APIS = {
        'Etherscan V2': {
            'url': 'https://api.etherscan.io/v2/api?chainid=1&module=account&action=balance&address=0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae&tag=latest&apikey={ETHERSCAN_API_KEY}',
            'category': '链上数据',
            'check_field': 'result',
            'env_key': 'ETHERSCAN_API_KEY',
        },
    }
    
    def __init__(self, wecom_webhook: Optional[str] = None):
        self.wecom_webhook = wecom_webhook or os.getenv('WECOM_WEBHOOK_URL')
        self.session: Optional[aiohttp.ClientSession] = None
        self.results: List[APICheckResult] = []
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def check_api(self, name: str, config: Dict) -> APICheckResult:
        """检查单个 API"""
        url = config['url']
        category = config.get('category', '其他')
        check_field = config.get('check_field')
        headers = config.get('headers', {})
        
        # 替换环境变量
        env_key = config.get('env_key')
        if env_key:
            env_value = os.getenv(env_key, '')
            if not env_value:
                return APICheckResult(
                    name=name,
                    url=url,
                    status='warning',
                    response_time_ms=0,
                    status_code=0,
                    message=f'缺少环境变量: {env_key}',
                    category=category,
                )
            url = url.replace(f'{{{env_key}}}', env_value)
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            session = await self._get_session()
            async with session.get(url, headers=headers) as resp:
                response_time = int((asyncio.get_event_loop().time() - start_time) * 1000)
                
                if resp.status == 200:
                    try:
                        data = await resp.json()
                        
                        # 检查返回字段
                        if check_field:
                            if isinstance(data, dict) and check_field in data:
                                return APICheckResult(
                                    name=name,
                                    url=self._mask_url(url),
                                    status='ok',
                                    response_time_ms=response_time,
                                    status_code=200,
                                    message='正常',
                                    category=category,
                                )
                            else:
                                return APICheckResult(
                                    name=name,
                                    url=self._mask_url(url),
                                    status='warning',
                                    response_time_ms=response_time,
                                    status_code=200,
                                    message=f'返回格式异常: 缺少 {check_field}',
                                    category=category,
                                )
                        else:
                            # 只检查是否有返回
                            if data:
                                return APICheckResult(
                                    name=name,
                                    url=self._mask_url(url),
                                    status='ok',
                                    response_time_ms=response_time,
                                    status_code=200,
                                    message='正常',
                                    category=category,
                                )
                            else:
                                return APICheckResult(
                                    name=name,
                                    url=self._mask_url(url),
                                    status='warning',
                                    response_time_ms=response_time,
                                    status_code=200,
                                    message='返回数据为空',
                                    category=category,
                                )
                    except Exception as e:
                        return APICheckResult(
                            name=name,
                            url=self._mask_url(url),
                            status='warning',
                            response_time_ms=response_time,
                            status_code=200,
                            message=f'JSON 解析失败: {str(e)[:50]}',
                            category=category,
                        )
                elif resp.status == 429:
                    return APICheckResult(
                        name=name,
                        url=self._mask_url(url),
                        status='warning',
                        response_time_ms=response_time,
                        status_code=429,
                        message='API 限速',
                        category=category,
                    )
                else:
                    return APICheckResult(
                        name=name,
                        url=self._mask_url(url),
                        status='error',
                        response_time_ms=response_time,
                        status_code=resp.status,
                        message=f'HTTP {resp.status}',
                        category=category,
                    )
                    
        except asyncio.TimeoutError:
            return APICheckResult(
                name=name,
                url=self._mask_url(url),
                status='error',
                response_time_ms=15000,
                status_code=0,
                message='请求超时 (>15s)',
                category=category,
            )
        except Exception as e:
            return APICheckResult(
                name=name,
                url=self._mask_url(url),
                status='error',
                response_time_ms=0,
                status_code=0,
                message=f'连接错误: {str(e)[:50]}',
                category=category,
            )
    
    def _mask_url(self, url: str) -> str:
        """隐藏 URL 中的 API Key"""
        import re
        return re.sub(r'(apikey=|api_key=|key=)[^&]+', r'\1***', url)
    
    async def check_all(self) -> List[APICheckResult]:
        """检查所有 API"""
        all_apis = {}
        all_apis.update(self.EXCHANGE_APIS)
        all_apis.update(self.DEFI_APIS)
        all_apis.update(self.SENTIMENT_APIS)
        all_apis.update(self.DERIVATIVES_APIS)
        all_apis.update(self.API_KEY_APIS)
        
        logger.info(f"开始检查 {len(all_apis)} 个 API...")
        
        # 串行检查（避免触发限速）
        results = []
        for name, config in all_apis.items():
            logger.info(f"检查: {name}")
            result = await self.check_api(name, config)
            results.append(result)
            
            # 短暂延迟避免限速
            await asyncio.sleep(0.5)
        
        self.results = results
        return results
    
    def generate_report(self) -> str:
        """生成检查报告"""
        if not self.results:
            return "未执行检查"
        
        ok_count = len([r for r in self.results if r.status == 'ok'])
        warning_count = len([r for r in self.results if r.status == 'warning'])
        error_count = len([r for r in self.results if r.status == 'error'])
        total = len(self.results)
        
        # 按类别分组
        by_category: Dict[str, List[APICheckResult]] = {}
        for r in self.results:
            if r.category not in by_category:
                by_category[r.category] = []
            by_category[r.category].append(r)
        
        lines = [
            "# 📊 API 健康检查报告",
            f"**检查时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**检查结果:** ✅ {ok_count} | ⚠️ {warning_count} | ❌ {error_count} / 共 {total} 个",
            "",
        ]
        
        # 总体状态
        if error_count == 0 and warning_count == 0:
            lines.append("**整体状态:** 🟢 全部正常")
        elif error_count == 0:
            lines.append("**整体状态:** 🟡 部分警告")
        else:
            lines.append("**整体状态:** 🔴 存在异常")
        
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 按类别输出
        for category, results in by_category.items():
            lines.append(f"## 📁 {category}")
            lines.append("")
            
            for r in results:
                status_icon = {'ok': '✅', 'warning': '⚠️', 'error': '❌'}[r.status]
                time_str = f"{r.response_time_ms}ms" if r.response_time_ms > 0 else '-'
                
                if r.status == 'ok':
                    lines.append(f"- {status_icon} **{r.name}** ({time_str})")
                else:
                    lines.append(f"- {status_icon} **{r.name}** ({time_str}): {r.message}")
            
            lines.append("")
        
        # 异常详情
        errors = [r for r in self.results if r.status == 'error']
        if errors:
            lines.append("## ❌ 异常详情")
            lines.append("")
            for r in errors:
                lines.append(f"**{r.name}**")
                lines.append(f"- URL: `{r.url}`")
                lines.append(f"- 状态码: {r.status_code}")
                lines.append(f"- 错误: {r.message}")
                lines.append("")
        
        return "\n".join(lines)
    
    def generate_wecom_message(self) -> Dict:
        """生成企业微信消息"""
        if not self.results:
            return {}
        
        ok_count = len([r for r in self.results if r.status == 'ok'])
        warning_count = len([r for r in self.results if r.status == 'warning'])
        error_count = len([r for r in self.results if r.status == 'error'])
        total = len(self.results)
        
        # 确定整体状态
        if error_count == 0 and warning_count == 0:
            status_text = "🟢 全部正常"
            color = "info"
        elif error_count == 0:
            status_text = "🟡 部分警告"
            color = "warning"
        else:
            status_text = "🔴 存在异常"
            color = "warning"
        
        # 构建详情
        details = []
        
        # 只列出非正常的 API
        abnormal = [r for r in self.results if r.status != 'ok']
        if abnormal:
            for r in abnormal:
                status_icon = {'warning': '⚠️', 'error': '❌'}[r.status]
                details.append(f"{status_icon} {r.name}: {r.message}")
        
        if not details:
            details.append("所有 API 运行正常 ✨")
        
        # 企业微信 Markdown 消息
        content = f"""## 📊 API 健康检查报告

**时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**状态:** {status_text}
**统计:** ✅{ok_count} ⚠️{warning_count} ❌{error_count} / 共{total}个

### 详情
{chr(10).join(details[:10])}
{'...' if len(details) > 10 else ''}
"""
        
        return {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }
    
    async def send_to_wecom(self) -> bool:
        """发送到企业微信"""
        if not self.wecom_webhook:
            logger.warning("未配置企业微信 Webhook，跳过推送")
            return False
        
        message = self.generate_wecom_message()
        if not message:
            return False
        
        try:
            session = await self._get_session()
            async with session.post(
                self.wecom_webhook,
                json=message,
                headers={'Content-Type': 'application/json'}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('errcode') == 0:
                        logger.info("✅ 企业微信推送成功")
                        return True
                    else:
                        logger.error(f"企业微信推送失败: {data}")
                        return False
                else:
                    logger.error(f"企业微信推送失败: HTTP {resp.status}")
                    return False
        except Exception as e:
            logger.error(f"企业微信推送异常: {e}")
            return False
    
    async def run(self, send_notification: bool = True) -> Tuple[int, int, int]:
        """
        运行健康检查
        
        Returns:
            (ok_count, warning_count, error_count)
        """
        try:
            await self.check_all()
            
            # 打印报告
            report = self.generate_report()
            print("\n" + "=" * 60)
            print(report)
            print("=" * 60 + "\n")
            
            # 发送通知
            if send_notification:
                await self.send_to_wecom()
            
            ok_count = len([r for r in self.results if r.status == 'ok'])
            warning_count = len([r for r in self.results if r.status == 'warning'])
            error_count = len([r for r in self.results if r.status == 'error'])
            
            return ok_count, warning_count, error_count
            
        finally:
            await self.close()


async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='API 健康检查')
    parser.add_argument('--no-notify', action='store_true', help='不发送企业微信通知')
    parser.add_argument('--webhook', type=str, help='企业微信 Webhook URL')
    args = parser.parse_args()
    
    webhook = args.webhook or os.getenv('WECOM_WEBHOOK_URL')
    
    checker = APIHealthChecker(wecom_webhook=webhook)
    ok, warn, err = await checker.run(send_notification=not args.no_notify)
    
    # 返回退出码
    if err > 0:
        sys.exit(1)
    elif warn > 0:
        sys.exit(0)
    else:
        sys.exit(0)


if __name__ == '__main__':
    asyncio.run(main())

