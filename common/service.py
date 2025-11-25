# encoding:utf-8

import re
import json
from datetime import datetime, timedelta
from typing import Optional, Tuple, List

from sqlalchemy import select, update, delete, func

from common.db import get_session
from common.models import User, Expense, Todo
from common.log import logger
from config import conf


def _first_number(text: str) -> Optional[float]:
    m = re.search(r"(-?\d+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _parse_time_with_llm(text: str) -> Tuple[str, Optional[datetime]]:
    """使用 LLM API 解析文本中的时间和任务
    返回: (任务名称, 提醒时间)
    """
    try:
        import openai
        
        api_key = conf().get("open_ai_api_key")
        api_base = conf().get("open_ai_api_base")
        model = conf().get("model") or "gpt-3.5-turbo"
        
        if not api_key:
            logger.warning("[Todo] LLM API key not configured, skip LLM parsing")
            return text, None
        
        logger.info(f"[Todo] Starting LLM parsing for: {text}")
        
        openai.api_key = api_key
        if api_base:
            openai.api_base = api_base
        
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")
        current_weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
        
        # 计算未来几天的日期
        tomorrow = now + timedelta(days=1)
        day_after_tomorrow = now + timedelta(days=2)
        
        # 计算本周剩余的日期
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        current_weekday_num = now.weekday()  # 0=周一, 6=周日
        
        system_prompt = (
            "你是一个智能时间解析助手。用户会输入包含任务和时间的文本，你需要准确提取任务名称和提醒时间。\n\n"
            "## 当前时间信息\n"
            f"- 完整时间：{current_date} {current_time} ({current_weekday})\n"
            f"- 明天：{tomorrow.strftime('%Y-%m-%d')} ({weekday_names[tomorrow.weekday()]})\n"
            f"- 后天：{day_after_tomorrow.strftime('%Y-%m-%d')} ({weekday_names[day_after_tomorrow.weekday()]})\n\n"
            "## 时间解析规则\n"
            "1. **相对时间**：\n"
            "   - '今天/今日/今晚' → 今天的日期\n"
            "   - '明天/明日/明早' → 明天的日期\n"
            "   - '后天' → 后天的日期\n"
            "   - '大后天' → 3天后\n\n"
            "2. **星期表达**：\n"
            "   - '周一/星期一/礼拜一' → 本周或下周的周一（如果今天是周一之后，则是下周）\n"
            "   - '周五/星期五' → 本周或下周的周五\n"
            "   - '下周一/下周五' → 明确指下周\n\n"
            "3. **时间点**：\n"
            "   - '早上/上午' → 09:00（如未指定具体时间）\n"
            "   - '中午' → 12:00\n"
            "   - '下午' → 15:00（如未指定具体时间）\n"
            "   - '晚上' → 19:00（如未指定具体时间）\n"
            "   - '凌晨' → 01:00（如未指定具体时间）\n"
            "   - '3点/3点半/15:30' → 具体时间\n\n"
            "4. **组合表达**：\n"
            "   - '明天下午3点' → 明天 15:00\n"
            "   - '周五晚上8点' → 本周或下周五 20:00\n"
            "   - '今晚8点' → 今天 20:00\n\n"
            "5. **智能判断**：\n"
            "   - 如果时间已过，自动推到明天或下一个合适的时间\n"
            "   - 如果只说'3点'且当前已过3点，推到明天3点\n\n"
            "## 输出格式\n"
            "必须返回有效的JSON，包含：\n"
            "- title: 任务名称（去掉时间描述，保留核心任务）\n"
            "- remind_at: 提醒时间（格式：YYYY-MM-DD HH:MM，无法解析则为null）\n\n"
            "## 示例\n"
            f"输入：'明天下午3点开会'\n"
            f"输出：{{\"title\": \"开会\", \"remind_at\": \"{tomorrow.strftime('%Y-%m-%d')} 15:00\"}}\n\n"
            f"输入：'今晚8点提醒我'\n"
            f"输出：{{\"title\": \"提醒我\", \"remind_at\": \"{current_date} 20:00\"}}\n\n"
            f"输入：'周五下午提交报告'\n"
            f"输出：{{\"title\": \"提交报告\", \"remind_at\": \"[计算本周或下周五的日期] 15:00\"}}\n\n"
            "输入：'买牛奶'\n"
            "输出：{\"title\": \"买牛奶\", \"remind_at\": null}\n\n"
            "注意：只返回JSON，不要有其他文字！"
        )
        
        user_prompt = f"请解析以下文本，提取任务名称和提醒时间：\n{text}"
        
        resp = openai.ChatCompletion.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=200,
        )
        
        content = resp["choices"][0]["message"]["content"].strip()
        logger.info(f"[Todo] LLM parsing result: {content}")
        
        # 尝试解析 JSON
        # 有时候 LLM 会在 JSON 外包裹 markdown 代码块，需要去掉
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        content = content.strip()
        
        result = json.loads(content)
        title = result.get("title", text).strip()
        remind_at_str = result.get("remind_at")
        
        logger.info(f"[Todo] Extracted - title: '{title}', remind_at: '{remind_at_str}'")
        
        if remind_at_str:
            try:
                remind_at = datetime.strptime(remind_at_str, "%Y-%m-%d %H:%M")
                # 如果解析出的时间已过期，自动调整为明天同一时间
                if remind_at <= now - timedelta(minutes=5):
                    logger.info(f"[Todo] Parsed time {remind_at} is in the past, adjusting to tomorrow")
                    remind_at = remind_at + timedelta(days=1)
                logger.info(f"[Todo] Final result - title: '{title}', remind_at: {remind_at}")
                return title, remind_at
            except ValueError as e:
                logger.warning(f"[Todo] Failed to parse time '{remind_at_str}': {e}")
                return title, None
        else:
            logger.info(f"[Todo] No remind_at in LLM response, returning title only")
            return title, None
            
    except json.JSONDecodeError as e:
        logger.error(f"[Todo] Failed to parse LLM response as JSON: {e}, content: {content}")
        return text, None
    except Exception as e:
        logger.error(f"[Todo] LLM parsing failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return text, None


def _parse_at(text: str) -> Tuple[str, Optional[datetime]]:
    """解析文本中的时间信息
    优先级：
    1. /noremind 或 /不提醒（明确不设置提醒）
    2. /at 格式（精确格式）
    3. LLM 智能解析（自然语言）
    """
    # 1. 检查是否明确指定不提醒
    noremind_pattern = r"/(noremind|不提醒|无提醒|no)"
    m_noremind = re.search(noremind_pattern, text, re.IGNORECASE)
    if m_noremind:
        # 去掉指令片段
        new_text = (text[: m_noremind.start()] + text[m_noremind.end():]).strip()
        logger.info(f"[Todo] No remind specified - title: '{new_text}'")
        return new_text, None
    
    # 2. 检查 /at 格式：/at YYYY-MM-DD HH:MM
    m = re.search(r"/at\s+([0-9]{4}[-/][0-9]{2}[-/][0-9]{2})\s+([0-9]{2}:[0-9]{2})", text)
    if m:
        date_part = m.group(1).replace("/", "-")
        time_part = m.group(2)
        dt = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M")
        # 去掉指令片段
        new_text = (text[: m.start()] + text[m.end():]).strip()
        logger.info(f"[Todo] Parsed /at format - title: '{new_text}', time: {dt}")
        return new_text, dt
    
    # 3. 使用 LLM 进行智能解析（支持自然语言）
    # 例如："明天下午3点开会"、"周五提交报告"、"今晚8点提醒我"
    logger.info(f"[Todo] Using LLM to parse natural language time: {text}")
    return _parse_time_with_llm(text)


def ensure_user(wework_conversation_id: str, nickname: Optional[str]) -> User:
    with get_session() as s:
        u = s.execute(select(User).where(User.wework_user_id == wework_conversation_id)).scalar_one_or_none()
        if u:
            if nickname and u.nickname != nickname:
                u.nickname = nickname
                s.commit()
            return u
        u = User(wework_user_id=wework_conversation_id, nickname=nickname)
        s.add(u)
        s.commit()
        s.refresh(u)
        return u


def create_expense_for_text(
    user: User,
    text: str,
    source_msg_id: Optional[str] = None,
) -> Tuple[bool, str]:
    amount = _first_number(text)
    if amount is None:
        return False, "未识别到金额，请使用示例：#记账 18.5 咖啡 备注"
    # 去掉金额，尝试解析分类和备注
    text_wo_amount = re.sub(r"(-?\d+(?:\.\d+)?)", "", text, count=1).strip()
    parts = text_wo_amount.split()
    category = parts[0] if parts else None
    note = " ".join(parts[1:]) if len(parts) > 1 else None

    with get_session() as s:
        exp = Expense(
            user_id=user.id,
            amount=amount,
            currency="CNY",
            category=category,
            note=note,
            spent_at=datetime.now(),
            source_msg_id=source_msg_id,
        )
        s.add(exp)
        s.commit()
        return True, f"已记账：¥{amount:.2f} {category or ''} {note or ''}"


def create_todo_for_text(
    user: User,
    text: str,
) -> Tuple[bool, str]:
    body, remind_at = _parse_at(text)
    title = body.strip()
    if not title:
        return False, "待办内容不能为空。示例：#todo 明早9点开会 /at 2025-10-22 09:00"
    with get_session() as s:
        todo = Todo(
            user_id=user.id,
            title=title[:128],
            remind_at=remind_at,
            status="pending",
        )
        s.add(todo)
        s.commit()
        when = remind_at.strftime("%Y-%m-%d %H:%M") if remind_at else "未设置提醒"
        return True, f"已创建待办：{title}（提醒：{when}）"


def create_todo(user: User, title: str, remind_at: Optional[datetime]) -> Tuple[bool, str]:
    title = (title or "").strip()
    if not title:
        return False, "待办内容不能为空。"
    with get_session() as s:
        todo = Todo(
            user_id=user.id,
            title=title[:128],
            remind_at=remind_at,
            status="pending",
        )
        s.add(todo)
        s.commit()
        when = remind_at.strftime("%Y-%m-%d %H:%M") if remind_at else "未设置提醒"
        return True, f"已创建待办：{title}（提醒：{when}）"


def fetch_due_reminders(now_utc: datetime):
    """获取需要提醒的待办事项
    包括：
    1. 首次提醒：remind_at 已到且还没提醒过
    2. 重复提醒：上次提醒后10分钟且提醒次数 < 3
    """
    with get_session() as s:
        # 首次提醒或第一次重复提醒（reminded=False且刚过提醒时间）
        initial_reminds = (
            s.execute(
                select(Todo, User)
                .join(User, Todo.user_id == User.id)
                .where(
                    Todo.status == "pending",
                    Todo.reminded == False,  # noqa: E712
                    Todo.remind_at != None,  # noqa: E711
                    Todo.remind_at <= now_utc,
                )
                .limit(50)
            ).all()
        )
        
        # 重复提醒：上次提醒后10分钟，且提醒次数 < 3
        ten_minutes_ago = now_utc - timedelta(minutes=10)
        repeat_reminds = (
            s.execute(
                select(Todo, User)
                .join(User, Todo.user_id == User.id)
                .where(
                    Todo.status == "pending",
                    Todo.remind_count < 3,
                    Todo.last_remind_at != None,
                    Todo.last_remind_at <= ten_minutes_ago,
                )
                .limit(50)
            ).all()
        )
        
        # 合并结果
        result = list(initial_reminds)
        result.extend(repeat_reminds)
        
        return result


def _calculate_next_remind_time(current_remind_at: datetime, repeat_rule: Optional[str]) -> Optional[datetime]:
    """根据重复规则计算下一次提醒时间"""
    if not repeat_rule or not current_remind_at:
        return None
    
    if repeat_rule == "daily":
        # 每天：加1天
        return current_remind_at + timedelta(days=1)
    elif repeat_rule == "workday":
        # 工作日（周一至周五）：如果不是周五，加1天；如果是周五，跳到下周一
        weekday = current_remind_at.weekday()  # 0=Monday, 4=Friday
        if weekday < 4:  # Monday to Thursday
            return current_remind_at + timedelta(days=1)
        else:  # Friday
            days_until_monday = 3  # Friday + 3 days = Monday
            return current_remind_at + timedelta(days=days_until_monday)
    elif repeat_rule == "weekly":
        # 每周：加7天
        return current_remind_at + timedelta(days=7)
    elif repeat_rule == "monthly":
        # 每月：加1个月
        year = current_remind_at.year
        month = current_remind_at.month
        day = current_remind_at.day
        hour = current_remind_at.hour
        minute = current_remind_at.minute
        second = current_remind_at.second
        
        # 处理月份加1
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
        
        # 处理月末日期（如1月31日 -> 2月28日）
        from calendar import monthrange
        max_day = monthrange(year, month)[1]
        day = min(day, max_day)
        
        return datetime(year, month, day, hour, minute, second)
    
    return None


def mark_reminded(todo_id: int):
    """标记待办为已提醒。
    逻辑：
    1. 首次提醒：设置 reminded=True，记录 last_remind_at，remind_count=1
    2. 重复提醒：remind_count += 1，更新 last_remind_at
    3. 如果 remind_count >= 3：设置 status='failed'
    4. 如果有重复规则，计算下一次提醒时间
    5. 周期性任务在凌晨会被 recover_failed_todos() 恢复
    """
    with get_session() as s:
        todo = s.execute(select(Todo).where(Todo.id == todo_id)).scalar_one_or_none()
        if not todo:
            return
        
        now = datetime.now()
        
        # 更新提醒计数和时间
        new_count = todo.remind_count + 1
        
        # 如果超过3次提醒仍未完成，标记为失败
        if new_count >= 3:
            status = 'failed'
        else:
            status = todo.status
        
        # 如果有重复规则，计算下一次提醒时间
        if todo.repeat_rule and todo.remind_at:
            next_remind_time = _calculate_next_remind_time(todo.remind_at, todo.repeat_rule)
        else:
            next_remind_time = None
        
        # 更新待办
        update_dict = {
            'reminded': True,
            'remind_count': new_count,
            'last_remind_at': now,
            'status': status
        }
        
        if next_remind_time:
            update_dict['remind_at'] = next_remind_time
            update_dict['reminded'] = False  # 重复任务重置提醒状态
        
        s.execute(update(Todo).where(Todo.id == todo_id).values(**update_dict))
        s.commit()



def list_todos(user: User, status: Optional[str] = None, limit: int = 20) -> List[Todo]:
    with get_session() as s:
        stmt = select(Todo).where(Todo.user_id == user.id)
        if status:
            if status == "pending":
                # "待办中"包含 pending 和 failed 状态
                stmt = stmt.where(Todo.status.in_(["pending", "failed"]))
            else:
                stmt = stmt.where(Todo.status == status)
        stmt = stmt.order_by(Todo.created_at.desc()).limit(limit)
        return s.execute(stmt).scalars().all()


def complete_todo(user: User, todo_id: int) -> Tuple[bool, str]:
    """完成待办
    重复任务不能被彻底完成，只能重置提醒计数
    """
    with get_session() as s:
        t = s.execute(select(Todo).where(Todo.id == todo_id, Todo.user_id == user.id)).scalar_one_or_none()
        if not t:
            return False, "未找到该待办"
        if t.status == "done":
            return True, "该待办已完成"
        
        # 重复任务：重置提醒计数和失败状态，不标记为完成
        if t.repeat_rule:
            t.status = "pending"
            t.remind_count = 0
            t.last_remind_at = None
            s.commit()
            return True, f"已确认：{t.title}（明日继续提醒）"
        
        # 非重复任务：标记为完成，记录完成时间
        t.status = "done"
        t.completed_at = datetime.now()
        s.commit()
        return True, f"已完成：{t.title}"


def delete_todo(user: User, todo_id: int) -> Tuple[bool, str]:
    with get_session() as s:
        t = s.execute(select(Todo).where(Todo.id == todo_id, Todo.user_id == user.id)).scalar_one_or_none()
        if not t:
            return False, "未找到该待办"
        s.execute(delete(Todo).where(Todo.id == todo_id))
        s.commit()
        return True, "已删除"


def edit_todo(user: User, todo_id: int, new_title: Optional[str] = None, new_time: Optional[datetime] = None, clear_remind: bool = False) -> Tuple[bool, str]:
    with get_session() as s:
        t = s.execute(select(Todo).where(Todo.id == todo_id, Todo.user_id == user.id)).scalar_one_or_none()
        if not t:
            return False, "未找到该待办"
        if new_title is not None:
            t.title = new_title[:128]
        if clear_remind:
            # 明确清除提醒时间
            t.remind_at = None
            t.reminded = False
        elif new_time is not None:
            t.remind_at = new_time
            t.reminded = False
        s.commit()
        when = t.remind_at.strftime("%Y-%m-%d %H:%M") if t.remind_at else "未设置"
        return True, f"已更新：{t.title}（提醒：{when}）"


def update_todo(user: User, todo_id: int, title: Optional[str] = None, remind_at: Optional[datetime] = None, 
                repeat_rule: Optional[str] = None) -> Tuple[bool, str]:
    """更新待办事项的完整信息"""
    with get_session() as s:
        t = s.execute(select(Todo).where(Todo.id == todo_id, Todo.user_id == user.id)).scalar_one_or_none()
        if not t:
            return False, "未找到该待办"
        if title is not None:
            t.title = title[:128]
        if remind_at is not None:
            t.remind_at = remind_at
            t.reminded = False
        if repeat_rule is not None:
            t.repeat_rule = repeat_rule
        s.commit()
        when = t.remind_at.strftime("%Y-%m-%d %H:%M") if t.remind_at else "未设置提醒"
        repeat_text = f"（重复：{repeat_rule}）" if repeat_rule else ""
        return True, f"已更新：{t.title}（提醒：{when}{repeat_text}）"


def undo_todo(user: User, todo_id: int) -> Tuple[bool, str]:
    """将已完成的待办恢复为待办中：删除原待办，创建新待办"""
    with get_session() as s:
        t = s.execute(select(Todo).where(Todo.id == todo_id, Todo.user_id == user.id)).scalar_one_or_none()
        if not t:
            return False, "未找到该待办"
        if t.status != "done":
            return False, "该待办尚未完成"
        
        # 保留原待办的信息
        title = t.title
        remind_at = t.remind_at
        repeat_rule = t.repeat_rule
        note = t.note
        
        # 删除原待办
        s.execute(delete(Todo).where(Todo.id == todo_id))
        
        # 创建新的待办（新的ID，新的创建时间）
        new_todo = Todo(
            user_id=user.id,
            title=title,
            note=note,
            status="pending",
            remind_at=remind_at,
            repeat_rule=repeat_rule,
        )
        s.add(new_todo)
        s.commit()
        s.refresh(new_todo)
        
        return True, f"已恢复为待办：{title}"


# ---- Stats helpers ----
def _day_bounds(dt: datetime) -> Tuple[datetime, datetime]:
    start = datetime(dt.year, dt.month, dt.day, 0, 0, 0)
    end = datetime(dt.year, dt.month, dt.day, 23, 59, 59)
    return start, end


def _week_bounds(dt: datetime) -> Tuple[datetime, datetime]:
    # Monday is 0
    weekday = dt.weekday()
    start = datetime(dt.year, dt.month, dt.day, 0, 0, 0) - timedelta(days=weekday)
    end = start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return start, end


def _month_bounds(dt: datetime) -> Tuple[datetime, datetime]:
    from calendar import monthrange
    last_day = monthrange(dt.year, dt.month)[1]
    start = datetime(dt.year, dt.month, 1, 0, 0, 0)
    end = datetime(dt.year, dt.month, last_day, 23, 59, 59)
    return start, end


def sum_expenses_between(user: User, start: datetime, end: datetime) -> float:
    with get_session() as s:
        total = s.execute(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                Expense.user_id == user.id,
                Expense.spent_at >= start,
                Expense.spent_at <= end,
            )
        ).scalar_one()
        try:
            return float(total)
        except Exception:
            return 0.0


