@echo off
echo #install PIL:  py -m pip install -U pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
echo #install torch:  py -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
echo Start Python Upload Server...
python upload.py

pause 