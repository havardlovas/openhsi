# AUTOGENERATED! DO NOT EDIT! File to edit: 05_calibrate.ipynb (unless otherwise specified).

__all__ = ['sum_gaussians', 'HgAr_lines', 'SettingsBuilderMixin', 'SettingsBuilderMetaclass', 'create_settings_builder',
           'specta_pt_contoller']

# Cell

from fastcore.foundation import patch
from fastcore.meta import delegates
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from scipy.interpolate import interp1d
from PIL import Image
from scipy.signal import decimate, medfilt
import holoviews as hv
hv.extension('bokeh',logo=False)
from fastprogress.fastprogress import master_bar, progress_bar

from scipy.signal import find_peaks, savgol_filter
from scipy.optimize import curve_fit
from scipy import interpolate
from functools import reduce

from typing import Iterable, Union, Callable, List, TypeVar, Generic, Tuple, Optional
import datetime
import json
import pickle

# Cell

from .data import *
from .capture import *
from .cameras import *

# Cell

HgAr_lines = np.array([404.656,407.783,435.833,546.074,576.960,579.066,696.543,706.722,727.294,738.393,
                           750.387,763.511,772.376,794.818,800.616,811.531,826.452,842.465,912.297])

def sum_gaussians(x:"indices np.array",
                    *args:"amplitude, peak position, peak width, constant") -> np.array:
    split = len(args)//3
    A   = args[0:split]         # amplitude
    mu  = args[split:2*split]   # peak position
    sigma = args[split*2:-1]    # peak stdev
    c   = args[-1]              # offset
    return np.array( [A[i] * np.exp( - np.square( (x - mu[i])/sigma[i] ) )
                        for i in range(len(A))] ).sum(axis=0) + c

# Cell

