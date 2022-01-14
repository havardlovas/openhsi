# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/02_cameras.ipynb (unless otherwise specified).

__all__ = ['WebCamera', 'XimeaCamera', 'LucidCamera', 'FlirCamera']

# Cell

from fastcore.foundation import patch
from fastcore.meta import delegates
import cv2
import numpy as np
import ctypes
import matplotlib.pyplot as plt
import warnings
from tqdm import tqdm

import holoviews as hv
hv.extension('bokeh',logo=False)

# Cell
from .capture import OpenHSI

# Cell

@delegates()
class WebCamera(OpenHSI):
    """Interface for webcam to test OpenHSI functionality"""
    def __init__(self, mode:str = None, **kwargs):
        """Initialise Webcam"""
        super().__init__(**kwargs)
        self.mode = mode
        if self.mode == "HgAr":
            self.gen = self.gen_sim_spectra()

        # Check if the webcam is opened correctly
        self.vid = cv2.VideoCapture(0)
        if not self.vid.isOpened():
            raise IOError("Cannot open webcam")

    def start_cam(self):
        pass

    def stop_cam(self):
        self.vid.release()
        cv2.destroyAllWindows()

    def get_img(self) -> np.ndarray:
        if self.mode == "HgAr":
            return next(self.gen)
        else:
            ret, frame = self.vid.read()
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            frame = cv2.resize(frame, tuple(np.flip(self.settings["resolution"])), interpolation = cv2.INTER_AREA)
            if self.mode == "crop":
                frame[:self.settings["row_slice"][0],...] = 0
                frame[self.settings["row_slice"][1]:,...] = 0
            return frame

    def gen_sim_spectra(self):
        lines_nm = [254,436,546,764,405,365,578,750,738,697,812,772,912,801,842,795,706,826,852,727] # approx sorted by emission strength
        img = np.zeros(tuple(self.settings["resolution"]),dtype=np.uint8)
        wavelengths = np.linspace(self.settings["index2wavelength_range"][0],self.settings["index2wavelength_range"][1],num=self.settings["resolution"][1])

        strength = 255
        for line in lines_nm:
            indx = np.sum(wavelengths<line)
            if indx > 0 and indx < self.settings["resolution"][1]:
                img[:,indx-2:indx+2] = strength
                strength -= 5
        while True:
            yield img

    def get_temp(self) -> float:
        return 20.0


# Cell

@delegates()
class XimeaCamera(OpenHSI):

    """Core functionality for Ximea cameras"""
    # https://www.ximea.com/support/wiki/apis/Python
    def __init__(self, xbinwidth:int = 896, xbinoffset:int = 528, exposure_ms:float = 10, serial_num:str = None, **kwargs):
        """Initialise Camera"""

        super().__init__(**kwargs)

        try:
            from ximea import xiapi
            self.xiapi=xiapi # make avalaible for later access just in case.
        except ModuleNotFoundError:
            warnings.warn("ModuleNotFoundError: No module named 'ximea'.",stacklevel=2)

        self.xicam = self.xiapi.Camera()

        self.xicam.open_device_by_SN(serial_num) if serial_num else self.xicam.open_device()

        print(f'Connected to device {self.xicam.get_device_sn()}')

        self.xbinwidth  = xbinwidth
        self.xbinoffset = xbinoffset
        self.exposure   = exposure_ms
        self.gain       = 0

        self.xicam.set_width(self.xbinwidth)
        self.xicam.set_offsetX(self.xbinoffset)
        self.xicam.set_exposure_direct(1000*self.exposure)
        self.xicam.set_gain_direct(self.gain)

        self.xicam.set_imgdataformat("XI_RAW16")
        self.xicam.set_output_bit_depth("XI_BPP_12")
        self.xicam.enable_output_bit_packing()
        self.xicam.disable_aeag()

        self.xicam.set_binning_vertical(2)
        self.xicam.set_binning_vertical_mode("XI_BIN_MODE_SUM")

        self.rows, self.cols = self.xicam.get_height(), self.xicam.get_width()
        self.img = xiapi.Image()

        #self.load_cam_settings()

    def __exit__(self, *args, **kwargs):
        self.xicam.stop_acquisition()
        self.xicam.close_device()

    def start_cam(self):
        self.xicam.start_acquisition()

    def stop_cam(self):
        self.xicam.stop_acquisition()

    def get_img(self) -> np.ndarray:
        self.xicam.get_image(self.img)
        return self.img.get_image_data_numpy()

    def get_temp(self) -> float:
        return self.xicam.get_temp()

# Cell

