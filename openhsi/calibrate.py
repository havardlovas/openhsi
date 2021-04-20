# AUTOGENERATED! DO NOT EDIT! File to edit: 01_calibrate.ipynb (unless otherwise specified).

__all__ = ['row_minmax', 'find_smile_shifts', 'sum_gaussians', 'fit_spectral_lines', 'HgAr_lines']

# Cell

import numpy as np
import matplotlib.pyplot as plt
import pickle
from PIL import Image
from fastcore.foundation import patch
import json


# Cell
from scipy.signal import find_peaks, savgol_filter
from scipy.optimize import curve_fit
from scipy import interpolate


# Cell

def row_minmax(img:np.ndarray,show:bool=False)->tuple:
    col_summed = np.sum(img,axis=1)
    edges = np.abs(np.gradient(col_summed))
    locs = find_peaks(edges, height=5000, width=1.5, prominence=0.01)[0]
    if show:
        plt.plot(col_summed)
        plt.plot([locs[0],locs[0]],[0,np.max(col_summed)],'r',alpha=0.5,label=f"{locs[0]}")
        plt.plot([locs[-1],locs[-1]],[0,np.max(col_summed)],'r',alpha=0.5,label=f"{locs[-1]}")
        plt.xlabel("row index")
        plt.legend()
    return (int(locs[0]),int(locs[-1]))

# Cell

def find_smile_shifts(img:np.ndarray):
    sz = np.shape(img)
    window = np.int32(np.flip(img[202,:].copy()))

    shifts = np.zeros((sz[0],),dtype=np.int16)

    for i in range(sz[0]):
        pattern_match = np.convolve(img[i,:],window,"same")
        shifts[i] = np.argmax(pattern_match)

    shifts -= sz[1]//2
    shifts -= np.min(shifts) # make all entries positive
    return shifts



# Cell

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

def fit_spectral_lines(spectra:np.array,spectral_lines:list,show=True):
    """finds the index to wavelength map given a spectra and a list of emission lines."""

    mu, props = find_peaks(spectra, height = 150, width = 1.5, prominence = 0.01)
    A = props["peak_heights"] # amplitude
    σ = 0.5 * props["widths"] # standard deviation
    c = 0.02                  # constant
    params0 = [*A,*mu,*σ,c]   # flatten to 1D array

    # refine the estimates from find_peaks by curve fitting Gaussians
    coeffs, _ = curve_fit(sum_gaussians, np.arange(len(spectra)), spectra, p0=params0)

    split = len(params0)//3
    A = coeffs[:split]
    μ = coeffs[split:2*split]
    σ = coeffs[2*split:-1]

    # find the array index for the top amplitude emissions lines
    top_A_idx = np.flip(np.argsort(A))[:len(spectral_lines)]
    sorted_idx = np.sort(μ[top_A_idx])

    # calculate the wavelength corresponding to each array index (should be straight)
    poly_func = np.poly1d( np.polyfit(sorted_idx, spectral_lines, 1) )
    wavelengths = poly_func(np.arange(len(spectra)))

    if show:
        plt.plot(wavelengths,spectra)
        plt.xlabel("wavelength (nm)")
        for i in np.uint16(np.round(sorted_idx)):
            plt.plot([wavelengths[i],wavelengths[i]],[0,np.max(spectra)],'r',alpha=0.5)
        plt.show()

    return wavelengths

# Cell

# top amplitude emission lines sorted in ascending order. You can use fewer entries if you'd like.
HgAr_lines = np.array([404.656,435.833,546.074,576.960,579.066,696.543,738.393,
                           750.387,763.511,772.376,794.818,800.616,811.531])
