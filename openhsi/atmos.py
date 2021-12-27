# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/03_atmos.ipynb (unless otherwise specified).

__all__ = ['Model6SV', 'SpectralMatcher', 'remap', 'ELC']

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
hv.extension('bokeh',logo=False)

from Py6S import *


# Cell

from .data import *


# Cell

class Model6SV():

    def __init__(self, lat:"degrees" = -17.7, lon:"degrees" = 146.1, # Queensland
                 z_time:"zulu datetime" = datetime.strptime("2021-05-26 04:26","%Y-%m-%d %H:%M"),
                 station_num:int = 94299, region:str = "pac",
                 alt:"km" = 0.12, zen:"degrees" = 0., azi:"degrees" = 0.,
                 tile_type:GroundReflectance = 1.0,
                 aero_profile:AeroProfile = AeroProfile.Maritime,
                 wavelength_array:"array [nm]" = np.arange(400, 800, 4),
                 sixs_path=None):

        self.wavelength_array = wavelength_array/1e3 # convert to μm for Py6S
        s = SixS(sixs_path)

        # Atmosphere
        s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeSummer)

        # crude calculation if daytime is 12Z or 0Z based on time and longitude
        z_hour = 0 if ((z_time.hour + int(lon/30))%24 - 12)/12. < 0.5 else 12
        radiosonde_url = f"http://weather.uwyo.edu/cgi-bin/sounding?region={region}&TYPE=TEXT%3ALIST&YEAR={z_time.year}&MONTH={z_time.month:02d}&FROM={z_time.day:02d}{z_hour:02d}{z_time.minute:02d}&TO={z_time.day:02d}{z_hour:02d}&STNM={station_num}"
        s.atmos_profile = SixSHelpers.Radiosonde.import_uow_radiosonde_data(radiosonde_url,AtmosProfile.MidlatitudeSummer)

        # Aerosol
        s.aero_profile = AeroProfile.PredefinedType(aero_profile)
        s.visibility = 40 # km

        #Viewing and sun geometry
        s.geometry = Geometry.User()
        s.geometry.day = z_time.day
        s.geometry.month = z_time.month
        dt_str = f"{z_time.year}-{z_time.month:02d}-{z_time.day:02d} {z_time.hour:02d}:{z_time.minute:02d}:{z_time.second:02d}"
        s.geometry.from_time_and_location(lat, lon, dt_str, zen, azi)

        #Altitude
        s.altitudes = Altitudes()
        s.altitudes.set_sensor_custom_altitude(alt) # km
        s.altitudes.set_target_sea_level()
        if tile_type is not None: s.ground_reflectance = GroundReflectance.HomogeneousLambertian(tile_type)

        self.s = s
        self.__call__()

    def rad2photons(self):
        self.photons = self.radiance/( 1.98644582e-25/(self.wavelength_array*1e-6) )

    def __call__(self) -> None:
        self.radiance = self.run_wavelengths(self.wavelength_array) # units of (W/m^2/sr/μm)

        df = pd.DataFrame({"wavelength":self.wavelength_array,"radiance":self.radiance})
        df.set_index("wavelength",inplace=True)
        df.interpolate(method="cubicspline",axis="index",limit_direction="both",inplace=True)
        self.radiance = df["radiance"].to_numpy()
        self.rad2photons()

    def show(self):
        plt.plot(self.wavelength_array,self.radiance/10,label="computed radiance")
        plt.xlabel("wavelength (nm)")
        plt.ylabel("radiance (μW/cm$^2$/sr/nm)")
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




# Cell

from numpy.linalg import norm

