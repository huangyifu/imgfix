@echo off
chcp 65001
echo 正在启动 PHP 服务器...

:: 检查 PHP 是否在环境变量中
where php >nul 2>nul
if %errorlevel% neq 0 (
    echo 错误：未找到 PHP。请确保 PHP 已安装并添加到环境变量中。
    pause
    exit /b
)

:: 获取当前目录
set PORT=8080
set HOST=localhost

:: 检查端口是否被占用
netstat -ano | find ":%PORT%" >nul
if %errorlevel% equ 0 (
    echo 警告：端口 %PORT% 已被占用，尝试使用 8081...
    set PORT=8081
)

:: 启动浏览器
start http://%HOST%:%PORT%

:: 启动 PHP 服务器
echo 服务器已启动：http://%HOST%:%PORT%
echo 按 Ctrl+C 停止服务器
php -S %HOST%:%PORT% 