#!/usr/bin/env python3
"""
钱包管理工具 - 交互式命令行界面
================================
功能:
- 加密存储私钥
- 分片备份
- 查看钱包状态
- 修改私钥
- 验证配置
"""

import os
import sys
import getpass
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

try:
    from eth_account import Account
    from web3 import Web3
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False
    print("⚠️  请安装 web3: pip install web3 eth-account")

try:
    from src.core.secure_key_manager import SecureKeyManager, ENCRYPTED_KEY_FILE, SHARD_DIR
    HAS_SECURE = True
except ImportError:
    HAS_SECURE = False
    print("⚠️  安全密钥管理器不可用")


def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')


def print_header():
    print("\033[1;36m" + "=" * 60 + "\033[0m")
    print("\033[1;36m" + "💰 Crypto Monitor - 钱包管理工具".center(60) + "\033[0m")
    print("\033[1;36m" + "=" * 60 + "\033[0m")
    print()


def print_success(msg):
    print(f"\033[1;32m✅ {msg}\033[0m")


def print_error(msg):
    print(f"\033[1;31m❌ {msg}\033[0m")


def print_warning(msg):
    print(f"\033[1;33m⚠️  {msg}\033[0m")


def print_info(msg):
    print(f"\033[1;34mℹ️  {msg}\033[0m")


def get_current_wallet_info():
    """获取当前钱包信息"""
    info = {
        'has_encrypted': False,
        'has_shards': False,
        'has_env': False,
        'address': None,
        'balances': {},
    }
    
    # 检查加密文件
    if ENCRYPTED_KEY_FILE.exists():
        info['has_encrypted'] = True
    
    # 检查分片
    if SHARD_DIR.exists() and list(SHARD_DIR.glob('shard_*.enc')):
        info['has_shards'] = True
    
    # 检查环境变量
    env_key = os.getenv('TRADING_WALLET_PRIVATE_KEY')
    if env_key:
        info['has_env'] = True
    
    # 尝试获取地址
    if HAS_SECURE and HAS_WEB3:
        try:
            manager = SecureKeyManager()
            key = manager.get_private_key(use_cache=False)
            if key:
                account = Account.from_key(key)
                info['address'] = account.address
                
                # 获取余额
                chains = {
                    'Ethereum': os.getenv('ETHEREUM_RPC_URL'),
                    'BSC': os.getenv('BSC_RPC_URL'),
                    'Base': os.getenv('BASE_RPC_URL'),
                    'Arbitrum': os.getenv('ARBITRUM_RPC_URL'),
                }
                
                for chain, rpc in chains.items():
                    if rpc:
                        try:
                            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout': 5}))
                            if w3.is_connected():
                                balance = w3.eth.get_balance(account.address)
                                info['balances'][chain] = balance / 1e18
                        except:
                            pass
        except:
            pass
    
    return info


def show_status():
    """显示当前状态"""
    print("\n\033[1;33m📊 当前钱包状态\033[0m")
    print("-" * 50)
    
    info = get_current_wallet_info()
    
    # 存储方式
    print("\n存储方式:")
    print(f"  加密文件 (wallet.enc):  {'✅ 已配置' if info['has_encrypted'] else '❌ 未配置'}")
    print(f"  分片备份 (shards/):     {'✅ 已配置' if info['has_shards'] else '❌ 未配置'}")
    print(f"  环境变量 (.env):        {'⚠️  已配置 (不推荐)' if info['has_env'] else '✅ 未配置'}")
    
    # 钱包地址
    if info['address']:
        print(f"\n钱包地址: \033[1;32m{info['address']}\033[0m")
        
        # 余额
        if info['balances']:
            print("\n多链余额:")
            for chain, balance in info['balances'].items():
                status = "✅" if balance > 0.001 else "⚠️ "
                print(f"  {chain:12} {status} {balance:.6f}")
    else:
        print_warning("\n无法获取钱包地址")
    
    print()


def setup_new_wallet():
    """设置新钱包"""
    print("\n\033[1;33m🔐 设置新钱包\033[0m")
    print("-" * 50)
    
    print("\n请选择操作:")
    print("  1. 导入现有私钥")
    print("  2. 生成新钱包")
    print("  0. 返回")
    
    choice = input("\n请选择 (0-2): ").strip()
    
    if choice == '1':
        import_private_key()
    elif choice == '2':
        generate_new_wallet()