class SpectralMatcher(object):
    """Match OpenHSI spectra against USGS spectral library"""
    def __init__(self,speclib_path,model_6SV:Model6SV):
        self.speclib_path = speclib_path
        self.wavelengths = model_6SV.wavelength_array*1e3
        self.model_6SV = model_6SV

        if "gzip" in speclib_path: self.speclib = pd.read_parquet(speclib_path)
        else: self.speclib = pd.read_pickle(speclib_path)
        self.orig_speclib = self.speclib.copy() # For updating saved spectral library
        self._interp()
        self.topk_idx = None

    def _interp(self):
        # interpolate the spectral library to the OpenHSI wavelengths
        self.speclib = self.orig_speclib.copy()
        self.speclib.insert(0,"type","USGS")
        self.speclib = pd.concat( [ pd.DataFrame({"type":"openhsi","wavelength":self.wavelengths}), self.speclib] )
        self.speclib.set_index("wavelength",inplace=True)
        self.speclib.interpolate(method="cubicspline",axis="index",limit_direction="both",inplace=True)
        self.speclib = self.speclib[self.speclib["type"].str.match("openhsi")]
        self.speclib.drop("type", 1,inplace=True)
        self.speclib_ref = self.speclib.copy()
        self.spectra = (self.speclib[:].T*self.model_6SV.radiance/10).T
        self.spectra_norm = norm(self.spectra,axis=0)

    def topk_spectra(self,spectrum:np.array,k:int=5):
        """Match a `spectrum` against a spectral library `spectra`. Return the top k."""
        self.last_spectra = spectrum
        cosine_dist = spectrum @ self.spectra / ( norm(spectrum) * self.spectra_norm ) # less than O(n^3)
        topk_idx    = np.argpartition(cosine_dist, -k)[-k:]                            # linear time rather than n log n
        self.topk_idx = topk_idx[np.argsort(cosine_dist[topk_idx])][::-1]              # k log k
        self.sim_df = pd.DataFrame({"label":self.speclib.columns[self.topk_idx],"score":cosine_dist[self.topk_idx]})
        return self.sim_df

    def _sort_save_show(self,sort=False,save=False,show=True):
        if sort:
            self.orig_speclib = self.orig_speclib.reindex(sorted(self.orig_speclib.columns), axis=1,)

        if save:
            if "gzip" in self.speclib_path: self.orig_speclib.to_parquet(self.speclib_path,compression="gzip")
            else: self.orig_speclib.to_pickle(self.speclib_path,protocol=4)
            print(f"Added {label} into your spectral library at {self.speclib_path}")

        if show: return self.show("bokeh")

    def update_lib_folder(self,directory,sort=False,save=False,show=True):
        fnames = sorted(os.listdir(directory))
        cwd = Path(directory)
        temp = None
        for f in fnames:
            if temp is None:
                temp = pd.read_csv(cwd/f,delimiter="\t")
                temp.rename({temp.columns[0]:f[9:-9]}, axis='columns',inplace=True)
                temp.loc[~(temp[temp.columns[0]] > 0), temp.columns[0]]=np.nan
                #col_name = temp.columns[0]
                #temp.assign(col_name = lambda x: x.col_name.where(x.col_name.ge(0)))
            else:
                buff = pd.read_csv(cwd/f,delimiter="\t")
                buff.loc[~(buff[buff.columns[0]] > 0), buff.columns[0]]=np.nan
                temp.insert(len(temp.columns),f[9:-9],buff[buff.columns[0]])
        self.orig_speclib = pd.concat([self.orig_speclib,temp[temp.columns[1:]]],axis=1)
        self.orig_speclib = self.orig_speclib.loc[:,~self.orig_speclib.columns.duplicated()]
        print(f"Added folder of ASD spectra to spectral library")
        self._interp()
        return self._sort_save_show(sort,save,show)

    def update_lib_asd_file(self,path,label=None,sort=False,save=False,show=True):
        temp = pd.read_csv(path,delimiter="\t")
        if label is None: label = temp.columns[1]
        self.orig_speclib.insert(len(self.orig_speclib.columns),label,temp[temp.columns[1]])
        self._interp()
        return self._sort_save_show(sort,save,show)

    def show(self,is_ref:bool=False,ref_est:bool=False):
        if self.topk_idx is not None:
            hv_curves = []
            if not is_ref:
                hv_curves.append( hv.Curve(zip(self.wavelengths,self.last_spectra),label="tap point") )
            elif ref_est:
                hv_curves.append( hv.Curve(zip(self.wavelengths,self.last_spectra/(self.model_6SV.radiance/10)),label="6SV estimate") )
            for l in self.sim_df["label"]:
                alpha = self.sim_df[self.sim_df["label"]==l]["score"].to_numpy()
                alpha = 0.2 if len(alpha) == 0 else alpha[0]
                thresh = 0.94 if self.refine else 0.99
                alpha = 0.2 if alpha < thresh else 0.9
                temp = self.speclib_ref.copy() if is_ref else self.spectra.copy()
                temp.insert(0,"wavelength",self.wavelengths)
                hv_curves.append( hv.Curve(temp,kdims="wavelength",vdims=l,label=l).opts(alpha=alpha) )
            return hv.Overlay(hv_curves).opts(width=1000, height=600,xlabel="wavelength (nm)",ylabel="reflectance")

        else:
            temp = self.speclib_ref.copy() if is_ref else self.spectra.copy()
            temp.insert(0,"wavelength",self.wavelengths)
            curve_list = [hv.Curve(temp,kdims="wavelength",vdims=i,label=i) for i in temp.columns[1:] ]
            if getattr(self,"last_spectra",None):
                return (hv.Overlay(curve_list)*hv.Curve(zip(self.wavelengths,self.last_spectra),label="last spectra")).opts(
                                width=1000, height=600,xlabel="wavelength (nm)",ylabel="reflectance",ylim=(0,1.1))
            return (hv.Overlay(curve_list)).opts(
                                width=1000, height=600,xlabel="wavelength (nm)",ylabel="reflectance",ylim=(0,1.1))



