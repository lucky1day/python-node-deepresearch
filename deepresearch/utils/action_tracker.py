"""
动作跟踪器
"""
from typing import Dict, List, Any, Optional, TYPE_CHECKING
import asyncio

if TYPE_CHECKING:
    from ..model_types import StepAction


class ActionState:
    """动作状态"""
    def __init__(self):
        self.this_step: Dict[str, Any] = {'action': 'answer', 'answer': '', 'references': [], 'think': ''}
        self.gaps: List[str] = []
        self.total_step: int = 0


class ActionTracker:
    """动作跟踪器"""
    
    def __init__(self):
        self.state = ActionState()
        self._listeners = {}
    
    def on(self, event_name: str, callback):
        """添加事件监听器"""
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        self._listeners[event_name].append(callback)
    
    def emit(self, event_name: str, *args):
        """触发事件"""
        if event_name in self._listeners:
            for callback in self._listeners[event_name]:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(*args))
                else:
                    callback(*args)
    
    def track_action(self, new_state: Dict[str, Any]):
        """跟踪动作"""
        # 更新状态
        self.state.__dict__.update(new_state)
        self.emit('action', self.state.this_step)
    
    def track_think(self, think: str, lang: Optional[str] = None, params = {}):
        """跟踪思考"""
        if lang:
            from .text_tools import get_i18n_text
            think = get_i18n_text(think, lang, params)
        
        # 更新状态
        self.state.this_step = {**self.state.this_step, 'url_targets': [], 'think': think}
        self.emit('action', self.state.this_step)
    
    def get_state(self):
        """获取状态"""
        return {
            'this_step': self.state.this_step,
            'gaps': self.state.gaps,
            'total_step': self.state.total_step
        }
    
    def reset(self):
        """重置状态"""
        self.state = ActionState()