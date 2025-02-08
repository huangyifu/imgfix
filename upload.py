import os
import json
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from email.parser import BytesParser
from io import BytesIO
import mimetypes
import cv2
import numpy as np
import torch
import time

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
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

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
            for ext in ['png','jpg', 'gif']:
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

            # 检查lama处理后的图片是否存在，且时间戳符合要求
            lama_output_path = os.path.join(image_dir, f"{md5}_lama.jpg")
            if os.path.exists(lama_output_path):
                print(f"[DEBUG] 找到已存在的lama处理结果: {lama_output_path}")
                lama_time = os.path.getmtime(lama_output_path)
                mask_time = os.path.getmtime(mask_image)
                current_time = time.time()
                
                if lama_time > mask_time and lama_time <= current_time:
                    print(f"[DEBUG] 使用已存在的lama处理结果（lama时间: {time.ctime(lama_time)}, mask时间: {time.ctime(mask_time)}）")
                    return {
                        'status': 'success',
                        'message': '使用已存在的图片修复结果',
                        'output_path': lama_output_path
                    }
                else:
                    print(f"[DEBUG] 已存在的lama结果不满足时间条件，将重新处理")
            
            # 3. 调用lama模型进行推理
            try:
                print("[DEBUG] 开始加载必要的库...")
                import torch
                import cv2
                import numpy as np
                
                # 加载JIT模型
                model_path = "lama/big-lama/models/best.ckpt.pt"
                print(f"[DEBUG] 尝试加载模型: {model_path}")
                if not os.path.exists(model_path):
                    print("[ERROR] 模型文件不存在")
                    return {
                        'status': 'error',
                        'message': '找不到模型文件'
                    }
                
                device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
                print(f"[DEBUG] 使用设备: {device}")
                model = torch.jit.load(model_path, map_location=device)
                model.eval()
                print("[DEBUG] 模型加载成功")
                
                # 读取和预处理图片
                print("[DEBUG] 开始读取和预处理图片...")
                image = cv2.imread(original_image)
                print(f"[DEBUG] 原始图片shape: {image.shape if image is not None else 'None'}")
                
                # 确保图片尺寸是8的倍数
                h, w = image.shape[:2]
                new_h = (h // 8) * 8
                new_w = (w // 8) * 8
                if h != new_h or w != new_w:
                    print(f"[DEBUG] 调整图片尺寸为8的倍数: {w}x{h} -> {new_w}x{new_h}")
                    image = cv2.resize(image, (new_w, new_h))
                
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                mask = cv2.imread(mask_image, cv2.IMREAD_GRAYSCALE)
                print(f"[DEBUG] Mask图片shape: {mask.shape if mask is not None else 'None'}")
                
                # 调整mask尺寸以匹配图片
                if mask.shape[:2] != image.shape[:2]:
                    print(f"[DEBUG] 调整mask尺寸以匹配原图: {mask.shape[:2]} -> {image.shape[:2]}")
                    mask = cv2.resize(mask, (image.shape[1], image.shape[0]))
                
                # 预处理图片
                print("[DEBUG] 开始图片预处理...")
                image = image.astype('float32') / 255.0
                image = image.transpose(2, 0, 1)
                image = torch.from_numpy(image).unsqueeze(0).to(device)
                print(f"[DEBUG] 处理后的图片tensor shape: {image.shape}")
                
                # 预处理mask - 确保mask是二值的，且黑色(0)表示要修复的区域
                print("[DEBUG] 开始mask预处理...")
                # 首先确保mask是二值的
                _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
                # 如果mask是白色表示要修复的区域，需要反转
                if np.mean(mask[mask > 127]) < 127:  # 如果白色部分平均值小于127，说明黑色表示背景(需要反转)
                    print("[DEBUG] 反转mask，确保黑色表示要修复区域")
                    mask = 255 - mask
                
                mask = mask.astype('float32') / 255.0  # 归一化到0-1
                mask = torch.from_numpy(mask).unsqueeze(0).unsqueeze(0).to(device)
                print(f"[DEBUG] 处理后的mask tensor shape: {mask.shape}")
                print(f"[DEBUG] mask值的范围: {mask.min().item():.3f} - {mask.max().item():.3f}")
                print(f"[DEBUG] mask平均值: {mask.mean().item():.3f} (越接近0表示要修复的区域越大)")
                
                # 进行推理
                print("[DEBUG] 开始模型推理...")
                with torch.no_grad():
                    output = model(image, mask)
                print("[DEBUG] 模型推理完成")
                
                # 后处理输出
                print("[DEBUG] 开始后处理输出...")
                output = output.cpu().numpy()[0]
                output = output.transpose(1, 2, 0)
                output = (output * 255).clip(0, 255).astype('uint8')
                output = cv2.cvtColor(output, cv2.COLOR_RGB2BGR)
                
                # 保存结果
                output_path = os.path.join(image_dir, f"{md5}_lama.jpg")
                print(f"[DEBUG] 保存结果到: {output_path}")
                cv2.imwrite(output_path, output)
                print("[DEBUG] 结果保存成功")
                
                return {
                    'status': 'success',
                    'message': '图片修复完成',
                    'output_path': output_path
                }
                
            except Exception as e:
                print(f"[ERROR] 模型推理失败: {str(e)}")
                import traceback
                print(f"[ERROR] 详细错误信息: {traceback.format_exc()}")
                return {
                    'status': 'error',
                    'message': f'模型推理失败: {str(e)}'
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
        
        # 处理 /lama 路径的请求
        if parsed_path.path == '/lama':
            response = self.handle_lama_request()
            self.wfile.write(json.dumps(response).encode())
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
                # 将二进制内容转换为numpy数组
                nparr = np.frombuffer(file_item['content'], np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
                
                # 进行二值化处理
                _, img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
                
                # 将处理后的图片编码为二进制
                _, buffer = cv2.imencode(f'.{extension}', img)
                content = buffer.tobytes()
            else:
                content = file_item['content']
                
            # 保存文件
            with open(target_path, 'wb') as f:
                f.write(content)
            
            response = {
                'status': 'success',
                'message': '文件上传成功',
                'file_path': target_path,
                'md5': md5,
                'type': extension
            }
        except Exception as e:
            response = {
                'status': 'error',
                'message': f'文件上传失败: {str(e)}'
            }

        self.wfile.write(json.dumps(response).encode())

def run(server_class=HTTPServer, handler_class=UploadHandler, port=8000):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f'Starting server on port {port}...')
    httpd.serve_forever()

if __name__ == '__main__':
    run() 