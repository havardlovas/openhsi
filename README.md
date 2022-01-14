# Open Source DIY Hyperspectral Imager Library
> Library to calibrate, trigger and capture data cubes for the open source DIY hyperspectral camera. 


![](https://github.com/openhsi/openhsi/actions/workflows/main.yml/badge.svg)

This Python library is licensed under the [Apache v2 License](https://www.apache.org/licenses/LICENSE-2.0). The documentation is licensed under a <a rel="license" href="http://creativecommons.org/licenses/by/3.0/au/">Creative Commons Attribution 3.0 Australia License</a>.

Documentation can be found here: [https://openhsi.github.io/openhsi/](https://openhsi.github.io/openhsi/).

## Install

`pip install openhsi`

## Requirements

- Python 3.6+
- Ximea SDK (See https://www.ximea.com/support/wiki/apis/Python)
- FLIR or LUCID SDKs accordingly.

## Development and Contributions

This whole software library, testing suite, documentation website, and PyPI package was developed in Jupyter Notebooks using [nbdev](https://nbdev.fast.ai/). 
{% include important.html content='This library is under active development and new features are still being added. ' %}

## Citation

If OpenHSI has been useful for your research, please acknowledge the project in your academic publication. We have a publication in progress. 

```
@Article{        mao2022openhsi,
 title         = {OpenHSI: A complete open-source hyperspectral imaging solution for everyone},
 author        = {Yiwei Mao, and Christopher H. Betters, et al.},
 year          = {2022},
 journal       = {},
}
```


## How to use

### Taking a single hyperspectral datacube

The example shown here uses a simulated camera for testing purposes. Replace `SimulatedCamera` with the appropriate Python class for your own camera to work with real hardware. For example, use `XimeaCamera` inplace of `SimulatedCamera`. 

```
#hide_output
from openhsi.capture import *

with SimulatedCamera(img_path="../assets/rocky_beach.png", n_lines=1024, processing_lvl = 3,
                    json_path="../assets/cam_settings.json",pkl_path="../assets/cam_calibration.pkl") as cam:
    cam.collect()
    fig = cam.show(plot_lib="matplotlib",robust=True)

```




    Text(0, 0.5, 'cross-track')




![png](docs/images/output_10_1.png)

