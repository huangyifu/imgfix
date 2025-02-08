import os
import json
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from email.parser import BytesParser
from io import BytesIO
import mimetypes

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

    def do_POST(self):
        # 设置响应头
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

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
            # 保存文件
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