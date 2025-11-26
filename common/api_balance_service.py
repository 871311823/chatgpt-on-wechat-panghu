# encoding:utf-8

"""
API余额监控服务
支持硅基流动API余额查询和监控
"""

import json
import os
import requests
from datetime import datetime
from typing import Optional, Dict, Any
from common.log import logger


class APIBalanceService:
    def __init__(self, data_file: str = "api_balance_data.json"):
        self.data_file = data_file
        self.api_url = "https://api.siliconflow.cn/v1/user/info"
        self._load_data()
    
    def _load_data(self):
        """加载存储的数据"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
            except Exception as e:
                logger.error(f"[APIBalance] Failed to load data: {e}")
                self.data = self._get_default_data()
        else:
            self.data = self._get_default_data()
            self._save_data()
    
    def _get_default_data(self) -> Dict[str, Any]:
        """获取默认数据结构"""
        return {
            "current_api_key": "sk-pfbkmdpceatxzdczjzzefbxercumkhmjrdhlvaezqujzgjlo",
            "last_balance": None,
            "last_check_time": None,
            "low_balance_notified": False,
            "history": []
        }
    
    def _save_data(self):
        """保存数据到文件"""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[APIBalance] Failed to save data: {e}")
    
    def query_balance(self, api_key: Optional[str] = None) -> Dict[str, Any]:
        """
        查询API余额
        返回格式: {
            "success": bool,
            "balance": float,
            "message": str,
            "error": str (可选)
        }
        """
        if not api_key:
            api_key = self.data["current_api_key"]
        
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(self.api_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                # 硅基流动API返回格式: {"data": {"balance": 123.45}}
                balance = float(result.get("data", {}).get("balance", 0))
                
                # 更新数据
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.data["last_balance"] = balance
                self.data["last_check_time"] = now
                
                # 添加历史记录（保留最近50条）
                self.data["history"].append({
                    "time": now,
                    "balance": balance,
                    "api_key_suffix": api_key[-8:] if len(api_key) > 8 else api_key
                })
                if len(self.data["history"]) > 50:
                    self.data["history"] = self.data["history"][-50:]
                
                # 检查是否需要重置低余额通知标志
                if balance >= 1.0:
                    self.data["low_balance_notified"] = False
                
                self._save_data()
                
                return {
                    "success": True,
                    "balance": balance,
                    "message": f"余额: ¥{balance:.2f}",
                    "check_time": now
                }
            else:
                error_msg = f"API返回错误: {response.status_code}"
                logger.error(f"[APIBalance] {error_msg}")
                return {
                    "success": False,
                    "balance": 0,
                    "message": "查询失败",
                    "error": error_msg
                }
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[APIBalance] Query failed: {error_msg}")
            return {
                "success": False,
                "balance": 0,
                "message": "查询失败",
                "error": error_msg
            }
    
    def check_and_notify(self) -> Optional[str]:
        """
        检查余额并返回通知消息（如果需要）
        返回: 通知消息字符串，如果不需要通知则返回None
        """
        result = self.query_balance()
        
        if not result["success"]:
            return None
        
        balance = result["balance"]
        
        # 如果余额不足1元且还未通知过
        if balance < 1.0 and not self.data["low_balance_notified"]:
            self.data["low_balance_notified"] = True
            self._save_data()
            
            return f"⚠️ API余额预警\n\n当前余额: ¥{balance:.2f}\n余额不足1元，请及时充值！\n\n查询时间: {result['check_time']}"
        
        return None
    
    def update_api_key(self, new_api_key: str) -> Dict[str, Any]:
        """
        更新API KEY
        返回格式: {
            "success": bool,
            "message": str,
            "balance": float (可选)
        }
        """
        # 先验证新的API KEY是否有效
        result = self.query_balance(new_api_key)
        
        if result["success"]:
            self.data["current_api_key"] = new_api_key
            self.data["low_balance_notified"] = False
            self._save_data()
            
            message = f"✅ API KEY已更新\n当前余额: ¥{result['balance']:.2f}"
            
            # 自动同步到NOFX交易系统（热更新，不中断交易）
            nofx_result = self._sync_to_nofx_hot_update(new_api_key)
            
            if nofx_result["success"]:
                message += f"\n\n✅ NOFX交易系统已同步更新"
                if nofx_result.get("affected_models", 0) > 0:
                    message += f"\n🤖 已更新 {nofx_result['affected_models']} 个AI模型"
                if nofx_result.get("affected_traders", 0) > 0:
                    message += f"\n📊 影响 {nofx_result['affected_traders']} 个交易员"
                    if nofx_result.get("running_traders", 0) > 0:
                        message += f"\n🔄 {nofx_result['running_traders']} 个正在运行（无需重启）"
            else:
                message += f"\n\n⚠️ NOFX同步失败: {nofx_result['message']}"
                message += "\n💡 请手动更新: http://47.109.82.94:3000"
            
            return {
                "success": True,
                "message": message,
                "balance": result["balance"],
                "nofx_synced": nofx_result["success"]
            }
        else:
            return {
                "success": False,
                "message": f"❌ API KEY验证失败\n{result.get('error', '未知错误')}"
            }
    
    def _sync_to_nofx_hot_update(self, api_key: str) -> Dict[str, Any]:
        """
        热更新NOFX交易系统的API KEY（不中断交易）
        使用新的 /api/models/update-keys 接口
        """
        try:
            from common.nofx_api_service import get_nofx_service
            
            nofx_service = get_nofx_service()
            
            # 检查NOFX服务是否运行
            if not nofx_service.get_health():
                logger.warning("[APIBalance] NOFX service is not running")
                return {
                    "success": False,
                    "message": "NOFX服务未运行"
                }
            
            # 使用新的模型更新接口（统一更新所有模型）
            logger.info("[APIBalance] Updating NOFX models via /api/models/update-keys")
            result = nofx_service.update_models_keys(api_key)
            
            if result["success"]:
                logger.info(f"[APIBalance] NOFX models updated: {result['message']}")
                return {
                    "success": True,
                    "message": result.get("message", "模型密钥已更新"),
                    "affected_traders": result.get("affected_traders", 0),
                    "running_traders": result.get("running_traders", 0),
                    "affected_models": result.get("affected_models", 0)
                }
            else:
                logger.error(f"[APIBalance] NOFX update failed: {result.get('message')}")
                return {
                    "success": False,
                    "message": result.get("message", "更新失败")
                }
                
        except Exception as e:
            logger.error(f"[APIBalance] NOFX hot update failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": f"热更新失败: {str(e)}"
            }
    
    def get_balance_info(self) -> str:
        """
        获取余额信息的格式化字符串
        """
        if not self.data["last_balance"] or not self.data["last_check_time"]:
            # 如果没有历史数据，先查询一次
            result = self.query_balance()
            if not result["success"]:
                return f"❌ 查询失败: {result.get('error', '未知错误')}"
        
        balance = float(self.data["last_balance"])
        check_time = self.data["last_check_time"]
        api_key_suffix = self.data["current_api_key"][-8:]
        
        # 构建消息
        msg = f"💰 API余额查询\n\n"
        msg += f"当前余额: ¥{balance:.2f}\n"
        msg += f"API KEY: ...{api_key_suffix}\n"
        msg += f"查询时间: {check_time}\n"
        
        # 添加状态提示
        if balance < 1.0:
            msg += f"\n⚠️ 余额不足1元，请及时充值"
        elif balance < 5.0:
            msg += f"\n💡 余额较低，建议充值"
        else:
            msg += f"\n✅ 余额充足"
        
        # 添加最近3条历史记录
        if len(self.data["history"]) > 1:
            msg += f"\n\n📊 最近记录:"
            for record in self.data["history"][-3:]:
                msg += f"\n{record['time']}: ¥{record['balance']:.2f}"
        
        return msg
    
    def get_current_api_key(self) -> str:
        """获取当前API KEY"""
        return self.data["current_api_key"]
    
    def get_balance_for_web(self) -> Dict[str, Any]:
        """
        获取用于Web展示的余额信息
        """
        if not self.data["last_balance"] or not self.data["last_check_time"]:
            result = self.query_balance()
            if not result["success"]:
                return {
                    "balance": 0,
                    "check_time": "未查询",
                    "status": "error",
                    "api_key_suffix": self.data["current_api_key"][-8:]
                }
        
        balance = float(self.data["last_balance"])
        
        # 确定状态
        if balance < 1.0:
            status = "low"
        elif balance < 5.0:
            status = "warning"
        else:
            status = "ok"
        
        return {
            "balance": balance,
            "check_time": self.data["last_check_time"],
            "status": status,
            "api_key_suffix": self.data["current_api_key"][-8:],
            "history": self.data["history"][-10:]  # 最近10条记录
        }


# 全局实例
_balance_service = None


def get_balance_service() -> APIBalanceService:
    """获取全局余额服务实例"""
    global _balance_service
    if _balance_service is None:
        _balance_service = APIBalanceService()
    return _balance_service
