<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

// 确保 image 目录存在
$uploadDir = 'image/';
if (!file_exists($uploadDir)) {
    mkdir($uploadDir, 0777, true);
}

$response = array();

// 首先检查是否有文件上传
if (!isset($_FILES['file'])) {
    $response['status'] = 'error';
    $response['message'] = '没有接收到文件';
    echo json_encode($response);
    exit;
}

// 检查是否提供了MD5值
if (!isset($_POST['md5'])) {
    $response['status'] = 'error';
    $response['message'] = '没有提供MD5值';
    echo json_encode($response);
    exit;
}

$file = $_FILES['file'];
$md5 = $_POST['md5'];

// 第一步：检查文件上传是否出错
if ($file['error'] !== UPLOAD_ERR_OK) {
    $response['status'] = 'error';
    switch ($file['error']) {
        case UPLOAD_ERR_INI_SIZE:
            $response['message'] = '文件超过了php.ini中upload_max_filesize限制';
            break;
        case UPLOAD_ERR_FORM_SIZE:
            $response['message'] = '文件超过了表单中MAX_FILE_SIZE限制';
            break;
        case UPLOAD_ERR_PARTIAL:
            $response['message'] = '文件只有部分被上传';
            break;
        case UPLOAD_ERR_NO_FILE:
            $response['message'] = '没有文件被上传';
            break;
        default:
            $response['message'] = '文件上传失败（错误码：' . $file['error'] . '）';
    }
    echo json_encode($response);
    exit;
}

// 第二步：确保临时文件存在且合法
if (!is_uploaded_file($file['tmp_name'])) {
    $response['status'] = 'error';
    $response['message'] = '非法的文件上传';
    echo json_encode($response);
    exit;
}

// 第三步：检查文件大小（限制为 10MB）
if ($file['size'] > 10 * 1024 * 1024) {
    $response['status'] = 'error';
    $response['message'] = '文件大小不能超过 10MB';
    echo json_encode($response);
    exit;
}

// 第四步：检查文件类型
$handle = fopen($file['tmp_name'], 'rb');
$bytes = fread($handle, 8); // 读取前8个字节
fclose($handle);

// 转换字节为十六进制
$hex = bin2hex($bytes);

// 判断文件类型
$isValidImage = false;
$extension = '';
if (substr($hex, 0, 6) === 'ffd8ff') { // JPEG
    $isValidImage = true;
    $extension = 'jpg';
} elseif (substr($hex, 0, 8) === '89504e47') { // PNG
    $isValidImage = true;
    $extension = 'png';
} elseif (substr($hex, 0, 6) === '474946') { // GIF
    $isValidImage = true;
    $extension = 'gif';
}

if (!$isValidImage) {
    $response['status'] = 'error';
    $response['message'] = '只允许上传 JPG、PNG 或 GIF 格式的图片';
    echo json_encode($response);
    exit;
}

// 检查是否是mask文件
$isMask = stripos($file['name'], 'mask') !== false;

// 设置文件名
$fileName = $md5 . ($isMask ? '_mask' : '') . '.' . $extension;
$targetPath = $uploadDir . $fileName;

// 如果文件已存在，删除旧文件
if (file_exists($targetPath)) {
    unlink($targetPath);
}

if (move_uploaded_file($file['tmp_name'], $targetPath)) {
    $response['status'] = 'success';
    $response['message'] = '文件上传成功';
    $response['file_path'] = $targetPath;
    $response['md5'] = $md5;
    $response['type'] = $extension;
} else {
    $response['status'] = 'error';
    $response['message'] = '文件上传失败';
}

echo json_encode($response);
?> 