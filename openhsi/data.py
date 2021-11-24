# AUTOGENERATED! DO NOT EDIT! File to edit: 00_data.ipynb (unless otherwise specified).

__all__ = ['Array', 'Shape', 'CircArrayBuffer', 'CameraProperties', 'DateTimeBuffer', 'DataCube']

# Cell
#hide

from fastcore.foundation import patch
from fastcore.meta import delegates
from fastcore.basics import listify
from fastcore.xtras import *
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from scipy.interpolate import interp1d
from PIL import Image
from scipy.signal import decimate
import holoviews as hv
hv.extension('bokeh',logo=False)

from typing import Iterable, Union, Callable, List, TypeVar, Generic, Tuple, Optional
import json
import pickle
from datetime import datetime, timezone, timedelta
from pathlib import Path
import warnings
import pprint

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

class CircArrayBuffer():
    """Circular FIFO Buffer implementation on ndarrays. Each put/get is a (n-1)darray."""

    def __init__(self, size:tuple = (100,100), axis:int = 0, dtype:type = np.int32, show_func:Callable[[np.ndarray],None] = None):
        """Preallocate a array of `size` and type `dtype` and init write/read pointer."""
        self.data = np.zeros(size, dtype=dtype)
        self.size = size
        self.axis = axis
        self.write_pos = [slice(None,None,None) if i != axis else 0 for i in range(len(size)) ]
        self.read_pos  = self.write_pos.copy()
        self.slots_left = self.size[self.axis]
        self.show_func = show_func

    def __getitem__(self, key:slice):
        return self.data[key]

    def _inc(self, idx:List[slice]) -> List[slice]:
        """Increment read/write index with wrap around"""
        idx[self.axis] += 1
        if idx[self.axis] == self.size[self.axis]:
            idx[self.axis] = 0
        return idx

    def is_empty(self) -> bool:
        return self.slots_left == self.size[self.axis]

    def put(self, line:np.ndarray):
        """Writes a (n-1)darray into the buffer"""
        self.data[tuple(self.write_pos)] = line

        # if buffer full, update read position to keep track of oldest slot
        self.slots_left -= 1
        if self.slots_left < 0:
            self.slots_left = 0
            self.read_pos = self._inc(self.read_pos)

        self.write_pos = self._inc(self.write_pos)

    def get(self) -> np.ndarray:
        """Reads the oldest (n-1)darray from the buffer"""
        if self.slots_left < self.size[self.axis]:
            val = self.data[tuple(self.read_pos)]
            self.slots_left += 1
            self.read_pos = self._inc(self.read_pos)
            return val
        else:
            return None

    def show(self):
        """Display the data """
        if self.show_func is None:
            if len(self.size) == 2:
                return hv.Image(self.data.copy(), bounds=(0,0,*self.size)).opts(
                    xlabel="wavelength index",ylabel="cross-track",cmap="gray")
            elif len(self.size) == 3:
                # Sum over the last dimensions (assumed wavelength) and show as monochrome
                return hv.Image(np.sum(self.data,axis=-1), bounds=(0,0,*self.size[:2])).opts(
                    xlabel="along-track",ylabel="cross-track",cmap="gray")
            elif len(self.size) == 1:
                print(f"#({self.size[0]}) {self.data}")
        elif self.show_func is not None:
            return self.show_func(self.data)
        else:
            print("Unsupported array shape. Please use 2D or 3D shapes or use your own custom show function")


# Cell

class CameraProperties():
    """Save and load OpenHSI camera settings and calibration"""
    def __init__(self, json_path:str = "assets/cam_settings.json", pkl_path:str = "assets/cam_calibration.pkl", print_settings=False, **kwargs):
        """Load the settings and calibration files"""
        self.json_path = json_path
        self.pkl_path = pkl_path

        if json_path:
            with open(self.json_path) as json_file:
                self.settings = json.load(json_file)
        else:
            self.settings = {}

        if pkl_path:
            with open(self.pkl_path,'rb') as handle:
                self.calibration = pickle.load(handle)
        else:
            self.calibration = {}

        # overide any settings from settings file with keywords value pairs.
        for key,value in kwargs.items():
            if key in self.settings.keys():
                self.settings[key] = value
                if print_settings:
                    print("Setting File Override: {0} = {1}".format(key, value))
        if print_settings:
            pprint.pprint(self.settings)
        #self.wavelengths = np.arange(*self.settings["index2wavelength_range"])

    def __repr__(self):
        return "settings = \n" + self.settings.__repr__() + \
               "\n\ncalibration = \n" + self.calibration.__repr__()

    def dump(self, json_path:str = None, pkl_path:str = None):
        """Save the settings and calibration files"""
        with open(self.json_path[:-5]+"_updated.json" if json_path is None else json_path, 'w') as outfile:
            json.dump(self.settings, outfile,indent=4,)
        with open(self.pkl_path[:-4]+"_updated.pkl" if pkl_path is None else pkl_path,'wb') as handle:
            pickle.dump(self.calibration,handle,protocol=4)