def expenses_summary(user: User, period: str) -> Tuple[str, float]:
    now = datetime.now()
    if period in ("today", "daily", "day", "今天", "今日"):
        start, end = _day_bounds(now)
        label = "今天"
    elif period in ("week", "weekly", "本周"):
        start, end = _week_bounds(now)
        label = "本周"
    elif period in ("month", "monthly", "本月"):
        start, end = _month_bounds(now)
        label = "本月"
    else:
        start, end = _day_bounds(now)
        label = "今天"
    total = sum_expenses_between(user, start, end)
    return label, total


def list_todos_for_day(user: User, day: Optional[datetime] = None) -> List[Todo]:
    if day is None:
        day = datetime.now()
    start, end = _day_bounds(day)
    with get_session() as s:
        stmt = (
            select(Todo)
            .where(
                Todo.user_id == user.id,
                Todo.status == "pending",
                Todo.remind_at != None,  # noqa: E711
                Todo.remind_at >= start,
                Todo.remind_at <= end,
            )
            .order_by(Todo.remind_at.asc(), Todo.created_at.asc())
            .limit(50)
        )
        return s.execute(stmt).scalars().all()


def recover_failed_todos():
    """凌晨自动恢复失败状态的任务（仅重复任务）"""
    with get_session() as s:
        # 查找所有失败状态的重复任务
        failed_todos = s.execute(
            select(Todo).where(
                Todo.status == "failed",
                Todo.repeat_rule != None  # noqa: E711
            )
        ).scalars().all()
        
        for todo in failed_todos:
            # 重置为待办状态
            todo.status = "pending"
            todo.remind_count = 0
            todo.last_remind_at = None
            # 提醒状态在 mark_reminded 时处理
            todo.reminded = False
        
        s.commit()
        return len(failed_todos)


