import os
import json
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from email.parser import BytesParser
from io import BytesIO
import mimetypes
from PIL import Image
import numpy as np
import torch
import time
from task_queue import task_queue
from lama_worker import worker

class UploadHandler(BaseHTTPRequestHandler):
	def get_content_type(self, path):
		return mimetypes.guess_type(path)[0] or 'application/octet-stream'

	def is_safe_path(self, requested_path):
		"""检查请求的路径是否安全（不包含 ..）"""
		normalized_path = os.path.normpath(requested_path)
		return '..' not in requested_path

	def do_GET(self):
		# 解析请求的路径
		parsed_path = urlparse(self.path)
		request_path = parsed_path.path
		
		# 处理任务状态查询
		if request_path == '/tasks':
			self.send_response(200)
			self.send_header('Content-Type', 'application/json')
			self.send_header('Access-Control-Allow-Origin', '*')
			self.end_headers()
			
			# 获取查询参数
			query_params = parse_qs(parsed_path.query)
			md5 = query_params.get('md5', [None])[0]
			page = int(query_params.get('page', ['1'])[0])
			per_page = int(query_params.get('per_page', ['5'])[0])
			
			# 获取任务状态
			status = task_queue.get_task_status(md5, page, per_page)
			self.wfile.write(json.dumps(status).encode())
			return
		
		# 如果请求根路径，默认返回index.html
		if request_path == '/':
			request_path = '/index.html'
			
		# 安全检查：确保路径中不包含 ..
		if not self.is_safe_path(request_path):
			self.send_error(403, 'Access Forbidden')
			return
			
		# 获取文件的绝对路径，移除开头的/
		file_path = os.path.join(os.getcwd(), request_path.lstrip('/'))
		
		try:
			# 检查文件是否存在
			if not os.path.exists(file_path):
				self.send_error(404, 'File not found')
				return
				
			# 读取文件内容
			with open(file_path, 'rb') as f:
				content = f.read()
				
			# 发送响应头
			self.send_response(200)
			self.send_header('Content-Type', self.get_content_type(file_path))
			self.send_header('Content-Length', len(content))
			self.end_headers()
			
			# 发送文件内容
			self.wfile.write(content)
			
		except Exception as e:
			self.send_error(500, f'Internal server error: {str(e)}')

	def do_OPTIONS(self):
		self.send_response(200)
		self.send_header('Access-Control-Allow-Origin', '*')
		self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS, GET')
		self.send_header('Access-Control-Allow-Headers', 'Content-Type')
		self.end_headers()

	def handle_delete_task(self):
		"""处理删除任务的请求"""
		try:
			# 获取请求体中的数据
			content_length = int(self.headers.get('Content-Length', 0))
			post_data = self.rfile.read(content_length)
			data = json.loads(post_data)
			
			if 'md5' not in data:
				return {
					'status': 'error',
					'message': '缺少 md5 参数'
				}
			
			# 删除任务及相关文件
			return task_queue.delete_task(data['md5'])
		except json.JSONDecodeError:
			return {
				'status': 'error',
				'message': 'JSON解析失败'
			}
		except Exception as e:
			print(f"[ERROR] 删除任务失败: {str(e)}")
			import traceback
			print(f"[ERROR] 详细错误信息: {traceback.format_exc()}")
			return {
				'status': 'error',
				'message': f'删除任务失败: {str(e)}'
			}

	def parse_multipart(self):
		content_type = self.headers.get('Content-Type')
		if not content_type:
			return None
		
		content_length = int(self.headers.get('Content-Length', 0))
		
		# 读取请求体
		body = self.rfile.read(content_length)
		
		# 使用BytesParser解析multipart数据
		parser = BytesParser()
		headers = f"Content-Type: {content_type}\n\n".encode()
		parsed = parser.parsebytes(headers + body)
		
		# 解析结果存储
		form_data = {}
		
		if parsed.is_multipart():
			for part in parsed.walk():
				# 跳过主消息体
				if part.get_content_maintype() == 'multipart':
					continue
					
				# 获取字段名
				disposition = part.get('Content-Disposition', '')
				if not disposition:
					continue
					
				# 解析Content-Disposition
				disp_params = dict(param.strip().split('=', 1) for param in disposition.split(';')[1:] if '=' in param)
				field_name = disp_params.get('name', '').strip('"')
				
				if 'filename' in disp_params:
					# 这是文件
					filename = disp_params['filename'].strip('"')
					content = part.get_payload(decode=True)
					form_data[field_name] = {
						'filename': filename,
						'content': content,
						'file': BytesIO(content)
					}
				else:
					# 这是普通字段
					form_data[field_name] = part.get_payload()
					
		return form_data

	def handle_lama_request(self):
		"""此注释保留!
		处理 /lama 路径的请求
		1.查找图片[md5].[jpg,png,gif]
		2.查找mask[md5]_mask.[jpg,png,gif]
		3.参考lama/bin/to_jit.py 调用lama推理,推理结果的图片保存同目录下,文件名是[md5]_lama.jpg
		4.返回结果
		"""
		print("[DEBUG] 开始处理lama请求...")
		content_length = int(self.headers.get('Content-Length', 0))
		post_data = self.rfile.read(content_length)
		
		try:
			# 尝试解析 JSON 数据
			print(f"[DEBUG] 接收到的原始数据: {post_data}")
			data = json.loads(post_data)
			if 'md5' not in data:
				print("[ERROR] 缺少md5参数")
				return {
					'status': 'error',
					'message': '缺少 md5 参数'
				}
			
			md5 = data['md5']
			print(f"[DEBUG] 处理的MD5值: {md5}")
			image_dir = 'image/'
			
			# 1. 查找原始图片
			original_image = None
			mask_image = None
			for ext in ['jpg', 'png', 'gif']:
				img_path = os.path.join(image_dir, f"{md5}.{ext}")
				print(f"[DEBUG] 尝试查找原始图片: {img_path}")
				if os.path.exists(img_path):
					original_image = img_path
					print(f"[DEBUG] 找到原始图片: {original_image}")
					break
			
			# 2. 查找mask图片
			for ext in ['png', 'jpg', 'gif']:
				mask_path = os.path.join(image_dir, f"{md5}_mask.{ext}")
				print(f"[DEBUG] 尝试查找mask图片: {mask_path}")
				if os.path.exists(mask_path):
					mask_image = mask_path
					print(f"[DEBUG] 找到mask图片: {mask_image}")
					break
			
			if not original_image or not mask_image:
				print(f"[ERROR] 图片查找失败 - 原始图片: {original_image}, mask图片: {mask_image}")
				return {
					'status': 'error',
					'message': '找不到原始图片或mask图片'
				}
			
			# # 检查lama处理后的图片是否存在，且时间戳符合要求
			# lama_output_path = os.path.join(image_dir, f"{md5}_lama.jpg")
			# if os.path.exists(lama_output_path):
			# 	print(f"[DEBUG] 找到已存在的lama处理结果: {lama_output_path}")
			# 	lama_time = os.path.getmtime(lama_output_path)
			# 	mask_time = os.path.getmtime(mask_image)
			# 	current_time = time.time()
				
			# 	if lama_time > mask_time and lama_time <= current_time:
			# 		print(f"[DEBUG] 使用已存在的lama处理结果（lama时间: {time.ctime(lama_time)}, mask时间: {time.ctime(mask_time)}）")
			# 		return {
			# 			'status': 'success',
			# 			'message': '使用已存在的图片修复结果',
			# 			'output_path': lama_output_path
			# 		}
			# 	else:
			# 		print(f"[DEBUG] 已存在的lama结果不满足时间条件，将重新处理")
			
			# 添加到任务队列
			if task_queue.add_task(md5):
				return {
					'status': 'success',
					'message': '任务已添加到队列',
					'task_id': md5
				}
			else:
				return {
					'status': 'error',
					'message': '任务已存在'
				}
			
		except json.JSONDecodeError:
			print("[ERROR] JSON解析失败")
			return {
				'status': 'error',
				'message': 'JSON解析失败'
			}
		except Exception as e:
			print(f"[ERROR] 未预期的错误: {str(e)}")
			import traceback
			print(f"[ERROR] 详细错误信息: {traceback.format_exc()}")
			return {
				'status': 'error',
				'message': f'处理请求时发生错误: {str(e)}'
			}

	def do_POST(self):
		# 设置响应头
		self.send_response(200)
		self.send_header('Content-Type', 'application/json')
		self.send_header('Access-Control-Allow-Origin', '*')
		self.end_headers()
		
		# 解析请求路径
		parsed_path = urlparse(self.path)
		
		# 处理删除任务请求
		if parsed_path.path == '/delete_task':
			response = self.handle_delete_task()
			self.wfile.write(json.dumps(response).encode())
			return
		
		# 处理 /lama 路径的请求
		if parsed_path.path == '/lama':
			response = self.handle_lama_request()
			self.wfile.write(json.dumps(response).encode())
			return

		if parsed_path.path != '/upload':
			self.send_error(404, 'File not found')
			return

		# 确保上传目录存在
		upload_dir = 'image/'
		if not os.path.exists(upload_dir):
			os.makedirs(upload_dir, mode=0o777, exist_ok=True)

		# 解析表单数据
		form = self.parse_multipart()

		response = {}

		# 检查是否有文件上传
		if 'file' not in form:
			response = {
				'status': 'error',
				'message': '没有接收到文件'
			}
			self.wfile.write(json.dumps(response).encode())
			return

		# 检查是否提供了MD5值
		if 'md5' not in form:
			response = {
				'status': 'error',
				'message': '没有提供MD5值'
			}
			self.wfile.write(json.dumps(response).encode())
			return

		file_item = form['file']
		md5 = form['md5']

		# 检查文件大小（限制为 10MB）
		if len(file_item['content']) > 10 * 1024 * 1024:
			response = {
				'status': 'error',
				'message': '文件大小不能超过 10MB'
			}
			self.wfile.write(json.dumps(response).encode())
			return
		
		# 读取文件头部来判断文件类型
		header = file_item['content'][:8]
		
		# 检查文件类型
		is_valid_image = False
		extension = ''
		hex_header = ''.join([f'{byte:02x}' for byte in header])
		
		if hex_header.startswith('ffd8ff'):  # JPEG
			is_valid_image = True
			extension = 'jpg'
		elif hex_header.startswith('89504e47'):  # PNG
			is_valid_image = True
			extension = 'png'
		elif hex_header.startswith('474946'):  # GIF
			is_valid_image = True
			extension = 'gif'

		if not is_valid_image:
			response = {
				'status': 'error',
				'message': '只允许上传 JPG、PNG 或 GIF 格式的图片'
			}
			self.wfile.write(json.dumps(response).encode())
			return

		# 检查是否是mask文件
		is_mask = 'mask' in file_item['filename'].lower()
		
		# 设置文件名
		file_name = f"{md5}{'_mask' if is_mask else ''}.{extension}"
		target_path = os.path.join(upload_dir, file_name)

		# 如果文件已存在，删除旧文件
		if os.path.exists(target_path):
			os.remove(target_path)

		try:
			# 如果是mask图片，需要进行二值化处理
			if is_mask:
				print("[DEBUG] 处理mask图片...")
				# 将二进制内容转换为PIL图像
				img = Image.open(BytesIO(file_item['content'])).convert('L')
				
				# 进行二值化处理
				img = img.point(lambda x: 0 if x < 127 else 255, '1')
				
				# 删除旧的lama结果图片（如果存在）
				lama_result_path = os.path.join(upload_dir, f"{md5}_lama.jpg")
				if os.path.exists(lama_result_path):
					try:
						os.remove(lama_result_path)
						print(f"[DEBUG] 已删除旧的lama结果: {lama_result_path}")
					except Exception as e:
						print(f"[WARNING] 删除旧的lama结果失败: {str(e)}")
				
				# 保存处理后的图片
				img.save(target_path, format=extension.upper())
			else:
				# 直接保存原始文件
				with open(target_path, 'wb') as f:
					f.write(file_item['content'])
			
			response = {
				'status': 'success',
				'message': '文件上传成功',
				'file_path': target_path,
				'md5': md5,
				'type': extension
			}
		except Exception as e:
			print(f"[ERROR] 文件上传失败: {str(e)}")
			import traceback
			print(f"[ERROR] 详细错误信息: {traceback.format_exc()}")
			response = {
				'status': 'error',
				'message': f'文件上传失败: {str(e)}'
			}

		self.wfile.write(json.dumps(response).encode())

def run(server_class=HTTPServer, handler_class=UploadHandler, port=8080):
	server_address = ('', port)
	httpd = server_class(server_address, handler_class)
	print(f'Starting server on http://localhost:{port} ...')
	try:
		httpd.serve_forever()
	except KeyboardInterrupt:
		print("Shutting down server...")
	finally:
		httpd.server_close()

if __name__ == '__main__':
	run() 