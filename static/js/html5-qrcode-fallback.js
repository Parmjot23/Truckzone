class Html5Qrcode {
  constructor(elementId) {
    this.element = document.getElementById(elementId);
    this.video = document.createElement('video');
    this.video.setAttribute('playsinline', '');
    this.element.appendChild(this.video);
    this.stream = null;
    this.barcodeDetector = ('BarcodeDetector' in window)
      ? new BarcodeDetector({formats: ['qr_code']})
      : null;
    this._onSuccess = null;
    this._scan = this._scan.bind(this);
  }

  start(deviceId, config, onSuccess) {
    this._onSuccess = onSuccess;
    const constraints = {video: {facingMode: 'environment'}};
    if (deviceId) constraints.video.deviceId = {exact: deviceId};
    return navigator.mediaDevices.getUserMedia(constraints).then(stream => {
      this.stream = stream;
      this.video.srcObject = stream;
      return this.video.play().then(() => {
        requestAnimationFrame(this._scan);
      });
    });
  }

  _scan() {
    if (!this.stream) return;
    if (this.barcodeDetector) {
      this.barcodeDetector.detect(this.video).then(barcodes => {
        if (!this.stream) return;
        if (barcodes.length > 0) {
          this._onSuccess(barcodes[0].rawValue);
        } else {
          requestAnimationFrame(this._scan);
        }
      }).catch(() => {
        requestAnimationFrame(this._scan);
      });
    } else {
      requestAnimationFrame(this._scan);
    }
  }

  stop() {
    if (this.stream) {
      this.stream.getTracks().forEach(t => t.stop());
      this.stream = null;
    }
    if (this.video) {
      this.video.remove();
      this.video = null;
    }
    return Promise.resolve();
  }

  static getCameras() {
    return navigator.mediaDevices.enumerateDevices().then(devices => {
      return devices.filter(d => d.kind === 'videoinput');
    });
  }
}
