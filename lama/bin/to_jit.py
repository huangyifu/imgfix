import os
import sys
import cv2
from pathlib import Path

import hydra
import torch
import yaml
from omegaconf import OmegaConf
from torch import nn

from saicinpainting.training.trainers import load_checkpoint
from saicinpainting.utils import register_debug_signal_handlers


class JITWrapper(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, image, mask):
        batch = {
            "image": image,
            "mask": mask
        }
        out = self.model(batch)
        return out["inpainted"]


@hydra.main(config_path="../configs/prediction", config_name="default.yaml")
def main(predict_config: OmegaConf):
    if sys.platform != 'win32':
        register_debug_signal_handlers()  # kill -10 <pid> will result in traceback dumped into log

    train_config_path = os.path.join(predict_config.model.path, "config.yaml")
    with open(train_config_path, "r") as f:
        train_config = OmegaConf.create(yaml.safe_load(f))

    train_config.training_model.predict_only = True
    train_config.visualizer.kind = "noop"

    checkpoint_path = os.path.join(
        predict_config.model.path, "models", predict_config.model.checkpoint
    )
    model = load_checkpoint(
        train_config, checkpoint_path, strict=False, map_location="cpu"
    )
    model.eval()
    jit_model_wrapper = JITWrapper(model)

    image = torch.rand(1, 3, 120, 120)
    mask = torch.rand(1, 1, 120, 120)
    output = jit_model_wrapper(image, mask)

    if torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")

    image = image.to(device)
    mask = mask.to(device)
    traced_model = torch.jit.trace(jit_model_wrapper, (image, mask), strict=False).to(device)

    save_path = Path(os.path.join(predict_config.model.path,"models", predict_config.model.checkpoint+".pt"))
    save_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Saving {predict_config.model.checkpoint} model to {save_path}")
    traced_model.save(save_path)

    print(f"Checking jit model output...")
    jit_model = torch.jit.load(str(save_path))
    jit_output = jit_model(image, mask)
    
    # 将PyTorch张量转换为numpy数组并进行必要的处理
    jit_output_np = jit_output.detach().cpu().numpy()[0]  # 移除批次维度
    jit_output_np = jit_output_np.transpose(1, 2, 0)  # 从CHW转换为HWC格式
    jit_output_np = (jit_output_np * 255).clip(0, 255).astype('uint8')  # 归一化并转换为uint8
    
    # 显示图像
    cv2.imshow("jit_output", jit_output_np)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    
    diff = (output - jit_output).abs().sum()
    print(f"diff: {diff}")


if __name__ == "__main__":
    main()
