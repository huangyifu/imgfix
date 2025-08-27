@echo off
rem Install Pillow: py -m pip install -U pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
rem Install PyTorch: py -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

echo Starting Caddy Server in background...
rem Caddyfile is now in the server directory, so no need to change directory
echo start /b caddy run

echo Starting Python Backend Server in foreground (closing this window will terminate all services)...
python server.py