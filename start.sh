#!/bin/bash

echo "============================================================"
echo "               Start ChatGPT-On-WeChat Services              "
echo "============================================================"

# Move to project root (script directory)
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

# Detect Python
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "❌ Python not found. Please install python3."
  exit 1
fi
echo "Using Python: $(command -v $PY)"

echo
echo "[1/5] Initialize database and ensure schema..."
$PY - <<'PY'
from config import load_config
from common.db import init_db, get_session
from sqlalchemy import text

load_config()
init_db()

with get_session() as s:
    try:
        s.execute(text("SELECT repeat_rule FROM todos LIMIT 1"))
        print("✓ DB schema OK: todos.repeat_rule exists")
    except Exception as e:
        msg = str(e)
        if "Unknown column 'repeat_rule'" in msg or "no such column: todos.repeat_rule" in msg:
            print("Adding column todos.repeat_rule ...")
            s.execute(text("ALTER TABLE todos ADD COLUMN repeat_rule VARCHAR(64) NULL"))
            s.commit()
            print("✓ Column added: todos.repeat_rule")
        else:
            print(f"⚠ Schema check warning: {e}")
PY

echo
echo "[2/5] Fix reminder status (prevent reminder loss)..."
$PY - <<'PY'
from datetime import datetime
from config import load_config
from common.db import init_db, get_session
from common.models import Todo
from sqlalchemy import update

load_config()
init_db()

now = datetime.now()

with get_session() as s:
    # 1. 重置已过期但 reminded=True 的非重复任务
    result1 = s.execute(
        update(Todo).where(
            Todo.status == "pending",
            Todo.reminded == True,
            Todo.remind_at != None,
            Todo.remind_at < now,
            Todo.repeat_rule == None
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
            Todo.reminded == True,
            Todo.remind_at != None,
            Todo.remind_at < now,
            Todo.repeat_rule != None
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
        print(f"✓ Fixed {total_fixed} reminder statuses (non-repeat: {count1}, repeat: {count2})")
    else:
        print("✓ No reminder status needs fixing")
    
    # 3. 统计待提醒的待办
    from sqlalchemy import select
    pending_todos = s.execute(
        select(Todo).where(
            Todo.status == "pending",
            Todo.reminded == False,
            Todo.remind_at != None,
            Todo.remind_at <= now
        )
    ).scalars().all()
    
    if pending_todos:
        print(f"✓ Found {len(pending_todos)} pending reminders ready to send")
        for todo in pending_todos[:3]:  # 只显示前3个
            print(f"  - #{todo.id}: {todo.title} (remind at: {todo.remind_at.strftime('%Y-%m-%d %H:%M')})")
PY

echo
echo "[3/5] Stop existing services (if any)..."
pkill -9 -f "start.py" >/dev/null 2>&1 || true
pkill -9 -f "todolist_api_server.py" >/dev/null 2>&1 || true
sleep 2
ps aux | grep -E "start.py|todolist_api" | grep -v grep || echo "✓ All services stopped"

echo
echo "[4/5] Start WeChat service..."
nohup $PY start.py > wechat.log 2>&1 &
WECHAT_PID=$!
echo "✓ WeChat service started (PID: $WECHAT_PID), log: wechat.log"

echo
echo "[5/5] Start Todolist API server (port 9900)..."
nohup $PY todolist_api_server.py > api.log 2>&1 &
API_PID=$!
echo "✓ API server started (PID: $API_PID), log: api.log"

sleep 2

echo
echo "Listening ports (9900 expected):"
ss -lntp 2>/dev/null | grep 9900 || netstat -tulpn 2>/dev/null | grep 9900 || true

echo
echo "============================================================"
echo " Services started."
echo " - Web:     http://<your-ip>:9900/todolist?user_id=1"
echo " - API:     http://<your-ip>:9900/api/todos?user_id=1"
echo " Logs:     tail -f api.log | tail -f wechat.log"
echo "============================================================"


