#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
独立 Todolist API 服务器
同时支持 Web 和微信端，共享同一数据库
"""

import web
import os
from datetime import datetime
import json
import openai
from typing import Optional

# 导入数据库相关
from common.db import get_session, init_db
from common.models import User, Todo
from common.service import ensure_user, list_todos, complete_todo, delete_todo, create_todo, _parse_at, update_todo, undo_todo, reset_failed_todo
from sqlalchemy import select
from config import load_config, conf

# 加载配置并初始化数据库
try:
    load_config()
    init_db()
    print("✓ 数据库初始化成功")
except Exception as e:
    print(f"⚠ 数据库初始化警告: {e}")

# Web URL 路由
urls = (
    '/api/todos', 'TodoListAPI',
    '/api/todos/create', 'TodoCreateAPI',
    r'/api/todos/(\d+)/remind', 'TodoRemindAPI',
    r'/api/todos/(\d+)/complete', 'TodoCompleteAPI',
    r'/api/todos/(\d+)/delete', 'TodoDeleteAPI',
    r'/api/todos/(\d+)/breakdown', 'TodoBreakdownAPI',
    r'/api/todos/(\d+)/update', 'TodoUpdateAPI',
    r'/api/todos/(\d+)/undo', 'TodoUndoAPI',
    r'/api/todos/(\d+)/reset', 'TodoResetAPI',
    r'/api/todos/(\d+)', 'TodoItemAPI',  # 放在最后，避免冲突
    '/api/agent-prompt', 'AgentPromptAPI',
    '/api/balance', 'APIBalanceAPI',
    '/todolist', 'TodoListPage',
)


# 辅助函数
def _get_request_user(params: Optional[dict] = None) -> User:
    """根据请求参数获取用户，优先级：
    1) 显式传入 user_id/uid
    2) 数据库中的第一个用户（已有业务数据的用户）
    3) 回退到测试用户
    """
    # 1) 显式 user_id/uid
    try:
        if params:
            uid = params.get("user_id") or params.get("uid")
            if uid:
                with get_session() as s:
                    u = s.execute(select(User).where(User.id == int(uid))).scalar_one_or_none()
                    if u:
                        return u
    except Exception:
        pass

    # 2) 取已有的第一个用户（通常是微信端已有数据的用户）
    with get_session() as s:
        u = s.execute(select(User).order_by(User.id.asc()).limit(1)).scalar_one_or_none()
        if u:
            return u

    # 3) 回退到测试用户
    return ensure_user("web_user_test", "Web用户")


def _set_status(code: int):
    try:
        web.ctx.status = {
            400: '400 Bad Request',
            404: '404 Not Found',
            500: '500 Internal Server Error',
        }.get(code, '200 OK')
    except Exception:
        pass


def _settings_file() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(current_dir, 'data')
    if not os.path.isdir(data_dir):
        try:
            os.makedirs(data_dir, exist_ok=True)
        except Exception:
            pass
    return os.path.join(data_dir, 'agent_prompts.json')


def _load_agent_prompt_map() -> dict:
    try:
        path = _settings_file()
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def _save_agent_prompt_map(data: dict):
    try:
        path = _settings_file()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def generate_breakdown_suggestions(title: str, note: Optional[str] = None, override_agent_prompt: Optional[str] = None) -> dict:
    """Use configured LLM API to generate breakdown suggestions and agent prompt.
    Returns a dict: { 'suggestions': [...], 'agent_prompt': '...' }
    """
    default = {
        'suggestions': [
            "明确目标与完成标准",
            "列出3-5个步骤并估时",
            "设置提醒时间与负责人",
        ],
        'agent_prompt': override_agent_prompt or f"你是效率教练。请把任务‘{title}’拆成3-7个可执行子任务，输出条目化清单，每条≤20字，包含先后顺序与粗略耗时，不做无关延伸。"
    }

    try:
        api_key = conf().get("open_ai_api_key")
        api_base = conf().get("open_ai_api_base")
        model = conf().get("model") or "gpt-3.5-turbo"
        if not api_key:
            return default
        openai.api_key = api_key
        if api_base:
            openai.api_base = api_base

        base_system = (
            "你是资深效率教练。按‘目标—步骤—验收’思路，把输入任务拆为3-7个"
            "可执行子任务。输出简明中文条目，每条≤20字，可含估时(如20min)。"
        )
        system_prompt = base_system
        if override_agent_prompt:
            system_prompt = base_system + "\n补充写作风格/侧重点：" + override_agent_prompt
        user_prompt = f"待办：{title}\n补充说明：{note or '无'}\n给出子任务清单。"
        resp = openai.ChatCompletion.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=300,
        )
        content = resp["choices"][0]["message"]["content"].strip()
        # Split lines to suggestions
        suggestions = []
        for line in content.splitlines():
            # 去掉开头的符号和序号，保留内容
            line = line.strip("- •* \t")
            # 去掉开头的数字序号（如 "1. " 或 "1、" 等）
            import re
            line = re.sub(r'^\d+[\.、]\s*', '', line)
            if line:
                suggestions.append(line)
        if not suggestions:
            return default
        return {"suggestions": suggestions[:7], "agent_prompt": override_agent_prompt or ""}
    except Exception:
        return default


def todo_to_dict(todo: Todo) -> dict:
    """将Todo对象转换为字典"""
    return {
        'id': todo.id,
        'title': todo.title,
        'note': todo.note,
        'status': todo.status,
        'due_at': todo.due_at.isoformat() if todo.due_at else None,
        'remind_at': todo.remind_at.isoformat() if todo.remind_at else None,
        'repeat_rule': todo.repeat_rule,
        'reminded': todo.reminded,
        'completed_at': todo.completed_at.isoformat() if todo.completed_at else None,
        'created_at': todo.created_at.isoformat(),
    }


# API Handlers
class TodoListAPI:
    """GET /api/todos"""
    
    def GET(self):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')
            
            params = web.input()
            user = _get_request_user(params)
            
            status = params.get('status', 'pending')
            if status == 'all':
                status = None
            
            todos = list_todos(user, status=status, limit=100)
            result = [todo_to_dict(t) for t in todos]
            
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)


class TodoCreateAPI:
    """POST /api/todos/create"""
    
    def POST(self):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')
            
            # 安全解析 JSON 数据
            raw_data = web.data()
            print(f"[DEBUG] Raw data: {raw_data}")  # 调试信息
            if not raw_data:
                _set_status(400)
                return json.dumps({'error': 'Request body is empty'}, ensure_ascii=False)
            
            try:
                data = json.loads(raw_data)
                print(f"[DEBUG] Parsed data: {data}")  # 调试信息
            except json.JSONDecodeError as e:
                _set_status(400)
                return json.dumps({'error': f'Invalid JSON: {str(e)}'}, ensure_ascii=False)
            
            params = web.input()
            user = _get_request_user(params)
            
            # 安全获取 title
            title = ''
            if isinstance(data, dict):
                title = (data.get('title') or '').strip()
            else:
                _set_status(400)
                return json.dumps({'error': 'Invalid request data format'}, ensure_ascii=False)
            if not title:
                _set_status(400)
                return json.dumps({'error': 'Title is required'}, ensure_ascii=False)
            
            # 解析时间（显式传入）
            remind_time = None
            if data.get('remind_at'):
                try:
                    remind_time = datetime.fromisoformat(data.get('remind_at').replace('Z', '+00:00'))
                except Exception:
                    remind_time = None
            
            parsed_title = title
            parsed_remind_time = remind_time
            # 如果请求中未显式提供提醒时间，则尝试通过语义解析拆解标题
            if parsed_remind_time is None:
                try:
                    body, parsed_time = _parse_at(title)
                    body = (body or '').strip()
                    if body:
                        parsed_title = body
                    # 解析到时间则使用
                    if parsed_time:
                        parsed_remind_time = parsed_time
                except Exception as e:
                    print(f"[WARN] Semantic parse failed: {e}")
            
            # 获取重复规则
            repeat_rule = None
            if data.get('repeat_rule'):
                repeat_rule = data.get('repeat_rule').strip() or None
            
            # 调用 service 创建，暂时先不传 repeat_rule（后续扩展）
            ok, result = create_todo(user, parsed_title, parsed_remind_time)
            
            # 如果创建成功且有 repeat_rule，更新数据库
            if ok and repeat_rule:
                from common.db import get_session
                from common.models import Todo
                from sqlalchemy import select, update
                with get_session() as s:
                    # 找到刚创建的 todo
                    stmt = select(Todo).where(Todo.user_id == user.id).order_by(Todo.id.desc()).limit(1)
                    todo = s.execute(stmt).scalar_one_or_none()
                    if todo:
                        s.execute(update(Todo).where(Todo.id == todo.id).values(repeat_rule=repeat_rule))
                        s.commit()
            
            if ok:
                # 返回最新创建的待办
                todos = list_todos(user, limit=1)
                if todos:
                    return json.dumps(todo_to_dict(todos[0]), ensure_ascii=False)
                return json.dumps({'message': result}, ensure_ascii=False)
            else:
                _set_status(400)
                return json.dumps({'error': result}, ensure_ascii=False)
                
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)


class TodoItemAPI:
    """GET/POST /api/todos/<id>"""
    
    def GET(self, todo_id):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')
            
            params = web.input()
            user = _get_request_user(params)
            todos = list_todos(user, limit=100)
            todo = next((t for t in todos if t.id == int(todo_id)), None)
            
            if not todo:
                _set_status(404)
                return json.dumps({'error': 'Todo not found'}, ensure_ascii=False)
            
            return json.dumps(todo_to_dict(todo), ensure_ascii=False)
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)
    
    def POST(self, todo_id):
        """更新待办（目前主要用于更新 repeat_rule）"""
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')
            
            params = web.input()
            user = _get_request_user(params)
            data = json.loads(web.data() or '{}')
            
            from common.db import get_session
            from common.models import Todo
            from sqlalchemy import select, update
            
            with get_session() as s:
                # 验证待办属于该用户
                todo = s.execute(select(Todo).where(Todo.id == int(todo_id), Todo.user_id == user.id)).scalar_one_or_none()
                if not todo:
                    _set_status(404)
                    return json.dumps({'error': 'Todo not found'}, ensure_ascii=False)
                
                # 更新字段
                update_data = {}
                if 'repeat_rule' in data:
                    update_data['repeat_rule'] = data['repeat_rule'] or None
                
                if update_data:
                    s.execute(update(Todo).where(Todo.id == int(todo_id)).values(**update_data))
                    s.commit()
                
                return json.dumps({'message': '更新成功', 'todo_id': int(todo_id)}, ensure_ascii=False)
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)


class TodoRemindAPI:
    """GET/PUT/DELETE /api/todos/<id>/remind
    - GET: 返回当前 remind_at
    - PUT: JSON { remind_at: ISO8601或'YYYY-MM-DD HH:MM' } 设置/更新提醒时间
    - DELETE: 清除提醒时间
    """

    def GET(self, todo_id):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')

            params = web.input()
            user = _get_request_user(params)
            todos = list_todos(user, limit=100)
            todo = next((t for t in todos if t.id == int(todo_id)), None)
            if not todo:
                _set_status(404)
                return json.dumps({'error': 'Todo not found'}, ensure_ascii=False)
            return json.dumps({'todo_id': todo.id, 'remind_at': todo.remind_at.isoformat() if todo.remind_at else None}, ensure_ascii=False)
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)

    def PUT(self, todo_id):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')

            params = web.input()
            user = _get_request_user(params)
            todos = list_todos(user, limit=100)
            todo = next((t for t in todos if t.id == int(todo_id)), None)
            if not todo:
                _set_status(404)
                return json.dumps({'error': 'Todo not found'}, ensure_ascii=False)

            data = json.loads(web.data() or '{}')
            value = (data.get('remind_at') or '').strip()

            # 解析时间
            new_time = None
            if value:
                try:
                    if 'T' in value:
                        new_time = datetime.fromisoformat(value.replace('Z', '+00:00'))
                    else:
                        new_time = datetime.strptime(value, '%Y-%m-%d %H:%M')
                except Exception:
                    _set_status(400)
                    return json.dumps({'error': 'Invalid time format'}, ensure_ascii=False)

            # 更新
            from common.service import edit_todo
            ok, msg = edit_todo(user, todo.id, new_time=new_time)
            if ok:
                return json.dumps({'message': msg, 'remind_at': new_time.isoformat() if new_time else None}, ensure_ascii=False)
            _set_status(400)
            return json.dumps({'error': msg}, ensure_ascii=False)
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)

    def DELETE(self, todo_id):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')

            params = web.input()
            user = _get_request_user(params)
            todos = list_todos(user, limit=100)
            todo = next((t for t in todos if t.id == int(todo_id)), None)
            if not todo:
                _set_status(404)
                return json.dumps({'error': 'Todo not found'}, ensure_ascii=False)

            from common.service import edit_todo
            ok, msg = edit_todo(user, todo.id, clear_remind=True)
            if ok:
                return json.dumps({'message': msg, 'remind_at': None}, ensure_ascii=False)
            _set_status(400)
            return json.dumps({'error': msg}, ensure_ascii=False)
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)

class TodoCompleteAPI:
    """POST /api/todos/<id>/complete"""
    
    def POST(self, todo_id):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')
            
            params = web.input()
            user = _get_request_user(params)
            ok, result = complete_todo(user, int(todo_id))
            
            if ok:
                return json.dumps({'message': result}, ensure_ascii=False)
            else:
                _set_status(400)
                return json.dumps({'error': result}, ensure_ascii=False)
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)


class TodoDeleteAPI:
    """POST /api/todos/<id>/delete"""
    
    def POST(self, todo_id):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')
            
            params = web.input()
            user = _get_request_user(params)
            ok, result = delete_todo(user, int(todo_id))
            
            if ok:
                return json.dumps({'message': result}, ensure_ascii=False)
            else:
                _set_status(400)
                return json.dumps({'error': result}, ensure_ascii=False)
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)


class TodoBreakdownAPI:
    """POST /api/todos/<id>/breakdown"""
    
    def POST(self, todo_id):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')
            
            params = web.input()
            user = _get_request_user(params)
            todos = list_todos(user, limit=100)
            todo = next((t for t in todos if t.id == int(todo_id)), None)
            
            if not todo:
                _set_status(404)
                return json.dumps({'error': 'Todo not found'}, ensure_ascii=False)
            
            # 解析可选自定义 agent 提示词（JSON body）
            try:
                raw = web.data()
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            override_prompt = payload.get('agent_prompt') or payload.get('prompt') if isinstance(payload, dict) else None

            gen = generate_breakdown_suggestions(todo.title, todo.note, override_agent_prompt=override_prompt)
            
            # 只返回建议，不返回 agent_prompt
            return json.dumps({
                'todo_id': todo.id,
                'todo_title': todo.title,
                'suggestions': gen.get('suggestions', []),
                'note': 'AI生成建议（不入库），仅供参考'
            }, ensure_ascii=False)
            
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)


class TodoUpdateAPI:
    """POST /api/todos/{id}/update - 更新待办"""
    
    def POST(self, todo_id):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')
            
            params = web.input()
            user = _get_request_user(params)
            
            # 解析请求体
            data = json.loads(web.data() or '{}')
            title = data.get('title', '').strip() if data.get('title') else None
            time_str = data.get('remind_at')
            repeat_rule = data.get('repeat_rule', '') if data.get('repeat_rule') else None
            
            # 解析提醒时间
            remind_at = None
            if time_str:
                try:
                    if 'T' in time_str:
                        remind_at = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    else:
                        remind_at = datetime.strptime(time_str, '%Y-%m-%dT%H:%M')
                except Exception as e:
                    print(f"Parse time error: {e}")
            
            ok, result = update_todo(user, int(todo_id), title=title, remind_at=remind_at, repeat_rule=repeat_rule)
            
            if ok:
                return json.dumps({'message': result}, ensure_ascii=False)
            else:
                _set_status(400)
                return json.dumps({'error': result}, ensure_ascii=False)
                
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)


class TodoUndoAPI:
    """POST /api/todos/{id}/undo - 恢复待办为待办中"""
    
    def POST(self, todo_id):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')
            
            params = web.input()
            user = _get_request_user(params)
            
            ok, result = undo_todo(user, int(todo_id))
            
            if ok:
                return json.dumps({'message': result}, ensure_ascii=False)
            else:
                _set_status(400)
                return json.dumps({'error': result}, ensure_ascii=False)
                
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)


class TodoResetAPI:
    """POST /api/todos/{id}/reset - 重置失败状态的待办"""
    
    def POST(self, todo_id):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')
            
            params = web.input()
            user = _get_request_user(params)
            
            ok, result = reset_failed_todo(user, int(todo_id))
            
            if ok:
                return json.dumps({'message': result}, ensure_ascii=False)
            else:
                _set_status(400)
                return json.dumps({'error': result}, ensure_ascii=False)
                
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)


class AgentPromptAPI:
    """GET/POST /api/agent-prompt
    GET: ?user_id=1  -> 返回 { user_id, agent_prompt }
    POST: JSON { user_id, agent_prompt } -> 保存并返回相同结构
    作用：持久化每个用户的 Agent 提示词
    """

    def GET(self):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')

            params = web.input()
            user = _get_request_user(params)
            store = _load_agent_prompt_map()
            prompt = store.get(str(user.id)) or ''
            return json.dumps({ 'user_id': user.id, 'agent_prompt': prompt }, ensure_ascii=False)
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)

    def POST(self):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')

            params = web.input()
            user = _get_request_user(params)
            body = json.loads(web.data() or '{}')
            prompt = (body.get('agent_prompt') or '').strip()
            store = _load_agent_prompt_map()
            store[str(user.id)] = prompt
            _save_agent_prompt_map(store)
            return json.dumps({ 'user_id': user.id, 'agent_prompt': prompt }, ensure_ascii=False)
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)


class APIBalanceAPI:
    """GET/POST /api/balance
    GET: 查询API余额
    POST: 更新API KEY
    """

    def GET(self):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')

            from common.api_balance_service import get_balance_service
            balance_service = get_balance_service()
            
            # 获取Web展示数据
            data = balance_service.get_balance_for_web()
            return json.dumps(data, ensure_ascii=False)
            
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)

    def POST(self):
        try:
            web.header('Content-Type', 'application/json')
            web.header('Access-Control-Allow-Origin', '*')

            body = json.loads(web.data() or '{}')
            api_key = body.get('api_key', '').strip()
            
            if not api_key:
                _set_status(400)
                return json.dumps({'error': 'API KEY不能为空'}, ensure_ascii=False)
            
            from common.api_balance_service import get_balance_service
            balance_service = get_balance_service()
            
            # 更新API KEY
            result = balance_service.update_api_key(api_key)
            
            if result['success']:
                return json.dumps({
                    'success': True,
                    'message': result['message'],
                    'balance': result.get('balance', 0)
                }, ensure_ascii=False)
            else:
                _set_status(400)
                return json.dumps({
                    'success': False,
                    'error': result['message']
                }, ensure_ascii=False)
                
        except Exception as e:
            _set_status(500)
            return json.dumps({'error': str(e)}, ensure_ascii=False)


class TodoListPage:
    """GET /todolist - 前端页面"""
    
    def GET(self):
        try:
            import os
            file_path = os.path.join(os.path.dirname(__file__), 'channel/web/todolist.html')
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error loading page: {e}"


if __name__ == '__main__':
    import sys
    import os
    
    # 确保在项目根目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(current_dir)
    
    # 加载配置
    from config import load_config
    try:
        load_config()
        print("✓ 配置加载成功")
    except Exception as e:
        print(f"⚠ 配置加载警告: {e}")
    
    print("=" * 60)
    print("Todolist API 服务器启动中...")
    print("=" * 60)
    print("访问地址：")
    print("  - 前端页面: http://localhost:9900/todolist")
    print("  - 前端页面（服务器）: http://你的IP:9900/todolist")
    print("  - API接口: http://localhost:9900/api/todos")
    print("=" * 60)
    print("")
    
    app = web.application(urls, globals())
    web.httpserver.runsimple(app.wsgifunc(), ("0.0.0.0", 9900))