# Cell
def remap(x, in_min, in_max, out_min, out_max):
    return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

# Cell

@patch
def topk_spectra(self:SpectralMatcher,spectrum:np.array,k:int=5,refine=True):
        """Match a `spectrum` against a spectral library `spectra`. Return the top k."""
        self.refine = refine

        self.last_spectra = np.array(spectrum)
        cosine_dist       = self.last_spectra @ self.spectra / ( norm(self.last_spectra) * self.spectra_norm ) # less than O(n^3)
        topk_idx          = np.argpartition(cosine_dist, -k)[-k:]             # linear time rather than n log n
        self.topk_idx     = topk_idx[np.argsort(cosine_dist[topk_idx])][::-1] # k log k

        if refine and k > 1:
            topk_spectra    = self.spectra[ self.speclib.columns[self.topk_idx] ].to_numpy().transpose()
            residuals       = norm(topk_spectra - self.last_spectra, axis=1)
            residuals       = remap(residuals, min(residuals),max(residuals),0,0.1)
            subset_topk_idx = np.argsort(cosine_dist[self.topk_idx] - residuals)[::-1]
            self.topk_idx   = self.topk_idx[subset_topk_idx]

            self.sim_df = pd.DataFrame({"label":self.speclib.columns[self.topk_idx],"score":cosine_dist[self.topk_idx]-residuals[subset_topk_idx]})
            return self.sim_df

        self.sim_df = pd.DataFrame({"label":self.speclib.columns[self.topk_idx],"score":cosine_dist[self.topk_idx]})
        return self.sim_df

# Cell

