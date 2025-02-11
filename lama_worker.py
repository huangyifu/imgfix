import os
import time
import threading
import torch
from PIL import Image
import numpy as np
from task_queue import task_queue

class LamaWorker:
	def __init__(self):
		self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
		self.model = None
		self.running = False
		self.thread = None
		# 自动启动worker
		self.start()
		print("[INFO] LamaWorker已自动启动")
	
	def __del__(self):
		"""析构函数，确保程序退出时停止worker"""
		self.stop()
	
	def load_model(self):
		"""加载模型"""
		if self.model is None:
			print("[DEBUG] 开始加载模型...")
			model_path = "big-lama/models/best.ckpt.pt"
			if not os.path.exists(model_path):
				raise FileNotFoundError("模型文件不存在")
			
			self.model = torch.jit.load(model_path, map_location=self.device)
			self.model.eval()
			print("[DEBUG] 模型加载成功")
	
	def process_image(self, md5):
		"""处理单个图片"""
		try:
			task_queue.update_task_status(md5, 'processing', '开始处理图片')
			image_dir = 'image/'
			
			# 查找原始图片和mask图片
			original_image = None
			mask_image = None
			for ext in ['jpg', 'png', 'gif']:
				img_path = os.path.join(image_dir, f"{md5}.{ext}")
				if os.path.exists(img_path):
					original_image = img_path
					break
			
			for ext in ['png', 'jpg', 'gif']:
				mask_path = os.path.join(image_dir, f"{md5}_mask.{ext}")
				if os.path.exists(mask_path):
					mask_image = mask_path
					break
			
			if not original_image or not mask_image:
				raise FileNotFoundError("找不到原始图片或mask图片")
			
			task_queue.update_task_status(md5, 'processing', '预处理图片', 20)
			
			# 读取和预处理图片
			image = Image.open(original_image)
			w, h = image.size
			new_h = (h // 8) * 8
			new_w = (w // 8) * 8
			if h != new_h or w != new_w:
				image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
			
			image = image.convert('RGB')
			image = np.array(image)
			
			task_queue.update_task_status(md5, 'processing', '处理mask图片', 40)
			
			# 处理mask
			mask = Image.open(mask_image).convert('L')
			if mask.size != (new_w, new_h):
				mask = mask.resize((new_w, new_h), Image.Resampling.NEAREST)
			
			mask = np.array(mask)
			mask = (mask > 127).astype(np.float32)
			if np.mean(mask[mask > 0.5]) < 0.5:
				mask = 1 - mask
			
			task_queue.update_task_status(md5, 'processing', '准备模型推理', 60)
			
			# 转换为tensor
			image = image.astype('float32') / 255.0
			image = image.transpose(2, 0, 1)
			image = torch.from_numpy(image).unsqueeze(0).to(self.device)
			mask = torch.from_numpy(mask).unsqueeze(0).unsqueeze(0).to(self.device)
			
			task_queue.update_task_status(md5, 'processing', '正在进行模型推理', 80)
			
			# 进行推理
			with torch.no_grad():
				output = self.model(image, mask)
			
			# 后处理输出
			output = output.cpu().numpy()[0]
			output = output.transpose(1, 2, 0)
			output = (output * 255).clip(0, 255).astype('uint8')
			
			# 保存结果
			output_image = Image.fromarray(output)
			output_path = os.path.join(image_dir, f"{md5}_lama.jpg")
			output_image.save(output_path, quality=90)
			
			task_queue.update_task_status(md5, 'completed', '处理完成', 100)
			
		except Exception as e:
			import traceback
			error_msg = f"处理失败: {str(e)}\n{traceback.format_exc()}"
			print(f"[ERROR] {error_msg}")
			task_queue.update_task_status(md5, 'error', error_msg)
	
	def run(self):
		"""运行工作线程"""
		while self.running:
			try:
				# 加载模型（如果还没加载）
				if self.model is None:
					self.load_model()
				
				# 获取下一个待处理任务
				md5 = task_queue.get_next_pending_task()
				if md5:
					self.process_image(md5)
				else:
					# 没有任务时休眠一段时间
					time.sleep(1)
					
			except Exception as e:
				print(f"[ERROR] 工作线程异常: {str(e)}")
				time.sleep(1)
	
	def start(self):
		"""启动工作线程"""
		if not self.running:
			self.running = True
			self.thread = threading.Thread(target=self.run)
			self.thread.daemon = True
			self.thread.start()
	
	def stop(self):
		"""停止工作线程"""
		self.running = False
		if self.thread:
			self.thread.join()
			self.thread = None

# 创建全局worker实例
worker = LamaWorker()

# 确保程序退出时正确停止worker
import atexit
def cleanup():
	print("[INFO] 正在停止LamaWorker...")
	worker.stop()
atexit.register(cleanup) 