def reset_failed_todo(user: User, todo_id: int) -> Tuple[bool, str]:
    """手动重置失败状态的待办为待办中"""
    with get_session() as s:
        t = s.execute(select(Todo).where(Todo.id == todo_id, Todo.user_id == user.id)).scalar_one_or_none()
        if not t:
            return False, "未找到该待办"
        if t.status != "failed":
            return False, "该待办状态不是失败"
        
        t.status = "pending"
        t.remind_count = 0
        t.last_remind_at = None
        t.reminded = False
        s.commit()
        return True, f"已重置：{t.title}"


def complete_recently_reminded_todos(user: User) -> Tuple[bool, str]:
    """完成最近提醒的待办
    如果有多条待办的 last_remind_at 相同（精确到秒），则完成所有这些待办
    否则只完成最新的那一条
    优先处理失败状态的待办（提醒三次后的任务）
    """
    with get_session() as s:
        # 优先查询失败状态的待办（提醒三次后的任务）
        failed_stmt = (
            select(Todo)
            .where(
                Todo.user_id == user.id,
                Todo.status == "failed",
                Todo.last_remind_at != None  # noqa: E711
            )
            .order_by(Todo.last_remind_at.desc())
            .limit(50)
        )
        failed_todos = list(s.execute(failed_stmt).scalars().all())
        
        # 如果找到失败状态的待办，优先处理这些
        if failed_todos:
            completed_count = 0
            completed_titles = []
            
            for todo in failed_todos:
                # 重复任务：重置提醒计数和失败状态，不标记为完成
                if todo.repeat_rule:
                    todo.status = "pending"
                    todo.remind_count = 0
                    todo.last_remind_at = None
                    todo.reminded = False
                    completed_count += 1
                    completed_titles.append(todo.title)
                else:
                    # 非重复任务：标记为完成，记录完成时间
                    todo.status = "done"
                    todo.completed_at = datetime.now()
                    completed_count += 1
                    completed_titles.append(todo.title)
            
            if completed_count > 0:
                s.commit()
                if completed_count == 1:
                    return True, f"已完成：{completed_titles[0]}"
                else:
                    return True, f"已完成 {completed_count} 条待办：{', '.join(completed_titles[:3])}{'...' if len(completed_titles) > 3 else ''}"
        
        # 如果没有失败状态的待办，查询最近被提醒的待办（status='pending'）
        pending_stmt = (
            select(Todo)
            .where(
                Todo.user_id == user.id,
                Todo.status == "pending",
                Todo.last_remind_at != None  # noqa: E711
            )
            .order_by(Todo.last_remind_at.desc())
            .limit(50)
        )
        todos = list(s.execute(pending_stmt).scalars().all())
        
        if not todos:
            return False, "没有找到最近提醒的待办"
        
        # 找出最新的提醒时间（第一条记录的 last_remind_at）
        latest_remind_time = todos[0].last_remind_at
        
        # 找出所有与最新提醒时间相同（精确到秒）的待办
        # 由于 last_remind_at 是 datetime，我们需要比较到秒级别
        same_time_todos = [
            todo for todo in todos
            if todo.last_remind_at and todo.last_remind_at.replace(microsecond=0) == latest_remind_time.replace(microsecond=0)
        ]
        
        # 完成这些待办（在同一事务中处理）
        completed_count = 0
        completed_titles = []
        
        for todo in same_time_todos:
            # 检查状态，确保仍然是 pending（防止并发修改）
            if todo.status != "pending":
                continue
            
            # 重复任务：重置提醒计数和失败状态，不标记为完成
            if todo.repeat_rule:
                todo.status = "pending"
                todo.remind_count = 0
                todo.last_remind_at = None
                completed_count += 1
                completed_titles.append(todo.title)
            else:
                # 非重复任务：标记为完成，记录完成时间
                todo.status = "done"
                todo.completed_at = datetime.now()
                completed_count += 1
                completed_titles.append(todo.title)
        
        if completed_count == 0:
            return False, "没有找到可完成的待办"
        
        s.commit()
        
        if completed_count == 1:
            return True, f"已完成：{completed_titles[0]}"
        else:
            return True, f"已完成 {completed_count} 条待办：{', '.join(completed_titles[:3])}{'...' if len(completed_titles) > 3 else ''}"

