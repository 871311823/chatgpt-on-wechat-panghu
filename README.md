# ChatGPT-on-WeChat 胖虎增强版

基于 [chatgpt-on-wechat](https://github.com/zhayujie/chatgpt-on-wechat) 的增强版本，专为个人助手场景优化，集成了智能提醒、API余额监控、交易系统热更新等实用功能。

## ✨ 核心功能

### 1. 智能待办提醒系统 📝

#### 基础功能
- **创建待办**: `#todo 买菜 /at 明天下午3点`
- **查看列表**: `#todo list`
- **完成待办**: `#todo done 1`
- **删除待办**: `#todo del 1`

#### 高级特性
- ✅ **智能时间解析**: 支持"明天"、"下周五"、"3天后"等自然语言
- ✅ **周期性提醒**: 支持每天、每周、每月重复提醒
- ✅ **批量完成**: 收到多个提醒时，回复"1"即可批量完成
- ✅ **自动修复**: 重启后自动恢复提醒状态，防止提醒丢失
- ✅ **Web管理**: 提供Web界面管理待办事项

### 2. API余额监控 💰

- **自动监控**: 每30分钟自动检查API余额
- **余额预警**: 余额低于1元自动发送通知
- **快速查询**: 发送 `#余额` 查询当前余额
- **一键更新**: 直接发送新的API KEY即可更新

### 3. NOFX交易系统热更新 🔄

- **自动同步**: 更新API KEY时自动同步到NOFX交易系统
- **不中断交易**: 热更新机制，运行中的交易不受影响
- **多交易所支持**: 支持Binance、OKX、Hyperliquid、Aster
- **安全认证**: 使用JWT Token安全认证

### 4. 天气推送 🌤️

- **每日推送**: 每天早上8点自动推送天气预报
- **AI生活建议**: 结合天气和待办事项提供智能建议
- **成都本地化**: 针对成都地区优化

## 🚀 快速开始

### 前置要求

- Python 3.8+
- MySQL 5.7+ 或 MariaDB
- 企业微信账号（或其他支持的通道）
- OpenAI API Key 或兼容的API服务

### 一键部署

#### 1. 克隆仓库

```bash
git clone https://github.com/871311823/chatgpt-on-wechat-panghu.git
cd chatgpt-on-wechat-panghu
```

#### 2. 安装依赖

```bash
pip install -r requirements.txt
```

#### 3. 配置数据库

创建MySQL数据库：
```sql
CREATE DATABASE panghu CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

#### 4. 配置文件

复制配置模板：
```bash
cp config-template.json config.json
```

编辑 `config.json`，填入必要配置：

```json
{
  "channel_type": "wechatcom_app",
  "model": "gpt-4",
  "open_ai_api_key": "你的API_KEY",
  "open_ai_api_base": "https://api.openai.com/v1",
  
  "wechatcom_corp_id": "企业微信ID",
  "wechatcomapp_secret": "应用Secret",
  "wechatcomapp_agent_id": "应用AgentID",
  
  "db_url": "mysql+pymysql://user:password@localhost:3306/panghu?charset=utf8mb4",
  
  "weather": {
    "amap_key": "高德地图API_KEY",
    "target_user": "接收天气推送的用户ID",
    "city_adcode": "510116",
    "city_name": "成都市双流区",
    "push_time": "08:00"
  },
  
  "nofx": {
    "email": "NOFX登录邮箱",
    "password": "NOFX登录密码",
    "base_url": "http://your-nofx-server",
    "port": 80,
    "exchanges": ["binance", "okx", "hyperliquid", "aster"]
  }
}
```

#### 5. 启动服务

```bash
chmod +x start.sh
./start.sh
```

服务启动后会自动：
- ✅ 初始化数据库
- ✅ 修复提醒状态
- ✅ 启动微信服务
- ✅ 启动API服务器（端口9900）

### 访问Web界面

- **待办管理**: http://your-server:9900/todolist?user_id=1
- **API接口**: http://your-server:9900/api/todos

## 📖 详细使用说明

### 待办提醒

#### 创建待办
```
#todo 买菜 /at 明天下午3点
#todo 开会 /at 2025-01-20 14:00
#todo 每天喝水 /at 09:00 /repeat daily
```

#### 时间表达支持
- 相对时间: "明天"、"后天"、"下周五"、"3天后"
- 绝对时间: "2025-01-20 14:00"
- 周期性: `/repeat daily`（每天）、`weekly`（每周）、`monthly`（每月）

#### 批量完成
收到多个提醒时：
```
机器人: ⏰ 提醒：早上锻炼
机器人: ⏰ 提醒：喝水
机器人: ⏰ 提醒：吃早餐

你: 1

机器人: ✅ 已批量完成 3 个待办
```

### API余额监控

#### 查询余额
```
#余额
```

#### 更新API KEY
直接发送新的API KEY：
```
sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

系统会自动：
1. 验证新KEY是否有效
2. 更新配置
3. 同步到NOFX交易系统（如果配置了）

### 天气推送

每天早上8点自动推送：
```
🌤️ 成都天气预报

今天：晴，15-25℃
明天：多云，14-23℃

💡 AI生活建议：
今天天气不错，适合户外活动...
```

## 🔧 高级配置

### 插件配置

编辑 `plugins/config.json`：

```json
{
  "api_balance": {
    "enabled": true
  },
  "todolist": {
    "enabled": true
  }
}
```

### 数据库迁移

如果需要更新数据库结构：
```bash
# 查看迁移脚本
cat 更新数据库结构.sql

# 执行迁移
mysql -u user -p panghu < 更新数据库结构.sql
```

### 日志查看

```bash
# 查看微信服务日志
tail -f wechat.log

# 查看API服务日志
tail -f api.log

# 查看提醒日志
grep "ReminderScheduler" wechat.log
```

## 🐛 故障排查

### 提醒不工作

1. 检查调度器是否运行：
```bash
grep "ReminderScheduler" wechat.log | tail -10
```

2. 检查待办状态：
```bash
mysql -u user -p panghu -e "SELECT id, title, remind_at, reminded FROM todos WHERE status='pending'"
```

3. 手动修复提醒状态：
```bash
python 修复提醒状态_v2.py
```

### API余额查询失败

1. 检查网络连接
2. 验证API KEY是否有效
3. 查看日志：
```bash
grep "APIBalance" wechat.log | tail -10
```

### NOFX同步失败

1. 检查NOFX服务是否运行
2. 验证登录凭证是否正确
3. 查看日志：
```bash
grep "NofxAPI" wechat.log | tail -10
```

## 📁 项目结构

```
chatgpt-on-wechat-panghu/
├── common/                      # 核心服务
│   ├── api_balance_service.py  # API余额监控
│   ├── nofx_api_service.py     # NOFX热更新
│   ├── scheduler.py            # 调度器
│   ├── weather_service.py      # 天气服务
│   ├── service.py              # 待办服务
│   ├── db.py                   # 数据库连接
│   └── models.py               # 数据模型
├── plugins/                     # 插件
│   ├── api_balance/            # API余额插件
│   └── todolist/               # 待办插件
├── config.py                    # 配置管理
├── start.sh                     # 启动脚本
├── todolist_api_server.py      # API服务器
└── README.md                    # 本文档
```

## 🔐 安全建议

### 敏感信息保护

1. **不要提交敏感文件**：
   - `config.json` - 包含API密钥
   - `api_balance_data.json` - 包含余额数据
   - `*.log` - 日志文件

2. **设置文件权限**：
```bash
chmod 600 config.json
chmod 600 api_balance_data.json
```

3. **定期更换密钥**：
   - API KEY: 每3个月
   - NOFX密码: 每月
   - 数据库密码: 每季度

### 网络安全

1. **使用HTTPS**: 配置反向代理（Nginx）
2. **限制IP访问**: 配置防火墙规则
3. **启用认证**: API接口添加Token认证

## 🔄 更新维护

### 拉取最新代码

```bash
cd chatgpt-on-wechat-panghu
git pull origin main
```

### 重启服务

```bash
./start.sh
```

### 备份数据

```bash
# 备份数据库
mysqldump -u user -p panghu > backup_$(date +%Y%m%d).sql

# 备份配置
cp config.json config.json.backup
```

## 🤝 贡献

欢迎提交Issue和Pull Request！

### 开发环境设置

```bash
# 安装开发依赖
pip install -r requirements-optional.txt

# 运行测试
python test_api_balance.py
python test_nofx_api.py
```

## 📄 许可证

本项目基于原项目的许可证，仅供个人学习和使用。

## 🙏 致谢

- [chatgpt-on-wechat](https://github.com/zhayujie/chatgpt-on-wechat) - 原始项目
- OpenAI - GPT模型
- 高德地图 - 天气API

## 📞 联系方式

- GitHub Issues: https://github.com/871311823/chatgpt-on-wechat-panghu/issues
- Email: 871311823@qq.com

## 🎯 路线图

### 已完成 ✅
- [x] 智能待办提醒系统
- [x] API余额监控
- [x] NOFX热更新
- [x] 批量完成提醒
- [x] 启动时自动修复
- [x] 天气推送

### 计划中 📋
- [ ] 支持更多AI模型
- [ ] 语音提醒功能
- [ ] 移动端App
- [ ] 多用户支持
- [ ] 数据统计分析
- [ ] 智能任务推荐

## 💡 使用技巧

### 1. 快速创建待办
```
#todo 明天9点开会
#todo 下周五提交报告
#todo 每天早上8点锻炼
```

### 2. 批量管理
收到多个提醒时，回复"1"批量完成

### 3. 余额监控
系统会自动监控，无需手动查询

### 4. 一键更新
更新API KEY时，NOFX会自动同步

## ⚠️ 注意事项

1. **首次部署**: 需要配置数据库和企业微信
2. **API余额**: 建议保持充足余额，避免服务中断
3. **定期备份**: 重要数据请定期备份
4. **日志监控**: 定期查看日志，及时发现问题

## 🌟 特色功能

### 与原版对比

| 功能 | 原版 | 增强版 |
|------|------|--------|
| 待办提醒 | ❌ | ✅ |
| 批量完成 | ❌ | ✅ |
| API监控 | ❌ | ✅ |
| 热更新 | ❌ | ✅ |
| 自动修复 | ❌ | ✅ |
| 天气推送 | ❌ | ✅ |
| Web管理 | ❌ | ✅ |

---

**版本**: v1.0.0  
**更新时间**: 2025-11-24  
**状态**: ✅ 稳定运行
