# encoding:utf-8

"""
天气服务模块
支持高德地图API获取天气信息，并结合AI生成生活建议
增强功能：每日小惊喜推荐（结合天气、待办、成都本地特色）
"""

import requests
import json
import os
from datetime import datetime
from typing import Optional, Tuple, Dict, List
from common.log import logger


class WeatherService:
    def __init__(self, api_key: str):
        """
        初始化天气服务
        :param api_key: 高德地图API Key
        """
        self.api_key = api_key
        self.base_url = "https://restapi.amap.com/v3/weather/weatherInfo"
    
    def get_weather(self, adcode: str = "510116") -> Optional[dict]:
        """
        获取天气信息
        :param adcode: 城市编码，默认510116（成都市双流区）
        :return: 天气数据字典
        """
        try:
            params = {
                'key': self.api_key,
                'city': adcode,
                'extensions': 'all'  # 获取预报天气
            }
            
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('status') == '1':
                logger.info(f"[Weather] Successfully fetched weather for city {adcode}")
                return data
            else:
                logger.error(f"[Weather] API error: {data.get('info')} (code: {data.get('infocode')})")
                return None
                
        except Exception as e:
            logger.error(f"[Weather] Failed to fetch weather: {e}")
            return None
    
    def format_weather_report(self, weather_data: dict) -> Optional[str]:
        """
        格式化天气报告
        :param weather_data: 天气数据
        :return: 格式化的天气文本
        """
        try:
            if not weather_data or weather_data.get('status') != '1':
                return None
            
            forecasts = weather_data.get('forecasts', [])
            if not forecasts:
                return None
            
            forecast = forecasts[0]
            city = forecast.get('city', '未知')
            casts = forecast.get('casts', [])
            
            if not casts:
                return None
            
            # 今天的天气
            today = casts[0]
            
            # 星期映射
            week_map = {"1": "周一", "2": "周二", "3": "周三", "4": "周四", "5": "周五", "6": "周六", "7": "周日"}
            today_week_num = today.get('week', '')
            today_week_name = week_map.get(today_week_num, today_week_num)
            
            report = f"📍 {city} 天气预报\n\n"
            report += f"📅 日期：{today.get('date')} {today_week_name}\n"
            report += f"☀️ 白天：{today.get('dayweather')} {today.get('daytemp')}°C {today.get('daywind')}风 {today.get('daypower')}级\n"
            report += f"🌙 夜间：{today.get('nightweather')} {today.get('nighttemp')}°C {today.get('nightwind')}风 {today.get('nightpower')}级\n\n"
            
            # 未来3天预报
            if len(casts) > 1:
                report += "📊 未来预报：\n"
                week_map = {"1": "周一", "2": "周二", "3": "周三", "4": "周四", "5": "周五", "6": "周六", "7": "周日"}
                for cast in casts[1:4]:  # 显示未来3天
                    week_num = cast.get('week', '')
                    week_name = week_map.get(week_num, week_num)
                    report += f"{cast.get('date')} {week_name}：{cast.get('dayweather')} {cast.get('daytemp')}~{cast.get('nighttemp')}°C\n"
            
            return report
            
        except Exception as e:
            logger.error(f"[Weather] Failed to format weather report: {e}")
            return None
    
    def generate_ai_advice(self, weather_data: dict, openai_client) -> Optional[str]:
        """
        使用AI生成生活建议
        :param weather_data: 天气数据
        :param openai_client: OpenAI客户端配置
        :return: AI生成的建议
        """
        try:
            if not weather_data or weather_data.get('status') != '1':
                return None
            
            forecasts = weather_data.get('forecasts', [])
            if not forecasts:
                return None
            
            casts = forecasts[0].get('casts', [])
            if not casts:
                return None
            
            today = casts[0]
            
            # 构建提示词
            prompt = f"""根据以下天气信息，给出简洁实用的生活建议（3-5条）：

天气：{today.get('dayweather')}
温度：{today.get('daytemp')}°C ~ {today.get('nighttemp')}°C
风力：{today.get('daywind')}风 {today.get('daypower')}级

请从以下方面给出建议：
1. 是否需要带伞
2. 穿衣建议（加衣/减衣）
3. 是否需要防晒
4. 其他注意事项

要求：
- 每条建议用emoji开头
- 简洁明了，每条不超过20字
- 只输出建议内容，不要额外说明"""

            import openai
            
            openai.api_key = openai_client['api_key']
            if openai_client.get('api_base'):
                openai.api_base = openai_client['api_base']
            
            response = openai.ChatCompletion.create(
                model=openai_client.get('model', 'gpt-3.5-turbo'),
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=200
            )
            
            advice = response['choices'][0]['message']['content'].strip()
            logger.info(f"[Weather] Generated AI advice: {advice}")
            
            return advice
            
        except Exception as e:
            logger.error(f"[Weather] Failed to generate AI advice: {e}")
            return None
    

    def get_complete_weather_message(self, adcode: str = "510116", openai_client: Optional[dict] = None,
                                    user_todos: Optional[List] = None, user_preferences: Optional[Dict] = None) -> str:
        """
        获取完整的天气消息（天气预报 + AI建议）
        :param adcode: 城市编码
        :param openai_client: OpenAI配置字典
        :param user_todos: 用户今日待办列表（保留参数但不使用）
        :param user_preferences: 用户偏好设置（保留参数但不使用）
        :return: 完整的天气消息
        """
        # 获取天气数据
        weather_data = self.get_weather(adcode)
        
        if not weather_data:
            return "❌ 获取天气信息失败，请稍后重试"
        
        # 格式化天气报告
        weather_report = self.format_weather_report(weather_data)
        
        if not weather_report:
            return "❌ 天气数据格式错误"
        
        message = "☀️ 早安！今日天气播报\n" + "="*25 + "\n\n"
        message += weather_report
        
        # 生成AI建议
        if openai_client:
            ai_advice = self.generate_ai_advice(weather_data, openai_client)
            if ai_advice:
                message += "\n💡 生活建议：\n"
                message += ai_advice
        
        return message


def send_daily_weather(send_func, user_id: str, api_key: str, openai_config: Optional[dict] = None,
                      get_user_todos_func: Optional[callable] = None):
    """
    发送每日天气预报
    :param send_func: 发送消息的函数
    :param user_id: 用户ID
    :param api_key: 高德地图API Key
    :param openai_config: OpenAI配置
    :param get_user_todos_func: 获取用户待办的函数（保留但不使用）
    """
    try:
        weather_service = WeatherService(api_key)
        
        # 生成天气消息
        message = weather_service.get_complete_weather_message(
            "510116", 
            openai_config
        )
        
        send_func(user_id, message)
        logger.info(f"[Weather] Sent daily weather to user {user_id}")
    except Exception as e:
        logger.error(f"[Weather] Failed to send daily weather: {e}")

