
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import pyqtSignal, QThread, pyqtSlot
from PyQt6.QtWidgets import QMessageBox
import numpy as np, cv2 as cv, matplotlib as mpl, time
from pyclesperanto_prototype import dilate_labels
from core.canvas import ImageGraphicsView, ImageWrapper
import ui.app
from utils import numpy_to_qimage, qimage_to_numpy
from skimage.segmentation import expand_labels
from core.Worker import Worker
# STARDIST
import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
from stardist.models import StarDist2D
from csbdeep.utils import normalize
import tensorflow as tf

class StarDist(QThread):
    stardistDone = pyqtSignal(ImageWrapper)
    # sendGrayScale = pyqtSignal(np.ndarray)
    progress = pyqtSignal(int, str)
    errorSignal = pyqtSignal(str)
    

    def __init__(self):
        super().__init__()
        self.protein_channels = None
        self.np_image = None
        self.params = {
        'channel': 'Channel 1',
        'model': '2D_versatile_fluo',
        'percentile_low' : 3,
        'percentile_high': 99.80,
        'prob_threshold': 0.48,
        'nms_threshold': 0.3,
        'n_tiles': 0,
        'radius': 5,
        }
        self.aligned = False

    def loadCellImage(self, arr):
        self.cell_image = arr
        self.aligned = True

    def runStarDist(self):
        if self.protein_channels is None and self.np_image is None:
            self.errorSignal.emit("please load image first")  # emit error message
            return
        elif self.protein_channels and self.np_image:
            self.errorSignal.emit("unknown error, canvas has both single channel image and multi-channel image initiated")  # emit error message
            return
        

        import platform

        system = platform.system()
        print("system: ", system)
        print("tensorflow version: ", tf.__version__)
        gpu = len(tf.config.list_physical_devices('GPU')) > 0
        if gpu:
            device_name= tf.test.gpu_device_name()
            print("gpu name: ", device_name)
        else:
            device_name = '/CPU:0'

        # if system == "Windows":
        with tf.device(device_name):
            self.run()
            self.finished.connect(self.quit)
            self.finished.connect(self.deleteLater)


        # else:
        #     print("on MacOS ")
        #     self.stardist_worker = Worker(self.stardistTask)
        #     self.stardist_worker.start()
                
        print("here")

    def __get_cell_image(self):
        if self.aligned:
            return self.cell_image
        elif self.protein_channels is None and self.np_image:
            return self.np_image
        elif self.protein_channels and self.np_image is None:
            return self.protein_channels[self.params['channel']].data
        
    def run(self):
        cell_image = self.__get_cell_image()

        # adjusted = cv.convertScaleAbs(cell_image, alpha=(255.0/65535.0))
    
        # alpha = 5 # Contrast control
        # beta = 15 # Brightness control
        # adjusted = cv.convertScaleAbs(adjusted, alpha=alpha, beta=beta)
        # cv.imshow('Image Window',adjusted)

        # cv.waitKey(0)

        # cv.destroyAllWindows()
        
        self.progress.emit(0, "Starting StarDist")
        model = StarDist2D.from_pretrained(str(self.params['model']))
                        
        self.progress.emit(25, "Training model")
        
        print("here2")
        if self.params['n_tiles'] == 0:
            guess_tiles= model._guess_n_tiles(cell_image)
            # total_tiles = int(guess_tiles[0] * guess_tiles[1])
            # self.setNumberTiles(n_tiles)
            stardist_labels, _ = model.predict_instances(normalize(cell_image, self.params['percentile_low'], self.params['percentile_high']), 
                                                            prob_thresh=self.params['prob_threshold'], 
                                                            nms_thresh=self.params['nms_threshold'], n_tiles = guess_tiles)
            
        else:
            
            stardist_labels, _ = model.predict_instances(normalize(cell_image, self.params['percentile_low'], self.params['percentile_high']), 
                                                            prob_thresh=self.params['prob_threshold'], 
                                                            nms_thresh=self.params['nms_threshold'], 
                                                            n_tiles =(self.params['n_tiles'], (self.params['n_tiles'])))
            
        # dilate
        print("here3")
        radius = self.params['radius']
        self.progress.emit(95, "Dilating")
        self.stardist_labels_grayscale = np.array(dilate_labels(stardist_labels, radius=radius), dtype=np.uint16)
        print("here 4")
        self.progress.emit(100, "Stardist Done")
        stardist_result = ImageWrapper(self.stardist_labels_grayscale, name="stardist")
        self.stardistDone.emit(stardist_result)
    def cancel(self):
        self.terminate()


    def saveImage(self):
        from PIL import Image
        from PyQt6.QtWidgets import QFileDialog
        file_name, _ = QFileDialog.getSaveFileName(None, "Save File", "image.png", "*.png;;*.jpg;;*.tif;; All Files(*)")
        if not self.stardist_labels_grayscale is None:
            Image.fromarray(self.stardist_labels_grayscale).save(file_name)
        else:
            self.errorSignal.emit("Cannot save. No stardist labels available")
    # @pyqtSlot(int)
    # def updateProgress(self, num):
    #     self.progress.emit(num, f"Generating Tile {num}")
    
    # only uint8
    # @pyqtSlot(ImageWrapper)
    # def on_stardist_completed(self, stardist_result):
    #     self.stardistDone.emit(stardist_result)

    def change_cmap(self):
        pass
    
    def generate_lut(self, cmap:str):
        label_range = np.linspace(0, 1, 256)
        return np.uint8(mpl.colormaps[cmap](label_range)[:,2::-1]*256).reshape(256, 1, 3)

    def label2rgb(self, labels, lut):
        return cv.LUT(cv.merge((labels, labels, labels)), lut)

    def updateChannels(self, protein_channels, _):
        self.np_image = None
        self.protein_channels = protein_channels
        
    def setImageToProcess(self, np_image):
        self.protein_channels = None
        self.np_image = np_image

    def setChannel(self, channel):
        self.params['channel'] = channel

    def setModel(self, model):
        self.params['model'] = model

    def setPercentileLow(self, value):
        self.params['percentile_low'] = value

    def setPercentileHigh(self, value):
        self.params['percentile_high'] = value

    def setProbThresh(self, value):
        self.params['prob_threshold'] = value

    def setNMSThresh(self, value):
        self.params['nms_threshold'] = value

    def setNumberTiles(self, value):
        self.params['n_tiles'] = value

    def setDilationRadius(self, value):
        self.params['radius'] = value