@delegates()
class LucidCamera(OpenHSI):

    """Core functionality for Lucid Vision Lab cameras

        Any keyword-value pair arguments must match the those avaliable in settings file. LucidCamera expects the ones listed below:

        - `binxy`: number of pixels to bin in (x,y) direction
        - `win_resolution`: size of area on detector to readout (width, height)
        - `win_offset`: offsets (x,y) from edge of detector for a selective
        - `exposure_ms`: is the camera exposure time to use
        - `pixel_format`: format of pixels readout sensor, ie Mono8, Mono10, Mono10p, Mono10Packed, Mono12, Mono12p, Mono12Packed, Mono16
        - `mac_addr`: str = "1c:0f:af:01:7b:a0",
    """

    # https://thinklucid.com/downloads-hub/
    def __init__(self, **kwargs):
        """Initialise Camera"""

        super().__init__(**kwargs)

        try:
            from arena_api.system import system as arsys
            self.arsys = arsys  # make avalaible for later access just in case.
            arsys.destroy_device() # reset an existing connections.

        except ModuleNotFoundError:
            warnings.warn(
                "ModuleNotFoundError: No module named 'arena_api'.", stacklevel=2
            )

        #init api and connect to device
#         try:
#             self.arsys.device_infos
#             print("2")
#             if self.settings["mac_addr"]:
#                 device_infos={"mac": self.settings["mac_addr"]} # use specfic camera
#                 print("3")
#             else:
#                 device_infos={} # or use first camera found

#             # self.device = arsys.create_device(device_infos=[{"mac": mac_addr}])[0]

#             self.device = arsys.create_device(device_infos=[device_infos])[0]
#         except:
#             warnings.warn(
#                 "DeviceNotFoundError: Please connect a lucid vision camera and run again.",
#                 stacklevel=2)

        try:
            self.arsys.device_infos
            #self.device = arsys.create_device(device_infos=[{"mac": mac_addr}])[0]
            self.device = arsys.create_device()[0]
        except:
            warnings.warn(
                "DeviceNotFoundError: Please connect a lucid vision camera and run again.",
                stacklevel=2,
            )

        # allow api to optimise stream
        tl_stream_nodemap = self.device.tl_stream_nodemap
        tl_stream_nodemap["StreamAutoNegotiatePacketSize"].value = True
        tl_stream_nodemap["StreamPacketResendEnable"].value = True

        # init access to device settings
        self.deviceSettings = self.device.nodemap.get_node([
                "AcquisitionFrameRate",
                "AcquisitionFrameRateEnable",
                "AcquisitionMode",
                "AcquisitionStart",
                "AcquisitionStop",
                "BinningHorizontal",
                "BinningVertical",
                "DevicePower",
                "DeviceTemperature",
                "DeviceUpTime",
                "DeviceUserID",
                "ExposureAuto",
                "ExposureTime",
                "Gain",
                "GammaEnable",
                "Height",
                "OffsetX",
                "OffsetY",
                "PixelFormat",
                "ReverseX",
                "ReverseY",
                "Width",
                "GevMACAddress",
                "DeviceSerialNumber"
            ]
        )

        # set pixel settings
        self.deviceSettings["BinningHorizontal"].value = self.settings["binxy"][0] # binning is symetric on this sensor, no need to set vertical
        self.deviceSettings["PixelFormat"].value = self.settings["pixel_format"]

        # always reset to no window.
        self.deviceSettings["OffsetY"].value = 0
        self.deviceSettings["OffsetX"].value = 0
        self.deviceSettings["Height"].value = self.deviceSettings["Height"].max
        self.deviceSettings["Width"].value = self.deviceSettings["Width"].max

        # print("Setting window to: height {}, offset y {}, width {}, offsetx {}".format(self.settings["win_resolution"][0],
        #                                                                     self.settings["win_offset"][0],
        #                                                                     self.settings["win_resolution"][1],
        #                                                                     self.settings["win_offset"][1])
        #      )

        # set window up.
        self.deviceSettings["Height"].value = self.settings["win_resolution"][0] if self.settings["win_resolution"][0] > 0 else self.deviceSettings["Height"].max
        self.deviceSettings["Width"].value = self.settings["win_resolution"][1] if self.settings["win_resolution"][1] > 0 else self.deviceSettings["Width"].max

        self.deviceSettings["OffsetY"].value = self.settings["win_offset"][0] if self.settings["win_offset"][0] > 0 else self.deviceSettings["OffsetY"].max
        self.deviceSettings["OffsetX"].value = self.settings["win_offset"][1] if self.settings["win_offset"][1] > 0 else self.deviceSettings["OffsetX"].max

        # set exposure realted props
        self.deviceSettings["ExposureAuto"].value = "Off" # always off as we need to match exposure to calibration data
        self.set_exposure(self.settings["exposure_ms"])

        self.set_gain(0) # default to 0 as we need to match to calibration data

        self.rows, self.cols = (
            self.deviceSettings["Height"].value,
            self.deviceSettings["Width"].value,
        )

        self.settings['camera_id'] = self.deviceSettings["DeviceUserID"].value

    def __exit__(self, *args, **kwargs):
        self.device.stop_stream()
        self.arsys.destroy_device()

    def start_cam(self):
        self.device.start_stream(1)

    def stop_cam(self):
        self.device.stop_stream()

    def set_exposure(self,exposure_ms:float):

        if exposure_ms < self.deviceSettings["ExposureTime"].min/1000.0:
            exposure_us=self.deviceSettings["ExposureTime"].min
        else:
            exposure_us = exposure_ms*1000.0

        nominal_framerate = 1_000_000.0/exposure_us*0.98

        # print("nominal_framerate {}, exposure_us {}".format(nominal_framerate,exposure_us))

        if  nominal_framerate < self.deviceSettings['AcquisitionFrameRate'].max:
            self.deviceSettings["AcquisitionFrameRateEnable"].value=True
            self.deviceSettings['AcquisitionFrameRate'].value = nominal_framerate
        else:
            self.deviceSettings["AcquisitionFrameRateEnable"].value=False

        self.deviceSettings["ExposureTime"].value = exposure_us # requires time in us float
        self.settings["exposure_ms"] = self.deviceSettings["ExposureTime"].value/1000.00  # exposure time rounds, so storing actual value

    def set_gain(self,gain_val:float):
        self.deviceSettings["Gain"].value = gain_val * 1. # make float always

    def get_img(self) -> np.ndarray:
        image_buffer = self.device.get_buffer()
        if image_buffer.bits_per_pixel == 8:
            nparray_reshaped = np.ctypeslib.as_array(
                image_buffer.pdata, (image_buffer.height, image_buffer.width)
            ).copy()

        elif image_buffer.bits_per_pixel == 12 or image_buffer.bits_per_pixel == 10:
            split=np.ctypeslib.as_array(image_buffer.pdata,(image_buffer.buffer_size,1)).astype(np.uint16)
            fst_uint12 = (split[0::3] << 4) + (split[1::3] >> 4)
            snd_uint12 = (split[2::3] << 4) + (np.bitwise_and(15, split[1::3]))
            nparray_reshaped = np.reshape(np.concatenate((fst_uint12[:, None], snd_uint12[:, None]), axis=1),
                                          (image_buffer.height, image_buffer.width))

        elif image_buffer.bits_per_pixel == 16:
            pdata_as16 = ctypes.cast(image_buffer.pdata, ctypes.POINTER(ctypes.c_ushort))
            nparray_reshaped = np.ctypeslib.as_array(
                pdata_as16, (image_buffer.height, image_buffer.width)
            ).copy()

        #nparray_reshaped=np.ctypeslib.as_array(image_buffer,(1,image_buffer.buffer_size))
        self.device.requeue_buffer(image_buffer)
        return nparray_reshaped

    def get_temp(self) -> float:
        return self.deviceSettings["DeviceTemperature"].value

    def get_mac(self)-> str:
        return ':'.join(['{}{}'.format(a, b)
                         for a, b
                         in zip(*[iter('{:012x}'.format(cam.deviceSettings['GevMACAddress'].value))]*2)])

