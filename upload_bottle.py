import os
import json
import hashlib
from io import BytesIO
import mimetypes
from PIL import Image
import numpy as np
import torch
import time
from bottle import route, run, request, response, static_file

# 确保 'image' 目录存在
if not os.path.exists('image/'):
    os.makedirs('image/', mode=0o777, exist_ok=True)

def is_safe_path(requested_path):
    """检查请求的路径是否安全（不包含 ..）"""
    normalized_path = os.path.normpath(requested_path)
    return '..' not in requested_path

@route('/')
def index():
    return static_file('index.html', root='./')

@route('/<filepath:path>')
def server_static(filepath):
    if not is_safe_path(filepath):
        response.status = 403
        return 'Access Forbidden'
    return static_file(filepath, root='./')

@route('/upload', method='POST')
def do_upload():
    # 检查是否有文件上传
    upload = request.files.get('file')
    if not upload:
        return {'status': 'error', 'message': '没有接收到文件'}

    # 检查是否提供了MD5值
    md5 = request.forms.get('md5')
    if not md5:
        return {'status': 'error', 'message': '没有提供MD5值'}

    # 检查文件大小（限制为 10MB）
    if upload.content_length > 10 * 1024 * 1024:
         return {'status': 'error', 'message': '文件大小不能超过 10MB'}

    # 读取文件头部来判断文件类型
    header = upload.file.read(8)
    upload.file.seek(0)  # 重置文件指针

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
        return {'status': 'error', 'message': '只允许上传 JPG、PNG 或 GIF 格式的图片'}

    # 检查是否是mask文件
    is_mask = 'mask' in upload.filename.lower()

    # 设置文件名
    file_name = f"{md5}{'_mask' if is_mask else ''}.{extension}"
    target_path = os.path.join('image/', file_name)

    # 如果文件已存在，删除旧文件
    if os.path.exists(target_path):
        os.remove(target_path)

    try:
        # 如果是mask图片，需要进行二值化处理
        if is_mask:
            print("[DEBUG] 处理mask图片...")
            # 将二进制内容转换为PIL图像
            img = Image.open(upload.file).convert('L')

            # 进行二值化处理
            img = img.point(lambda x: 0 if x < 127 else 255, '1')

            # 保存处理后的图片
            img.save(target_path, format=extension.upper())
        else:
            # 直接保存原始文件
            upload.save(target_path)

        return {
            'status': 'success',
            'message': '文件上传成功',
            'file_path': target_path,
            'md5': md5,
            'type': extension
        }
    except Exception as e:
        return {'status': 'error', 'message': f'文件上传失败: {str(e)}'}

@route('/lama', method='POST')
def handle_lama_request():
    """此注释保留!
    处理 /lama 路径的请求
    1.查找图片[md5].[jpg,png,gif]
    2.查找mask[md5]_mask.[jpg,png,gif]
    3.参考lama/bin/to_jit.py 调用lama推理,推理结果的图片保存同目录下,文件名是[md5]_lama.jpg
    4.返回结果
    """
    print("[DEBUG] 开始处理lama请求...")
    data = request.json
    if not data or 'md5' not in data:
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

        # 加载JIT模型
        model_path = "big-lama/models/best.ckpt.pt"
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
        image = Image.open(original_image)
        print(f"[DEBUG] 原始图片size: {image.size if image else 'None'}")

        # 确保图片尺寸是8的倍数
        w, h = image.size
        new_h = (h // 8) * 8
        new_w = (w // 8) * 8
        if h != new_h or w != new_w:
            print(f"[DEBUG] 调整图片尺寸为8的倍数: {w}x{h} -> {new_w}x{new_h}")
            image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 转换为RGB并转为numpy数组
        image = image.convert('RGB')
        image = np.array(image)

        # 读取mask图片
        mask = Image.open(mask_image).convert('L')
        print(f"[DEBUG] Mask图片size: {mask.size if mask else 'None'}")

        # 调整mask尺寸以匹配图片
        if mask.size != (new_w, new_h):
            print(f"[DEBUG] 调整mask尺寸以匹配原图: {mask.size} -> {(new_w, new_h)}")
            mask = mask.resize((new_w, new_h), Image.Resampling.NEAREST)

        # 预处理图片
        print("[DEBUG] 开始图片预处理...")
        image = image.astype('float32') / 255.0
        image = image.transpose(2, 0, 1)
        image = torch.from_numpy(image).unsqueeze(0).to(device)
        print(f"[DEBUG] 处理后的图片tensor shape: {image.shape}")

        # 预处理mask - 确保mask是二值的，且黑色(0)表示要修复的区域
        print("[DEBUG] 开始mask预处理...")
        mask = np.array(mask)
        mask = (mask > 127).astype(np.float32)

        # 如果mask是白色表示要修复的区域，需要反转
        if np.mean(mask[mask > 0.5]) < 0.5:  # 如果白色部分平均值小于0.5，说明黑色表示背景(需要反转)
            print("[DEBUG] 反转mask，确保黑色表示要修复区域")
            mask = 1 - mask

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

        # 转换为PIL图像并保存
        output_image = Image.fromarray(output)
        output_path = os.path.join(image_dir, f"{md5}_lama.jpg")
        print(f"[DEBUG] 保存结果到: {output_path}")
        output_image.save(output_path, quality=95)
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

if __name__ == '__main__':
    run(host='0.0.0.0', port=8000) 