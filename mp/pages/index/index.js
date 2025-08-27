const SparkMD5 = require('../../utils/spark-md5.min.js')

Page({
  data: {
    fileInfo: '',
    brushSize: 10,
    editMode: 'add', // 'add', 'erase', 'move'
    tasks: [],
    taskCount: '',
    isTaskPanelCollapsed: false,
    isRefreshing: false,
    canvasWidth: 300,
    canvasHeight: 150,
    toast: {
      show: false,
      message: ''
    },
    isPreviewing: false,
    isPreviewLoading: false,
    previewCurrent: 0,
    previewImageOriginal: '',
    previewImageLama: '',
    password: '',
    showPasswordModal: true,
    serverUrl: 'http://127.0.0.1:8000', // 请根据您的实际后端地址修改
    scale: 1,
    offsetX: 0,
    offsetY: 0,
    currentPage: 1,
    totalPages: 1,
    pageNumbers: [],
  },

  onLoad: function () {
    this.ctx = wx.createCanvasContext('imageCanvas')
    this.maskData = null; // Stores ImageData for the mask

    this.isDrawing = false;
    this.isPanning = false;
    this.lastTouchDistance = 0;
    this.lastX = 0;
    this.lastY = 0;
    this.originalImage = null; // Stores wx.getImageInfo result
    this.imageMD5 = null;
    this.isMaskModified = false;
    this.isMultiTouch = false;
    this.history = []; // Stores maskData history
    this.maxHistoryLength = 50;
    this.isImageUploaded = false;
    this.lastTouchCenter = null;

    // Check for password in localStorage or prompt
    const savedPassword = wx.getStorageSync('password');
    if (savedPassword) {
      this.setData({
        password: savedPassword,
        showPasswordModal: false
      });
      this.refreshTaskList();
    } else {
      this.setData({
        showPasswordModal: true
      });
    }

    // Polling for task status
    this.taskPollInterval = setInterval(() => {
      if (this.data.tasks.some(t => t.status === 'pending' || t.status === 'processing')) {
        this.refreshTaskList();
      }
    }, 30000); // Every 30 seconds
  },

  onUnload: function() {
    clearInterval(this.taskPollInterval);
  },

  handlePasswordInput: function(e) {
    this.setData({
      password: e.detail.value
    });
  },

  submitPassword: function() {
    if (this.data.password) {
      wx.setStorageSync('password', this.data.password);
      this.setData({
        showPasswordModal: false
      });
      this.refreshTaskList();
    } else {
      this.showToast('请输入密码');
    }
  },

  getToken: function() {
    const pwd = this.data.password;
    const now = new Date();
    const year = now.getFullYear();
    const month = (now.getMonth() + 1).toString().padStart(2, '0');
    const day = now.getDate().toString().padStart(2, '0');
    const hours = now.getHours().toString().padStart(2, '0');
    const minutes = now.getMinutes().toString().padStart(2, '0');
    const timeStr = `${year}-${month}-${day} ${hours}:${minutes}`;
    return SparkMD5.hash(timeStr + pwd);
  },

  showToast: function(message, duration = 2000) {
    this.setData({
      toast: {
        show: true,
        message: message
      }
    });
    clearTimeout(this.toastTimeout);
    this.toastTimeout = setTimeout(() => {
      this.setData({
        toast: {
          show: false,
          message: ''
        }
      });
    }, duration);
  },

  chooseImage: function() {
    wx.chooseImage({
      count: 1,
      sizeType: ['original', 'compressed'],
      sourceType: ['album', 'camera'],
      success: (res) => {
        const tempFilePath = res.tempFilePaths[0];
        this.loadImage(tempFilePath);
      },
    })
  },

  calculateMD5: function(filePath) {
    return new Promise((resolve, reject) => {
      wx.getFileSystemManager().readFile({
        filePath: filePath,
        encoding: 'binary', // Read as binary to get ArrayBuffer
        success: (res) => {
          const spark = new SparkMD5.ArrayBuffer();
          spark.append(res.data);
          resolve(spark.end());
        },
        fail: (err) => {
          console.error(err);
          reject('Error calculating MD5');
        }
      });
    });
  },

  loadImage: async function(filePath) {
    wx.showLoading({ title: '图片加载中...' });
    try {
      const md5 = await this.calculateMD5(filePath);
      this.imageMD5 = md5;
      this.isMaskModified = false;

      wx.getImageInfo({
        src: filePath,
        success: async (res) => {
          this.originalImage = res;
          let width = res.width;
          let height = res.height;
          const MAX_SIZE = 1920;

          if (width > MAX_SIZE || height > MAX_SIZE) {
            if (width > height) {
              height = Math.round((height * MAX_SIZE) / width);
              width = MAX_SIZE;
            } else {
              width = Math.round((width * MAX_SIZE) / height);
              height = MAX_SIZE;
            }
            this.showToast(`图片尺寸过大，将自动缩放至 ${width} × ${height}`);
          }
          
          this.setData({
            canvasWidth: width,
            canvasHeight: height,
            fileInfo: `${res.width} × ${res.height} ${width !== res.width ? `⇨ ${width} × ${height}`: ''}`
          });

          // Create a temporary canvas for resizing if needed
          if (width !== res.width || height !== res.height) {
            const tempCanvas = wx.createOffscreenCanvas({ type: '2d', width, height });
            const tempCtx = tempCanvas.getContext('2d');
            const image = tempCanvas.createImage();
            await new Promise(resolve => {
              image.onload = resolve;
              image.src = this.originalImage.path;
            });
            tempCtx.drawImage(image, 0, 0, width, height);
            this.originalImage.path = tempCanvas.toDataURL('image/png'); // Get base64 data URL
          }

          // Initialize mask data (all black)
          this.maskData = new Uint8ClampedArray(width * height * 4);
          for (let i = 0; i < this.maskData.length; i += 4) {
            this.maskData[i] = 0;     // R
            this.maskData[i + 1] = 0; // G
            this.maskData[i + 2] = 0; // B
            this.maskData[i + 3] = 255; // A (fully opaque)
          }

          this.fitScreen();
          this.isImageUploaded = false;
          this.history = [];
          this.redrawCanvas();
          wx.hideLoading();
        },
        fail: (err) => {
          wx.hideLoading();
          this.showToast('图片信息获取失败');
          console.error(err);
        }
      });
    } catch (error) {
      wx.hideLoading();
      this.showToast('加载图片出错: ' + error);
      console.error(error);
    }
  },

  redrawCanvas: function() {
    if (!this.originalImage) return;

    const { canvasWidth, canvasHeight, scale, offsetX, offsetY } = this.data;

    this.ctx.clearRect(0, 0, canvasWidth, canvasHeight);
    this.ctx.save();
    this.ctx.translate(offsetX, offsetY);
    this.ctx.scale(scale, scale);

    this.ctx.drawImage(this.originalImage.path, 0, 0, this.originalImage.width, this.originalImage.height);

    // Draw mask
    if (this.maskData) {
      const tempCanvas = wx.createOffscreenCanvas({ type: '2d', width: canvasWidth, height: canvasHeight });
      const tempCtx = tempCanvas.getContext('2d');
      const imageData = tempCtx.createImageData(canvasWidth, canvasHeight);
      imageData.data.set(this.maskData);
      tempCtx.putImageData(imageData, 0, 0);
      
      this.ctx.globalAlpha = 0.5; // Apply transparency to the mask
      this.ctx.drawImage(tempCanvas, 0, 0, canvasWidth, canvasHeight);
      this.ctx.globalAlpha = 1; // Reset globalAlpha
    }

    this.ctx.restore();
    this.ctx.draw();
  },

  getCanvasRelativePos: function(touch) {
    const { canvasWidth, canvasHeight, scale, offsetX, offsetY } = this.data;
    const rect = {
      left: (wx.getSystemInfoSync().windowWidth - canvasWidth) / 2, // Simplified, assuming canvas is centered
      top: (wx.getSystemInfoSync().windowHeight - canvasHeight) / 2, // Simplified
    };
    return {
      x: (touch.x - offsetX) / scale,
      y: (touch.y - offsetY) / scale,
    };
  },

  onTouchStart: function(e) {
    if (!this.originalImage) return;

    if (e.touches.length === 1) {
      this.isMultiTouch = false;
      if (this.data.editMode === 'move') {
        this.isPanning = true;
        this.lastX = e.touches[0].x;
        this.lastY = e.touches[0].y;
      } else {
        this.isDrawing = true;
        this.saveToHistory();
        const pos = this.getCanvasRelativePos(e.touches[0]);
        this.lastX = pos.x;
        this.lastY = pos.y;
        this.drawPoint(pos.x, pos.y);
      }
    } else if (e.touches.length >= 2) {
      this.isMultiTouch = true;
      this.isDrawing = false;
      this.isPanning = false;
      const touch1 = e.touches[0];
      const touch2 = e.touches[1];
      this.lastTouchDistance = Math.hypot(touch1.x - touch2.x, touch1.y - touch2.y);
      this.lastTouchCenter = {
        x: (touch1.x + touch2.x) / 2,
        y: (touch1.y + touch2.y) / 2,
      };
    }
  },

  onTouchMove: function(e) {
    if (!this.originalImage) return;

    if (this.isMultiTouch && e.touches.length >= 2) {
        const touch1 = e.touches[0];
        const touch2 = e.touches[1];
        const newDistance = Math.hypot(touch1.x - touch2.x, touch1.y - touch2.y);
        const newCenter = {
            x: (touch1.x + touch2.x) / 2,
            y: (touch1.y + touch2.y) / 2,
        };

        const scaleChange = newDistance / this.lastTouchDistance;
        const deltaX = newCenter.x - this.lastTouchCenter.x;
        const deltaY = newCenter.y - this.lastTouchCenter.y;
        
        this.zoomAndPan(scaleChange, deltaX, deltaY, newCenter.x, newCenter.y);

        this.lastTouchDistance = newDistance;
        this.lastTouchCenter = newCenter;

    } else if (this.isDrawing && e.touches.length === 1) {
        const pos = this.getCanvasRelativePos(e.touches[0]);
        this.drawLine(this.lastX, this.lastY, pos.x, pos.y);
        this.lastX = pos.x;
        this.lastY = pos.y;
        this.redrawCanvas();
    } else if (this.isPanning && e.touches.length === 1) {
        const deltaX = e.touches[0].x - this.lastX;
        const deltaY = e.touches[0].y - this.lastY;
        this.setData({
            offsetX: this.data.offsetX + deltaX,
            offsetY: this.data.offsetY + deltaY,
        });
        this.lastX = e.touches[0].x;
        this.lastY = e.touches[0].y;
        this.redrawCanvas();
    }
  },

  onTouchEnd: function(e) {
    this.isDrawing = false;
    this.isPanning = false;
    if (e.touches.length < 2) {
        this.isMultiTouch = false;
    }
  },
  
  changeEditMode: function(e) {
    this.setData({ editMode: e.currentTarget.dataset.mode });
  },

  onBrushSizeChange: function(e) {
    this.setData({ brushSize: e.detail.value });
  },

  zoom: function(factor) {
    const oldScale = this.data.scale;
    const newScale = Math.min(Math.max(0.1, oldScale * factor), 10);
    
    // Zoom around center of canvas
    const centerX = this.data.canvasWidth / 2;
    const centerY = this.data.canvasHeight / 2;

    const newOffsetX = centerX - (centerX - this.data.offsetX) * (newScale / oldScale);
    const newOffsetY = centerY - (centerY - this.data.offsetY) * (newScale / oldScale);

    this.setData({ 
      scale: newScale,
      offsetX: newOffsetX,
      offsetY: newOffsetY
    });
    this.redrawCanvas();
  },

  zoomIn: function() { this.zoom(1.2); },
  zoomOut: function() { this.zoom(0.8); },

  resetZoom: function() {
    this.setData({ scale: 1, offsetX: 0, offsetY: 0 });
    this.redrawCanvas();
  },

  fitScreen: function() {
    if (!this.originalImage) return;
    const { windowWidth, windowHeight } = wx.getSystemInfoSync();
    const containerWidth = windowWidth;
    const containerHeight = windowHeight - 200; // Approximate height for controls and task panel

    const imageWidth = this.data.canvasWidth;
    const imageHeight = this.data.canvasHeight;

    const scaleX = containerWidth / imageWidth;
    const scaleY = containerHeight / imageHeight;
    const newScale = Math.min(scaleX, scaleY);

    this.setData({
      scale: newScale,
      offsetX: (containerWidth - imageWidth * newScale) / 2,
      offsetY: (containerHeight - imageHeight * newScale) / 2,
    });
    this.redrawCanvas();
  },

  saveToHistory: function() {
    if (!this.maskData) return;
    const historyItem = new Uint8ClampedArray(this.maskData);
    this.history.push(historyItem);
    if (this.history.length > this.maxHistoryLength) {
      this.history.shift();
    }
    this.isMaskModified = true;
  },

  undo: function() {
    if (this.history.length > 0) {
      this.maskData = this.history.pop();
      this.redrawCanvas();
      this.isMaskModified = true;
    }
  },

  clearMask: function() {
    if (!this.originalImage) {
      this.showToast('请先选择图片');
      return;
    }
    this.saveToHistory();
    const { canvasWidth, canvasHeight } = this.data;
    this.maskData = new Uint8ClampedArray(canvasWidth * canvasHeight * 4);
    for (let i = 0; i < this.maskData.length; i += 4) {
      this.maskData[i] = 0;     // R
      this.maskData[i + 1] = 0; // G
      this.maskData[i + 2] = 0; // B
      this.maskData[i + 3] = 255; // A (fully opaque)
    }
    this.redrawCanvas();
    this.isMaskModified = true;
  },

  drawPoint: function(x, y) {
    if (!this.maskData) return;
    const { canvasWidth, canvasHeight, brushSize } = this.data;
    const radius = brushSize / 2;
    const color = this.data.editMode === 'add' ? 255 : 0; // White for add, black for erase

    for (let i = Math.max(0, Math.floor(y - radius)); i < Math.min(canvasHeight, Math.ceil(y + radius)); i++) {
      for (let j = Math.max(0, Math.floor(x - radius)); j < Math.min(canvasWidth, Math.ceil(x + radius)); j++) {
        const dist = Math.sqrt(Math.pow(j - x, 2) + Math.pow(i - y, 2));
        if (dist <= radius) {
          const index = (i * canvasWidth + j) * 4;
          this.maskData[index] = color;
          this.maskData[index + 1] = color;
          this.maskData[index + 2] = color;
          this.maskData[index + 3] = 255; // Opaque
        }
      }
    }
  },

  drawLine: function(x1, y1, x2, y2) {
    if (!this.maskData) return;
    const { canvasWidth, canvasHeight, brushSize } = this.data;
    const color = this.data.editMode === 'add' ? 255 : 0;

    const dist = Math.sqrt(Math.pow(x2 - x1, 2) + Math.pow(y2 - y1, 2));
    const angle = Math.atan2(y2 - y1, x2 - x1);

    for (let i = 0; i < dist; i++) {
      const x = x1 + Math.cos(angle) * i;
      const y = y1 + Math.sin(angle) * i;
      this.drawPoint(x, y);
    }
  },

  zoomAndPan: function(scaleFactor, deltaX, deltaY, centerX, centerY) {
    const oldScale = this.data.scale;
    const newScale = Math.min(Math.max(0.1, oldScale * scaleFactor), 10);
    
    const newOffsetX = centerX - (centerX - this.data.offsetX) * (newScale / oldScale) + deltaX;
    const newOffsetY = centerY - (centerY - this.data.offsetY) * (newScale / oldScale) + deltaY;

    this.setData({ 
      scale: newScale,
      offsetX: newOffsetX,
      offsetY: newOffsetY
    });
    this.redrawCanvas();
  },

  uploadImage: async function() {
    if (!this.originalImage) {
      this.showToast('请先选择一张图片');
      return;
    }
    this.showToast('开始原图图片上传 ... ');
    wx.showLoading({ title: '上传原图...' });

    try {
      const uploadRes = await wx.uploadFile({
        url: `${this.data.serverUrl}/upload?token=${this.getToken()}`,
        filePath: this.originalImage.path,
        name: 'file',
        formData: {
          md5: this.imageMD5,
          type: 'image'
        },
      });
      const result = JSON.parse(uploadRes.data);
      if (result.status === 'success') {
        this.showToast('原图上传成功');
        this.isImageUploaded = true;
      } else {
        this.showToast('原图上传失败: ' + result.message);
      }
    } catch (error) {
      this.showToast('原图上传出错: ' + error.message);
      console.error(error);
    } finally {
      wx.hideLoading();
    }
  },

  uploadMask: async function() {
    if (!this.maskData || !this.imageMD5) {
      this.showToast('请先选择图片并创建遮罩');
      return;
    }
    this.showToast('开始遮罩图片上传 ... ');
    wx.showLoading({ title: '上传遮罩...' });

    try {
      // Create a temporary file for the mask
      const { canvasWidth, canvasHeight } = this.data;
      const tempCanvas = wx.createOffscreenCanvas({ type: '2d', width: canvasWidth, height: canvasHeight });
      const tempCtx = tempCanvas.getContext('2d');
      const imageData = tempCtx.createImageData(canvasWidth, canvasHeight);
      imageData.data.set(this.maskData);
      tempCtx.putImageData(imageData, 0, 0);

      const tempFilePath = wx.env.USER_DATA_PATH + '/mask.png';
      await new Promise((resolve, reject) => {
        tempCanvas.toDataURL('image/png', {
          success: (res) => {
            const base64Data = res.replace(/^data:image\/\w+;base64,/, "");
            const fileBuffer = wx.base64ToArrayBuffer(base64Data);
            wx.getFileSystemManager().writeFile({
              filePath: tempFilePath,
              data: fileBuffer,
              encoding: 'binary',
              success: resolve,
              fail: reject
            });
          },
          fail: reject
        });
      });

      const uploadRes = await wx.uploadFile({
        url: `${this.data.serverUrl}/upload?token=${this.getToken()}`,
        filePath: tempFilePath,
        name: 'file',
        formData: {
          md5: this.imageMD5,
          type: 'mask'
        },
      });
      const result = JSON.parse(uploadRes.data);
      if (result.status === 'success') {
        this.showToast('遮罩图片上传成功');
        this.isMaskModified = false;
      } else {
        this.showToast('遮罩图片上传失败: ' + result.message);
      }
    } catch (error) {
      this.showToast('遮罩图片上传出错: ' + error.message);
      console.error(error);
    } finally {
      wx.hideLoading();
    }
  },

  uploadLama: async function() {
    if (!this.maskData || !this.imageMD5) {
      this.showToast('请先选择图片并创建遮罩');
      return;
    }

    if (!this.isImageUploaded) {
      this.showToast('原图还未上传，正在上传...');
      await this.uploadImage();
    }

    if (this.isMaskModified) {
      this.showToast('遮罩已修改，正在上传...');
      await this.uploadMask();
    }

    this.showToast('开始Lama图像修复...', 120000);
    wx.showLoading({ title: '修复中...' });
    try {
      const res = await wx.request({
        url: `${this.data.serverUrl}/lama?token=${this.getToken()}`,
        method: 'POST',
        header: {
          'Content-Type': 'application/json'
        },
        data: {
          md5: this.imageMD5
        },
      });

      const result = res.data;
      if (result.status === 'success') {
        this.showToast('OK: ' + result.message);
        this.refreshTaskList();
      } else {
        this.showToast('修复失败: ' + result.message);
      }
    } catch (error) {
      this.showToast('修复出错: ' + error.message);
      console.error(error);
    } finally {
      wx.hideLoading();
    }
  },

  getTaskStatus: async function(page = 1) {
    try {
      const res = await wx.request({
        url: `${this.data.serverUrl}/tasks?page=${page}&token=${this.getToken()}`,
      });
      if (res.statusCode === 200) {
        return res.data;
      } else if (res.statusCode === 401) {
        return { error: 'Unauthorized' };
      } else {
        throw new Error(`HTTP error! status: ${res.statusCode}`);
      }
    } catch (error) {
      console.error('获取任务状态失败:', error);
      throw error;
    }
  },

  updateTaskList: function(data) {
    const tasks = Object.entries(data.tasks).map(([md5, task]) => ({
      md5,
      ...task,
      statusText: {
        'pending': '等待处理',
        'processing': '处理中',
        'completed': '已完成',
        'error': '失败'
      }[task.status],
      create_time: new Date(task.create_time * 1000).toLocaleString()
    }));
    this.setData({
      tasks: tasks,
      taskCount: `共${data.total}个任务 (${tasks.filter(t => t.status === 'pending').length}待处理/${tasks.filter(t => t.status === 'processing').length}处理中)`,
      currentPage: data.page,
      totalPages: data.total_pages,
    });
    this.updatePagination(data);
  },

  updatePagination: function(data) {
    const pageNumbers = [];
    const currentPage = data.page;
    const totalPages = data.total_pages;

    // Logic to generate page numbers for display
    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i++) {
        pageNumbers.push(i);
      }
    } else {
      if (currentPage <= 4) {
        for (let i = 1; i <= 5; i++) {
          pageNumbers.push(i);
        }
        pageNumbers.push('...');
        pageNumbers.push(totalPages);
      } else if (currentPage >= totalPages - 3) {
        pageNumbers.push(1);
        pageNumbers.push('...');
        for (let i = totalPages - 4; i <= totalPages; i++) {
          pageNumbers.push(i);
        }
      } else {
        pageNumbers.push(1);
        pageNumbers.push('...');
        for (let i = currentPage - 1; i <= currentPage + 1; i++) {
          pageNumbers.push(i);
        }
        pageNumbers.push('...');
        pageNumbers.push(totalPages);
      }
    }
    this.setData({ pageNumbers: pageNumbers });
  },

  changePage: function(e) {
    const page = parseInt(e.currentTarget.dataset.page);
    if (page < 1 || page > this.data.totalPages) return;
    this.setData({ currentPage: page });
    this.refreshTaskList();
  },

  refreshTaskList: async function() {
    this.setData({ isRefreshing: true });
    try {
      const data = await this.getTaskStatus(this.data.currentPage);
      if (data.error && data.error === 'Unauthorized') {
        this.showToast('密码错误，请重新输入');
        this.setData({ showPasswordModal: true });
        return;
      }
      this.updateTaskList(data);
      this.setData({ isTaskPanelCollapsed: false }); // Expand panel on refresh
    } catch (error) {
      this.showToast('刷新任务列表失败: ' + error.message);
      console.error(error);
    } finally {
      this.setData({ isRefreshing: false });
    }
  },

  deleteTask: async function(e) {
    const md5 = e.currentTarget.dataset.md5;
    if (!md5) return;

    wx.showModal({
      title: '确认删除',
      content: '确定要删除此任务吗？',
      success: async (res) => {
        if (res.confirm) {
          try {
            const reqRes = await wx.request({
              url: `${this.data.serverUrl}/delete_task?token=${this.getToken()}`,
              method: 'POST',
              header: {
                'Content-Type': 'application/json'
              },
              data: { md5 },
            });
            const result = reqRes.data;
            if (result.status === 'success') {
              this.showToast('任务删除成功');
              this.refreshTaskList();
            } else {
              this.showToast('删除失败: ' + result.message);
            }
          } catch (error) {
            this.showToast('删除任务失败: ' + error.message);
            console.error(error);
          }
        }
      }
    });
  },

  reLama: async function(e) {
    const md5 = e.currentTarget.dataset.md5;
    if (!md5) return;

    this.showToast('再次Lama中...');
    wx.showLoading({ title: '再次处理...' });
    try {
      const res = await wx.request({
        url: `${this.data.serverUrl}/relama?token=${this.getToken()}`,
        method: 'POST',
        header: {
          'Content-Type': 'application/json'
        },
        data: { md5 },
      });
      const result = res.data;
      if (result.status === 'success') {
        this.showToast('OK: ' + result.message);
        this.refreshTaskList();
      } else {
        this.showToast('再次Lama失败: ' + result.message);
      }
    } catch (error) {
      this.showToast('再次Lama失败: ' + error.message);
      console.error(error);
    } finally {
      wx.hideLoading();
    }
  },

  loadTask: async function(e) {
    const md5 = e.currentTarget.dataset.md5;
    if (!md5) return;

    wx.showLoading({ title: '加载任务...' });
    try {
      // Load original image
      const originalImagePath = `${this.data.serverUrl}/image/${md5}.jpg?t=${Date.now()}&token=${this.getToken()}`;
      const originalImageInfo = await new Promise((resolve, reject) => {
        wx.getImageInfo({ src: originalImagePath, success: resolve, fail: reject });
      });
      this.originalImage = originalImageInfo;
      this.imageMD5 = md5;
      this.isImageUploaded = true;

      this.setData({
        canvasWidth: originalImageInfo.width,
        canvasHeight: originalImageInfo.height,
        fileInfo: `${originalImageInfo.width} × ${originalImageInfo.height}`
      });

      // Load mask
      const maskPath = `${this.data.serverUrl}/image/${md5}_mask.png?t=${Date.now()}&token=${this.getToken()}`;
      try {
        const maskImageInfo = await new Promise((resolve, reject) => {
          wx.getImageInfo({ src: maskPath, success: resolve, fail: reject });
        });
        // Draw mask to offscreen canvas to get ImageData
        const tempCanvas = wx.createOffscreenCanvas({ type: '2d', width: maskImageInfo.width, height: maskImageInfo.height });
        const tempCtx = tempCanvas.getContext('2d');
        const image = tempCanvas.createImage();
        await new Promise(resolve => {
          image.onload = resolve;
          image.src = maskImageInfo.path;
        });
        tempCtx.drawImage(image, 0, 0, maskImageInfo.width, maskImageInfo.height);
        const imageData = tempCtx.getImageData(0, 0, maskImageInfo.width, maskImageInfo.height);
        this.maskData = new Uint8ClampedArray(imageData.data);
      } catch (maskError) {
        // Mask not found or error, create a black mask
        this.maskData = new Uint8ClampedArray(originalImageInfo.width * originalImageInfo.height * 4);
        for (let i = 0; i < this.maskData.length; i += 4) {
          this.maskData[i] = 0;     // R
          this.maskData[i + 1] = 0; // G
          this.maskData[i + 2] = 0; // B
          this.maskData[i + 3] = 255; // A
        }
      }

      this.fitScreen();
      this.history = [];
      this.redrawCanvas();
      this.showToast('任务加载成功');
    } catch (error) {
      this.showToast('加载任务失败: ' + error.message);
      console.error(error);
    } finally {
      wx.hideLoading();
    }
  },

  previewImage: function(e) {
    const url = e.currentTarget.dataset.url;
    const isLama = e.currentTarget.dataset.isLama;
    const md5 = url.split('/').pop().split('.')[0].replace('_lama', '');

    this.setData({
      isPreviewing: true,
      isPreviewLoading: true,
      previewImageOriginal: `${this.data.serverUrl}/image/${md5}.jpg?t=${Date.now()}&token=${this.getToken()}`,
      previewImageLama: `${this.data.serverUrl}/image/${md5}_lama.jpg?t=${Date.now()}&token=${this.getToken()}`,
      previewCurrent: isLama ? 1 : 0
    });

    // Simulate loading completion
    setTimeout(() => {
      this.setData({ isPreviewLoading: false });
    }, 500);
  },

  closePreview: function() {
    this.setData({ isPreviewing: false });
  },

  onPreviewChange: function(e) {
    this.setData({ previewCurrent: e.detail.current });
  },
})