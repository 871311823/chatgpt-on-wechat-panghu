# encoding:utf-8

"""
API余额查询插件
支持查询硅基流动API余额和更新API KEY
"""

import plugins
from plugins import Plugin
from plugins.event import Event, EventAction, EventContext
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from common.api_balance_service import get_balance_service


@plugins.register(
    name="api_balance",
    desire_priority=1996,
    hidden=False,
    desc="API余额查询和管理",
    version="1.0.0",
    author="auto",
)
class APIBalancePlugin(Plugin):
    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context

    def on_handle_context(self, e_context: EventContext):
        context = e_context["context"]
        if context.type != ContextType.TEXT:
            return
        
        text = str(context.content).strip()
        
        # 处理 #余额 命令
        if text.startswith("#余额"):
            self._handle_balance_query(e_context)
            return
        
        # 处理更新API KEY命令（检测是否是以sk-开头的长字符串）
        if text.startswith("sk-") and len(text) > 40:
            self._handle_api_key_update(e_context, text)
            return
    
    def _handle_balance_query(self, e_context: EventContext):
        """处理余额查询"""
        reply = Reply()
        
        try:
            balance_service = get_balance_service()
            message = balance_service.get_balance_info()
            
            reply.type = ReplyType.TEXT
            reply.content = message
            
        except Exception as e:
            logger.error(f"[APIBalance] Failed to query balance: {e}")
            reply.type = ReplyType.ERROR
            reply.content = f"❌ 查询余额失败：{str(e)}"

        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_api_key_update(self, e_context: EventContext, api_key: str):
        """处理API KEY更新"""
        reply = Reply()
        
        try:
            balance_service = get_balance_service()
            result = balance_service.update_api_key(api_key)
            
            reply.type = ReplyType.TEXT if result["success"] else ReplyType.ERROR
            reply.content = result["message"]
            
            if result["success"]:
                reply.content += "\n\n💡 系统将每30分钟自动检查余额"
                
                # 如果NOFX同步失败，提供手动更新说明
                if not result.get("nofx_synced", False):
                    reply.content += "\n\n" + "="*30
                    reply.content += "\n⚠️ 需要手动更新NOFX"
                    reply.content += "\n" + "="*30
                    reply.content += "\n\n📝 更新步骤:"
                    reply.content += "\n1. 访问 http://47.109.82.94:3000"
                    reply.content += "\n2. 登录 -> 设置 -> AI模型配置"
                    reply.content += "\n3. 选择DeepSeek -> 粘贴新KEY -> 保存"
            
        except Exception as e:
            logger.error(f"[APIBalance] Failed to update API key: {e}")
            reply.type = ReplyType.ERROR
            reply.content = f"❌ 更新API KEY失败：{str(e)}"

        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS

    def get_help_text(self, **kwargs):
        return "💰 API余额：#余额\n🔑 更新KEY：直接发送新的API KEY（sk-开头）"
