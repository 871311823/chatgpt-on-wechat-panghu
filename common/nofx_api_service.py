#!/usr/bin/env python3
# encoding:utf-8

"""
NOFX交易系统API服务
用于热更新API密钥，不中断交易
"""

import requests
import json
from typing import Dict, Any, Optional
from common.log import logger


class NofxAPIService:
    def __init__(self, base_url: str = "http://47.109.82.94", port: int = 80):
        self.base_url = f"{base_url}:{port}" if port != 80 else base_url
        self.api_url = f"{self.base_url}/api"
        self.token = None
        self.email = None
        self.password = None
    
    def set_credentials(self, email: str, password: str):
        """设置登录凭证"""
        self.email = email
        self.password = password
    
    def login(self) -> bool:
        """登录获取JWT Token"""
        try:
            if not self.email or not self.password:
                logger.warning("[NofxAPI] No credentials set")
                return False
            
            url = f"{self.api_url}/login"
            data = {
                "email": self.email,
                "password": self.password
            }
            
            response = requests.post(url, json=data, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                self.token = result.get("token")
                if self.token:
                    logger.info("[NofxAPI] Login successful")
                    return True
            
            logger.error(f"[NofxAPI] Login failed: {response.status_code}")
            return False
            
        except Exception as e:
            logger.error(f"[NofxAPI] Login error: {e}")
            return False
    
    def update_exchange_keys(self, exchange_id: str, api_key: str, secret_key: str = "") -> Dict[str, Any]:
        """
        热更新交易所API密钥（不中断交易）
        注意：此方法保留用于向后兼容，实际调用 update_models_keys
        
        Args:
            exchange_id: 交易所ID (binance, okx, hyperliquid, aster) - 已废弃，保留用于兼容
            api_key: 新的API密钥
            secret_key: 新的Secret密钥（某些交易所需要） - 已废弃，保留用于兼容
        
        Returns:
            dict: 更新结果
        """
        # 直接调用新的模型更新接口
        return self.update_models_keys(api_key)
    
    def update_models_keys(self, api_key: str) -> Dict[str, Any]:
        """
        热更新模型API密钥（使用 /api/models/update-keys 接口）
        
        Args:
            api_key: 新的API密钥
        
        Returns:
            dict: 更新结果
        """
        try:
            # 确保已登录
            if not self.token:
                if not self.login():
                    return {
                        "success": False,
                        "message": "登录失败，无法更新NOFX"
                    }
            
            url = f"{self.api_url}/models/update-keys"
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
            data = {
                "api_key": api_key
            }
            
            logger.info(f"[NofxAPI] Calling /api/models/update-keys with api_key: {api_key[:10]}...")
            response = requests.post(url, json=data, headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"[NofxAPI] Models keys updated: {result.get('message')}")
                return {
                    "success": True,
                    "message": result.get("message", "模型密钥已更新"),
                    "affected_traders": result.get("affected_traders", 0),
                    "running_traders": result.get("running_traders", 0),
                    "trader_ids": result.get("trader_ids", []),
                    "affected_models": result.get("affected_models", 0)
                }
            elif response.status_code == 401:
                # Token过期，重新登录
                logger.info("[NofxAPI] Token expired, re-login...")
                if self.login():
                    # 重试一次
                    return self.update_models_keys(api_key)
                else:
                    return {
                        "success": False,
                        "message": "认证失败"
                    }
            else:
                error_msg = response.text
                logger.error(f"[NofxAPI] Update failed: {response.status_code} - {error_msg}")
                return {
                    "success": False,
                    "message": f"更新失败: {error_msg}"
                }
                
        except Exception as e:
            logger.error(f"[NofxAPI] Update error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": f"更新异常: {str(e)}"
            }
    
    def get_health(self) -> bool:
        """检查NOFX服务健康状态"""
        try:
            url = f"{self.api_url}/health"
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"[NofxAPI] Health check failed: {e}")
            return False
    
    def get_exchanges(self) -> list:
        """获取交易所列表"""
        try:
            if not self.token:
                if not self.login():
                    return []
            
            url = f"{self.api_url}/exchanges"
            headers = {"Authorization": f"Bearer {self.token}"}
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            
            return []
            
        except Exception as e:
            logger.error(f"[NofxAPI] Get exchanges error: {e}")
            return []


# 全局实例
_nofx_service = None


def get_nofx_service() -> NofxAPIService:
    """获取全局NOFX服务实例"""
    global _nofx_service
    if _nofx_service is None:
        _nofx_service = NofxAPIService()
        
        # 从配置文件读取凭证
        try:
            from config import conf
            nofx_config = conf().get("nofx", {})
            email = nofx_config.get("email")
            password = nofx_config.get("password")
            
            if email and password:
                _nofx_service.set_credentials(email, password)
                logger.info("[NofxAPI] Credentials loaded from config")
            else:
                logger.warning("[NofxAPI] No credentials in config, will use default")
                # 使用默认凭证（需要在config.json中配置）
                
        except Exception as e:
            logger.warning(f"[NofxAPI] Failed to load credentials: {e}")
    
    return _nofx_service