def import_private_key():
    """导入私钥"""
    print("\n\033[1;33m📥 导入私钥\033[0m")
    print("-" * 50)
    
    print_warning("请确保在安全环境下操作！")
    print()
    
    # 输入私钥
    private_key = getpass.getpass("请输入私钥 (不会显示): ")
    
    if not private_key:
        print_error("私钥不能为空")
        return
    
    # 格式化
    if not private_key.startswith('0x'):
        private_key = '0x' + private_key
    
    # 验证
    try:
        account = Account.from_key(private_key)
        print_success(f"私钥有效！地址: {account.address}")
    except Exception as e:
        print_error(f"无效的私钥: {e}")
        return
    
    # 确认
    confirm = input("\n确认保存? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("已取消")
        return
    
    # 设置主密码
    print("\n设置主密码 (用于加密私钥):")
    master_pwd = getpass.getpass("主密码: ")
    master_pwd2 = getpass.getpass("确认密码: ")
    
    if master_pwd != master_pwd2:
        print_error("两次密码不一致")
        return
    
    if len(master_pwd) < 8:
        print_error("密码至少8位")
        return
    
    # 保存到加密存储
    try:
        manager = SecureKeyManager(master_password=master_pwd)
        
        # 加密存储
        if manager.encrypt_and_save(private_key):
            print_success("私钥已加密保存")
        
        # 分片存储
        if manager.split_and_save(private_key):
            print_success("私钥已分片备份")
        
        # 更新 .env 中的主密码
        env_file = PROJECT_ROOT / '.env'
        env_content = env_file.read_text() if env_file.exists() else ""
        
        # 删除旧的私钥和主密码配置
        lines = env_content.split('\n')
        new_lines = [l for l in lines if not l.startswith('TRADING_WALLET_PRIVATE_KEY=') 
                     and not l.startswith('WALLET_MASTER_PASSWORD=')]
        
        # 添加主密码
        new_lines.append(f"WALLET_MASTER_PASSWORD={master_pwd}")
        
        env_file.write_text('\n'.join(new_lines))
        print_success("主密码已保存到 .env")
        
        # 同步到 docker
        docker_env = PROJECT_ROOT / 'docker' / '.env'
        docker_env.write_text('\n'.join(new_lines))
        print_success("配置已同步到 Docker")
        
        print("\n" + "=" * 50)
        print_success("钱包配置完成！")
        print(f"  地址: {account.address}")
        print(f"  加密文件: {ENCRYPTED_KEY_FILE}")
        print(f"  分片目录: {SHARD_DIR}")
        
    except Exception as e:
        print_error(f"保存失败: {e}")


def generate_new_wallet():
    """生成新钱包"""
    print("\n\033[1;33m🆕 生成新钱包\033[0m")
    print("-" * 50)
    
    import secrets
    private_key = '0x' + secrets.token_hex(32)
    account = Account.from_key(private_key)
    
    print(f"\n新钱包已生成:")
    print(f"  地址: \033[1;32m{account.address}\033[0m")
    print(f"  私钥: {private_key[:10]}...{private_key[-6:]}")
    
    print_warning("\n请立即备份私钥到安全位置！")
    
    show_full = input("\n显示完整私钥? (yes/no): ").strip().lower()
    if show_full == 'yes':
        print(f"\n私钥: {private_key}")
        print_warning("请立即复制并安全保存！")
    
    use_this = input("\n使用此钱包? (yes/no): ").strip().lower()
    if use_this == 'yes':
        # 复用导入逻辑
        print("\n设置主密码 (用于加密私钥):")
        master_pwd = getpass.getpass("主密码: ")
        master_pwd2 = getpass.getpass("确认密码: ")
        
        if master_pwd != master_pwd2:
            print_error("两次密码不一致")
            return
        
        try:
            manager = SecureKeyManager(master_password=master_pwd)
            manager.encrypt_and_save(private_key)
            manager.split_and_save(private_key)
            
            # 更新 .env
            env_file = PROJECT_ROOT / '.env'
            env_content = env_file.read_text() if env_file.exists() else ""
            lines = [l for l in env_content.split('\n') 
                     if not l.startswith('TRADING_WALLET_PRIVATE_KEY=') 
                     and not l.startswith('WALLET_MASTER_PASSWORD=')]
            lines.append(f"WALLET_MASTER_PASSWORD={master_pwd}")
            env_file.write_text('\n'.join(lines))
            
            # 同步
            (PROJECT_ROOT / 'docker' / '.env').write_text('\n'.join(lines))
            
            print_success("新钱包已配置完成！")
            
        except Exception as e:
            print_error(f"保存失败: {e}")


def change_master_password():
    """修改主密码"""
    print("\n\033[1;33m🔑 修改主密码\033[0m")
    print("-" * 50)
    
    # 验证旧密码
    old_pwd = getpass.getpass("当前主密码: ")
    
    try:
        manager = SecureKeyManager(master_password=old_pwd)
        private_key = manager.load_and_decrypt()
        
        if not private_key:
            print_error("密码错误或无法解密")
            return
        
        print_success("密码验证成功")
        
    except Exception as e:
        print_error(f"验证失败: {e}")
        return
    
    # 设置新密码
    new_pwd = getpass.getpass("\n新密码: ")
    new_pwd2 = getpass.getpass("确认新密码: ")
    
    if new_pwd != new_pwd2:
        print_error("两次密码不一致")
        return
    
    if len(new_pwd) < 8:
        print_error("密码至少8位")
        return
    
    # 用新密码重新加密
    try:
        new_manager = SecureKeyManager(master_password=new_pwd)
        new_manager.encrypt_and_save(private_key)
        new_manager.split_and_save(private_key)
        
        # 更新 .env
        env_file = PROJECT_ROOT / '.env'
        env_content = env_file.read_text()
        lines = [l for l in env_content.split('\n') if not l.startswith('WALLET_MASTER_PASSWORD=')]
        lines.append(f"WALLET_MASTER_PASSWORD={new_pwd}")
        env_file.write_text('\n'.join(lines))
        
        # 同步
        (PROJECT_ROOT / 'docker' / '.env').write_text('\n'.join(lines))
        
        print_success("主密码已更新！")
        
    except Exception as e:
        print_error(f"更新失败: {e}")


def verify_wallet():
    """验证钱包配置"""
    print("\n\033[1;33m🔍 验证钱包配置\033[0m")
    print("-" * 50)
    
    try:
        manager = SecureKeyManager()
        private_key = manager.get_private_key()
        
        if not private_key:
            print_error("无法获取私钥")
            return
        
        account = Account.from_key(private_key)
        print_success(f"钱包地址: {account.address}")
        
        # 检查余额
        print("\n检查多链余额...")
        chains = {
            'Ethereum': os.getenv('ETHEREUM_RPC_URL'),
            'BSC': os.getenv('BSC_RPC_URL'),
            'Base': os.getenv('BASE_RPC_URL'),
        }
        
        for chain, rpc in chains.items():
            if rpc:
                try:
                    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout': 5}))
                    if w3.is_connected():
                        balance = w3.eth.get_balance(account.address)
                        eth_balance = balance / 1e18
                        status = "✅" if eth_balance > 0.001 else "⚠️ "
                        print(f"  {chain:12} {status} {eth_balance:.6f}")
                except Exception as e:
                    print(f"  {chain:12} ❌ 连接失败")
        
        print_success("\n钱包配置验证通过！")
        
    except Exception as e:
        print_error(f"验证失败: {e}")


def remove_env_key():
    """删除环境变量中的私钥"""
    print("\n\033[1;33m🗑️  清理环境变量私钥\033[0m")
    print("-" * 50)
    
    env_file = PROJECT_ROOT / '.env'
    if not env_file.exists():
        print_warning(".env 文件不存在")
        return
    
    content = env_file.read_text()
    if 'TRADING_WALLET_PRIVATE_KEY=' not in content:
        print_info("环境变量中没有私钥")
        return
    
    confirm = input("确认删除 .env 中的明文私钥? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("已取消")
        return
    
    lines = [l for l in content.split('\n') if not l.startswith('TRADING_WALLET_PRIVATE_KEY=')]
    env_file.write_text('\n'.join(lines))
    
    # 同步
    (PROJECT_ROOT / 'docker' / '.env').write_text('\n'.join(lines))
    
    print_success("已删除环境变量中的私钥")


def main_menu():
    """主菜单"""
    while True:
        clear_screen()
        print_header()
        show_status()
        
        print("\033[1;33m📋 请选择操作:\033[0m")
        print("-" * 50)
        print("  1. 设置新钱包 (导入/生成)")
        print("  2. 修改主密码")
        print("  3. 验证钱包配置")
        print("  4. 清理环境变量私钥")
        print("  5. 刷新状态")
        print("  0. 退出")
        print()
        
        choice = input("请选择 (0-5): ").strip()
        
        if choice == '1':
            setup_new_wallet()
        elif choice == '2':
            change_master_password()
        elif choice == '3':
            verify_wallet()
        elif choice == '4':
            remove_env_key()
        elif choice == '5':
            continue
        elif choice == '0':
            print("\n再见！👋\n")
            break
        else:
            print_warning("无效选择")
        
        if choice != '5':
            input("\n按回车键继续...")


if __name__ == '__main__':
    if not HAS_WEB3 or not HAS_SECURE:
        print_error("依赖缺失，请先安装: pip install web3 eth-account cryptography")
        sys.exit(1)
    
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\n\n已取消")
        sys.exit(0)

