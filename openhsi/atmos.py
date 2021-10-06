# AUTOGENERATED! DO NOT EDIT! File to edit: 03_atmos.ipynb (unless otherwise specified).

__all__ = ['Model6SV']

# Cell

from fastcore.foundation import patch
from fastcore.meta import delegates
from fastcore.basics import num_cpus
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime
import os
import copy
from tqdm import tqdm

import param
import panel as pn
pn.extension()

import holoviews as hv
hv.extension('bokeh')

from Py6S import *


# Cell

from .data import *


# Cell

class Model6SV():

    def __init__(self, lat:"degrees" = -17.7, lon:"degrees" = 146.1, # Queensland
                 z_time:"zulu" = datetime.strptime("2021-05-26 03:26","%Y-%m-%d %H:%M"),
                 station_num:int = 94299, region:str = "pac",
                 alt:"km" = 0.12, zen:"degrees" = 0., azi:"degrees" = 0.,
                 tile_type:GroundReflectance = 1.0,
                 aero_profile:AeroProfile = AeroProfile.Maritime,
                 λ_array:"array [μm]" = np.arange(0.4, .8, 0.004),
                 sixs_path="assets/6SV1.1/sixsV1.1"):

        self.λ_array = λ_array

        s = SixS(sixs_path)

        #Atmosphere
        s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeSummer)

        # crude calculation if daytime is 12Z or 0Z based on time and longitude
        z_hour = 0 if ((z_time.hour + int(lon/30))%24 - 12)/12. < 0.5 else 12
        radiosonde_url = f"http://weather.uwyo.edu/cgi-bin/sounding?region={region}&TYPE=TEXT%3ALIST&YEAR={z_time.year}&MONTH={z_time.month:02d}&FROM={z_time.day:02d}{z_hour:02d}{z_time.minute:02d}&TO={z_time.day:02d}{z_hour:02d}&STNM={station_num}"
        #print(radiosonde_url)
        s.atmos_profile = SixSHelpers.Radiosonde.import_uow_radiosonde_data(radiosonde_url,AtmosProfile.MidlatitudeSummer)

        # website at http://weather.uwyo.edu/cgi-bin/sounding?region=pac&TYPE=TEXT%3ALIST&YEAR=2021&MONTH=05&FROM=1212&TO=1212&STNM=94299

        # this can be custom?
        s.aero_profile = AeroProfile.PredefinedType(aero_profile)
        #s = SixSHelpers.Aeronet.import_aeronet_data_fixed(SixSHelpers.Aeronet,s,"assets/20190101_20211231_Lucinda.ONEILL_lev15","26-05-2021 03:26")
        s.visibility = 40 # km

        #Viewing and sun geometry
        s.geometry = Geometry.User()
        #s.geometry.solar_z = 0; s.geometry.solar_a = 0; s.geometry.view_z = 0; s.geometry.view_a = 0
        s.geometry.day = z_time.day
        s.geometry.month = z_time.month
        s.geometry.from_time_and_location(lat, lon, f"{z_time.year}-{z_time.month:02d}-{z_time.day:02d} {z_time.hour:02d}:{z_time.minute:02d}:{z_time.second:02d}", zen, azi)

        #Altitude
        s.altitudes = Altitudes()
        s.altitudes.set_sensor_custom_altitude(alt) # km
        s.altitudes.set_target_sea_level()
        if tile_type is not None: s.ground_reflectance = GroundReflectance.HomogeneousLambertian(tile_type)

        self.s = s

        self.__call__()

    def rad2photons(self):
        self.photons = self.radiance/( 1.98644582e-25/(self.λ_array*1e-6) )

    def __call__(self) -> None:
        self.radiance = self.run_wavelengths(self.λ_array)

        df = pd.DataFrame({"wavelength":self.λ_array,"radiance":self.radiance})
        df.set_index("wavelength",inplace=True)
        df.interpolate(method="cubicspline",axis="index",limit_direction="both",inplace=True)
        self.radiance = df["radiance"].to_numpy()
        self.rad2photons()

    def show(self):
        plt.plot(self.λ_array*1000,self.radiance,label="computed radiance")
        plt.xlabel("wavelength (nm)")
        plt.ylabel("radiance (W/m$^2$/sr/$\mu$m)")
        plt.legend()
        plt.minorticks_on()


# Cell


@patch
def _sixs_run_one_wavelength(self:Model6SV, wv:float) -> float:
    """Runs one instance of 6SV for one wavelength wv"""
    self.s.outputs = None
    a = copy.deepcopy(self.s)
    a.wavelength = Wavelength(wv)
    a.run()
    return SixSHelpers.Wavelengths.recursive_getattr(a.outputs, "pixel_radiance")

@patch
def run_wavelengths(self:Model6SV, wavelengths:np.array, n_threads:int = None) -> np.array:
    """Modified version of SixSHelpers.Wavelengths.run_wavelengths that has a progress bar.
    This implementation uses threading (through Python's multiprocessing API)."""
    from multiprocessing.dummy import Pool

    if n_threads is None: n_threads = num_cpus()
    with Pool(n_threads) as p, tqdm(total=len(wavelengths)) as pbar:
        res = [p.apply_async( self._sixs_run_one_wavelength, args=(wavelengths[i],),
                callback=lambda _: pbar.update(1)) for i in range(len(wavelengths))]
        results = [r.get() for r in res]

    return np.array(results)


