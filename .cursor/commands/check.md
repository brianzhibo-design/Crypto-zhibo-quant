# 名称: check-syntax
# 描述: 检查所有Python文件语法

find /root/v8.3_crypto_monitor -name "*.py" -not -path "*/venv/*" -exec python3 -m py_compile {} \; && echo "✅ 所有文件语法正确"
```

---

## 📋 快速设置清单

在 Cursor 中：

1. **Project Rules** (2个)
   - [ ] 项目架构和约定
   - [ ] 修改代码时的注意事项

2. **Project Commands** (8个)
   - [ ] restart-all-services
   - [ ] check-resources
   - [ ] check-redis-streams
   - [ ] backup-code
   - [ ] test-wechat
   - [ ] deploy-to-server
   - [ ] tail-logs
   - [ ] check-syntax

---

## 💡 使用建议

### 在 Cursor 中与 AI 对话时：

**优化代码示例：**
```
优化 scoring_engine.py 中的韩国交易所评分逻辑，
将 Upbit 乘数从 2.0 提升到 2.2
```

**添加新功能示例：**
```
在 wechat_pusher.py 中添加失败重试机制，
最多重试3次，间隔2秒
```

**调试问题示例：**
```
dex_consumer 无法读取 symbols 字段，
应该从 data.get("symbols") 而不是 data.get("symbol")