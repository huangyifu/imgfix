import json
import os
import time
from threading import Lock

class TaskQueue:
	def __init__(self):
		self.queue_file = 'tasks.json'
		self.lock = Lock()
		self.max_tasks = 1000  # 最大保存1000个任务
		self._load_tasks()
	
	def _load_tasks(self):
		"""从文件加载任务列表"""
		try:
			if os.path.exists(self.queue_file):
				with open(self.queue_file, 'r') as f:
					self.tasks = json.load(f)
			else:
				self.tasks = {}
		except Exception:
			self.tasks = {}
	
	def _save_tasks(self):
		"""保存任务列表到文件"""
		with open(self.queue_file, 'w') as f:
			json.dump(self.tasks, f, indent=2)
	
	def _cleanup_old_tasks(self):
		"""清理旧任务，保持任务数量在限制内"""
		if len(self.tasks) > self.max_tasks:
			# 按创建时间排序
			sorted_tasks = sorted(self.tasks.items(), key=lambda x: x[1]['create_time'])
			# 删除最老的任务，直到数量符合限制
			while len(self.tasks) > self.max_tasks:
				oldest_md5 = sorted_tasks[0][0]
				del self.tasks[oldest_md5]
				sorted_tasks.pop(0)
				print(f"[INFO] 删除最老的任务: {oldest_md5}")
	
	def add_task(self, md5):
		"""添加新任务"""
		with self.lock:
			# 如果任务已存在，先删除旧任务
			if md5 in self.tasks:
				print(f"[INFO] 删除已存在的任务: {md5}")
				del self.tasks[md5]
			
			self.tasks[md5] = {
				'status': 'pending',  # pending, processing, completed, error
				'create_time': time.time(),
				'start_time': None,
				'end_time': None,
				'progress': 0,
				'message': '等待处理'
			}
			self._cleanup_old_tasks()  # 检查并清理旧任务
			self._save_tasks()
			return True
	
	def get_task_status(self, md5=None, page=1, per_page=5):
		"""获取任务状态，支持分页
		:param md5: 具体任务的md5，如果为None则返回分页列表
		:param page: 页码，从1开始
		:param per_page: 每页数量
		:return: 任务状态或分页列表
		"""
		with self.lock:
			if md5 is not None:
				return self.tasks.get(md5)
			
			# 按创建时间倒序排序
			sorted_tasks = sorted(
				self.tasks.items(),
				key=lambda x: x[1]['create_time'],
				reverse=True
			)
			
			# 计算分页
			start_idx = (page - 1) * per_page
			end_idx = start_idx + per_page
			page_tasks = sorted_tasks[start_idx:end_idx]
			
			# 转换为字典格式返回
			return {
				'tasks': dict(page_tasks),
				'total': len(self.tasks),
				'page': page,
				'per_page': per_page,
				'total_pages': (len(self.tasks) + per_page - 1) // per_page
			}
	
	def update_task_status(self, md5, status, message='', progress=None):
		"""更新任务状态"""
		with self.lock:
			if md5 in self.tasks:
				self.tasks[md5]['status'] = status
				self.tasks[md5]['message'] = message
				
				if progress is not None:
					self.tasks[md5]['progress'] = progress
				
				if status == 'processing' and not self.tasks[md5].get('start_time'):
					self.tasks[md5]['start_time'] = time.time()
				elif status in ['completed', 'error']:
					self.tasks[md5]['end_time'] = time.time()
				
				self._save_tasks()
				return True
			return False
	
	def get_next_pending_task(self):
		"""获取下一个待处理的任务"""
		with self.lock:
			for md5, task in self.tasks.items():
				if task['status'] == 'pending':
					return md5
			return None

# 创建全局任务队列实例
task_queue = TaskQueue() 