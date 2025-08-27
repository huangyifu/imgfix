# Pure Story 图片擦除工具 - 微信小程序版升级说明

## 项目概述

本项目将原始的基于 Web 的图片擦除工具升级为微信小程序版本，并对 Python 后端进行了适配，以实现在移动端更便捷的图片处理体验。

## 升级目的

本次升级旨在将原有的浏览器端应用转换为微信小程序，以便用户可以在微信生态内直接使用，无需通过浏览器访问，提升用户体验和便捷性。

## 项目结构

*   `mp/`: 微信小程序客户端代码，由原始 Web 客户端适配而来。
*   `server/`: Python 后端服务代码，由原始后端适配而来。
*   `README.md`: 项目说明文件，包含原始功能描述及本次升级的详细说明。

## 客户端适配 (`mp` 目录)

原始 Web 客户端的 HTML、CSS 和 JavaScript 代码已全面转换为微信小程序对应的 WXML、WXSS 和 JavaScript。主要适配工作包括：

*   **UI 组件转换：** HTML 标签（如 `div`, `button`, `input`, `img`, `canvas`）转换为微信小程序对应的 WXML 组件（如 `view`, `button`, `slider`, `image`, `canvas`）。
*   **事件绑定：** 浏览器事件监听器（如 `addEventListener`）转换为小程序的事件绑定机制（如 `bindtap`, `bindinput`, `bindtouchstart` 等）。
*   **API 替换：** 浏览器 Web API（如 `fetch`, `FileReader`, `Image`, `document.getElementById`, `localStorage`）替换为微信小程序对应的 API（如 `wx.request`, `wx.uploadFile`, `wx.chooseImage`, `wx.getImageInfo`, `wx.createCanvasContext`, `wx.getFileSystemManager`, `wx.showModal`, `wx.showToast`, `wx.showLoading`, `wx.hideLoading`, `wx.setStorageSync` 等）。
*   **画布操作：** 原始的 Canvas 2D 上下文操作被适配为 `wx.createCanvasContext`。蒙版绘制通过在内存中管理 `ImageData` 数组并结合 `wx.createOffscreenCanvas` 进行模拟绘制实现。
*   **认证机制：** 原始的 `prompt()` 密码输入方式被替换为自定义的密码输入模态框。
*   **模块化：** `spark-md5.min.js` 作为工具模块引入。

## 服务端适配 (`server` 目录)

原始 Python 后端代码（`upload.py`, `task_queue.py`, `lama_worker.py`）已进行适配，以确保与微信小程序客户端的无缝对接。主要适配内容包括：

*   **静态文件服务移除：** `upload.py` 中用于服务 `index.html` 和 `spark-md5.min.js` 等客户端静态文件的逻辑已被移除，因为这些文件现在已打包在小程序客户端中。但图片服务（`/image/` 路径）得以保留。
*   **CORS 配置：** 确保所有 API 响应都正确设置了 `Access-Control-Allow-Origin: *` 头部，以满足小程序跨域请求的需求。
*   **核心逻辑不变：** `task_queue.py` 和 `lama_worker.py` 作为后端核心处理逻辑，无需进行任何修改，保持了其原有功能和性能。
*   **后端实现：** `server.py` (原 `upload.py`) 是基于 Python 内置 `http.server` 模块实现的自定义 HTTP 服务器，而非 Flask 或其他 Web 框架。
*   **模型文件：** Lama 模型文件 (`best.ckpt.pt`) 及其配置文件 (`config.yaml`) 保持原样，并放置在 `server/big-lama/models/` 目录下，供 `lama_worker.py` 调用。

## 功能对比与 Bug 检查

经过详细的功能对比和代码审查，本次升级在功能上与原始 Web 应用程序保持了高度一致性。以下是主要发现：

*   **高度功能等效性：** 原始 Web 客户端的核心功能，包括图片选择、画笔控制、画布操作（绘制、撤销、清除、缩放、平移）、Lama 处理、任务管理（列表、状态、刷新、删除、加载任务）、图片预览、认证和 Toast 通知，均已在小程序中成功复制。
*   **已解决的缺陷：**
    *   **分页功能：** 原始 Web 客户端的分页功能在小程序版本中已完全实现，解决了之前识别出的功能缺失。
    *   **画布触摸交互：** 为 `<canvas>` 标签添加了 `catchtouchmove="true"`，有效解决了在触摸操作时可能出现的页面滚动冲突问题，提升了用户体验。

