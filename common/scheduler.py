# encoding:utf-8

import threading
import time
from datetime import datetime, timezone
from typing import Callable

from common.log import logger
from common.service import fetch_due_reminders, mark_reminded, recover_failed_todos


class ReminderScheduler:
    def __init__(self, send_func: Callable[[str, str], None]):
        # send_func(receiver_id, text)
        self._send = send_func
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def start(self):
        # 启动前先修复提醒状态
        self._fix_reminder_status_on_startup()
        self._t.start()
    
    def _fix_reminder_status_on_startup(self):
        """启动时修复提醒状态"""
        try:
            from datetime import datetime, timedelta
            from common.db import get_session
            from common.models import Todo
            from sqlalchemy import select, update
            
            logger.info("[ReminderScheduler] Fixing reminder status on startup...")
            
            now = datetime.now()
            
            with get_session() as s:
                # 1. 重置已过期但 reminded=True 的非重复任务
                result1 = s.execute(
                    update(Todo).where(
                        Todo.status == "pending",
                        Todo.reminded == True,  # noqa: E712
                        Todo.remind_at != None,  # noqa: E711
                        Todo.remind_at < now,
                        Todo.repeat_rule == None  # noqa: E711
                    ).values(
                        reminded=False,
                        remind_count=0,
                        last_remind_at=None
                    )
                )
                count1 = result1.rowcount
                
                # 2. 重置重复任务的提醒状态
                result2 = s.execute(
                    update(Todo).where(
                        Todo.status == "pending",
                        Todo.reminded == True,  # noqa: E712
                        Todo.remind_at != None,  # noqa: E711
                        Todo.remind_at < now,
                        Todo.repeat_rule != None  # noqa: E711
                    ).values(
                        reminded=False,
                        remind_count=0,
                        last_remind_at=None
                    )
                )
                count2 = result2.rowcount
                
                s.commit()
                
                total_fixed = count1 + count2
                if total_fixed > 0:
                    logger.info(f"[ReminderScheduler] Fixed {total_fixed} reminder statuses (non-repeat: {count1}, repeat: {count2})")
                else:
                    logger.info("[ReminderScheduler] No reminder status needs fixing")
                
                # 3. 统计待提醒的待办
                pending_count = s.execute(
                    select(Todo).where(
                        Todo.status == "pending",
                        Todo.reminded == False,  # noqa: E712
                        Todo.remind_at != None,  # noqa: E711
                        Todo.remind_at <= now
                    )
                ).scalars().all()
                
                if pending_count:
                    logger.info(f"[ReminderScheduler] Found {len(pending_count)} pending reminders to send")
                
        except Exception as e:
            logger.error(f"[ReminderScheduler] Failed to fix reminder status on startup: {e}")

    def stop(self):
        self._stop.set()
        self._t.join(timeout=2)

    def _send_daily_weather(self):
        """发送每日天气"""
        try:
            from config import conf
            from common.weather_service import send_daily_weather
            
            weather_config = conf().get("weather", {})
            if not weather_config:
                return
            
            amap_key = weather_config.get("amap_key")
            target_user = weather_config.get("target_user")
            
            if not amap_key or not target_user:
                logger.warning("[ReminderScheduler] Weather config not complete, skip daily weather")
                return
            
            # 准备OpenAI配置
            openai_config = {
                'api_key': conf().get("open_ai_api_key"),
                'api_base': conf().get("open_ai_api_base"),
                'model': conf().get("model", "gpt-3.5-turbo")
            }
            
            # 发送天气
            send_daily_weather(
                self._send,
                target_user,
                amap_key,
                openai_config
            )
            
        except Exception as e:
            logger.error(f"[ReminderScheduler] Failed to send daily weather: {e}")
    
    def _check_api_balance(self):
        """检查API余额"""
        try:
            from common.api_balance_service import get_balance_service
            from config import conf
            
            balance_service = get_balance_service()
            notify_msg = balance_service.check_and_notify()
            
            if notify_msg:
                # 发送给配置的目标用户
                weather_config = conf().get("weather", {})
                target_user = weather_config.get("target_user")
                
                if target_user:
                    self._send(target_user, notify_msg)
                    logger.info("[ReminderScheduler] Sent API balance warning")
                else:
                    logger.warning("[ReminderScheduler] No target user configured for API balance notification")
                    
        except Exception as e:
            logger.error(f"[ReminderScheduler] Failed to check API balance: {e}")
    
    def _run(self):
        logger.info("[ReminderScheduler] thread started, checking every 60s")
        check_count = 0
        last_recover_check = None  # 上次检查凌晨恢复的时间
        last_weather_push = None  # 上次天气推送的日期
        last_balance_check = None  # 上次余额检查的时间
        
        while not self._stop.is_set():
            try:
                check_count += 1
                # 使用本地时间（与数据库中的 remind_at 一致）
                now = datetime.now()
                # 每10次检查输出一次日志，避免刷屏
                if check_count % 10 == 1:
                    logger.info(f"[ReminderScheduler] alive, checked {check_count} times, now: {now.strftime('%Y-%m-%d %H:%M:%S')}")
                
                # 每日天气推送（早上8点，每天只推送一次）
                if now.hour == 8 and now.minute < 10:
                    today_date = now.date()
                    if last_weather_push != today_date:
                        try:
                            self._send_daily_weather()
                            last_weather_push = today_date
                            logger.info(f"[ReminderScheduler] Sent daily weather at {now.strftime('%H:%M:%S')}")
                        except Exception as e:
                            logger.warning(f"[ReminderScheduler] send daily weather error: {e}")
                
                # API余额检查（每30分钟检查一次）
                if last_balance_check is None or (now - last_balance_check).total_seconds() >= 1800:
                    try:
                        self._check_api_balance()
                        last_balance_check = now
                        if check_count % 10 == 1:  # 每10次检查输出一次日志
                            logger.info(f"[ReminderScheduler] Checked API balance at {now.strftime('%H:%M:%S')}")
                    except Exception as e:
                        logger.warning(f"[ReminderScheduler] check API balance error: {e}")
                
                # 凌晨恢复失败任务（每天只执行一次）
                if now.hour == 0 and now.minute < 5:  # 凌晨0点-5分之间
                    if last_recover_check is None or (now - last_recover_check).total_seconds() > 3600:
                        try:
                            count = recover_failed_todos()
                            if count > 0:
                                logger.info(f"[ReminderScheduler] recovered {count} failed todos at midnight")
                            last_recover_check = now
                        except Exception as e:
                            logger.warning(f"[ReminderScheduler] recover failed todos error: {e}")
                
                # 检查需要提醒的待办
                due = fetch_due_reminders(now)
                if due:
                    logger.info(f"[ReminderScheduler] found {len(due)} due reminders at {now.strftime('%H:%M:%S')}")
                    for todo, user in due:
                        try:
                            msg = f"⏰ 提醒：{todo.title}"
                            if todo.remind_at:
                                msg += f"\n时间：{todo.remind_at.strftime('%Y-%m-%d %H:%M')}"
                            msg += f"\n\n💡 快速完成：回复 #todo done {todo.id}"
                            self._send(user.wework_user_id, msg)
                            mark_reminded(todo.id)
                            logger.info(f"[ReminderScheduler] sent reminder for todo #{todo.id} '{todo.title}' to user {user.id}")
                        except Exception as e:
                            logger.warning(f"[ReminderScheduler] remind failed for todo {todo.id}: {e}")
                time.sleep(60)
            except Exception as e:
                logger.warning(f"[ReminderScheduler] loop error: {e}")
                time.sleep(60)


