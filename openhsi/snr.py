# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/04_snr.ipynb (unless otherwise specified).

__all__ = ['Widget_SNR']

# Cell
#hide_output

import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime
import os
from fastcore.meta import delegates

import param
import panel as pn
pn.extension()

import holoviews as hv
hv.extension('bokeh',logo=False)

from Py6S import *


# Cell

from .data import *
from .atmos import *

# Cell

@delegates()
class Widget_SNR(param.Parameterized):
    """OpenHSI SNR calculator"""
    aperture_mm         = param.Number(4, bounds=(1,200),doc="aperture (mm)")
    focal_length_mm     = param.Number(16,doc="focal length (mm)")
    pixel_length_x_μm   = param.Number(65, bounds=(1,80),doc="pixel length x (μm)")
    pixel_length_y_μm   = param.Number(6.9, bounds=(1,60),doc="pixel length y (μm)")
    integration_time_ms = param.Number(10, bounds=(5,100), step=1,doc="integration time (ms)")
    bandwidth_nm        = param.Number(4, bounds=(0.1,20), step=0.1,doc="FWHM bandwidth (nm)")
    QE_model            = param.ObjectSelector(default="imx252qe", doc="Camera QE model", objects =
                                [f.split(".")[0] for f in os.listdir("assets") if ".csv" in f and "qe" in f])
    surface_albedo      = param.Number(0.3, bounds=(0,1.0),doc="constant surface albedo reflectance")
    optical_trans_efficiency = param.Number(0.9, bounds=(0.1,1), step=0.05,doc="Optical transmission efficiency")
    DE_model            = param.ObjectSelector(default="600lpmm_28.7", doc="Grating efficiency model", objects =
                                 [f.split("_grating")[0] for f in os.listdir("assets") if ".csv" in f and "lpmm" in f])

    def __init__(self, ref_model:Model6SV, **kwargs):
        """Initialise widget"""
        super().__init__(**kwargs)

        self.photons     = ref_model.photons
        self.wavelengths = ref_model.wavelength_array

    @param.depends("aperture_mm","focal_length_mm","pixel_length_x_μm","pixel_length_y_μm",
                   "integration_time_ms","bandwidth_nm","QE_model","optical_trans_efficiency","surface_albedo")#,"solar_zenith_deg")
    def view(self):

        self.f_num = self.focal_length_mm / self.aperture_mm
        self.A_d = self.pixel_length_x_μm*1e-6 * self.pixel_length_y_μm*1e-6

        # interpolation to OpenHSI wavelengths and remove NaNs
        self.QE = pd.read_csv(f"assets/{self.QE_model}.csv",names=["wavelength","QE_pct"], header=None)
        self.QE["wavelength"] /= 1000
        self.QE.insert(0,"type","manufacturer")
        self.QE = pd.concat( [ pd.DataFrame({"type":"6SV","wavelength":self.wavelengths}), self.QE] )
        self.QE.set_index("wavelength",inplace=True)
        self.QE.interpolate(method="cubicspline",axis="index",limit_direction="both",inplace=True)
        self.QE = self.QE[self.QE["type"].str.match("6SV")]
        self.QE.drop("type", 1,inplace=True)

        self.DE = pd.read_csv(f"assets/{self.DE_model}_grating.csv",names=["wavelength","DE"], header=None)
        self.DE["wavelength"] /= 1000
        self.DE.insert(0,"type","manufacturer")
        self.DE = pd.concat( [ pd.DataFrame({"type":"6SV","wavelength":self.wavelengths}), self.DE] )
        self.DE.set_index("wavelength",inplace=True)
        self.DE.interpolate(method="cubicspline",axis="index",limit_direction="both",inplace=True)
        self.DE = self.DE[self.DE["type"].str.match("6SV")]
        self.DE.drop("type", 1,inplace=True)

        self.N = self.photons * self.integration_time_ms*1e-3 * self.A_d * np.pi/(2*self.f_num)**2 * \
                    self.bandwidth_nm*1e-3 * self.QE["QE_pct"].to_numpy()/100 * self.optical_trans_efficiency * \
                    self.surface_albedo * self.DE["DE"].to_numpy()

        self.table = hv.Table((self.wavelengths*1e3, np.sqrt(self.N)), 'wavelength (nm)', 'SNR')
        return hv.Curve(self.table).opts(tools=["hover"],width=600,height=200,ylim=(0,None))
