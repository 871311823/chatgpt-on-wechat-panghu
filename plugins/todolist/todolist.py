import re
from datetime import datetime

import plugins
from plugins import Plugin
from plugins.event import Event, EventAction, EventContext
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from common.service import ensure_user, list_todos, complete_todo, delete_todo, create_todo, _parse_at
from config import conf


@plugins.register(
    name="todolist",
    desire_priority=1999,
    hidden=False,
    desc="待办功能：通过对话管理待办事项",
    version="1.0.0",
    author="auto",
)
class TodoListPlugin(Plugin):
    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context

    def on_handle_context(self, e_context: EventContext):
        context = e_context["context"]
        if context.type != ContextType.TEXT:
            return
        
        text = str(context.content).strip()
        
        # 检查是否是单个数字（批量完成快捷方式）
        if text.isdigit() and len(text) == 1:
            self._handle_batch_complete(e_context, text)
            return
        
        # 只处理 #todo 开头的消息
        if not text.startswith("#todo"):
            return

        # 确保用户存在
        msg = context["msg"]
        user_id = getattr(msg, "other_user_id", getattr(msg, "from_user_id", "unknown"))
        user = ensure_user(user_id, getattr(msg, "other_user_nickname", None))

        # 解析命令
        parts = text.split(None, 2)  # 最多分成3部分
        command = parts[1] if len(parts) > 1 else ""
        arg = parts[2] if len(parts) > 2 else ""

        reply = Reply()
        
        # 处理不同命令
        if command.lower() in ("list", "ls", "列表"):
            # 查看列表
            status = arg.lower() if arg else "pending"
            if status == "all":
                status = None
            
            todos = list_todos(user, status=status, limit=20)
            
            if not todos:
                reply.type = ReplyType.TEXT
                reply.content = "📋 暂无待办事项"
            else:
                lines = ["📋 待办列表："]
                for t in todos:
                    status_emoji = "✅" if t.status == "done" else "⏳"
                    when = t.remind_at.strftime("%m-%d %H:%M") if t.remind_at else ""
                    time_str = f" ({when})" if when else ""
                    lines.append(f"{status_emoji} {t.id}. {t.title}{time_str}")
                reply.type = ReplyType.TEXT
                reply.content = "\n".join(lines)
        
        elif command.lower() in ("done", "完成") and arg:
            # 完成待办
            todo_id = int(arg)
            ok, msg_text = complete_todo(user, todo_id)
            reply.type = ReplyType.TEXT if ok else ReplyType.ERROR
            reply.content = msg_text
        
        elif command.lower() in ("del", "rm", "删除") and arg:
            # 删除待办
            todo_id = int(arg)
            ok, msg_text = delete_todo(user, todo_id)
            reply.type = ReplyType.TEXT if ok else ReplyType.ERROR
            reply.content = msg_text
        
        elif command.lower() in ("break", "breakdown", "拆分"):
            # 拆解待办（仅显示建议）
            if arg:
                try:
                    todo_id = int(arg)
                    todos = list_todos(user, limit=100)
                    todo = next((t for t in todos if t.id == todo_id), None)
                    
                    if todo:
                        reply.type = ReplyType.TEXT
                        reply.content = f"📝 待办拆解建议（{todo.title}）：\n\n1. 准备工作\n2. 执行步骤\n3. 检查完成\n\n💡 这只是建议，不会保存"
                    else:
                        reply.type = ReplyType.ERROR
                        reply.content = "未找到该待办"
                except ValueError:
                    reply.type = ReplyType.ERROR
                    reply.content = "无效的待办ID"
            else:
                reply.type = ReplyType.ERROR
                reply.content = "请指定待办ID，例如：#todo break 1"
        
        else:
            # 创建待办或显示帮助
            if not command and not arg:
                # 空的 #todo 命令，显示帮助
                reply.type = ReplyType.TEXT
                reply.content = "📝 待办功能使用帮助：\n\n创建：#todo 内容\n创建（含时间）：#todo 内容 /at 2025-01-20 09:00\n查看：#todo list\n完成：#todo done 1\n删除：#todo del 1\n拆解：#todo break 1"
            else:
                # 创建待办
                # 合并 command 和 arg 作为完整内容
                full_content = text[len("#todo"):].strip()
                body, remind_time = _parse_at(full_content)
                
                if not body.strip():
                    reply.type = ReplyType.ERROR
                    reply.content = "待办内容不能为空"
                else:
                    ok, result = create_todo(user, body.strip(), remind_time)
                    reply.type = ReplyType.TEXT if ok else ReplyType.ERROR
                    reply.content = result

        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS

    def _handle_batch_complete(self, e_context: EventContext, digit: str):
        """处理批量完成：回复单个数字完成最近的多个提醒"""
        context = e_context["context"]
        msg = context["msg"]
        user_id = getattr(msg, "other_user_id", getattr(msg, "from_user_id", "unknown"))
        user = ensure_user(user_id, getattr(msg, "other_user_nickname", None))
        
        reply = Reply()
        
        try:
            from datetime import timedelta
            from common.db import get_session
            from common.models import Todo
            from sqlalchemy import select
            
            # 查找最近5分钟内应该提醒的待办（还未完成的）
            now = datetime.now()
            time_window_start = now - timedelta(minutes=5)
            
            with get_session() as s:
                # 查找符合条件的待办：
                # 1. 属于当前用户
                # 2. 状态为pending
                # 3. 提醒时间在最近5分钟内
                # 4. 还未完成
                recent_todos = s.execute(
                    select(Todo).where(
                        Todo.user_id == user.id,
                        Todo.status == "pending",
                        Todo.remind_at != None,
                        Todo.remind_at >= time_window_start,
                        Todo.remind_at <= now
                    ).order_by(Todo.remind_at)
                ).scalars().all()
                
                if not recent_todos:
                    # 没有找到最近的提醒，不处理
                    return
                
                # 批量完成这些待办
                completed_count = 0
                completed_titles = []
                
                for todo in recent_todos:
                    ok, _ = complete_todo(user, todo.id)
                    if ok:
                        completed_count += 1
                        completed_titles.append(todo.title)
                
                if completed_count > 0:
                    reply.type = ReplyType.TEXT
                    if completed_count == 1:
                        reply.content = f"✅ 已完成：{completed_titles[0]}"
                    else:
                        titles_str = "\n".join([f"  • {title}" for title in completed_titles])
                        reply.content = f"✅ 已批量完成 {completed_count} 个待办：\n{titles_str}"
                    
                    e_context["reply"] = reply
                    e_context.action = EventAction.BREAK_PASS
                else:
                    # 没有成功完成任何待办，不处理
                    return
                    
        except Exception as e:
            logger.error(f"[TodoList] Batch complete error: {e}")
            # 出错时不处理，让其他插件继续
            return
    
    def get_help_text(self, **kwargs):
        return "📝 待办功能：#todo 内容 /at 时间\n💡 快捷完成：收到提醒后回复数字1即可批量完成"