class SettingsBuilderMixin():

    def retake_flat_field(self, show:bool = False):
        self.start_cam()
        self.calibration["flat_field_pic"] = self.get_img()
        self.stop_cam()

        if show:
            return hv.Image(self.calibration["flat_field_pic"], bounds=(0,0,*self.calibration["flat_field_pic"].shape)).opts(
                    xlabel="wavelength index",ylabel="cross-track",cmap="gray",title="flat field picture")

    def retake_HgAr(self, show:bool = False, numframes:int=10):

        self.calibration["HgAr_pic"] = np.mean(self.getNimgs(numframes),2)

        if show:
            return hv.Image(self.calibration["HgAr_pic"], bounds=(0,0,*self.calibration["HgAr_pic"].shape)).opts(
                    xlabel="wavelength index",ylabel="cross-track",cmap="gray",title="HgAr spectra picture")


    def update_resolution(self) -> None:
        self.settings["resolution"] = np.shape(self.calibration["flat_field_pic"])

    def update_row_minmax(self) -> "figure object":
        """"""
        col_summed = np.sum(self.calibration["flat_field_pic"],axis=1)
        edges      = np.abs(np.gradient(col_summed))
        locs       = find_peaks(edges, height=5000, width=1.5, prominence=0.01)[0]
        print("Locs row_min: {} and row_max: {}".format(locs[0],locs[1]))
        row_min  = int(locs[0]+2) # shift away from the edge a little to make sure we are in well lit region
        row_max = int(locs[-1])
        num   = len(col_summed)
        big   = np.max(col_summed)
        self.settings["row_slice"] = (row_min,row_max)

        return (hv.Curve(zip(np.arange(num),col_summed)).opts(xlabel="row index",ylabel="count",width=500) * \
                hv.Curve(zip((row_min,row_min),(0,big)),label=f"{row_min}").opts(color="r") * \
                hv.Curve(zip((row_max,row_max),(0,big)),label=f"{row_max}").opts(color="r") ).opts(
                xlim=(0,num),ylim=(0,big),legend_position='top_left')

    def update_smile_shifts(self) -> "figure object":
        """"""
        cropped = self.calibration["HgAr_pic"][slice(*self.settings["row_slice"]),:]
        rows, cols = cropped.shape

        window = np.int32(np.flip(cropped[rows//2,:].copy()))

        shifts = np.zeros((rows,),dtype=np.int16)

        for i in range(rows):
            pattern_match = np.convolve(cropped[i,:],window,"same")
            shifts[i] = np.argmax(pattern_match)

        shifts -= cols//2
        shifts -= np.min(shifts) # make all entries positive
        shifts = medfilt(shifts,5).astype(np.int16) # use some median smoothing
        self.calibration["smile_shifts"] = shifts

        return hv.Curve(zip(np.arange(rows),shifts)).opts(
                        invert_axes=True,invert_yaxis=True,xlabel="row index",ylabel="pixel shift")

    def fit_HgAr_lines(self, top_k:int = 10,
                       brightest_peaks=[435.833,546.074,763.511],
                       find_peaks_height:int = 10) -> "figure object":
        """finds the index to wavelength map given a spectra and a list of emission lines."""

        cropped      = self.calibration["HgAr_pic"][slice(*self.settings["row_slice"]),:]
        rows, cols   = cropped.shape
        spectra      = cropped[rows//2,self.calibration["smile_shifts"][rows//2]:].copy()
        _start_idx   = self.calibration["smile_shifts"][rows//2] # get smile shifted indexes
        _num_idx     = self.settings["resolution"][1]-np.max(self.calibration["smile_shifts"]) # how many pixels kept per row
        shifted_idxs = np.arange(len(spectra))[_start_idx:_start_idx+_num_idx]

        filtered_spec = savgol_filter(spectra, 9, 3)
        μ, props      = find_peaks(filtered_spec, height = find_peaks_height, width = 1.5, prominence = 0.2)
        A = props["peak_heights"] # amplitude
        σ = 0.5 * props["widths"] # standard deviation
        c = 0                    # constant
        params0 = [*A,*μ,*σ,c]   # flatten to 1D array

        # refine the estimates from find_peaks by curve fitting Gaussians
        coeffs, _ = curve_fit(sum_gaussians, np.arange(len(spectra)), spectra, p0=params0)
        split = len(params0)//3
        A = coeffs[:split]
        μ = coeffs[split:2*split]
        σ = coeffs[2*split:-1]

        # interpolate with top 3 spectral lines
        top_A_idx = np.flip(np.argsort(A))[:len(brightest_peaks)]
        first_fit = np.poly1d( np.polyfit(np.sort(μ[top_A_idx]),brightest_peaks,2) )
        predicted_λ = first_fit(μ)

        # predict wavelengths for the rest of the peaks and get the nearest indicies
        closest_λ = np.array([ HgAr_lines[np.argmin(np.abs(HgAr_lines-λ))] for λ in predicted_λ])
        top_A_idx = np.flip(np.argsort(A))[:max(min(top_k,len(HgAr_lines)),4)]
        final_fit = np.poly1d( np.polyfit(μ[top_A_idx],closest_λ[top_A_idx] ,3) )
        spec_wavelengths = final_fit(μ[top_A_idx])

        # update the calibration files
        self.calibration["wavelengths"] = final_fit(shifted_idxs)
        linear_fit = np.poly1d( np.polyfit(μ[top_A_idx],closest_λ[top_A_idx] ,1) )
        self.calibration["wavelengths_linear"] = linear_fit(shifted_idxs)

        # create plot of fitted spectral lines
        plots_list = [hv.Curve( zip(final_fit(np.arange(len(spectra))),spectra) )]
        for λ in spec_wavelengths:
            plots_list.append( hv.Curve(zip((λ,λ),(0,np.max(spectra))),).opts(color="r",alpha=0.5) )

        return reduce((lambda x, y: x * y), plots_list).opts(
                    xlim=(final_fit(0),final_fit(len(spectra))),ylim=(0,np.max(spectra)),
                    xlabel="wavelength (nm)",ylabel="digital number",width=700,height=200,toolbar="below")

    def update_intsphere_fit(self, calibrated_ref='spectra_pt_cal.txt') -> "figure object":
        wavelen  = [350,360,370,380,390,400,450,500,555,600,654.6,700,800,900,1050,1150,1200,
                            1300,1540,1600,1700,2000,2100,2300,2400,2500]
        spec_rad = [2.122e0,2.915e0,3.848e0,5.124e0,7.31e0,9.72e0,2.395e1,4.356e1,7.067e1,9.46e1,
                   1.217e2,1.426e2,1.755e2,1.907e2,1.905e2,1.785e2,1.620e2,1.541e2,1.110e2,1.022e2,
                   7.386e1,3.79e1,2.333e1,1.783e1,1.280e1,3.61e1]

        self.calibration["sfit"] = interp1d(wavelen, spec_rad, kind='cubic')

        # plot
        wavelen_arr = np.linspace(np.min(wavelen),np.max(wavelen),num=200)
        spec_rad_ref = np.float64(self.calibration["sfit"](self.calibration["wavelengths"]))

        fig, ax = plt.subplots(figsize=(12,4))
        ax.plot(wavelen,spec_rad,"r.",label="Manufacturer Calibration Points")
        ax.plot(wavelen_arr,self.calibration["sfit"](wavelen_arr),label="Spline Fit")
        ax.grid("on")
        #plt.axis([393,827,0,200])
        ax.set_xlabel("wavelength (nm)")
        ax.set_ylabel("spectral radiance ($\mu$W/cm$^2$/sr/nm)")
        ax.legend()
        ax.axvspan(np.min(self.calibration["wavelengths"]), np.max(self.calibration["wavelengths"]), alpha=0.3, color="gray")
        ax.axis([np.min(self.calibration["wavelengths"])-50,2500,0,200])
        ax.text(410, 190, "OpenHSI Wavelengths", fontsize=11)
        ax.minorticks_on()
        return fig


    def update_window_across_track(self, crop_buffer) -> "figure object":
        pass

    def update_window_along_track(self, crop_buffer) -> "figure object":
        pass

    def update_intsphere_cube(self,exposures:np.array,
                              luminances:np.array,
                              noframe:int=10,
                              lum_chg_func:Callable=print,
                              interactive:bool=False,
                              ):
        shape = (np.ptp(self.settings["row_slice"]),self.settings["resolution"][1],len(exposures),len(luminances))

        lum_buff = CircArrayBuffer(shape[:3],axis=2,dtype=np.int32)
        rad_ref  = CircArrayBuffer(shape,axis=3,dtype=np.int32)

        mb = master_bar(range(len(luminances)))
        for i in mb:
            mb.main_bar.comment = f"Luminance = {luminances[i]} Cd/m^2"
            if interactive: input(f"\rLuminance = {luminances[i]} Cd/m^2. Press enter key when ready...")

            if luminances[i] == 0:
                input(f"\rLuminance = 0 Cd/m^2. Place lens cap on and press enter to continue.")
            else:
                lum_chg_func(luminances[i])

            for j in progress_bar(range(len(exposures)), parent=mb):
                mb.child.comment = f"exposure = {exposures[j]} ms"
                self.set_exposure(exposures[j])

                lum_buff.put( self.crop(np.mean(self.getNimgs(noframe),2)) )

            rad_ref.put( lum_buff.data )
            mb.write(f"Finished collecting at luminance {luminances[i]} Cd/m^2.")
            if luminances[i] == 0:
                input(f"\rLuminance = 0 Cd/m^2. Remove lens cap and place on int sphere and press enter to continue.")

        return xr.Dataset(data_vars=dict(datacube=(["cross_track","wavelength_index","exposure","luminance"],rad_ref.data)),
                                                 coords=dict(cross_track=(["cross_track"],np.arange(shape[0])),
                                                          wavelength_index=(["wavelength_index"],np.arange(shape[1])),
                                                          exposure=(["exposure"],exposures),
                                                          luminance=(["luminance"],luminances)), attrs={}).to_array()


# Cell

class SettingsBuilderMetaclass(type):
    def __new__(cls, clsname:str, cam_class, attrs) -> "SettingsBuilder Class":
        """Create a SettingsBuilder class based on your chosen `CameraClass`."""
        return super(SettingsBuilderMetaclass, cls).__new__(cls, clsname, (cam_class,SettingsBuilderMixin), attrs)


def create_settings_builder(clsname:str, cam_class:"Camera Class") -> "SettingsBuilder Class":
    """Create a `SettingsBuilder` class called `clsname` based on your chosen `cam_class`."""
    return type(clsname, (cam_class,SettingsBuilderMixin), {})



# Cell

import socket
import collections
import time
import math

try:
    import winsound
except ImportError:
    def playAlert():
        pass
else:
    def playAlert():
        winsound.MessageBeep(type=winsound.MB_ICONHAND)

class specta_pt_contoller:
    def __init__(self,
                 lum_preset_dict={0:1, 1000:2, 2000:3, 3000:4, 4000:5, 5000:6,
                                  6000:7, 7000:8, 8000:9, 9000:10, 10000:11,
                                  20000:12, 25000:12, 30000:13, 35000:14, 40000:15},
                 host="localhost",
                 port=3434):
        self.lum_preset_dict=lum_preset_dict
        self.host=host
        self.port=port

    # address and port of the SPECTRA PT-1000 S
    def client(self, msg):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((self.host, self.port))

            data = bytes.fromhex(hex(len(msg))[2:].zfill(8)) + msg.encode()
            sock.sendall(data)
    #         print("[+] Sending {} to {}:{}".format(data, host, port))

            response1 = sock.recv(4096)
            response2 = sock.recv(4096)

    #         print("[+] Received", repr(response2.decode('utf-8')))

            return response2.split(b';')[2]

    def selectPreset(self, lumtarget):
        self.client("main:1:pre {}".format(self.lum_preset_dict[lumtarget]))
        time.sleep(2)
        lum=collections.deque(maxlen=100)

        for i in range(100):
            lum.append(float(self.client("det:1:sca?")))
            time.sleep(0.01)

        while np.abs((np.mean(lum)-lumtarget)) > lumtarget*0.0025:
            lum.append(float(self.client("det:1:sca?")))
            time.sleep(0.1)

        playAlert()

        return np.abs((np.mean(lum)-lumtarget))

    def turnOnLamp(self):
        response=self.client("ps:1:out 1")

    def turnOffLamp(self):
        response=self.client("ps:1:out 0")