@delegates()
class ELC(SpectralMatcher):

    def __init__(self,nc_path:str,old_style:bool=False,**kwargs):
        """Apply ELC for radiance datacubes"""

        self.dc = DataCube()
        self.dc.load_nc(nc_path,old_style)
        self.RGB = self.dc.show("bokeh",robust=True).opts(height=250, width=1000, invert_yaxis=True,tools=["tap"],toolbar="below")
        self.a_ELC = np.ones((self.dc.dc.data.shape[-1],))
        self.b_ELC = np.zeros((self.dc.dc.data.shape[-1],))
        super().__init__(**kwargs)
        self.xx = np.zeros((len(self.wavelengths),2))

    def __call__(self):

        self.setup_streams()
        self.setup_callbacks()

        return pn.Column( self.RGB * self.boxes * self.ELC_dmap * self.hit_dmap * self.ch_dmap,
                         pn.Tabs( ("Reflectance", self.ref_curve), ("Radiance",self.rad_curve),dynamic=True) )

    def setup_streams(self):
        # Declare Tap stream with heatmap as source and initial values
        self.posxy = hv.streams.Tap(source=self.RGB)

        # Declare pointer stream initializing at (0, 0) and linking to Image
        self.pointer = hv.streams.PointerXY(x=0, y=0, source=self.RGB)

        self.boxes = hv.Rectangles([]).opts(active_tools=['box_edit'], fill_alpha=0.5)
        self.box_stream = hv.streams.BoxEdit(source=self.boxes, num_objects=5, styles={'fill_color': 'red'})

    def setup_callbacks(self):

        # update 'x' marker on mouseclick
        def hit_mark(x,y):
            return hv.Scatter((x,y)).opts(color='r', marker='x', size=20)
        self.hit_dmap = hv.DynamicMap(hit_mark, streams=[self.posxy])

        # Draw cross-hair at cursor position
        def cross_hair_info(x, y):
            return hv.HLine(y) * hv.VLine(x)
        self.ch_dmap = hv.DynamicMap(cross_hair_info, streams=[self.pointer])

        def tap_radiance(x,y):
            if x is None or y is None:
                x = 0; y = 0
            x = int(x); y = int(y)

            sim_df = self.topk_spectra(np.array(self.dc.dc.data[y,x,:]),5,refine=True)

            return self.show().opts(
                legend_position='right', legend_offset=(0, 20),title=f'top match: {self.sim_df["label"][0]}, score: {self.sim_df["score"][0]:.3f}, position=({y:d},{x:d})').opts(framewise=True,
                xlabel="wavelength (nm)",ylabel="radiance (uW/cm^2/sr/nm)",height=400, width=1000,ylim=(0,np.max(self.spectra["spectralon"])))
        self.rad_curve =  hv.DynamicMap(tap_radiance, streams=[self.posxy]).opts(shared_axes=False,height=250)

        def tap_reflectance(x, y):
            if x is None or y is None:
                x = 0; y = 0
            x = int(x); y = int(y)

            spectra = (self.dc.dc.data[y,x,:] - self.b_ELC)/self.a_ELC
            sim_df = self.topk_spectra(self.dc.dc.data[y,x,:],5,refine=True)

            return (hv.Curve(zip(self.wavelengths,spectra),label="ELC estimate") * self.show(is_ref=True,ref_est=True)).opts(axiswise=True,
                legend_position='right', legend_offset=(0, 20),title=f'top match: {self.sim_df["label"][0]}, score: {self.sim_df["score"][0]:.3f}, position=({y:d},{x:d})').opts(framewise=True,
                ylabel="reflectance",xlabel="wavelength (nm)",yaxis="left",height=400, width=1000,ylim=(0,1.05))

        # Connect the Tap stream to the tap_spectra callback
        self.ref_curve = hv.DynamicMap(tap_reflectance, streams=[self.posxy]).opts(shared_axes=False,height=250)

        def update_ELC(data):
            if data is None or len(data) == 0: return hv.Curve([])

            # build up the matrices
            A = []; b = []
            data = zip(np.int32(data['x0']), np.int32(data['x1']), np.int32(data['y0']), np.int32(data['y1']) )
            for i, (x0, x1, y0, y1) in enumerate(data):
                if y1 > y0: y0, y1 = y1, y0
                sz = ((y0-y1)*(x1-x0),len(self.wavelengths))
                selection = np.reshape(np.array(self.dc.dc.data[y1:y0,x0:x1,:]),sz)

                AA = np.zeros((len(self.wavelengths),sz[0],2))
                bb = np.zeros((len(self.wavelengths),sz[0],1))

                for j in range(sz[0]):
                    self.topk_spectra(selection[j,:],k=5,refine=True)
                    label = self.sim_df["label"][0]
                    AA[:,j,0] = self.speclib[label].to_numpy()
                    bb[:,j,0] = selection[j,:]
                AA[:,:,1] = 1

                A.append(AA); b.append(bb)

            A = np.concatenate(A,axis=1); b = np.concatenate(b,axis=1)
            x = np.linalg.pinv(A) @ b

            self.xx[:,0] = x[:,0,0]; self.xx[:,1] = x[:,1,0]
            self.a_ELC = self.xx[:,0]; self.b_ELC = self.xx[:,1]
            return hv.Curve([])
        self.ELC_dmap = hv.DynamicMap(update_ELC, streams=[self.box_stream])