# Cell

@patch
def tfm_setup(self:CameraProperties, more_setup:Callable[[CameraProperties],None] = None, dtype:Union[np.int32,np.float32] = np.int32):
    """Setup for transforms"""
    # for fast smile correction
    self.smiled_size = (np.ptp(self.settings["row_slice"]), self.settings["resolution"][1] - np.max(self.calibration["smile_shifts"]) )
    self.line_buff = CircArrayBuffer(self.smiled_size, axis=0, dtype=dtype)

    # for collapsing spectral pixels into bands
    self.byte_sz = dtype(0).nbytes
    self.width = np.uint16(self.settings["fwhm_nm"]*self.settings["resolution"][1]/np.ptp(self.calibration["wavelengths_linear"]))
    self.bin_rows = np.ptp(self.settings["row_slice"])
    self.bin_cols = self.settings["resolution"][1] - np.max(self.calibration["smile_shifts"])
    self.reduced_shape = (self.bin_rows,self.bin_cols//self.width,self.width)

    # update the wavelengths for fast binning
    self.binned_wavelengths = self.calibration["wavelengths_linear"].astype(np.float32)
    self.binned_wavelengths = np.lib.stride_tricks.as_strided(self.binned_wavelengths,
                                        strides=(self.width*4,4), # assumed np.float32
                                        shape=(len(self.binned_wavelengths)//self.width,self.width))
    self.binned_wavelengths = np.around(self.binned_wavelengths.mean(axis=1),decimals=1)

    # update the wavelengths for slow binning
    n_bands = int(np.ptp(self.calibration["wavelengths"])//self.settings["fwhm_nm"])
    # jump by `fwhm_nm` and find closest array index, then let the wavelengths be in the middle between jumps
    self.λs = np.around(np.array([np.min(self.calibration["wavelengths"]) + i*self.settings["fwhm_nm"] for i in range(n_bands+1)]),decimals=1)
    self.bin_idxs = [np.argmin(np.abs(self.calibration["wavelengths"]-λ)) for λ in self.λs]
    self.λs += self.settings["fwhm_nm"]//2 #
    self.bin_buff = CircArrayBuffer((np.ptp(self.settings["row_slice"]),n_bands), axis=1, dtype=dtype)

    # precompute some reference data for converting digital number to radiance
    self.nearest_exposure = self.calibration["rad_ref"].sel(exposure=self.settings["exposure_ms"],method="nearest").exposure
    #
    self.dark_current = np.array( self.settings["exposure_ms"]/self.nearest_exposure * \
                        self.calibration["rad_ref"].sel(exposure=self.nearest_exposure,luminance=0).isel(luminance=0) )
    self.ref_luminance = np.array( self.settings["exposure_ms"]/self.nearest_exposure * \
                         self.calibration["rad_ref"].sel(exposure=self.nearest_exposure,luminance=self.settings["luminance"]) - \
                         self.dark_current )
    self.spec_rad_ref = np.float32(self.calibration["sfit"](self.calibration["wavelengths"]))

    # prep for converting radiance to reflectance
    self.rad_6SV = np.float32(self.calibration["rad_fit"](self.calibration["wavelengths"]))

    if more_setup is not None:
        more_setup(self)


# Cell

@patch
def crop(self:CameraProperties, x:np.ndarray) -> np.ndarray:
    """Crops to illuminated area"""
    return x[self.settings["row_slice"][0]:self.settings["row_slice"][1],:]

@patch
def fast_smile(self:CameraProperties, x:np.ndarray) -> np.ndarray:
    """Apply the fast smile correction procedure"""
    for i in range(self.smiled_size[0]):
            self.line_buff.put(x[i,self.calibration["smile_shifts"][i]:self.calibration["smile_shifts"][i]+self.smiled_size[1]])
    return self.line_buff.data





# Cell

@patch
def fast_bin(self:CameraProperties, x:np.ndarray) -> np.ndarray:
    """Changes the view of the datacube so that everything that needs to be binned is in the last axis. The last axis is then binned."""
    buff = np.lib.stride_tricks.as_strided(x, shape=self.reduced_shape,
                        strides=(self.bin_cols*self.byte_sz,self.width*self.byte_sz,self.byte_sz))
    return buff.sum(axis=-1)

@patch
def slow_bin(self:CameraProperties, x:np.ndarray) -> np.ndarray:
    """Bins spectral bands accounting for the slight nonlinearity in the index-wavelength map"""
    for i in range(len(self.bin_idxs)-1):
        self.bin_buff.put( x[:,self.bin_idxs[i]:self.bin_idxs[i+1]].sum(axis=1) )
    return self.bin_buff.data

# Cell

@patch
def dn2rad(self:CameraProperties, x:Array['λ,x',np.int32]) -> Array['λ,x',np.float32]:
    """Converts digital numbers to radiance (uW/cm^2/sr/nm). Use after cropping to useable area."""

    # If wavelength dimension shapes do not match, do some hacks
    if x.shape[1] < self.spec_rad_ref.shape[0]:   # use wavelengths after binning to match input
        self.spec_rad_ref = np.float64(self.calibration["sfit"]( self.binned_wavelengths ))
    elif x.shape[1] > self.spec_rad_ref.shape[0]: # upsize wavelength range to match input
        self.spec_rad_ref = np.float64(self.calibration["sfit"]( np.resize(self.calibration["wavelengths"],x.shape[1]) ))
    if x.shape[1] > self.dark_current.shape[1]:   # upsizing rad cal variables to match input
        mult = self.ref_luminance.size/x.size
        self.ref_luminance = np.resize(self.ref_luminance,x.shape)*mult
        self.dark_current  = np.resize(self.dark_current ,x.shape)*mult
    elif x.shape[1] < self.dark_current.shape[1]: # binning radiance cal variables to match input
        # the following two commented lines will crash the kernel using the radiance variables I have
        #self.ref_luminance = self.fast_bin(self.ref_luminance)
        #self.dark_current  = self.fast_bin(self.dark_current)
        mult = self.ref_luminance.size/x.size
        self.ref_luminance = np.resize(decimate(self.ref_luminance,self.ref_luminance.shape[1]//x.shape[1]),x.shape)*mult
        self.dark_current = np.resize(decimate(self.dark_current,self.dark_current.shape[1]//x.shape[1]),x.shape)*mult

    # convert to luminance, then convert to radiance
    return (x - self.dark_current)*self.settings["luminance"]/self.ref_luminance    *    self.spec_rad_ref/53_880

@patch
def rad2ref_6SV(self:CameraProperties, x:Array['λ,x',np.float32]) -> Array['λ,x',np.float32]:
    """"""
    # If wavelength dimension shapes do not match, do some hacks
    if x.shape[1] < self.rad_6SV.shape[0]:   # use wavelengths after binning to match input
        self.rad_6SV = np.float32(self.calibration["rad_fit"](self.binned_wavelengths))
    elif x.shape[1] < self.rad_6SV.shape[0]: # upsize wavelength range to match input
        self.rad_6SV = np.float64(self.calibration["rad_fit"]( np.resize(self.calibration["wavelengths"],x.shape[1]) ))

    return x/self.rad_6SV

# Cell

@patch
def set_processing_lvl(self:CameraProperties, lvl:int = 2, custom_tfms:List[Callable[[np.ndarray],np.ndarray]] = None):
    """Define the output `lvl` of the transform pipeline.
    0 : raw digital numbers cropped to useable sensor area
    1 : case 0 + fast smile correction
    2 : case 1 + fast binning (default)
    3 : case 1 + slow binning
    4 : case 2 + conversion to radiance in units of uW/cm^2/sr/nm
    5 : case 4 except radiance conversion moved to 2nd step
    6 : case 4 + conversion to reflectance
    7 : smile corrected and binned -> radiance
    8 : case 7 + converted to reflectance
    """
    if   lvl == 0:
        self.tfm_list = [self.crop]
    elif lvl == 1:
        self.tfm_list = [self.crop,self.fast_smile]
    elif lvl == 2:
        self.tfm_list = [self.crop,self.fast_smile,self.fast_bin]
    elif lvl == 3:
        self.tfm_list = [self.crop,self.fast_smile,self.slow_bin]
    elif lvl == 4:
        self.tfm_list = [self.crop,self.fast_smile,self.fast_bin,self.dn2rad]
    elif lvl == 5:
        self.tfm_list = [self.crop,self.dn2rad,self.fast_smile,self.fast_bin]
    elif lvl == 6:
        self.tfm_list = [self.crop,self.fast_smile,self.fast_bin,self.dn2rad,self.rad2ref_6SV]
    elif lvl == 7:
        self.tfm_list = [self.dn2rad]
    elif lvl == 8:
        self.tfm_list = [self.dn2rad,self.rad2ref_6SV]
    else:
        self.tfm_list = []

    if custom_tfms is not None:
        self.tfm_list = listify(custom_tfms)

    self.dtype_in = np.float32 if lvl in (4,) else np.int32 # we need floats if we convert to radiance from the beginning
    self.dtype_out = np.float32 if lvl in (3,4,5,6,7,) else np.int32
    if len(self.tfm_list) > 0:
        self.tfm_setup(dtype=self.dtype_in)
        self.dc_shape = self.pipeline(self.calibration["flat_field_pic"]).shape
    else:
        self.dc_shape = tuple(self.settings["resolution"])

# Cell

@patch
def pipeline(self:CameraProperties, x:np.ndarray) -> np.ndarray:
    """Compose a list of transforms and apply to x."""
    for f in self.tfm_list:
        x = f(x)
    return x


# Cell

class DateTimeBuffer():
    """Records timestamps in UTC time."""
    def __init__(self, n:int = 16):
        """Initialise a nx1 array and write index"""
        self.data = np.arange(datetime.now(), datetime.now() + timedelta(seconds=n-1), timedelta(seconds=1)).astype(datetime)
        self.n = n
        self.write_pos = 0

    def __getitem__(self, key:slice) -> datetime:
        return self.data[key]

    def update(self):
        """Stores current UTC time in an internal buffer when this method is called."""
        ts = datetime.timestamp(datetime.now())
        self.data[self.write_pos] = datetime.fromtimestamp(ts, tz=timezone.utc)
        self.write_pos += 1

        # Loop back if buffer is full
        if self.write_pos == self.n:
            self.write_pos = 0

# Cell

@delegates()
class DataCube(CameraProperties):
    """docstring."""

    def __init__(self, n_lines:int = 16, processing_lvl:int = 2, **kwargs):
        """docstring"""
        self.n_lines = n_lines
        self.proc_lvl = processing_lvl
        super().__init__(**kwargs)
        self.set_processing_lvl(processing_lvl)

        self.timestamps = DateTimeBuffer(n_lines)
        self.dc_shape = (self.dc_shape[0],self.n_lines,self.dc_shape[1])
        self.dc = CircArrayBuffer(size=self.dc_shape, axis=1, dtype=self.dtype_out)

    def __repr__(self):
        return f"DataCube: shape = {self.dc_shape}, Processing level = {self.proc_lvl}\n"

    def put(self, x:np.ndarray):
        """Applies the composed tranforms and writes the 2D array into the data cube. Stores a timestamp for each push."""
        self.timestamps.update()
        self.dc.put( self.pipeline(x) )





# Cell

@patch
def save(self:DataCube, save_dir:str, preconfig_meta_path:str=None, prefix:str="", suffix:str=""):
    """Saves to a NetCDF file (and RGB representation) to directory dir_path in folder given by date with file name given by UTC time."""
    if preconfig_meta_path is not None:
        with open(preconfig_meta_path) as json_file:
            attrs = json.load(json_file)
    else: attrs = {}

    self.directory = Path(f"{save_dir}/{self.timestamps[0].strftime('%Y_%m_%d')}/").mkdir(parents=False, exist_ok=True)
    self.directory = f"{save_dir}/{self.timestamps[0].strftime('%Y_%m_%d')}"

    wavelengths = self.binned_wavelengths if self.proc_lvl != 3 else self.λs

    if getattr(self,"cam_temperatures",None):
        self.coords = dict(x=(["x"],np.arange(self.dc.data.shape[0])),
                           y=(["y"],np.arange(self.dc.data.shape[1])),
                           wavelength=(["wavelength"],wavelengths),
                           time=(["time"],self.timestamps.data.astype(np.datetime64)),
                           temperature=(["temperature"],self.cam_temperatures.data))
    else:
        self.coords = dict(x=(["x"],np.arange(self.dc.data.shape[0])),
                           y=(["y"],np.arange(self.dc.data.shape[1])),
                           wavelength=(["wavelength"],wavelengths),
                           time=(["time"],self.timestamps.data.astype(np.datetime64)))

    # time coordinates can only be saved in np.datetime64 format
    self.nc = xr.Dataset(data_vars=dict(datacube=(["x","y","wavelength"],self.dc.data)),
                         coords=self.coords, attrs=attrs)

    """provide metadata to NetCDF coordinates"""
    self.nc.x.attrs["long_name"]   = "cross-track"
    self.nc.x.attrs["units"]       = "pixels"
    self.nc.x.attrs["description"] = "cross-track spatial coordinates"
    self.nc.y.attrs["long_name"]   = "along-track"
    self.nc.y.attrs["units"]       = "pixels"
    self.nc.y.attrs["description"] = "along-track spatial coordinates"
    self.nc.time.attrs["long_name"]   = "along-track"
    self.nc.time.attrs["description"] = "along-track spatial coordinates"
    self.nc.wavelength.attrs["long_name"]   = "wavelength_nm"
    self.nc.wavelength.attrs["units"]       = "nanometers"
    self.nc.wavelength.attrs["description"] = "wavelength in nanometers."
    if getattr(self,"cam_temperatures",None):
        self.nc.temperature.attrs["long_name"] = "camera temperature"
        self.nc.temperature.attrs["units"] = "degrees Celsius"
        self.nc.temperature.attrs["description"] = "temperature of sensor at time of image capture"

    self.nc.datacube.attrs["long_name"]   = "hyperspectral datacube"
    self.nc.datacube.attrs["units"]       = "uW/cm^2/sr/nm" if self.proc_lvl in (3,4,6) else "digital number"
    self.nc.datacube.attrs["description"] = "hyperspectral datacube"

    self.nc.to_netcdf(f"{self.directory}/{prefix}{self.timestamps[0].strftime('%Y_%m_%d-%H_%M_%S')}{suffix}.nc")
    hv.save(self.show("matplotlib",robust=True),f"{self.directory}/{prefix}{self.timestamps[0].strftime('%Y_%m_%d-%H_%M_%S')}{suffix}.png")


# Cell

@patch
def load_nc(self:DataCube, nc_path:str):
    """Lazy load a NetCDF datacube into the DataCube buffer."""
    with xr.open_dataset(nc_path) as ds:
        self.dc = CircArrayBuffer(size=ds.datacube.shape, axis=1, dtype=type(np.array(ds.datacube[0,0])[0]))
        self.dc.data = np.array(ds.datacube)
        self.binned_wavelengths = np.array(ds.wavelength)

# Cell

@patch
def show(self:DataCube, plot_lib:str = "bokeh",
         red_nm:float = 640., green_nm:float = 550., blue_nm:float = 470.,
         robust:bool = False, hist_eq:bool = False) -> "bokeh or matplotlib plot":
    """Generate a histogram equalised RGB plot from chosen RGB wavelengths.
    The plotting backend can be specified by plot_lib and can be "bokeh" or "matplotlib". """
    hv.extension(plot_lib,logo=False)

    rgb = np.zeros( (*self.dc.data.shape[:2],3), dtype=np.float32)
    rgb[...,0] = self.dc.data[:,:,np.argmin(np.abs(self.binned_wavelengths-red_nm))]
    rgb[...,1] = self.dc.data[:,:,np.argmin(np.abs(self.binned_wavelengths-green_nm))]
    rgb[...,2] = self.dc.data[:,:,np.argmin(np.abs(self.binned_wavelengths-blue_nm))]

    if robust and not hist_eq: # scale everything to the 2% and 98% percentile
        vmax = np.nanpercentile(rgb, 98)
        vmin = np.nanpercentile(rgb, 2)
        rgb = ((rgb.astype("f8") - vmin) / (vmax - vmin)).astype("f4")
        rgb = np.minimum(np.maximum(rgb, 0), 1)
    elif hist_eq and not robust:
        img_hist, bins = np.histogram(rgb.flatten(), 256, density=True)
        cdf = img_hist.cumsum() # cumulative distribution function
        cdf = 1. * cdf / cdf[-1] # normalize
        img_eq = np.interp(rgb.flatten(), bins[:-1], cdf) # find new pixel values from linear interpolation of cdf
        rgb = img_eq.reshape(rgb.shape)
    elif robust and hist_eq:
        warnings.warn("Cannot mix robust with histogram equalisation. No RGB adjustments will be made.",stacklevel=2)
        rgb /= np.max(rgb)
    else:
        rgb /= np.max(rgb)

    rgb_hv = hv.RGB((np.arange(rgb.shape[1]),np.arange(rgb.shape[0]),
                     rgb[:,:,0],rgb[:,:,1],rgb[:,:,2])).opts(width=1000,height=250,
                     xlabel="along-track",ylabel="cross-track",invert_yaxis=True)

    if plot_lib == "bokeh":
        return rgb_hv.opts(frame_height=int(rgb.shape[0]//3))
    else: # plot_lib == "matplotlib"
        return rgb_hv.opts(fig_inches=22)
