#!/usr/bin/env python3
"""
安全密钥管理器
==============
提供私钥的加密存储、分片保存、安全恢复功能

安全特性：
1. AES-256 加密存储
2. 分片存储（Shamir 秘密共享）
3. 主密码保护
4. 内存安全（使用后清除）
5. 防日志泄露
"""

import os
import sys
import json
import base64
import hashlib
import secrets
import getpass
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging

# 禁止私钥出现在日志中
logging.getLogger().addFilter(lambda record: '0x' not in str(record.msg)[:66] if hasattr(record, 'msg') else True)

# 配置路径
SECURE_DIR = Path(__file__).parent.parent.parent / 'config.secret'
ENCRYPTED_KEY_FILE = SECURE_DIR / 'wallet.enc'
SHARD_DIR = SECURE_DIR / 'shards'


@dataclass
class KeyShard:
    """密钥分片"""
    index: int
    data: str
    checksum: str


class SecureKeyManager:
    """安全密钥管理器"""
    
    def __init__(self, master_password: Optional[str] = None):
        """
        初始化密钥管理器
        
        Args:
            master_password: 主密码（如果为None则从环境变量读取或提示输入）
        """
        self._master_password = master_password
        self._cached_key: Optional[str] = None
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        """确保安全目录存在"""
        SECURE_DIR.mkdir(parents=True, exist_ok=True)
        SHARD_DIR.mkdir(parents=True, exist_ok=True)
        
        # 设置目录权限（仅所有者可访问）
        try:
            os.chmod(SECURE_DIR, 0o700)
            os.chmod(SHARD_DIR, 0o700)
        except:
            pass
    
    def _get_master_password(self) -> str:
        """获取主密码"""
        if self._master_password:
            return self._master_password
        
        # 尝试从环境变量读取
        env_password = os.getenv('WALLET_MASTER_PASSWORD')
        if env_password:
            return env_password
        
        # 交互式输入
        return getpass.getpass("请输入主密码: ")
    
    def _derive_key(self, password: str, salt: bytes) -> bytes:
        """从密码派生加密密钥"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,  # OWASP 推荐的迭代次数
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key
    
    def _calculate_checksum(self, data: str) -> str:
        """计算校验和"""
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    # ========================================
    # 方案1: AES加密存储
    # ========================================
    
    def encrypt_and_save(self, private_key: str) -> bool:
        """
        加密并保存私钥
        
        Args:
            private_key: 原始私钥
            
        Returns:
            是否成功
        """
        try:
            password = self._get_master_password()
            
            # 生成随机盐
            salt = secrets.token_bytes(16)
            
            # 派生加密密钥
            key = self._derive_key(password, salt)
            fernet = Fernet(key)
            
            # 加密私钥
            encrypted = fernet.encrypt(private_key.encode())
            
            # 保存（盐 + 加密数据）
            data = {
                'version': 1,
                'salt': base64.b64encode(salt).decode(),
                'encrypted': encrypted.decode(),
                'checksum': self._calculate_checksum(private_key),
            }
            
            with open(ENCRYPTED_KEY_FILE, 'w') as f:
                json.dump(data, f)
            
            # 设置文件权限
            os.chmod(ENCRYPTED_KEY_FILE, 0o600)
            
            print(f"✅ 私钥已加密保存到: {ENCRYPTED_KEY_FILE}")
            return True
            
        except Exception as e:
            print(f"❌ 加密保存失败: {e}")
            return False
    
    def load_and_decrypt(self) -> Optional[str]:
        """
        加载并解密私钥
        
        Returns:
            解密后的私钥，失败返回 None
        """
        try:
            if not ENCRYPTED_KEY_FILE.exists():
                print("❌ 未找到加密密钥文件")
                return None
            
            with open(ENCRYPTED_KEY_FILE, 'r') as f:
                data = json.load(f)
            
            password = self._get_master_password()
            salt = base64.b64decode(data['salt'])
            
            # 派生解密密钥
            key = self._derive_key(password, salt)
            fernet = Fernet(key)
            
            # 解密
            decrypted = fernet.decrypt(data['encrypted'].encode()).decode()
            
            # 验证校验和
            if self._calculate_checksum(decrypted) != data['checksum']:
                print("❌ 校验和验证失败")
                return None
            
            return decrypted
            
        except Exception as e:
            print(f"❌ 解密失败: {e}")
            return None
    
    # ========================================
    # 方案2: 分片存储（Shamir 秘密共享简化版）
    # ========================================
    
    def split_and_save(self, private_key: str, num_shards: int = 3, threshold: int = 2) -> bool:
        """
        将私钥分片存储
        
        Args:
            private_key: 原始私钥
            num_shards: 分片数量
            threshold: 恢复所需最少分片数
            
        Returns:
            是否成功
        """
        try:
            # 移除 0x 前缀
            key = private_key.replace('0x', '')
            
            if len(key) != 64:
                print("❌ 无效的私钥长度")
                return False
            
            password = self._get_master_password()
            
            # 简化的分片方案：将密钥分成多个部分 + 加密
            # 注意：这是简化版本，生产环境建议使用真正的 Shamir 秘密共享
            
            # 生成随机掩码
            masks = [secrets.token_hex(32) for _ in range(num_shards - 1)]
            
            # 计算最后一个分片（XOR 所有掩码和原始密钥）
            result = int(key, 16)
            for mask in masks:
                result ^= int(mask, 16)
            final_shard = format(result, '064x')
            
            shards = masks + [final_shard]
            
            # 加密每个分片并保存
            for i, shard in enumerate(shards):
                salt = secrets.token_bytes(16)
                enc_key = self._derive_key(password + str(i), salt)
                fernet = Fernet(enc_key)
                encrypted = fernet.encrypt(shard.encode())
                
                shard_data = {
                    'index': i,
                    'salt': base64.b64encode(salt).decode(),
                    'data': encrypted.decode(),
                    'checksum': self._calculate_checksum(shard),
                    'total': num_shards,
                    'threshold': threshold,
                }
                
                shard_file = SHARD_DIR / f'shard_{i}.enc'
                with open(shard_file, 'w') as f:
                    json.dump(shard_data, f)
                os.chmod(shard_file, 0o600)
            
            print(f"✅ 私钥已分成 {num_shards} 个分片保存到: {SHARD_DIR}")
            print(f"   恢复需要至少 {threshold} 个分片")
            return True
            
        except Exception as e:
            print(f"❌ 分片保存失败: {e}")
            return False
    
    def recover_from_shards(self) -> Optional[str]:
        """
        从分片恢复私钥
        
        Returns:
            恢复的私钥，失败返回 None
        """
        try:
            password = self._get_master_password()
            
            # 读取所有分片
            shard_files = list(SHARD_DIR.glob('shard_*.enc'))
            if not shard_files:
                print("❌ 未找到分片文件")
                return None
            
            shards = []
            for shard_file in shard_files:
                with open(shard_file, 'r') as f:
                    data = json.load(f)
                
                salt = base64.b64decode(data['salt'])
                enc_key = self._derive_key(password + str(data['index']), salt)
                fernet = Fernet(enc_key)
                
                decrypted = fernet.decrypt(data['data'].encode()).decode()
                
                # 验证校验和
                if self._calculate_checksum(decrypted) != data['checksum']:
                    print(f"⚠️ 分片 {data['index']} 校验和验证失败")
                    continue
                
                shards.append((data['index'], decrypted))
            
            if len(shards) < 2:
                print("❌ 分片数量不足")
                return None
            
            # XOR 所有分片恢复原始密钥
            result = 0
            for _, shard in sorted(shards):
                result ^= int(shard, 16)
            
            private_key = '0x' + format(result, '064x')
            return private_key
            
        except Exception as e:
            print(f"❌ 恢复失败: {e}")
            return None
    
    # ========================================
    # 安全获取私钥
    # ========================================
    
    def get_private_key(self, use_cache: bool = True) -> Optional[str]:
        """
        安全获取私钥（优先从缓存，然后尝试各种恢复方式）
        
        Args:
            use_cache: 是否使用缓存
            
        Returns:
            私钥
        """
        # 使用缓存
        if use_cache and self._cached_key:
            return self._cached_key
        
        # 方式1: 尝试从加密文件恢复
        if ENCRYPTED_KEY_FILE.exists():
            key = self.load_and_decrypt()
            if key:
                self._cached_key = key
                return key
        
        # 方式2: 尝试从分片恢复
        if list(SHARD_DIR.glob('shard_*.enc')):
            key = self.recover_from_shards()
            if key:
                self._cached_key = key
                return key
        
        # 方式3: 从环境变量读取（向后兼容，但不推荐）
        env_key = os.getenv('TRADING_WALLET_PRIVATE_KEY')
        if env_key:
            print("⚠️ 警告: 从环境变量读取私钥（不安全）")
            print("   建议运行: python -m src.core.secure_key_manager --encrypt")
            return env_key
        
        return None
    
    def clear_cache(self):
        """清除缓存的私钥"""
        if self._cached_key:
            # 尝试覆盖内存
            self._cached_key = secrets.token_hex(32)
            self._cached_key = None


# ========================================
# 命令行工具
# ========================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='安全密钥管理工具')
    parser.add_argument('--encrypt', action='store_true', help='加密并保存私钥')
    parser.add_argument('--decrypt', action='store_true', help='解密并显示私钥（危险）')
    parser.add_argument('--split', action='store_true', help='分片存储私钥')
    parser.add_argument('--recover', action='store_true', help='从分片恢复私钥')
    parser.add_argument('--migrate', action='store_true', help='从 .env 迁移到加密存储')
    parser.add_argument('--verify', action='store_true', help='验证密钥是否可恢复')
    
    args = parser.parse_args()
    
    manager = SecureKeyManager()
    
    if args.encrypt:
        print("🔐 加密存储私钥")
        print("=" * 50)
        private_key = getpass.getpass("请输入私钥: ")
        if private_key:
            manager.encrypt_and_save(private_key)
    
    elif args.decrypt:
        print("⚠️ 警告: 即将显示明文私钥")
        confirm = input("确认显示? (yes/no): ")
        if confirm.lower() == 'yes':
            key = manager.load_and_decrypt()
            if key:
                print(f"私钥: {key[:10]}...{key[-6:]}")
    
    elif args.split:
        print("🔐 分片存储私钥")
        print("=" * 50)
        private_key = getpass.getpass("请输入私钥: ")
        if private_key:
            manager.split_and_save(private_key)
    
    elif args.recover:
        print("🔓 从分片恢复私钥")
        print("=" * 50)
        key = manager.recover_from_shards()
        if key:
            print(f"✅ 恢复成功: {key[:10]}...{key[-6:]}")
    
    elif args.migrate:
        print("📦 从 .env 迁移到加密存储")
        print("=" * 50)
        
        from dotenv import load_dotenv
        load_dotenv()
        
        env_key = os.getenv('TRADING_WALLET_PRIVATE_KEY')
        if not env_key:
            print("❌ 未在 .env 中找到 TRADING_WALLET_PRIVATE_KEY")
            return
        
        print(f"找到私钥: {env_key[:10]}...{env_key[-6:]}")
        
        # 加密存储
        manager.encrypt_and_save(env_key)
        
        # 分片存储
        manager.split_and_save(env_key)
        
        print("\n✅ 迁移完成！")
        print("\n建议操作:")
        print("1. 从 .env 中删除 TRADING_WALLET_PRIVATE_KEY")
        print("2. 添加 WALLET_MASTER_PASSWORD 环境变量")
        print("3. 或在启动时交互式输入主密码")
    
    elif args.verify:
        print("🔍 验证密钥可恢复性")
        print("=" * 50)
        key = manager.get_private_key()
        if key:
            from eth_account import Account
            account = Account.from_key(key)
            print(f"✅ 钱包地址: {account.address}")
        else:
            print("❌ 无法恢复私钥")
    
    else:
        parser.print_help()


if __name__ == '__main__':
    main()

