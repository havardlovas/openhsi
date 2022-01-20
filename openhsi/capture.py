# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/01_capture.ipynb (unless otherwise specified).

__all__ = ['Array', 'Shape', 'OpenHSI', 'SimulatedCamera', 'ProcessRawDatacube']

# Cell
#hide_output

from fastcore.foundation import patch
from fastcore.meta import delegates
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from scipy.interpolate import interp1d
from PIL import Image
from tqdm import tqdm
import warnings

from typing import Iterable, Union, Callable, List, TypeVar, Generic, Tuple, Optional
import json
import pickle

# Cell
from .data import *

# Cell
#hide

# numpy.ndarray type hints
Shape = TypeVar("Shape"); DType = TypeVar("DType")
class Array(np.ndarray, Generic[Shape, DType]):
    """
    Use this to type-annotate numpy arrays, e.g.
        image: Array['H,W,3', np.uint8]
        xy_points: Array['N,2', float]
        nd_mask: Array['...', bool]
    from: https://stackoverflow.com/questions/35673895/type-hinting-annotation-pep-484-for-numpy-ndarray
    """
    pass

# Cell

@delegates()
class OpenHSI(DataCube):
    """Base Class for the OpenHSI Camera."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        super().set_processing_lvl(self.proc_lvl)
        if callable(getattr(self,"get_temp",None)):
            self.cam_temperatures = CircArrayBuffer(size=(self.n_lines,),dtype=np.float32)

    def __enter__(self):
        return self

    def __close__(self):
        self.stop_cam()

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop_cam()

    def collect(self):
        """Collect the hyperspectral datacube."""
        self.start_cam()
        for i in tqdm(range(self.n_lines)):
            self.put(self.get_img())

            if callable(getattr(self,"get_temp",None)):
                self.cam_temperatures.put( self.get_temp() )
        self.stop_cam()

    def avgNimgs(self, n) -> np.ndarray:
        """Take `n` images and find the average"""
        data = np.zeros(tuple(self.settings['resolution'])+(n,),np.int32)

        self.start_cam()
        for f in range(n):
            data[:,:,f]=self.get_img()
        self.stop_cam()
        return np.mean(data,axis=2)


# Cell

@delegates()
class SimulatedCamera(OpenHSI):
    """Simulated camera using an RGB image as an input. Hyperspectral data is produced using CIE XYZ matching functions."""
    def __init__(self, img_path:str = None, **kwargs):
        """Initialise Simulated Camera"""
        super().__init__(**kwargs)

        if img_path is None:
            self.img = np.random.randint(0,255,(*self.settings["resolution"],3))
        else:
            with Image.open(img_path) as img:
                img = img.resize((np.shape(img)[1],self.settings["resolution"][0]))
                self.img = np.array(img)[...,:3]

        self.rgb_buff = CircArrayBuffer(self.img.shape,axis=1,dtype=np.uint8)
        self.rgb_buff.data = self.img
        self.rgb_buff.slots_left = 0 # make buffer full

        # Precompute the CIE XYZ matching functions to convert RGB values to a pseudo-spectra
        def piecewise_Guass(x,A,μ,σ1,σ2):
            t = (x-μ) / ( σ1 if x < μ else σ2 )
            return A * np.exp( -(t**2)/2 )
        def wavelength2xyz(λ):
            """λ is in nanometers"""
            λ *= 10 # convert to angstroms for the below formulas
            x̅ = piecewise_Guass(λ,  1.056, 5998, 379, 310) + \
                piecewise_Guass(λ,  0.362, 4420, 160, 267) + \
                piecewise_Guass(λ, -0.065, 5011, 204, 262)
            y̅ = piecewise_Guass(λ,  0.821, 5688, 469, 405) + \
                piecewise_Guass(λ,  0.286, 5309, 163, 311)
            z̅ = piecewise_Guass(λ,  1.217, 4370, 118, 360) + \
                piecewise_Guass(λ,  0.681, 4590, 260, 138)
            return np.array([x̅,y̅,z̅])
        self.λs = np.poly1d( np.polyfit(np.arange(len(self.calibration["wavelengths"])),self.calibration["wavelengths"] ,3) )(
                            np.arange(self.settings["resolution"][1]))
        self.xs = np.zeros( (1,len(self.λs)),dtype=np.float32)
        self.ys = self.xs.copy(); self.zs = self.xs.copy()
        for i in range(len(self.xs[0])):
            self.xs[0,i], self.ys[0,i], self.zs[0,i] = wavelength2xyz(self.λs[i])

        self.xyz_buff = CircArrayBuffer(self.settings["resolution"],axis=0,dtype=np.int32)

    def rgb2xyz_matching_funcs(self, rgb:np.ndarray) -> np.ndarray:
        """convert an RGB value to a pseudo-spectra with the CIE XYZ matching functions."""
        for i in range(rgb.shape[0]):
            self.xyz_buff.put( rgb[i,0]*self.xs + rgb[i,1]*self.ys + rgb[i,2]*self.zs )
        return self.xyz_buff.data

    def start_cam(self):
        pass

    def stop_cam(self):
        pass

    def get_img(self) -> np.ndarray:
        if self.rgb_buff.is_empty():
            self.rgb_buff.slots_left = 0 # make buffer full again
        return self.rgb2xyz_matching_funcs(self.rgb_buff.get())

    def set_exposure(self):
        pass

    def get_temp(self):
        return 20.


# Cell


class ProcessRawDatacube(OpenHSI):
    """Post-process datacubes"""
    def __init__(self, fname:str, processing_lvl:int, json_path:str, pkl_path:str, old_style:bool=False):
        """Post-process datacubes"""
        self.fname = fname
        self.buff = DataCube()
        self.buff.load_nc(fname, old_style=old_style)
        super().__init__(n_lines=self.buff.dc.data.shape[1], processing_lvl=processing_lvl, json_path=json_path, pkl_path=pkl_path)

    def start_cam(self):
        pass

    def stop_cam(self):
        pass

    def get_img(self) -> np.ndarray:
        return self.buff.dc.get()

    def set_exposure(self):
        pass