# Cell
from typing import Tuple

@delegates()
class FlirCamera(OpenHSI):
    """Interface for FLIR camera"""

    def __init__(self, **kwargs):
        """Initialise FLIR camera"""
        super().__init__(**kwargs)

        try:
            from simple_pyspin import Camera
        except ModuleNotFoundError:
            warnings.warn("ModuleNotFoundError: No module named 'PySpin'.",stacklevel=2)

        self.flircam = Camera()
        self.flircam.GainAuto = 'Off'
        self.flircam.Gain = 0
        self.flircam.AcquisitionFrameRateAuto = 'Off'
        self.flircam.AcquisitionFrameRateEnabled = True
        self.flircam.AcquisitionFrameRate = int( 1_000/self.settings["exposure_ms"] )

        self.flircam.ExposureAuto = 'Off'
        self.flircam.ExposureTime = self.settings["exposure_ms"]*1e3 # convert to us
        self.flircam.GammaEnabled = False

        self.flircam.Width, self.flircam.Height = self.settings["win_resolution"]
        if self.settings["win_resolution"][0] == 0:
            self.flircam.Width = self.flircam.SensorWidth
        if self.settings["win_resolution"][1] == 0:
            self.flircam.Width = self.flircam.SensorHeight
        self.flircam.OffsetX, self.flircam.OffsetY = self.settings["win_offset"]


    def start_cam(self):
        self.flircam.init()
        self.flircam.start()

    def stop_cam(self):
        self.flircam.stop()

    def __close__(self):
        self.flircam.close()

    def get_img(self) -> np.ndarray:
        return self.flircam.get_array()

    def get_temp(self) -> float:
        return self.flircam.DeviceTemperature