*   **已知限制与注意事项：**
    *   **蒙版绘制性能：** 微信小程序 Canvas API 在进行像素级操作时，对于非常大的图片或频繁操作，可能会存在一定的性能开销。这属于平台特性，非功能性 Bug，但可能影响流畅度。
    *   **`wx.uploadFile` 兼容性：** 尽管已适配，但 `wx.uploadFile` 在处理 `formData` 时可能与标准 Web `fetch` API 存在细微差异。建议在实际环境中进行充分测试。
    *   **错误处理健壮性：** 尽管代码中包含了错误捕获机制，但全面的错误处理和用户友好的错误提示仍需在实际部署和测试中进一步完善。
    *   **UI 响应性：** 微信小程序 WXSS 对响应式布局的支持与标准 CSS 存在差异，复杂的 `@media` 查询可能无法完全转换。建议在不同设备上进行视觉测试，以确保界面显示正常。
    *   **模型文件：** Lama 模型文件 (`best.ckpt.pt`) 较大，无法通过自动化脚本直接传输。用户需手动复制。

## 设置与运行

### 1. 后端设置

1.  **进入后端目录：**
    ```bash
    cd server
    ```

2.  **复制 Lama 模型文件：**
    由于模型文件较大，无法通过自动化脚本直接复制。请手动将原始项目中的 Lama 模型文件复制到后端指定位置：
    *   **源路径：** `D:\huangyifu\hbuilderproj\cursor\imgfix - Copy\big-lama\models\best.ckpt.pt`
    *   **目标路径：** `D:\huangyifu\hbuilderproj\cursor\imgfix - Copy\server\big-lama\models\best.ckpt.pt`

3.  **安装 Python 依赖：**
    后端需要 `Pillow`、`numpy` 和 `torch`。建议使用 `pip` 安装：
    ```bash
    pip install Pillow numpy
    ```
    对于 `torch`，请务必根据您的操作系统和是否使用 GPU，从 [PyTorch 官方网站](https://pytorch.org/get-started/locally/) 获取正确的安装命令。例如，如果您有 CUDA 支持的 GPU，安装命令可能类似于：
    ```bash
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
    ```

4.  **运行后端服务：**
    ```bash
    python upload.py
    ```
    服务将默认运行在 `http://localhost:8080`。

### 2. 微信小程序设置

1.  **打开微信开发者工具。**

2.  **导入项目：**
    选择项目目录 `D:\huangyifu\hbuilderproj\cursor\imgfix - Copy\mp` 进行导入。

3.  **配置后端服务地址：**
    打开 `mp/pages/index/index.js` 文件，找到 `serverUrl` 变量，并将其设置为您的后端服务地址。如果后端运行在本地，通常设置为：
    ```javascript
    serverUrl: 'http://127.0.0.1:8080',
    ```
    如果您通过 Caddy 或其他代理将后端服务暴露在公网，请将 `serverUrl` 设置为相应的公网地址。

## 使用说明

1.  **选择图片：** 点击“选择图片”按钮上传本地图片。图片会自动缩放并显示在画布上。
2.  **编辑蒙版：**
    *   选择“绘制蒙版”模式，在图片上涂抹以标记需要擦除的区域。
    *   选择“消除蒙版”模式，擦除已绘制的蒙版区域。
    *   使用滑块调节画笔大小。
3.  **移动和缩放：**
    *   选择“移动图片”模式，单指拖动可平移画布。
    *   使用双指手势进行缩放和再次平移。
    *   使用“放大”、“缩小”、“[1:1]”、“全图”按钮进行视图调整。
4.  **智能擦除：** 点击“一键擦除”按钮，图片和蒙版将上传至后端进行 Lama 处理。处理进度和结果将在任务列表中显示。
5.  **任务管理：**
    *   任务列表会实时更新处理进度。
    *   点击任务状态可加载该任务的图片和蒙版到画布进行二次编辑。
    *   可以对已完成的任务点击“再擦一次”按钮，基于上次处理结果再次进行擦除。
    *   点击“删除”按钮可删除不需要的任务记录。
6.  **图片预览：** 点击任务列表中的图片缩略图，可查看原图和处理结果的对比。

## 开发注意事项与限制

*   **画布绘制性能：** 微信小程序 Canvas API 在进行像素级操作（如蒙版绘制）时，对于非常大的图片或频繁操作，可能会存在一定的性能开销，导致绘制不够流畅。这是小程序环境下的一个常见限制。
*   **`wx.uploadFile` 兼容性：** 尽管已适配，但 `wx.uploadFile` 在处理 `formData` 时可能与标准 Web `fetch` API 存在细微差异。建议在实际环境中进行充分测试。
*   **错误处理：** 尽管代码中包含了错误捕获机制，但全面的错误处理和用户友好的错误提示仍需在实际部署和测试中进一步完善。
*   **UI 响应性：** 微信小程序 WXSS 对响应式布局的支持与标准 CSS 存在差异，复杂的 `@media` 查询可能无法完全转换。建议在不同设备上进行视觉测试，以确保界面显示正常。
*   **模型文件：** Lama 模型文件 (`best.ckpt.pt`) 较大，无法通过自动化脚本直接传输。用户需手动复制。

## 贡献

欢迎对本项目提出建议或贡献代码。