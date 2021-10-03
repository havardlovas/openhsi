# AUTOGENERATED! DO NOT EDIT! File to edit: 02_calibrate.ipynb (unless otherwise specified).

__all__ = []

# Cell

from fastcore.foundation import patch
from fastcore.meta import delegates
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from scipy.interpolate import interp1d
from PIL import Image
from scipy.signal import decimate

from typing import Iterable, Union, Callable, List, TypeVar, Generic, Tuple, Optional
import datetime
import json
import pickle

# Cell

from .data import *
from .capture import *